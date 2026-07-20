from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.http import urlencode
from django.urls import reverse

from authentification.models import School
from .models import SchoolFee, FeeInstallment, FeeType, StudentPayment, PaymentMethod
from .forms import StudentPaymentForm
from student.models import Student
from osm.utils import school_year, message, logged_admin_view, stamp_bytes, paste_stamp, resize_image,\
    number_to_words_fr, safe_redirect_back
from classroom.views import add_fonts
from fpdf import FPDF
import json
from datetime import datetime
from django.db import transaction
from classroom.models import Class


# TODO: logged_financial_user
# ---------------------------------------------------------------------------
#  PAGE PRINCIPALE : la grille d'une année
# ---------------------------------------------------------------------------
@logged_admin_view
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

    # niveaux/séries EXISTANTS dans cet établissement (selects dynamiques)
    niveaux = list(Class.objects.exclude(niveau__isnull=True)
                   .values_list("niveau", flat=True).distinct())
    series = [s for s in Class.objects.values_list("serie", flat=True)
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
        "niveaux": niveaux, "series": series,
        "fees_json": fees_json,
        "previous_year": _previous_year(year),
        "has_previous": SchoolFee.objects.filter(
            school_year=_previous_year(year)).exists(),
    })


def _previous_year(year):
    """'2025-2026' -> '2024-2025'."""
    try:
        a, b = year.split("-")
        return f"{int(a)-1}-{int(b)-1}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
#  ENREGISTRER une ligne de grille (création OU édition) + ses tranches
# ---------------------------------------------------------------------------
@logged_admin_view
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
@logged_admin_view
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
@logged_admin_view
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
@logged_admin_view
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
@logged_admin_view
def cash_in(request):
    """?q= : recherche d'élèves ; ?student= : situation + formulaire.
    POST : enregistre le paiement puis propose le reçu."""
    year = school_year()
    context = {'year': year, 'methods': PaymentMethod.choices, 'title': "Encaissement"}

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
@logged_admin_view
def payment_receipt(request, pk):
    """Reçu PDF (2 exemplaires : parent + souche). Réimprimable à volonté."""
    payment = get_object_or_404(
        StudentPayment.objects.select_related("student", "fee_type"), pk=pk)
    pdf = PaymentReceipt(payment)
    response = HttpResponse(bytes(pdf.output()), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="Recu_{payment.receipt_number}.pdf"')
    return response


# ---------------------------------------------------------------------------
#  ANNULATION TRACÉE (jamais de suppression)
# ---------------------------------------------------------------------------
@logged_admin_view
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





"""
=============================================================================
 PaymentReceipt — Reçu de paiement PDF (finance/pdf.py)
=============================================================================
 A4 portrait, DEUX exemplaires identiques (haut = Exemplaire parent,
 bas = Souche établissement) séparés par une ligne de découpe pointillée.
 Montant en chiffres ET EN LETTRES (nombre_en_lettres.number_to_words_fr).
 Cachet de l'établissement apposé si disponible (stamp_bytes/paste_stamp).

 À ADAPTER : imports de tes helpers (add_fonts, stamp_bytes, paste_stamp,
 school data) selon leur emplacement réel.
=============================================================================
"""

GREEN = (10, 125, 63)
RED   = (200, 30, 45)
NAVY  = (10, 61, 98)
GREY  = (110, 120, 132)
LINE  = (215, 222, 230)


class PaymentReceipt(FPDF):
    """pdf = PaymentReceipt(payment) ; bytes(pdf.output()) -> réponse HTTP."""

    def __init__(self, payment):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.payment = payment
        self.school = School.objects.first()          # tenant courant
        add_fonts(self)
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)
        # cachet préchargé UNE fois en bytes (pattern anti "seek of closed file")
        try:
            self._stamp = stamp_bytes("cachet")
        except Exception:
            self._stamp = None
        self.add_page()
        self._draw_copy(y0=10,  label="Exemplaire parent")
        self._cut_line(y=148.5)
        self._draw_copy(y0=158, label="Souche établissement")

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

        # --- en-tête : logo + établissement --------------------------------
        try:
            logo = resize_image(s.logo, new_width=200)
            self.image(logo, x=L, y=y0, w=16, h=16, keep_aspect_ratio=True)
        except Exception:
            pass
        self.set_text_color(*NAVY)
        self.set_font("inter", "B", 11)
        self.set_xy(L + 20, y0)
        self.cell(120, 5, s.nom or "")
        self.set_font("inter", "", 7.5)
        self.set_text_color(*GREY)
        self.set_xy(L + 20, y0 + 5)
        self.cell(120, 4, s.name or "")
        self.set_xy(L + 20, y0 + 9)
        contact = " • ".join(x for x in [s.localite, s.contact, s.email] if x)
        self.cell(120, 4, contact)
        # étiquette d'exemplaire (droite)
        self.set_font("inter", "I", 7)
        self.set_xy(R - 45, y0)
        self.cell(45, 4, label, align="R")

        # --- titre + n° de reçu ---------------------------------------------
        y = y0 + 19
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
        caissier = str(getattr(p.received_by, "get_full_name", lambda: "")()
                       or p.received_by or "")
        self.cell(80, 5, f"Le responsable financier : {p.received_by.staff_member.__str__()}")
        self.set_xy(R - 60, y + 10)
        self.cell(60, 5, "Signature & cachet", align="R")
        if self._stamp:
            try:
                paste_stamp(self, self._stamp, x=R - 42, y=y + 4, w=30)
            except Exception:
                pass
