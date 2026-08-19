from django.db.models import Q, Sum
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.http import urlencode
from django.urls import reverse

from authentification.models import SchoolYear
from .models import SchoolFee, FeeInstallment, FeeType, StudentPayment, PaymentMethod, FeeDiscount, Transaction,\
    TransactionCategory, CashBox
from .forms import StudentPaymentForm
from student.models import Student
from staff.models import Personnel
from osm.utils import school_year, message, logged_financial_user_view, stamp_bytes, paste_stamp, resize_image, \
    base_header, number_to_words_fr, safe_redirect_back, pdf_response, base_infos, formated_float, filigrane, add_fonts,\
    format_date
from classroom.models import ClassRoom, Class
from fpdf import FPDF
from fpdf.fonts import FontFace
from fpdf.table import Table
from fpdf.enums import TableHeadingsDisplay
import json
from datetime import datetime, date as _date
from django.db import transaction


# TODO: logged_financial_user
# ---------------------------------------------------------------------------
#  PAGE PRINCIPALE : la grille d'une année
# ---------------------------------------------------------------------------
@logged_financial_user_view
def fee_grid(request):
    year = request.GET.get("year") or school_year()

    fees = (SchoolFee.objects.filter(school_year=year)
            .select_related("fee_type")
            .prefetch_related("installments")
            .order_by("fee_type__nom", "level", "serie"))

    # groupées par type de frais (pour l'affichage en cartes)
    groups = {}
    for f in fees:
        groups.setdefault(f.fee_type, []).append(f)

    school = request.user.school
    classes = Class.objects

    niveaux_premier_cycle_esg_fr = ["Sixième", "Cinquième", "Quatrième", "Troisième"]
    niveaux_premier_cycle_est_fr = ["1ère Année", "2ème Année", "3ème Année", "4ème Année"]
    niveaux_premier_cycle_esg_en = ["From One", "From Two", "From Three", "From Four"]
    niveaux_second_cycle_esg_fr = ["Seconde", "Première", "Terminale"]
    niveaux_second_cycle_esg_en = ["From Five", "Lower Sixth", "Upper Sixth"]
    series_premier_cycle_esg_fr = ["Bilingue", ]
    series_premier_cycle_esg_en = ["Arts", "Sciences"]
    series_second_cycle_esg_en = ["Commercial"]
    series_second_cycle_esg_fr = ["A1", "A2", "A3", "A4", "A5", "ABI", "AC", "B", "C", "D", "E", "SH", "TI"]
    series_premier_cycle_est_fr = ["MACO"]
    series_second_cycle_est_fr = ["F4", "IH"]
    if school.type_ets == "CES":
        s_niveaux, s_series = niveaux_premier_cycle_esg_fr, series_premier_cycle_esg_fr
    elif school.type_ets in ["Collège", "Lycée"]:
        s_niveaux, s_series = (niveaux_premier_cycle_esg_fr + niveaux_second_cycle_esg_fr,
                           series_premier_cycle_esg_fr + series_second_cycle_esg_fr)
    elif school.type_ets == "CES Bilingue":
        s_niveaux, s_series = (niveaux_premier_cycle_esg_fr + niveaux_premier_cycle_esg_en,
                           series_premier_cycle_esg_fr + series_premier_cycle_esg_en)
    elif school.type_ets in ["Lycée Bilingue", "Collège Bilingue"]:
        s_niveaux, s_series = (niveaux_premier_cycle_esg_fr + niveaux_second_cycle_esg_fr + niveaux_premier_cycle_esg_en + niveaux_second_cycle_esg_en,
                           series_premier_cycle_esg_fr + series_second_cycle_esg_fr + series_premier_cycle_esg_en + series_second_cycle_esg_en)
    elif school.type_ets == "CETIC":
        s_niveaux, s_series = niveaux_premier_cycle_est_fr, series_premier_cycle_est_fr
    elif school.type_ets == "Lycée Technique":
        s_niveaux, s_series = (niveaux_premier_cycle_est_fr + niveaux_second_cycle_esg_fr,
                           series_premier_cycle_est_fr + series_second_cycle_est_fr)
    # niveaux/séries EXISTANTS dans cet établissement (selects dynamiques)
    niveaux = list(classes.exclude(niveau__isnull=True).filter(niveau__in=s_niveaux)
                   .values_list("niveau", flat=True).distinct())
    series = [s for s in Class.objects.filter(serie__in=s_series).values_list("serie", flat=True)
              .distinct() if s]

    # années déjà paramétrées (sélecteur) + année courante
    years = list(SchoolFee.objects.values_list("school_year", flat=True)
                 .distinct().order_by("-school_year"))
    if school_year() not in years:
        years.insert(0, school_year())

    # sérialisation des lignes pour l'édition en modale (data-* JSON)
    fees_json = {
        f.id: {
            "fee_type": f.fee_type_id, "level": f.level or "",
            "serie": f.serie or "", "amount": f.amount,
            "installments": [
                {"label": i.label, "amount": i.amount,
                 "due_date": i.due_date.isoformat()}
                for i in f.installments.all()],
        } for f in fees
    }

    return render(request, "fee_grid.html", {
        "year": year, "years": years, "groups": groups,
        "fee_types": FeeType.objects.order_by("nom"),
        "niveaux": sorted(niveaux), "series": sorted(series),
        "fees_json": fees_json,
        "previous_year": _previous_year(year),
        'title': "Grille Tarifaire",
        "has_previous": SchoolFee.objects.filter(school_year=_previous_year(year)).exists(),
    })


def _previous_year(year):
    """'2025/2026' -> '2024/2025'."""
    try:
        a, b = year.split("/")
        return f"{int(a)-1}/{int(b)-1}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
#  ENREGISTRER une ligne de grille (création OU édition) + ses tranches
# ---------------------------------------------------------------------------
@logged_financial_user_view
def fee_save(request):
    if request.method != "POST":
        return redirect("fee_grid")
    year = request.POST.get("year") or school_year()

    fee_id = request.POST.get("fee_id") or None
    fee_type = get_object_or_404(FeeType, pk=request.POST.get("fee_type"))
    level = (request.POST.get("level") or "").strip() or None
    serie = (request.POST.get("serie") or "").strip() or None
    if serie and not level:
        message(request, "Une série sans niveau n'a pas de sens.", msg_type="error")
        return safe_redirect_back(request)
    try:
        amount = int(request.POST.get("amount"))
        assert amount > 0
    except Exception:
        message(request, "Montant invalide.", msg_type="error")
        return safe_redirect_back(request)

    if serie and level:
        if not Class.objects.filter(niveau=level, serie=serie).exists():
            message(request, "Cette série n'existe pas pour ce niveau.", msg_type="error")
            return safe_redirect_back(request)
    # tranches (champs parallèles du formulaire dynamique)
    labels = request.POST.getlist("inst_label")
    amounts = request.POST.getlist("inst_amount")
    dates = request.POST.getlist("inst_date")
    installments = []
    for lab, amt, dat in zip(labels, amounts, dates):
        lab, amt, dat = lab.strip(), amt.strip(), dat.strip()
        if not (lab or amt or dat):
            continue                       # ligne vide ignorée
        try:
            installments.append((lab or f"Tranche {len(installments)+1}",
                                 int(amt), datetime.fromisoformat(dat).date()))
        except Exception:
            message(request, "Tranche incomplète ou invalide (libellé, montant et date requis).", msg_type="error")
            return safe_redirect_back(request)

    # RÈGLE : la somme des tranches doit égaler le montant total
    if installments and sum(a for _, a, _ in installments) != amount:
        message(request, "La somme des tranches doit être égale au montant total.", msg_type="error")
        return safe_redirect_back(request)

    # unicité (fee_type, year, level, serie) hors ligne en cours d'édition
    dup = SchoolFee.objects.filter(fee_type=fee_type, school_year=year,
                                   level=level, serie=serie)
    if fee_id:
        dup = dup.exclude(pk=fee_id)
    if dup.exists():
        message(request, "Une ligne existe déjà pour ce frais et ce niveau/série.", msg_type="error")
        return safe_redirect_back(request)

    with transaction.atomic():
        if fee_id:
            fee = get_object_or_404(SchoolFee, pk=fee_id)
            fee.fee_type, fee.level, fee.serie, fee.amount = fee_type, level, serie, amount
            fee.save()
            fee.installments.all().delete()   # paramétrage : recréation OK
        else:
            fee = SchoolFee.objects.create(fee_type=fee_type,
                                           school_year=year, level=level,
                                           serie=serie, amount=amount)
        FeeInstallment.objects.bulk_create([
            FeeInstallment(school_fee=fee, label=l, amount=a, due_date=d)
            for l, a, d in installments])

    message(request, "Ligne de grille enregistrée.")
    url = reverse("fee_grid")
    return redirect(f"{url}?{urlencode({'year': year})}")


# ---------------------------------------------------------------------------
#  SUPPRIMER une ligne (paramétrage pur : autorisé, avec confirmation UI)
# ---------------------------------------------------------------------------
@logged_financial_user_view
def fee_delete(request, pk):
    if request.method == "POST":
        fee = get_object_or_404(SchoolFee, pk=pk)
        year = fee.school_year
        fee.delete()                       # les paiements ne pointent PAS ici
        message(request, "Ligne de grille supprimée.")
        url = reverse("fee_grid")
        return redirect(f"{url}?{urlencode({'year': year})}")
    return redirect("fee_grid")


# ---------------------------------------------------------------------------
#  DUPLIQUER la grille d'une année vers une autre (rentrée facile)
# ---------------------------------------------------------------------------
@logged_financial_user_view
def fee_duplicate(request):
    """Copie toutes les lignes (et tranches, dates décalées d'un an) de
    from_year vers to_year, en ignorant celles qui existent déjà."""
    if request.method != "POST":
        return redirect("fee_grid")
    from_year = request.POST.get("from_year")
    to_year = request.POST.get("to_year")
    created = 0
    with transaction.atomic():
        for fee in (SchoolFee.objects.filter(school_year=from_year)
                    .prefetch_related("installments")):
            if SchoolFee.objects.filter(fee_type=fee.fee_type,
                                        school_year=to_year,
                                        level=fee.level,
                                        serie=fee.serie).exists():
                continue
            clone = SchoolFee.objects.create(
                fee_type=fee.fee_type, school_year=to_year,
                level=fee.level, serie=fee.serie, amount=fee.amount)
            FeeInstallment.objects.bulk_create([
                FeeInstallment(school_fee=clone, label=i.label,
                               amount=i.amount,
                               due_date=i.due_date.replace(
                                   year=i.due_date.year + 1))
                for i in fee.installments.all()])
            created += 1
    message(request, f"{created} ligne(s) copiée(s) depuis {from_year}.")
    url = reverse("fee_grid")
    return redirect(f"{url}?{urlencode({'year': to_year})}")


# ---------------------------------------------------------------------------
#  CRÉATION RAPIDE d'un type de frais
# ---------------------------------------------------------------------------
@logged_financial_user_view
def fee_type_save(request):
    if request.method == "POST":
        nom = (request.POST.get("nom") or "").strip()
        if nom:
            FeeType.objects.get_or_create(
                nom=nom,
                defaults={"affects_cashbox":
                          request.POST.get("affects_cashbox") == "on"})
            message(request, f"Type de frais « {nom} » créé.")
    return safe_redirect_back(request, "fee_grid")


# ---------------------------------------------------------------------------
#  ENCAISSEMENT (recherche + situation + paiement) — une seule page
# ---------------------------------------------------------------------------
@logged_financial_user_view
def cash_in(request):
    """?q= : recherche d'élèves ; ?student= : situation + formulaire.
    POST : enregistre le paiement puis propose le reçu."""
    year = school_year()
    context = {'year': year, 'methods': PaymentMethod.choices, 'title': "Encaissements"}

    # --- recherche -----------------------------------------------------------
    q = (request.GET.get("q") or "").strip()
    if q:
        context["q"] = q
        context["results"] = (Student.objects
                              .filter(Q(nom__icontains=q) | Q(prenom__icontains=q)
                                      | Q(unique_id__icontains=q))
                              .select_related("classe")
                              .order_by("nom", "prenom")[:25])

    # --- élève sélectionné ----------------------------------------------------
    student_id = request.GET.get("student") or request.POST.get("student")
    if student_id:
        student = get_object_or_404(Student, pk=student_id)
        context["student"] = student
        # situation par type de frais (méthode déplacée sur Student)
        context["status"] = student.student_fee_status(year)
        # historique des paiements de l'année (reçus réimprimables)
        context["history"] = (student.payments
                              .filter(school_year=year)
                              .select_related("fee_type")
                              .order_by("-date", "-id"))

        if request.method == "POST":
            form = StudentPaymentForm(request.POST, student=student, year=year)
            if form.is_valid():
                payment = form.save(commit=False)
                if payment.amount > student.student_fee_status(year, fee_type_id=payment.fee_type.id)[0]['reste']:
                    message(request, "Le montant ne peut être supérieur au reste à payer.", msg_type="error")
                elif payment.date > datetime.today().date():
                    message(request, "La date de payement ne peut être supérieure à celle d'aujourd'hui.", msg_type="error")
                else:
                    payment.student = student
                    payment.school_year = year
                    payment.received_by = request.user
                    payment.save()
                    message(request,
                        f"Paiement de {payment.amount:,} FCFA enregistré "
                        f"(reçu {payment.receipt_number}).".replace(",", " "))
                    # PRG + ouverture directe du reçu possible côté template
                    if payment.fee_type.affects_cashbox:
                        return redirect(f"{request.path}?student={student.pk}"
                                        f"&receipt={payment.pk}")
                    else:
                        return HttpResponseRedirect(f"{request.path}?student={student.pk}")
            context["form"] = form
        else:
            context["form"] = StudentPaymentForm(student=student, year=year)
            context["new_receipt"] = request.GET.get("receipt")
    return render(request, "cash_in.html", context)


# ---------------------------------------------------------------------------
#  REÇU PDF
# ---------------------------------------------------------------------------
@logged_financial_user_view
def payment_receipt(request, pk):
    """Reçu PDF (2 exemplaires : parent + souche). Réimprimable à volonté."""
    payment = get_object_or_404(
        StudentPayment.objects.select_related("student", "fee_type"), pk=pk)
    pdf = PaymentReceipt(payment, request.user.school)
    response = HttpResponse(bytes(pdf.output()), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="Recu_{payment.receipt_number}.pdf"')
    return response


# ---------------------------------------------------------------------------
#  ANNULATION TRACÉE (jamais de suppression)
# ---------------------------------------------------------------------------
@logged_financial_user_view
def cancel_payment(request, pk):
    if request.method != "POST":
        return redirect("cash_in")
    payment = get_object_or_404(StudentPayment, pk=pk, cancelled=False)
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        message(request, "Le motif d'annulation est obligatoire.", msg_type="error")
    else:
        payment.cancelled = True
        payment.cancel_reason = reason
        payment.cancelled_by = request.user
        payment.cancelled_at = timezone.now()
        payment.save(update_fields=["cancelled", "cancel_reason",
                                    "cancelled_by", "cancelled_at"])
        message(request,f"Paiement {payment.receipt_number} annulé (tracé).")
    return safe_redirect_back(request, "cash_in")


@logged_financial_user_view
def discounts(request):
    year = school_year()
    context = {"year": year}

    # ------- liste des remises de l'année (courte par nature) -------
    dlist = (FeeDiscount.objects.filter(school_year=year)
             .select_related("student", "student__classe", "fee_type",
                             "granted_by")
             .order_by("student__nom", "student__prenom"))
    context["discounts"] = dlist
    context["total"] = dlist.aggregate(t=Sum("amount"))["t"] or 0

    # ------- recherche d'un élève à qui accorder -------
    q = (request.GET.get("q") or "").strip()
    if q:
        context["q"] = q
        context["results"] = (Student.objects
                              .filter(Q(nom__icontains=q)
                                      | Q(prenom__icontains=q)
                                      | Q(unique_id__icontains=q))
                              .select_related("classe")
                              .order_by("nom", "prenom")[:25])

    # ------- élève sélectionné : formulaire d'attribution -------
    student_id = request.GET.get("student")
    if student_id:
        student = get_object_or_404(Student, pk=student_id)
        context["student"] = student
        # frais applicables à CET élève (cascade niveau/série) + dû brut,
        # et remise existante éventuelle (pré-remplissage = modification)
        existing = {d.fee_type_id: d for d in
                    FeeDiscount.objects.filter(student=student, school_year=year)}
        fees = []
        for f in student.applicable_fees(year):
            fees.append({"fee": f,
                         "current": existing.get(f.fee_type_id)})
        context["fees"] = fees
    context['title'] = "Remises et Exonérations"
    return render(request, "discounts.html", context)


@logged_financial_user_view
def discount_save(request):
    if request.method != "POST":
        return redirect("discounts")
    year = school_year()
    student = get_object_or_404(Student, pk=request.POST.get("student"))
    fee_type = get_object_or_404(FeeType, pk=request.POST.get("fee_type"))
    reason = (request.POST.get("reason") or "").strip()
    try:
        amount = int(request.POST.get("amount"))
        assert amount > 0 and reason
    except Exception:
        message(request, "Montant et motif sont obligatoires.", msg_type="error")
        return safe_redirect_back(request)

    # garde-fou : la remise ne dépasse pas le dû brut de la grille
    grid = {f.fee_type_id: f.amount for f in student.applicable_fees(year)}
    du_brut = grid.get(fee_type.id)
    if du_brut is not None and amount > du_brut:
        message(request, f"La remise ({amount:,} F) dépasse le montant "
                                f"dû ({du_brut:,} F).".replace(",", " "), msg_type="error")
        return safe_redirect_back(request)

    _, created = FeeDiscount.objects.update_or_create(
        student=student, fee_type=fee_type, school_year=year,
        defaults={"amount": amount, "reason": reason,
                  "granted_by": request.user})
    message(request, f"Remise {'accordée' if created else 'modifiée'} : {amount:,} FCFA sur {fee_type} pour {student}."
                     .replace(",", " "))
    return redirect("discounts")


@logged_financial_user_view
def discount_delete(request, pk):
    if request.method == "POST":
        d = get_object_or_404(FeeDiscount, pk=pk)
        message(request, f"Remise retirée pour {d.student}.")
        d.delete()
    return redirect("discounts")


MONTHS_FR = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

FIXE, HORAIRE = "FIXE", "HORAIRE"


def _int(raw):
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


# ---------------------------------------------------------------------------
#  ATTRIBUTION DES SALAIRES (paramétrage)
# ---------------------------------------------------------------------------
@logged_financial_user_view
def salary_assignment(request):
    staff = Personnel.objects.all().order_by("nom", "prenom")

    if request.method == "POST":
        updated = 0
        for p in staff:
            mode = (request.POST.get(f"mode_{p.id}") or "").strip() or None
            salaire = _int(request.POST.get(f"sal_{p.id}"))
            rate = _int(request.POST.get(f"rate_{p.id}"))
            hours = _int(request.POST.get(f"hrs_{p.id}"))

            if mode == FIXE:
                rate = None                       # cohérence : pas de taux en fixe
            elif mode == HORAIRE:
                salaire = None                    # le fixe n'a pas de sens ici
            else:
                mode = None                       # non payé -> tout à vide
                salaire = rate = hours = None

            changed = (p.salary_mode != mode or p.salaire != salaire
                       or p.hourly_rate != rate or p.default_hours != hours)
            if changed:
                p.salary_mode, p.salaire = mode, salaire
                p.hourly_rate, p.default_hours = rate, hours
                p.save(update_fields=["salary_mode", "salaire", "hourly_rate", "default_hours"])
                updated += 1
        message(request, f"Salaires enregistrés ({updated} modification(s)).")
        return redirect(request.path)

    box = CashBox.objects.first()
    return render(request, "salary_assignment.html", {
        "staff": staff, "FIXE": FIXE, "HORAIRE": HORAIRE, 'title': "Gestion des Salaires",
        "default_rate": (box.default_hourly_rate if box else None) or "",
    })


# ---------------------------------------------------------------------------
#  PAIE MENSUELLE
# ---------------------------------------------------------------------------
def _month_from(raw):
    try:
        y, m = raw.split("-")
        return _date(int(y), int(m), 1)
    except Exception:
        return timezone.localdate().replace(day=1)


@logged_financial_user_view
def payroll(request):
    month = _month_from(request.GET.get("month") or request.POST.get("month") or "")
    earners = Personnel.objects.filter(salary_mode__isnull=False).order_by("nom", "prenom")

    # transactions de paie déjà passées ce mois : {personnel_id: transaction}
    paid = {t.beneficiary_id: t for t in Transaction.objects.filter(cancelled=False, salary_month=month,
        beneficiary__in=earners)}

    if request.method == "POST":
        selected = set(int(i) for i in request.POST.getlist("pay"))
        method = request.POST.get("method") or PaymentMethod.CASH
        category = TransactionCategory.objects.filter(
            nom__icontains="alaire").first()
        if not category:
            message(request, "Catégorie de salaires introuvable (voir paramétrage).", "error")
            return redirect(f"{request.path}?month={month:%Y-%m}")

        created = 0
        with transaction.atomic():
            for p in earners:
                if p.id not in selected or p.id in paid:
                    continue
                # calcul du montant + heures selon le mode
                if p.salary_mode == HORAIRE:
                    hours = _int(request.POST.get(f"hrs_{p.id}"))
                    if not hours or not p.hourly_rate:
                        continue                  # rien à payer sans heures/taux
                    amount = int(p.hourly_rate * hours)
                else:                             # FIXE
                    amount = p.salaire or 0
                    hours = None
                    if amount <= 0:
                        continue
                Transaction.objects.create(
                    category=category, amount=amount,
                    date=timezone.localdate(),
                    description=f"Salaire {MONTHS_FR[month.month]} {month.year}",
                    beneficiary=p, method=method, salary_month=month,
                    hours=hours, created_by=request.user)
                created += 1
        message(request, f"{created} salaire(s) payé(s) pour {MONTHS_FR[month.month]} {month.year}.")
        return redirect(f"{request.path}?month={month:%Y-%m}")

    # préparation de l'affichage
    rows = []
    total_due = total_paid = 0
    for p in earners:
        t = paid.get(p.id)
        if t:
            total_paid += t.amount
            rows.append({"p": p, "paid": True, "amount": t.amount, "hours": t.hours})
        else:
            hours = p.default_hours or 0
            if p.salary_mode == HORAIRE:
                amount = int((p.hourly_rate or 0) * hours)
            else:
                amount = p.salaire or 0
            total_due += amount
            rows.append({"p": p, "paid": False, "amount": amount, "hours": p.default_hours,
                         "is_hourly": p.salary_mode == HORAIRE})

    return render(request, "payroll.html", {
        "rows": rows, "month": month, "month_str": f"{month:%Y-%m}",
        "month_label": f"{MONTHS_FR[month.month]} {month.year}",
        "total_due": total_due, "total_paid": total_paid,
        "methods": PaymentMethod.choices, "HORAIRE": HORAIRE,
        'title': "Paiement des Salaires"
    })


# ---------------------------------------------------------------------------
#  FICHE D'ÉMARGEMENT (adossée aux paies RÉELLES du mois)
# ---------------------------------------------------------------------------
@logged_financial_user_view
def emargement_sheet(request):
    month = _month_from(request.GET.get("month") or "")
    payments = list(
            Transaction.objects.filter(cancelled=False, salary_month=month)
            .select_related("beneficiary")
            .order_by("beneficiary__nom", "beneficiary__prenom"))
    if not payments:
        message(request, "Aucun salaire défini.", msg_type="error")
        return safe_redirect_back(request)
    return pdf_response(FicheEmargement(month, school=request.user.school, payments=payments),
                        f"Fiche d'émargement {MONTHS_FR[month.month]} {month.year}.pdf")


# ---------------------------------------------------------------------------
#  PAGE CAISSE
# ---------------------------------------------------------------------------
@logged_financial_user_view
def cashbox(request):
    today = timezone.localdate()
    try:
        date_from = _date.fromisoformat(request.GET.get("from", ""))
    except ValueError:
        date_from = today.replace(day=1)          # défaut : mois courant
    try:
        date_to = _date.fromisoformat(request.GET.get("to", ""))
    except ValueError:
        date_to = today

    opening, entries, closing = CashBox.cash_journal_ui(date_from, date_to)
    total_in = sum(e["montant"] for e in entries if e["sens"] > 0)
    total_out = sum(e["montant"] for e in entries if e["sens"] < 0)

    return render(request, "cashbox.html", {
        "date_from": date_from, "date_to": date_to,
        "opening": f"{opening:,}".replace(",", " "), "closing": f"{closing:,}".replace(",", " "),
        "entries": entries,
        "total_in": f"{total_in:,}".replace(",", " "), "total_out": f"{total_out:,}".replace(",", " "),
        "balance_now": f"{CashBox.cashbox_balance(today):,}".replace(",", " "),
        "box": CashBox.objects.first(),
        "categories": TransactionCategory.objects.filter(is_active=True).order_by("kind", "nom"),
        "personnel": Personnel.objects.all().order_by("nom"),
        "methods": PaymentMethod.choices,
        'title': "Caisse"
    })


# ---------------------------------------------------------------------------
#  SAISIE d'une opération (dépense ou recette selon la catégorie)
# ---------------------------------------------------------------------------
@logged_financial_user_view
def transaction_save(request):
    if request.method != "POST":
        return redirect("cashbox")
    try:
        category = TransactionCategory.objects.get(
            pk=request.POST.get("category"))
        amount = int(request.POST.get("amount"))
        assert amount > 0
        day = _date.fromisoformat(request.POST.get("date"))
        description = (request.POST.get("description") or "").strip()
        assert description
    except Exception:
        message(request, "Opération invalide : catégorie, montant, date et libellé obligatoires.",
                msg_type="error")
        return safe_redirect_back(request)

    beneficiary_id = request.POST.get("beneficiary") or None
    Transaction.objects.create(
        category=category, amount=amount, date=day, description=description, beneficiary_id=beneficiary_id,
        method=request.POST.get("method") or PaymentMethod.CASH,
        reference=(request.POST.get("reference") or "").strip(),
        created_by=request.user)
    message(request, f"{category.get_kind_display()} de {amount:,} FCFA enregistrée.".replace(",", " "))
    return safe_redirect_back(request)


# ---------------------------------------------------------------------------
#  PARAMÈTRES DE CAISSE (solde initial)
# ---------------------------------------------------------------------------
@logged_financial_user_view
def cashbox_settings(request):
    if request.method == "POST":
        try:
            opening = int(request.POST.get("opening_balance"))
            day = _date.fromisoformat(request.POST.get("opening_date"))
        except Exception:
            message(request, "Solde initial ou date invalide.", msg_type="error")
            return safe_redirect_back(request)
        box, _ = CashBox.objects.get_or_create(pk=1)
        box.opening_balance = opening
        box.opening_date = day
        # taux horaire par défaut (facultatif) : pré-remplit les vacataires horaires ; jamais utilisé pour le calcul de paie.
        box.default_hourly_rate = _int(request.POST.get("default_hourly_rate"))
        box.save()
        message(request, "Paramètres financiers enregistrés.")
    return safe_redirect_back(request, "cashbox")


# ---------------------------------------------------------------------------
#  ANNULATION TRACÉE d'une transaction
# ---------------------------------------------------------------------------
@logged_financial_user_view
def cancel_transaction(request, pk):
    if request.method != "POST":
        return redirect("cashbox")
    t = get_object_or_404(Transaction, pk=pk, cancelled=False)
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        message(request, "Le motif d'annulation est obligatoire.", msg_type="error")
    else:
        t.cancelled = True
        t.cancel_reason = reason
        t.cancelled_by = request.user
        t.cancelled_at = timezone.now()
        t.save(update_fields=["cancelled", "cancel_reason", "cancelled_by", "cancelled_at"])
        message(request, "Opération annulée (tracée).")
    return safe_redirect_back(request)


@logged_financial_user_view
def _period(request):
    today = timezone.localdate()
    try:
        f = _date.fromisoformat(request.GET.get("from", ""))
    except ValueError:
        f = today.replace(day=1)
    try:
        t = _date.fromisoformat(request.GET.get("to", ""))
    except ValueError:
        t = today
    try:
        assert f <= t
    except AssertionError:
        f = today.replace(day=1)
    return f, t


@logged_financial_user_view
def reports(request):
    today = timezone.localdate()
    year = school_year()
    annee_debut = year.split("/")[0]
    return render(request, "reports.html", {
        'title': "États financiers", "year": year,
        'years': [s.libelle for s in SchoolYear.objects.filter(annee_debut__lte=annee_debut)],
        "classrooms": ClassRoom.objects.all().order_by_niveau(),
        "fee_types": FeeType.objects.filter(is_active=True).order_by("nom"),
        "month_start": today.replace(day=1),
        "today": today,
    })


@logged_financial_user_view
def defaulters_pdf(request, classroom_id):
    classroom = get_object_or_404(ClassRoom, pk=classroom_id)
    fee_type = (FeeType.objects.filter(pk=request.GET.get("fee_type")).first() if request.GET.get("fee_type") else None)
    on_installments = request.GET.get("crit") == "retard"
    year = SchoolYear.objects.get(libelle=request.GET.get("year")).libelle
    data = classroom.classroom_defaulters(year, fee_type=fee_type, on_installments=on_installments)
    if data:
        pdf = DefaultersListPDF(classroom, year, data, fee_type=fee_type, on_installments=on_installments,
                                school=request.user.school)
        return pdf_response(pdf, f"Insolvables {classroom.code}{' - ' + fee_type.nom if fee_type else ''}"
                                 f"{' ' + year if year != school_year() else ''}.pdf")
    else:
        message(request, "Aucun insolvable pour ces frais dans cette classe.", msg_type="error")
        return safe_redirect_back(request)


@logged_financial_user_view
def convocations_pdf(request, classroom_id):
    classroom = get_object_or_404(ClassRoom, pk=classroom_id)
    fee_type = (FeeType.objects.filter(pk=request.GET.get("fee_type")).first() if request.GET.get("fee_type") else None)
    year = SchoolYear.objects.get(libelle=request.GET.get("year")).libelle
    data = classroom.classroom_defaulters(year, fee_type=fee_type)
    if data:
        pdf = ConvocationsPDF(classroom, year, data, request.user.school, meet_date=request.GET.get("date", ""),
                              meet_time=request.GET.get("time", ""))
        return pdf_response(pdf, f"Convocations {classroom.code}{' - ' + fee_type.nom if fee_type else ''}"
                                 f"{' ' + year if year != school_year() else ''}.pdf")
    else:
        message(request, "Aucun insolvable à convoquer pour ces frais dans cette classe.", msg_type="error")
        return safe_redirect_back(request)


@logged_financial_user_view
def recovery_pdf(request):
    fee_type = (FeeType.objects.filter(pk=request.GET.get("fee_type")).first() if request.GET.get("fee_type") else None)
    year = SchoolYear.objects.get(libelle=request.GET.get("year")).libelle
    if (not Student.objects.exists()) or (not ClassRoom.objects.exists()) or (not FeeType.objects.exists()):
        if not Student.objects.exists():
            msg = "Aucun élève enregistré."
        elif not ClassRoom.objects.exists():
            msg = "Aucune salle de classe."
        else:
            msg = "Aucun frais enregistré."
        message(request, msg, msg_type="error")
        return safe_redirect_back(request)
    else:
        pdf = RecoveryReportPDF(ClassRoom.objects.all().order_by("code"), year, request.user.school, fee_type=fee_type)
        return pdf_response(pdf, f"Recouvrement {' ' + year if year != school_year() else ''}.pdf")


@logged_financial_user_view
def journal_pdf(request):
    f, t = _period(request)
    opening, entries, closing = CashBox.cash_journal_ui(f, t)
    if not entries:
        message(request, "Aucune transaction enregistré sur cette période", msg_type="error")
        return safe_redirect_back(request)
    else:
        pdf = CashJournalPDF(f, t, opening, entries, closing, request.user.school)
        return pdf_response(pdf, f"Journal de Caisse du {f:%Y-%m-%d} au {t:%Y-%m-%d}.pdf")

@logged_financial_user_view
def expenses_pdf(request):
    f, t = _period(request)
    qs = (Transaction.objects
          .filter(cancelled=False, date__range=(f, t))
          .values("category__nom", "kind")
          .annotate(total=Sum("amount"))
          .order_by("kind", "-total"))
    if not qs.exists():
        message(request, 'Aucune dépense et recette sur cette période.', msg_type="error")
        return safe_redirect_back(request)
    else:
        pdf = ExpensesReportPDF(qs, f, t, request.user.school)
        return pdf_response(pdf, f"Dépenses et Recettes du {f:%Y-%m-%d} au {t:%Y-%m-%d}.pdf")


GREEN = (10, 125, 63)
RED   = (200, 30, 45)
NAVY  = (10, 61, 98)
GREY  = (110, 120, 132)
LINE  = (215, 222, 230)


class _FinReport(FPDF):
    DOC_NAME = "État financier"

    def __init__(self, orientation="P", school=None):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.alias_nb_pages()
        add_fonts(self)
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(True, margin=6)
        self.now = datetime.now().strftime("%d-%m-%Y à %H:%M")
        self.school = school
        self._land = orientation == "L"

    def start(self, title, subtitle=""):
        self.add_page()
        base_header(self, mode="L" if self._land else "P")
        self.ln(2)
        self.set_font("inter", "B", 12)
        self.set_text_color(*GREEN)
        self.cell(0, 7, title, align="C")
        self.ln(6)
        if subtitle:
            self.set_font("inter", "", 8)
            self.set_text_color(*GREY)
            self.cell(0, 4, subtitle, align="C")
            self.ln(5)
        self.set_text_color(0)

    def footer(self):
        w = 285 if self._land else 198
        line_xy = (6, 204, 291, 204) if self._land else (6, 291, 204, 291)
        self.set_y(-6)
        self.set_draw_color(200)
        self.line(*line_xy)
        self.set_font("inter", "I", 7)
        self.set_text_color(*GREY)
        self.cell(w/2, 6, f"Document généré par Oméga School Manager le {self.now}",
                  align="L")
        self.cell(w/2, 6, f"{self.DOC_NAME} • Page {self.page_no()}/{{nb}}",
                  align="R")


"""
=============================================================================
 FicheEmargement
=============================================================================
 Adossée aux paies RÉELLES du mois : liste les Transactions de salaire du
 mois (montant snapshoté + heures réelles). Colonnes :
 N°, Noms et Prénoms, Poste, H. (heures réelles si horaire, sinon —),
 Contact, Montant, N° pièce d'identité (LIBRE), Signature/Empreinte (LIBRE).
=============================================================================
"""
class FicheEmargement(_FinReport):        # hérite du socle commun
    DOC_NAME = "Fiche d'émargement"

    def __init__(self, month, school, payments):
        super().__init__(orientation="L", school=school)             # paysage
        self.month = month
        label = f"{MONTHS_FR[month.month]} {month.year}"

        # les paies de salaire réellement enregistrées ce mois
        self.payments = payments

        self.set_font('inter', '', 8)
        self.start(f"FICHE D'ÉMARGEMENT DES SALAIRES — {label.upper()}")
        self._table()
        self._totals_and_signatures()

    def _table(self):
        self.ln(2)
        # 8 + 75 + 34 + 15 + 27 + 27 + 49 + 50 = 285
        col_widths = (8, 75, 34, 15, 27, 27, 49, 50)
        header = ["N°", "NOM(S) ET PRÉNOM(S)", "POSTE", "Heures", "CONTACT", "MONTANT", "N° PIÈCE D'IDENTITÉ",
                  "SIGNATURE / EMPREINTE"]
        self.set_font("inter", "", 8.5)
        table = Table(self, line_height=9, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(220)
        for h in header:
            th.cell(f"**{h}**")
        self.set_fill_color(0)

        for i, t in enumerate(self.payments, start=1):
            p = t.beneficiary
            row = table.row()
            row.cell(str(i))
            row.cell(str(p) if p else "—", align="L")
            poste = self._fit((p.poste_display() if p.poste != "Autre" else "—") if p else "—", 32, 8.5, False)
            row.cell(poste)
            # heures RÉELLES du mois (renseignées seulement pour l'horaire)
            row.cell(f"{t.hours:g}" if t.hours else "—")
            row.cell((p.contact or "—") if p else "—")
            row.cell(fmt(t.amount), align="R")
            row.cell("")                  # N° pièce d'identité : à la main
            row.cell("")                  # Signature / empreinte : à la main
        table.render()

    def _fit(self, text, max_w, size, bold=False):
        if not text:
            return ""
        self.set_font('inter', 'B' if bold else '', size)
        if self.get_string_width(text) <= max_w:
            return text
        ell = "…"
        while text and self.get_string_width(text + ell) > max_w:
            text = text[:-1]
        return text + ell

    def _totals_and_signatures(self):
        y = self.get_y()
        total = sum(t.amount for t in self.payments)
        self.ln(1)
        self.set_font("inter", "B", 10)
        self.set_text_color(*GREEN)
        self.cell(0, 6, f"TOTAL : {fmt(total)} FCFA", align="R")
        if y > 168:
            self.add_page()
        else:
            self.ln(2)
        self.set_font("inter", "I", 8.5)
        self.set_text_color(60, 72, 88)
        self.cell(0, 5, f"Arrêtée la présente fiche à la somme de : "
                        f"{number_to_words_fr(total)} francs CFA.", align="L")
        self.ln(5)
        self.set_font("inter", "", 9)
        self.set_text_color(0)
        self.cell(138, 5, "                 Le Caissier", align="L")
        self.cell(138, 5, "Le Chef d'établissement              ", align="R")


def fmt(n):
    return f"{n:,}".replace(",", " ")


# ---------------------------------------------------------------------------
# INSOLVABLES D'UNE CLASSE
# ---------------------------------------------------------------------------
class DefaultersListPDF(_FinReport):
    DOC_NAME = "Insolvables"

    def __init__(self, classroom, year, data, fee_type=None, on_installments=False, school=None):
        super().__init__(orientation="P", school=school)
        crit = "retard sur tranches échues" if on_installments else "reste à payer"
        sub = f"Année {year} • Critère : {crit}"
        if fee_type:
            sub += f" • Frais : {fee_type}"
        self.set_font("inter", "", 8)
        self.start(f"ÉLÈVES INSOLVABLES — {classroom.code}", sub)

        self.set_font("inter", "", 8)
        col_widths = (8, 22, 62, 40, 22, 22, 22)
        header = ["N°", "MATRICULE", "NOM(S) ET PRÉNOM(S)", "FRAIS", "DÛ NET", "PAYÉ", "RESTE"]
        table = Table(self, line_height=5.5, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(220)
        for h in header:
            th.cell(f"**{h}**")
        self.set_fill_color(0)

        total_due = 0
        i = 0
        for student, rows in data:
            for r in rows:
                i += 1
                key = "retard" if on_installments else "reste"
                total_due += r[key]
                row = table.row()
                row.cell(str(i))
                row.cell(str(student.unique_id) or "—")
                row.cell(str(student), align="L")
                row.cell(str(r["fee_type"]), align="L")
                row.cell(fmt(r["du_net"]), align="R")
                row.cell(fmt(r["paye"]), align="R")
                row.cell(f"**{fmt(r[key])}**", align="R")
        table.render()

        self.ln(1)
        self.set_font("inter", "B", 10)
        self.set_text_color(*RED)
        self.cell(0, 6, f"TOTAL À RECOUVRER : {fmt(total_due)} FCFA "
                        f"({i} ligne(s))", align="R")


# ---------------------------------------------------------------------------
# CONVOCATIONS DES PARENTS (2 par page)
# ---------------------------------------------------------------------------
class ConvocationsPDF(_FinReport):
    DOC_NAME = "Convocations"

    def __init__(self, classroom, year, data, school, meet_date="", meet_time=""):
        super().__init__(orientation="P", school=school)
        self.set_auto_page_break(False)
        try:
            self._cachet_bytes = stamp_bytes(school.cachet)
            self._visa_bytes = stamp_bytes(school.visa)
        except Exception:
            self._cachet_bytes = None
            self._visa_bytes = None

        for slot, (student, rows) in enumerate(data):
            if slot % 2 == 0:
                self.add_page()
                filigrane(self)
                filigrane(self, y=218.5)
            y0 = 12 if slot % 2 == 0 else 160.5
            self._convocation(student, rows, y0, classroom, year, meet_date, meet_time)
            if slot % 2 == 0:
                self.set_draw_color(*GREY)
                self.set_dash_pattern(dash=2, gap=2)
                self.line(8, 148.5, 202, 148.5)
                self.set_dash_pattern()

    def _convocation(self, student, rows, y0, classroom, year, mdate, mtime):
        s = self.school
        if y0 == 12:
            self.set_xy(6, 6)
            self.set_font("inter", "", 8)
            base_header(self)
        else:
            self.set_xy(6, 154.5)
            self.set_font("inter", "", 8)
            base_header(self, y_img=148.5)
        L, R = 16, 194

        self.set_font("inter", "B", 11)
        self.set_text_color(*RED)
        self.set_xy(L, y0 + 20 + 13)
        self.cell(R - L, 6, "CONVOCATION DES PARENTS", align="C")

        self.set_font("inter", "", 9)
        self.set_text_color(0)
        reste_total = sum(r["reste"] for r in rows)
        frais_txt = ", ".join(f"{r['fee_type']} ({fmt(r['reste'])} F)" for r in rows)
        rdv = (f" le **{format_date(mdate)}**" + (f" à **{mtime}**" if mtime else "")) if mdate else ""
        texte = (f"Monsieur / Madame, parent de l'élève **{student}** "
                 f"({classroom.code}, matricule {student.unique_id or '—'}), "
                 f"vous êtes prié(e) de bien vouloir vous présenter à la "
                 f"direction de l'établissement{rdv}, au sujet de la situation "
                 f"financière de votre enfant pour l'année scolaire {year} : {frais_txt}. "
                 f"Soit un reste total à payer de {fmt(reste_total)} FCFA "
                 f"({number_to_words_fr(reste_total)} francs CFA).")
        self.set_xy(L, y0 + 20 + 24)
        self.multi_cell(R - L, 5.2, texte, align="J", markdown=True)

        yy = self.get_y() + 8
        self.set_font("inter", "", 8.5)
        self.set_xy(L, yy)
        self.cell(90, 5, "Comptant sur votre diligence.", align="L")
        self.set_xy(R - 70, yy)
        self.cell(70, 5, f"**Le {s.chef}**", align="C", markdown=True)
        paste_stamp(self, self._cachet_bytes, x=R - 75, y=yy + 4, w=40)
        paste_stamp(self, self._visa_bytes, x=R - 40, y=yy + 19, w=50)

    def footer(self):
        pass


# ---------------------------------------------------------------------------
# RECOUVREMENT PAR CLASSE
# ---------------------------------------------------------------------------
class RecoveryReportPDF(_FinReport):
    DOC_NAME = "Recouvrement"

    def __init__(self, classrooms, year, school, fee_type=None):
        super().__init__(orientation="P", school=school)
        sub = f"Année {year}" + (f" • Frais : {fee_type}" if fee_type else " • Tous frais entrant en caisse")
        self.set_font("inter", "", 8)
        self.start("TAUX DE RECOUVREMENT PAR CLASSE", sub)

        self.set_font("inter", "", 8)
        col_widths = (40, 20, 34, 34, 34, 24)
        header = ["CLASSE", "EFFECTIF", "ATTENDU", "ENCAISSÉ", "RESTE", "TAUX"]
        table = Table(self, line_height=6, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(220)
        for h in header:
            th.cell(f"**{h}**")
        self.set_fill_color(0)

        g_att = g_enc = 0
        for classroom in classrooms:
            att = enc = 0
            students = classroom.students.all()
            for st in students:
                for r in st.student_fee_status(year):
                    if fee_type and r["fee_type"].id != fee_type.id:
                        continue
                    if not fee_type and not r["affects_cashbox"]:
                        continue
                    att += r["du_net"]
                    enc += min(r["paye"], r["du_net"])
            g_att += att
            g_enc += enc
            taux = formated_float((enc / att) * 100) if att else '—'
            row = table.row()
            row.cell(classroom.code, align="L")
            row.cell(str(students.count()))
            row.cell(fmt(att) + ' FCFA' if att else "—", align="R")
            row.cell(fmt(enc) + ' FCFA' if enc else "—", align="R")
            row.cell(fmt(att - enc) + ' FCFA' if att else "—", align="R")
            row.cell(f"**{str(taux) + ' %' if taux != '—' else '—'}**")
        row = table.row()
        row.cell("**ENSEMBLE**", align="L")
        row.cell("")
        row.cell(f"**{fmt(g_att) + ' FCFA' if g_att else '—'}**", align="R")
        row.cell(f"**{fmt(g_enc) + ' FCFA' if g_enc else '—'}**", align="R")
        row.cell(f"**{fmt(g_att - g_enc) + ' FCFA' if g_att else '—'}**", align="R")
        row.cell(f"**{str(formated_float((g_enc / g_att) * 100)) + ' %' if g_att else '—'}**")
        table.render()


# ---------------------------------------------------------------------------
# JOURNAL DE CAISSE
# ---------------------------------------------------------------------------
class CashJournalPDF(_FinReport):
    DOC_NAME = "Journal de Caisse"

    def __init__(self, date_from, date_to, opening, entries, closing, school):
        super().__init__(orientation="L", school=school)
        self.set_font("inter", "", 8)
        self.start("JOURNAL DE CAISSE", f"Du {date_from:%d/%m/%Y} au {date_to:%d/%m/%Y} • "
                   f"Solde d'ouverture : {fmt(opening)} FCFA")

        self.set_font("inter", "", 8)
        col_widths = (22, 95, 32, 28, 34, 34, 40)
        header = ["DATE", "LIBELLÉ", "RÉF.", "MODE", "ENTRÉE", "SORTIE", "SOLDE"]
        table = Table(self, line_height=5.5, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(220)
        for h in header:
            th.cell(f"**{h}**")
        self.set_fill_color(0)

        tin = tout = 0
        for e in entries:
            if e["sens"] > 0:
                tin += e["montant"]
            else:
                tout += e["montant"]
            row = table.row()
            row.cell(e["date"].strftime("%d/%m/%Y"))
            row.cell(e["libelle"][:70], align="L")
            row.cell(e["ref"] or "—")
            row.cell(e["methode"])
            row.cell(f"{fmt(e["montant"])} FCFA" if e["sens"] > 0 else "", align="R")
            row.cell(f"{fmt(e["montant"])} FCFA" if e["sens"] < 0 else "", align="R")
            row.cell(f"{fmt(e["solde"])} FCFA", align="R")
        row = table.row()
        row.cell("**TOTAUX**", align="R", colspan=4)
        row.cell(f"**{fmt(tin)} FCFA**", align="R")
        row.cell(f"**{fmt(tout)} FCFA**", align="R")
        row.cell(f"**{fmt(closing)} FCFA**", align="R")
        table.render()

        self.ln(1)
        self.set_font("inter", "I", 8.5)
        self.set_text_color(60, 72, 88)
        self.cell(0, 5, f"Arrêté le présent journal à un solde de : "
                        f"{number_to_words_fr(closing)} francs CFA.", align="L")


# ---------------------------------------------------------------------------
# DÉPENSES & RECETTES PAR CATÉGORIE
# ---------------------------------------------------------------------------
class ExpensesReportPDF(_FinReport):
    DOC_NAME = "Dépenses et Recettes par catégorie"

    def __init__(self, qs, date_from, date_to, school):
        super().__init__(orientation="P", school=school)
        self.set_font("inter", "", 8)
        self.start("DÉPENSES & RECETTES PAR CATÉGORIE", f"Du {date_from:%d/%m/%Y} au {date_to:%d/%m/%Y}")

        for kind, label, color in [
                (TransactionCategory.Kind.EXPENSE, "DÉPENSES", RED),
                (TransactionCategory.Kind.INCOME, "RECETTES DIVERSES", GREEN)]:
            rows = [r for r in qs if r["kind"] == kind]
            self.set_font("inter", "B", 10)
            self.set_text_color(*color)
            self.cell(0, 7, label, align="L")
            self.ln(7)
            self.set_text_color(0)
            total = sum(r["total"] for r in rows)
            self.set_font("inter", "", 8.5)
            table = Table(self, line_height=6, col_widths=(110, 40, 36), text_align="LEFT", markdown=True)
            th = table.row()
            self.set_fill_color(220)
            for h in ["CATÉGORIE", "MONTANT (FCFA)", "PART"]:
                th.cell(f"**{h}**")
            self.set_fill_color(0)
            for r in rows:
                row = table.row()
                row.cell(r["category__nom"])
                row.cell(fmt(r["total"]), align="R")
                row.cell(f"{formated_float((r['total'] / total) * 100) if total else 0} %", align="R")
            row = table.row()
            row.cell("**TOTAL**")
            row.cell(f"**{fmt(total)}**", align="R")
            row.cell("**100 %**" if total else "—", align="R")
            table.render()
            self.ln(6)


"""
=============================================================================
 PaymentReceipt — Reçu de paiement PDF (finance/pdf.py)
=============================================================================
 A4 portrait, DEUX exemplaires identiques (haut = Exemplaire parent,
 bas = Souche établissement) séparés par une ligne de découpe pointillée.
 Montant en chiffres ET EN LETTRES (utils.number_to_words_fr).
 Cachet de l'établissement apposé si disponible (stamp_bytes/paste_stamp).
=============================================================================
"""


class PaymentReceipt(FPDF):
    """pdf = PaymentReceipt(payment) ; bytes(pdf.output()) -> réponse HTTP."""

    def __init__(self, payment, school):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.payment = payment
        self.school = school          # tenant courant
        add_fonts(self)
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)
        self.add_page()
        filigrane(self)
        filigrane(self, y=218.5)
        self.set_xy(6, 6)
        self.set_font("inter", "", 8)
        base_header(self)
        self.set_xy(6, 154.5)
        self.set_font("inter", "", 8)
        base_header(self, y_img=148.5)
        self._draw_copy(y0=20,  label="Exemplaire parent")
        self._cut_line(y=148.5)
        self._draw_copy(y0=168, label="Souche établissement")

    # ------------------------------------------------------------------
    def _cut_line(self, y):
        self.set_draw_color(*GREY)
        self.set_line_width(0.2)
        self.set_dash_pattern(dash=2, gap=2)
        self.line(8, y, 202, y)
        self.set_dash_pattern()                       # retour trait plein
        self.set_font("inter", "", 7)
        self.set_text_color(*GREY)
        #self.set_font("ZapfDingbats", size=18)
        #self.set_xy(202, y - 1.4)
        #self.cell(10, 3, chr(34))

    # ------------------------------------------------------------------
    def _draw_copy(self, y0, label):
        p = self.payment
        s = self.school
        L, R = 14, 196                                 # marges du volet

        # --- titre + n° de reçu ---------------------------------------------
        y = y0 + 19
        self.set_font("inter", "I", 7)
        self.set_text_color(*GREY)
        self.set_xy(L, y + 2)
        self.cell(182, 7, label, align="C")

        self.set_font("inter", "B", 13)
        self.set_text_color(*GREEN)
        self.set_xy(L, y)
        self.cell(110, 7, "REÇU DE PAIEMENT")
        self.set_text_color(*RED)
        self.set_xy(R - 70, y)
        self.cell(70, 7, f"N° {p.receipt_number}", align="R")
        self.set_draw_color(*LINE)
        self.set_line_width(0.4)
        self.line(L, y + 8.5, R, y + 8.5)

        # --- corps : deux colonnes d'infos ----------------------------------
        y += 12
        def field(x, yy, label_, value, w=88, bold=True):
            self.set_font("inter", "", 7)
            self.set_text_color(*GREY)
            self.set_xy(x, yy)
            self.cell(w, 3.5, label_)
            self.set_font("inter", "B" if bold else "", 9.5)
            self.set_text_color(30, 40, 55)
            self.set_xy(x, yy + 3.7)
            self.cell(w, 5, str(value))

        student = p.student
        classe = student.classe.code if student.classe else "—"
        field(L, y,      "Reçu de (élève)", f"{student}")
        field(L + 95, y, "Matricule", student.unique_id or "—", w=45)
        field(L + 145, y, "Classe", classe, w=45)
        y += 11
        field(L, y,      "Au titre de", f"{p.fee_type} — Année {p.school_year}")
        field(L + 95, y, "Date", p.date.strftime("%d/%m/%Y"), w=45)
        field(L + 145, y, "Mode", p.method, w=45)

        # --- montant : chiffres + LETTRES -----------------------------------
        y += 13
        self.set_fill_color(243, 248, 245)
        self.set_draw_color(*LINE)
        self.rect(L, y, R - L, 16, "DF")
        self.set_font("inter", "B", 15)
        self.set_text_color(*GREEN)
        self.set_xy(L + 4, y + 2)
        self.cell(70, 7, f"{p.amount:,} FCFA".replace(",", " "))
        self.set_font("inter", "I", 8.5)
        self.set_text_color(60, 72, 88)
        self.set_xy(L + 4, y + 9.5)
        lettres = number_to_words_fr(p.amount)
        self.cell(R - L - 8, 5, f"Arrêté à la somme de : {lettres} francs CFA")

        # --- situation après paiement (cumul/reste sur CE frais) ------------
        y += 20
        rows = [r for r in student.student_fee_status(p.school_year)
                if r["fee_type"].id == p.fee_type_id]
        if rows:
            r0 = rows[0]
            self.set_font("inter", "", 8)
            self.set_text_color(*GREY)
            self.set_xy(L, y)
            resume = (f"Situation {p.fee_type} : dû net {r0['du_net']:,} • "
                      f"payé {r0['paye']:,} • reste {r0['reste']:,} FCFA"
                      ).replace(",", " ")
            self.cell(120, 5, resume)

        # --- signatures + cachet ---------------------------------------------
        self.set_font("inter", "", 8)
        self.set_text_color(30, 40, 55)
        self.set_xy(L, y + 10)
        self.cell(80, 5, f"Frais encaissés par : {p.received_by.staff_member.__str__()}")
        self.set_xy(R - 60, y + 10)
        self.cell(60, 5, "Signature & cachet", align="R")
