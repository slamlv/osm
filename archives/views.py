from django.http import JsonResponse, Http404, HttpResponse, FileResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from classroom.models import ClassRoom
from osm.utils import message, logged_admin_view, base_header, add_fonts, logged_admin_view, school_year
from student.models import Student
from .models import ArchivedDocument, YearClosure, DocType, TERMS, MANDATORY_TYPES, NOTE_DEPENDENT
from . import services as S
import datetime
from fpdf import FPDF
from fpdf.table import Table


"""
=============================================================================
 APP `archives` — Vues
=============================================================================
 A. Assistant de clôture      (léger : ne refait que manquant + périmé)
 B. Consultation des archives (navigation, recherche, suppression)
=============================================================================
"""

# ===========================================================================
#  A. ASSISTANT DE CLÔTURE
# ===========================================================================
@logged_admin_view
def closure_wizard(request):
    year = request.user.school.establishment_year
    closure = YearClosure.objects.filter(school_year=year).first()

    ctx = {
        "year": year,
        'title': f"Clôture de l'année scolaire {year}",
        "next_year": S.next_year_label(year),
        "closure": closure,
        "closed": closure.status == YearClosure.Status.CLOSED if closure else False,
        "coherence": S.year_coherence(request.user.school),
        "doc_types": [(t.value, t.label, t.value in MANDATORY_TYPES,
                       t.value in NOTE_DEPENDENT)
                      for t in DocType if t not in [DocType.CLOSURE_REPORT, DocType.BULLETIN_WITH_COMPETENCES]],
    }

    if closure is None:
        holes = S.missing_marks()
        ctx["holes"] = holes[:60]
        ctx["holes_total"] = len(holes)
        ctx["decisions"] = S.missing_decisions(request.user.school, year)
        return render(request, "closure_wizard.html", ctx)

    ctx["steps_view"] = [
        {"key": k, "label": lab, "done": closure.is_done(k),
         "current": k == closure.current_step}
        for k, lab in YearClosure.STEPS]
    ctx["need_select"] = not closure.is_done("select")
    if closure.selected_types:
        state = S.units_state(request.user.school, closure.selected_types, year)
        ctx["state"] = state
        ctx["progress"] = S.refresh_progress(request.user.school, closure)
        ctx["todo_preview"] = state["todo"][:40]
    ctx["can_refresh"] = closure.is_done("select")
    ctx["verify"] = S.verify_archives(request.user.school, closure) if closure.is_done("refresh") else None
    if closure.is_done("verify") and not closure.is_done("consolidate"):
        ctx["need_consolidate"] = True
        ctx["consolidation"] = S.verify_consolidation(request.user.school, year)
    ctx["cleanup_rows"] = S.cleanup_preview() if closure.is_done("consolidate") else None
    return render(request, "closure_wizard.html", ctx)


@require_POST
@logged_admin_view
def closure_start(request):
    year = request.user.school.establishment_year
    holes = S.missing_marks()
    if holes:
        message(request, f"Clôture impossible : {len(holes)} saisie(s) de notes manquante(s).", msg_type="error")
        return redirect("closure_wizard")
    closure, _ = YearClosure.objects.get_or_create(school_year=year, defaults={"started_by": request.user})
    closure.mark("checks", {"holes": 0}, save=False)
    closure.mark("decisions", S.missing_decisions(request.user.school, year))
    message(request, "Vérifications passées.")
    return redirect("closure_wizard")


@require_POST
@logged_admin_view
def closure_select(request):
    closure = get_object_or_404(YearClosure, school_year=request.user.school.establishment_year)
    closure.selected_types = sorted(set(request.POST.getlist("types")) | set(MANDATORY_TYPES))
    closure.status = YearClosure.Status.REFRESHING
    closure.save(update_fields=["selected_types", "status"])
    closure.mark("select", {"types": closure.selected_types})
    message(request, "Sélection enregistrée — les notes sont désormais verrouillées pour cette année.")
    return redirect("closure_wizard")


@require_POST
@logged_admin_view
def refresh_next(request):
    """Traite UNE unité manquante ou périmée (appelé en boucle par le
    navigateur). Les unités déjà à jour ne sont jamais retouchées."""
    closure = get_object_or_404(YearClosure, school_year=request.user.school.establishment_year)
    try:
        label, finished = S.refresh_one(request.user.school, closure, user=request.user)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=200)
    progress = S.refresh_progress(request.user.school, closure)
    if finished:
        closure.status = YearClosure.Status.ARCHIVED
        closure.save(update_fields=["status"])
        closure.mark("refresh", progress)
    return JsonResponse({"label": label or "", "finished": finished, **progress})


@require_POST
@logged_admin_view
def closure_verify(request):
    closure = get_object_or_404(YearClosure, school_year=request.user.school.establishment_year)
    result = S.verify_archives(request.user.school, closure)
    if result["ok"]:
        closure.mark("verify", result)
        message(request, f"Intégrité vérifiée : {result['count']} document(s).")
    else:
        message(request, f"Vérification échouée : {result['missing']} manquant(s), {result['stale']} périmé(s).",
                msg_type="error")
    return redirect("closure_wizard")


@require_POST
@logged_admin_view
def closure_consolidate(request):
    """Vérifie que les résultats sont figés ; comble les trous si demandé.

    Ne recalcule jamais : combler consiste à régénérer les bulletins
    manquants, ce qui déclenche le gel par le chemin normal.
    """
    closure = get_object_or_404(YearClosure, school_year=request.user.school.establishment_year)
    report = S.verify_consolidation(request.user.school, closure.school_year)

    if not report["ok"] and request.POST.get("fill") == "1":
        filled = S.fill_consolidation_gaps(request.user.school, closure, user=request.user)
        report = S.verify_consolidation(request.user.school, closure.school_year)
        message(request, f"{filled['regenerated']} bulletin(s) régénéré(s) — "
                         f"{report['count']} inscription(s) encore incomplète(s).")

    if report["ok"]:
        closure.mark("consolidate", {"count": 0})
        message(request, "Résultats consolidés : tous les parcours sont complets.")
    else:
        message(request, f"{report['count']} inscription(s) sans résultats figés. Comblez les trous avant de "
                         f"poursuivre.", msg_type="error")
    return redirect("closure_wizard")


@require_POST
@logged_admin_view
def closure_cleanup(request):
    closure = get_object_or_404(YearClosure, school_year=request.user.school.establishment_year)
    if (request.POST.get("confirm") or "").strip() != closure.school_year:
        message(request, "Confirmation incorrecte : aucune donnée n'a été supprimée.", msg_type="error")
        return redirect("closure_wizard")
    try:
        deleted = S.cleanup_year(request.user.school, closure, keys=request.POST.getlist("targets"))
    except RuntimeError as exc:
        message(request, str(exc), "error")
        return redirect("closure_wizard")
    closure.status = YearClosure.Status.CLEANED
    closure.save(update_fields=["status"])
    closure.mark("cleanup", deleted)
    message(request, "Nettoyage effectué.")
    return redirect("closure_wizard")


@require_POST
@logged_admin_view
def closure_promote(request):
    closure = get_object_or_404(YearClosure, school_year=request.user.school.establishment_year)
    closure.classrooms = ClassRoom.objects.count()
    closure.students = Student.objects.count()
    closure.save(update_fields=["classrooms", "students"])
    detail = S.promote_year(request.user.school, closure)
    closure.mark("promote", detail)
    closure.status = YearClosure.Status.CLOSED
    closure.closed_by = request.user
    closure.closed_at = timezone.now()
    closure.save(update_fields=["status", "closed_by", "closed_at"])

    try:                                        # rapport de clôture archivé
        pdf = ClosureReport(closure)
        data = bytes(pdf.output())
        doc = ArchivedDocument(school_year=closure.school_year, doc_type=DocType.CLOSURE_REPORT,
                               title="Rapport de clôture")
        doc.store("rapport-cloture.pdf", data, user=request.user)
    except Exception:
        pass

    message(request, f"Année {closure.school_year} clôturée • {detail['new_year']} ouverte • "
                     f"{detail['moved']} élève(s) réinscrit(s).")
    return redirect("archives_index")


# ===========================================================================
#  B. CONSULTATION DES ARCHIVES
# ===========================================================================
@logged_admin_view
def archives_index(request):
    rows = []
    print(ArchivedDocument.objects.all().delete())
    for y in ArchivedDocument.objects.values_list("school_year", flat=True).distinct().order_by("-school_year"):
        docs = ArchivedDocument.objects.filter(school_year=y, size_bytes__gt=0)
        rows.append({"year": y, "count": docs.count(), "size": sum(docs.values_list("size_bytes", flat=True))})
    return render(request, "archives_index.html",
                  {"years": rows, "current": request.user.school.establishment_year, 'title': "Archives"})


@logged_admin_view
def archives_year(request, year):
    docs = ArchivedDocument.objects.filter(school_year=year, size_bytes__gt=0)
    if not docs.exists():
        raise Http404
    groups = []
    for value, label in DocType.choices:
        sub = docs.filter(doc_type=value)
        if sub.exists():
            groups.append({"type": value, "label": label, "count": sub.count(),
                           "size": sum(sub.values_list("size_bytes", flat=True)),
                           "deletable": value not in MANDATORY_TYPES})
    return render(request, "archives_year.html",
                  {"year": year, "groups": groups, 'title': f"Archives / {year}"})


@logged_admin_view
def archives_type(request, year, doc_type):
    docs = (ArchivedDocument.objects.filter(school_year=year, doc_type=doc_type, size_bytes__gt=0)
            .select_related("classroom").order_by("classroom_label", "term_index"))
    by_class = {}
    for d in docs:
        by_class.setdefault(d.classroom_label or "Établissement", []).append(d)
    label = DocType(doc_type).label
    return render(request, "archives_type.html", {
        "year": year, "doc_type": doc_type, "label": label, 'title': f"Archives / {year} / {label}",
        "deletable": doc_type not in MANDATORY_TYPES, "by_class": list(by_class.items()),
    })


@require_POST
@logged_admin_view
def archive_delete(request, pk):
    """Suppression d'une archive OPTIONNELLE. Les bulletins sont protégés."""
    doc = get_object_or_404(ArchivedDocument, pk=pk)
    if not doc.is_deletable:
        message(request, "Les bulletins ne peuvent pas être supprimés.", msg_type="error")
        return redirect("archives_type", year=doc.school_year, doc_type=doc.doc_type)
    year, dtype, title = doc.school_year, doc.doc_type, str(doc)
    try:
        doc.file.delete(save=False)
    except Exception:
        pass
    doc.delete()
    message(request, f"Archive supprimée : {title}.")
    return redirect("archives_type", year=year, doc_type=dtype)


@logged_admin_view
def archive_download(request, pk):
    """Extrait les seules pages de l'élève : il reçoit SON bulletin."""
    from urllib.parse import quote
    doc = get_object_or_404(ArchivedDocument, pk=pk)
    label = DocType(doc.doc_type).label
    trim = (
        ((("Trimestre 1", "Trimestre 2")[doc.term_index == 2], "Trimestre 3")[doc.term_index == 3], "Annuel")[doc.term_index == 0]
    ) if doc.term_index is not None else None
    cls = doc.classroom_label
    filename = f"{label}{f' {cls} ' if cls else ' '}{f' {trim} ' if trim else ' '}{doc.school_year}.pdf"
    filename_ascii = filename.encode('ascii', 'ignore').decode('ascii')
    quoted = quote(filename)
    resp = FileResponse(doc.file.open('rb'), as_attachment=True, filename=filename_ascii)
    resp['Content-Disposition'] = (
        f"attachment; filename='{filename_ascii}'; filename*=UTF-8''{quoted}"
    )
    return resp


@require_POST
@logged_admin_view
def archive_delete_group(request, year, doc_type):
    """Suppression de TOUT un type de documents d'une année (optionnels)."""
    if doc_type in MANDATORY_TYPES:
        message(request, "Les bulletins ne peuvent pas être supprimés.", "error")
        return redirect("archives_year", year=year)
    docs = ArchivedDocument.objects.filter(school_year=year, doc_type=doc_type)
    n = docs.count()
    for d in docs:
        try:
            d.file.delete(save=False)
        except Exception:
            pass
    docs.delete()
    message(request, f"{n} archive(s) supprimée(s).")
    return redirect("archives_year", year=year)


@logged_admin_view
def archives_search(request):
    """Retrouver les bulletins d'un ancien élève, toutes années confondues."""
    from django.db.models import Q

    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        for st in Student.objects.filter(Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(unique_id__icontains=q))[:10]:
            docs = (ArchivedDocument.objects
                    .filter(doc_type__in=[DocType.BULLETIN, DocType.BULLETIN_WITH_COMPETENCES], page_map__has_key=str(st.id))
                    .order_by("-school_year", "term_index"))
            if docs:
                results.append({"student": st, "docs": docs})
    return render(request, "archives_search.html", {"q": q, "results": results})


@logged_admin_view
def student_bulletin(request, doc_id, student_id):
    """Extrait les seules pages de l'élève : il reçoit SON bulletin."""
    from urllib.parse import quote
    doc = get_object_or_404(ArchivedDocument, pk=doc_id)
    pages = (doc.page_map or {}).get(str(student_id))
    if not pages or not doc.file:
        raise Http404("Bulletin introuvable dans cette archive.")
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    doc.file.open("rb")
    reader = PdfReader(doc.file)
    writer = PdfWriter()
    for p in range(pages[0] - 1, min(pages[1], len(reader.pages))):
        writer.add_page(reader.pages[p])
    buf = BytesIO()
    writer.write(buf)
    doc.file.close()
    buf.seek(0)

    student = Student.objects.get(id=student_id)
    trim = ((("Trimestre 1", "Trimestre 2")[doc.term_index == 2], "Trimestre 3")[doc.term_index == 3], "Annuel")[doc.term_index == 0]
    filename = f"Bulletin {trim} {doc.school_year} {student.short_name}.pdf"
    filename_ascii = filename.encode('ascii', 'ignore').decode('ascii')
    quoted = quote(filename)
    resp = FileResponse(buf, as_attachment=True, filename=filename_ascii)
    resp['Content-Disposition'] = (
        f"attachment; filename='{filename_ascii}'; filename*=UTF-8''{quoted}"
    )
    return resp


"""
=============================================================================
 ClosureReport — Rapport de clôture (archivé avec le reste)
=============================================================================
 Pièce de traçabilité : QUI a clôturé, QUAND, ce qui était déjà archivé au
 fil de l'année, ce qui a dû être régénéré, ce qui a été supprimé, et l'état
 de la nouvelle année. C'est le document à ressortir si l'on demande des
 comptes sur une année effacée.
=============================================================================
"""
GREEN = (10, 125, 63)
RED   = (200, 30, 45)
GREY  = (110, 120, 132)


class ClosureReport(FPDF):
    def __init__(self, closure):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.alias_nb_pages()
        add_fonts(self)
        self.set_margins(10, 10, 10)
        self.set_auto_page_break(True, margin=14)
        self.closure = closure
        self.now = datetime.datetime.now().strftime("%d-%m-%Y à %H:%M")
        self.add_page()
        self.set_font("inter", "", 8)
        base_header(self, mode="P", y_img=4)
        self._title()
        self._identity()
        self._archives()
        self._refresh()
        self._cleanup()
        self._promotion()

    # ------------------------------------------------------------------
    def _title(self):
        self.ln(3)
        self.set_font("inter", "B", 14)
        self.set_text_color(*GREEN)
        self.cell(0, 8, f"RAPPORT DE CLÔTURE — ANNÉE {self.closure.school_year}", align="C")
        self.ln(9)
        self.set_font("inter", "I", 8)
        self.set_text_color(*GREY)
        self.cell(0, 4, "Document de traçabilité — conservé dans les archives", align="C")
        self.ln(8)
        self.set_text_color(0)

    def _section(self, titre):
        self.ln(3)
        self.set_font("inter", "B", 10.5)
        self.set_text_color(*GREEN)
        self.cell(0, 6, titre)
        self.ln(7)
        self.set_font("inter", "", 9)
        self.set_text_color(0)

    def _line(self, label, value):
        self.set_font("inter", "", 9)
        self.set_text_color(*GREY)
        self.cell(66, 5.5, label)
        self.set_font("inter", "B", 9.5)
        self.set_text_color(20, 30, 45)
        self.cell(0, 5.5, str(value))
        self.ln(5.5)

    # ------------------------------------------------------------------
    def _identity(self):
        c = self.closure
        self._section("1. Identification")
        self._line("Année clôturée", c.school_year)
        self._line("Lancée par", c.started_by or "—")
        self._line("Lancée le", c.started_at.strftime("%d/%m/%Y à %H:%M")
                   if c.started_at else "—")
        self._line("Clôturée par", c.closed_by or "—")
        self._line("Clôturée le", c.closed_at.strftime("%d/%m/%Y à %H:%M")
                   if c.closed_at else "—")
        self._line("Documents conservés",
                   ", ".join(DocType(t).label for t in (c.selected_types or []))
                   or "—")

    def _archives(self):
        c = self.closure
        self._section("2. Documents archivés")
        docs = ArchivedDocument.objects.filter(school_year=c.school_year)
        table = Table(self, line_height=5.5, col_widths=[92, 26, 26, 26, 20],
                      text_align="LEFT", markdown=True)
        th = table.row()
        self.set_fill_color(220)
        for h in ["Type de document", "Unités", "Pages", "Taille", "Régén."]:
            th.cell(f"**{h}**")
        self.set_fill_color(0)
        t_size = t_units = t_regen = 0
        for value, label in DocType.choices:
            sub = docs.filter(doc_type=value)
            if not sub.exists():
                continue
            size = sum(sub.values_list("size_bytes", flat=True))
            pages = sum(sub.values_list("page_count", flat=True))
            regen = sum(max(0, (v or 1) - 1)
                        for v in sub.values_list("versions", flat=True))
            t_size += size; t_units += sub.count(); t_regen += regen
            row = table.row()
            row.cell(label)
            row.cell(str(sub.count()), align="CENTER")
            row.cell(str(pages or "—"), align="CENTER")
            row.cell(f"{size/1024/1024:.1f} Mo", align="RIGHT")
            row.cell(str(regen or "—"), align="CENTER")
        row = table.row()
        row.cell("**TOTAL**")
        row.cell(f"**{t_units}**", align="CENTER")
        row.cell("")
        row.cell(f"**{t_size/1024/1024:.1f} Mo**", align="RIGHT")
        row.cell(f"**{t_regen or '—'}**", align="CENTER")
        table.render()
        self.ln(2)
        self.set_font("inter", "I", 7.5)
        self.set_text_color(*GREY)
        self.multi_cell(0, 4,
                        "« Régén. » compte les régénérations dues à une "
                        "modification des notes après un premier archivage.")

    def _refresh(self):
        d = self.closure.detail("refresh")
        if not d:
            return
        self._section("3. Mise à jour à la clôture")
        self._line("Documents contrôlés", d.get("total", "—"))
        self._line("Régénérés à la clôture", d.get("todo", 0) or "aucun")

    def _cleanup(self):
        self._section("4. Données supprimées")
        detail = self.closure.detail("cleanup")
        if not detail:
            self.set_text_color(*GREY)
            self.cell(0, 5, "Aucune suppression effectuée.")
            self.ln(6)
            return
        self.set_font("inter", "", 9)
        for label, n in detail.items():
            self.set_text_color(*RED)
            self.cell(5, 5.5, "•")
            self.set_text_color(20, 30, 45)
            self.cell(0, 5.5, f"{label} : {n}")
            self.ln(5.5)
        self.ln(1)
        self.set_font("inter", "I", 8)
        self.set_text_color(*GREY)
        self.multi_cell(0, 4.2,
                        "Conservés : archives, parcours des élèves (moyennes et "
                        "rangs par trimestre et annuels), élèves, personnel, et "
                        "l'intégralité des données financières et de paie.")

    def _promotion(self):
        d = self.closure.detail("promote")
        if not d:
            return
        self._section("5. Ouverture de l'année suivante")
        self._line("Nouvelle année", d.get("new_year", "—"))
        self._line("Élèves réinscrits", d.get("moved", 0))
        self._line("Élèves sortis de l'effectif", d.get("left", 0))
        self._line("Élèves sans décision (à traiter)", d.get("pending", 0))

    def footer(self):
        self.set_y(-10)
        self.set_draw_color(200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.set_font("inter", "I", 7)
        self.set_text_color(*GREY)
        self.cell(95, 6, f"Oméga School Manager — généré le {self.now}", align="L")
        self.cell(95, 6, f"Rapport de clôture • Page {self.page_no()}/{{nb}}",
                  align="R")
