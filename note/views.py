# Create your views here.
import datetime
import os.path
import threading
import time
import copy
from io import BytesIO
import uuid
import django.db.models
from urllib.parse import quote
from osm.utils import formated_float, resized_image, school_year, message, LoggedUserView, LoggedAdminView, \
    logged_user_view, logged_admin_view, resize_image, truncate_str, generate_temp_file, download_and_delete, \
    base_infos, base_header
from django.db.models import Sum
from django.http import Http404, HttpResponse, JsonResponse, FileResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.urls import reverse
from django.views import View
from classroom.models import ClassRoom, Enseignements
from note.models import Period, Note
from staff.models import Personnel
from note.forms import MarksForm, SelectForm, PeriodForm, CheckForm, LevelMarksForms, MarksCopyForm
from django.utils import timezone
from fpdf import FPDF
from fpdf.fonts import FontFace
from fpdf.table import CellBordersLayout, VAlign, Table, TableHeadingsDisplay, Row, Cell
from authentification.models import User


@logged_user_view
def competences(request, evl: int):
    compt, compt1 = request.POST['competences'], request.POST['competences1']
    if compt:
        compt1 = compt
    elif compt1:
        compt = compt1
    classroom = ClassRoom.objects.all()[0]
    data = {'classroom': classroom, 'enseignement': None, 'eval': evl, "request": request, 'trim': True,
            'compts': (compt, compt1)}
    marks_form = MarksForm(context=data, method="GET")
    return render(request, "competences.html", {"marks_form": marks_form, 'evl': evl})


class TLevelMarksEdit(LoggedUserView):
    template_name = "level_marks_form.html"
    title = "Remplissage des Notes trimestrielles par niveau"

    def get(self, *args, **kwargs):
        niveau, did, evl = self.request.GET['classroom'], self.request.GET["matiere_level"], int(self.request.GET["eval"])
        evl_in = (([1, 2], [3, 4])[evl == 2], [5, 6])[evl == 3]
        result = MarksEdit.check_period(self, evl_in, trim=True)
        if result == 0:
            data, matiere = LevelMarksEdit.get_object(niveau=niveau, enseignement_id=did, evaluation=evl,
                                                      user=self.request.user, request=self.request, trim=True)
            level_marks_form = LevelMarksForms(context=data, method="GET")
            context = {"title": f"{self.title}", "level_marks_form": level_marks_form, "evalx": evl_in, 'trim': True,
                       "matiere": matiere, "niveau": niveau, "error": False, 'evl': evl}
        else:
            context = {"admin": result[0], "error": True, "info": result[1], "title": self.title}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        niveau, did, evl = self.request.POST['classroom'], self.request.POST["matiere_level"],\
            int(self.request.POST["eval"])
        evl_in = (([1, 2], [3, 4])[evl == 2], [5, 6])[evl == 3]
        data, matiere = LevelMarksEdit.get_object(niveau=niveau, enseignement_id=did, evaluation=evl,
                                                  user=self.request.user, request=self.request, trim=True)
        level_marks_form = LevelMarksForms(context=data, method="POST")
        context = {"title": f"{self.title}", "level_marks_form": level_marks_form, "evalx": evl_in,
                   "matiere": matiere, "niveau": niveau, 'trim': True, 'evl': evl}
        if level_marks_form.level_marks_form[0].is_valid():
            if level_marks_form.isvalid():
                if data['with_competences']:
                    compt = level_marks_form.level_marks_form[0].cleaned_data["competences"]
                    compt1 = level_marks_form.level_marks_form[0].cleaned_data["competences1"]
                else:
                    compt, compt1 = None, None
                x = level_marks_form.save((compt, compt1))
                y = LevelMarksForms.marks_check(ens=data["enseignements"], evl=evl_in)
                if x:
                    if not y:
                        message(self.request, "Les données ont été enregistrées avec succès, aucune note enregistrée.")
                    else:
                        message(self.request, "Les données ont été enregistrées avec succès.")
                else:
                    message(self.request, "Aucune modification effectuée.", msg_type="warning")
            else:
                message(self.request, "Les notes doivent être comprises entre 0 et 20", msg_type="warning")
        else:
            message(self.request, "Veuillez entrer les compétences.", msg_type="warning")
        response = render(self.request, self.template_name, context)
        response['HX-Trigger'] = 'AJAXMessages'
        return response

    @classmethod
    def get_object(cls, niveau, enseignement_id, evaluation, user):
        staff_member = Personnel.objects.get(user_id=user.id)
        enseignements = staff_member.rapporteur.all().filter(matiere__sujet_id=enseignement_id,
                                                             classroom__classe__niveau=niveau)
        data = {"enseignements": enseignements, "eval": evaluation}
        return data


class TLevelMarks(LoggedUserView):
    template_name = "level_marks_edit.html"
    title = "Remplissage des Notes trimestrielles par niveau"

    def get(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(context={"request": self.request, 'trim': True, 'enseignements': enseignements,
                                              'level': True})
            context = {'title': self.title, 'select_form': select_form, 'trim': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(self.request.POST, context={"request": self.request, 'trim': True,
                                                                 'enseignements': enseignements, 'level': True})
            context = {'title': self.title, 'select_form': select_form, 'trim': True}
        return render(self.request, self.template_name, context)


class LevelMarksEdit(LoggedUserView):
    template_name = "level_marks_form.html"
    title = "Remplissage des Notes par niveau"

    def get(self, *args, **kwargs):
        niveau, did, evl = self.request.GET['classroom'], self.request.GET["matiere_level"], int(self.request.GET["eval"])
        result = MarksEdit.check_period(self, (evl,))
        if result == 0:
            data, matiere = LevelMarksEdit.get_object(niveau=niveau, enseignement_id=did, evaluation=evl,
                                                      user=self.request.user, request=self.request)
            level_marks_form = LevelMarksForms(context=data, method="GET")
            context = {"title": f"{self.title}", "level_marks_form": level_marks_form, "eval": evl, 'trim': False,
                       "matiere": matiere, "niveau": niveau, "error": False}
        else:
            context = {"admin": result[0], "error": True, "info": result[1], "title": self.title}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        niveau, did, evl = self.request.POST['classroom'], self.request.POST["matiere_level"],\
            int(self.request.POST["eval"])
        data, matiere = LevelMarksEdit.get_object(niveau=niveau, enseignement_id=did, evaluation=evl,
                                                  user=self.request.user, request=self.request)
        level_marks_form = LevelMarksForms(context=data, method="POST")
        context = {"title": f"{self.title}", "level_marks_form": level_marks_form, "eval": evl, 'trim': False,
                   "matiere": matiere, "niveau": niveau}
        if level_marks_form.level_marks_form[0].is_valid():
            if level_marks_form.isvalid():
                if data['with_competences']:
                    compt = level_marks_form.level_marks_form[0].cleaned_data["competences"]
                else:
                    compt = None
                x = level_marks_form.save((compt,))
                y = LevelMarksForms.marks_check(ens=data["enseignements"], evl=evl)
                if x:
                    if not y:
                        message(self.request, "Les données ont été enregistrées avec succès, aucune note enregistrée.")
                    else:
                        message(self.request, "Les données ont été enregistrées avec succès.")
                else:
                    message(self.request, "Aucune modification effectuée.", msg_type="warning")
            else:
                message(self.request, "Les notes doivent être comprises entre 0 et 20", msg_type="warning")
        else:
            message(self.request, "Veuillez entrer les compétences.", msg_type="warning")
        response = render(self.request, self.template_name, context)
        response['HX-Trigger'] = 'AJAXMessages'
        return response

    @classmethod
    def get_object(cls, niveau, enseignement_id, evaluation, user, request, trim=False):
        staff_member = Personnel.objects.get(user_id=user.id)
        enseignements = staff_member.rapporteur.select_related('matiere__sujet', 'classroom__classe').\
            filter(matiere__sujet_id=enseignement_id, classroom__classe__niveau=niveau)
        data = {"enseignements": enseignements, "eval": evaluation, 'request': request, 'trim': trim,
                'with_competences': request.user.school.with_competences}
        matiere = enseignements[0].matiere.sujet.label
        matiere = (f"d'{matiere}", f"de {matiere}")[matiere[0] not in ["A", "E", "I", "H", "0", "U", "Y"]]
        return data, matiere


class LevelMarks(LoggedUserView):
    template_name = "level_marks_edit.html"
    title = "Remplissage des Notes par niveau"

    def get(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(context={"request": self.request, 'trim': False, 'enseignements': enseignements,
                                              'level': True})
            context = {'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(self.request.POST, context={"request": self.request, 'trim': False,
                                                                 'enseignements': enseignements, 'level': True})
            context = {'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)


class TrimesterMarksEdit(LoggedUserView):
    template_name = "marks_form.html"
    title = "Remplissage des Notes trimestrielles"

    def get(self, *args, **kwargs):
        cid, did, evl = self.request.GET["classroom"], self.request.GET["matiere"], int(self.request.GET["eval"])
        evl_in = (([1, 2], [3, 4])[evl == 2], [5, 6])[evl == 3]
        result = MarksEdit.check_period(self, evl_in, trim=True)
        if result == 0:
            data, matiere = MarksEdit.get_object(classroom_id=cid, enseignement_id=did, evaluation=evl,
                                                 request=self.request, trim=True)
            marks_form = MarksForm(context=data, method="GET")
            context = {"title": f"{self.title}", "marks_form": marks_form, "matiere": matiere, 'evalx': evl_in,
                       "classe": data["classroom"].code, "error": False, 'trim': True, 'evl': evl}
        else:
            context = {"admin": result[0], "error": True, "info": result[1], "title": self.title}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        cid, did, evl = self.request.POST["classroom"], self.request.POST["matiere"], int(self.request.POST["eval"])
        evl_in = (([1, 2], [3, 4])[evl == 2], [5, 6])[evl == 3]
        data, matiere = MarksEdit.get_object(classroom_id=cid, enseignement_id=did, evaluation=evl,
                                             request=self.request, trim=True)
        marks_form = MarksForm(self.request.POST or None, context=data, method="POST")
        context = {"title": f"{self.title}", "marks_form": marks_form, 'evalx': evl_in, "matiere": matiere,
                   "classe": data["classroom"].code, 'trim': True, 'evl': evl}
        if marks_form.is_valid():
            if marks_form.isvalid():
                if data['with_competences']:
                    compts = (marks_form.cleaned_data["competences"], marks_form.cleaned_data["competences1"])
                else:
                    compts = (None, None)

                x = marks_form.save(compts)
                y = MarksForm.marks_check(ens=data["enseignement"], evl=evl_in)
                if x:
                    if not y:
                        message(self.request, "Les données ont été enregistrées avec succès, aucune note enregistrée.")
                    else:
                        message(self.request, "Les données ont été enregistrées avec succès.")
                else:
                    message(self.request, "Aucune modification effectuée.", msg_type="warning")
            else:
                message(self.request, "Les notes doivent être comprises entre 0 et 20", msg_type="warning")
        else:
            message(self.request, "Veuillez entrer les compétences.", msg_type="warning")
        response = render(self.request, self.template_name, context)
        response['HX-Trigger'] = 'AJAXMessages'
        return response


class TrimesterMarks(LoggedUserView):
    template_name = "edit_marks.html"
    title = "Remplissage des Notes trimestrielles"

    def get(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(context={"request": self.request, 'trim': True, 'enseignements': enseignements})
            context = {'marks_sheet': False, 'title': self.title, 'select_form': select_form, 'trim': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(self.request.POST,
                                     context={"request": self.request, 'trim': True, 'enseignements': enseignements})
            context = {'marks_sheet': False, 'title': self.title, 'select_form': select_form, 'trim': True}
        return render(self.request, self.template_name, context)


@logged_admin_view
def reload_period(request):
    periods = Period.objects.order_by("evalx")
    period_form = PeriodForm(context={'request': request, 'periods': periods})
    context = {"form": period_form}
    return render(request, "period_form.html", context)


class SetPeriods(LoggedAdminView):
    template_name = "set_periods.html"
    title = "Périodes de remplissage"

    def get(self, *args, **kwargs):
        periods = Period.objects.order_by("evalx")
        period_form = PeriodForm(context={'request': self.request, 'periods': periods})
        context = {"form": period_form, "title": self.title, "periods": periods}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        periods = Period.objects.order_by("evalx")
        period_form = PeriodForm(self.request.POST, context={'request': self.request, 'periods': periods})
        if period_form.is_valid():
            start, end = period_form.cleaned_data["start"], period_form.cleaned_data["end"]
            if start < end:
                period = Period.objects.get(evalx=period_form.cleaned_data["evalx"])
                ex_start, ex_end = period.start, period.end
                if ex_start != start or ex_end != end:
                    period.start = start
                    period.end = end
                    period.save()
                    message(self.request, "Modifications enregistrées avec succès.")
                else:
                    message(self.request, "Aucune modification effectuée.", msg_type="warning")
            else:
                message(self.request, "La date de début doit être inférieure à la date de fin.", msg_type="warning")
        context = {"form": period_form, "title": self.title, "periods": periods}
        return render(self.request, self.template_name, context)


class Marks(LoggedUserView):
    template_name = "edit_marks.html"
    title = "Remplissage des Notes"

    @classmethod
    def check(cls, self):
        staff_member = self.request.user.staff_member.first()
        msg, enseignements = "", None
        if staff_member.rapporteur.exists():
            enseignements = staff_member.rapporteur.select_related('matiere__sujet', 'classroom')
        else:
            msg = "Vous n'êtes affecté à aucune salle de classe"
        return msg, enseignements

    def get(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(context={"request": self.request, 'trim': False, 'enseignements': enseignements})
            context = {'marks_sheet': False, 'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        msg, enseignements = Marks.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(self.request.POST,
                                     context={"request": self.request, 'trim': False, 'enseignements': enseignements})
            context = {'marks_sheet': False, 'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)


@logged_user_view
def classrooms_set(request):
    pg = int(request.GET.get('pg', 0))
    staff_member = request.user.staff_member.first()
    if pg:
        enseignements = staff_member.enseignant.select_related('matiere__sujet', 'classroom')
    else:
        enseignements = staff_member.rapporteur.select_related('matiere__sujet', 'classroom')
    select_form = SelectForm(request.GET, context={"request": request, 'trim': False,
                                                   'enseignements': enseignements, 'pg': pg})
    return render(request, "classrooms.html", {"select_form": select_form})


@logged_user_view
def levels_set(request):
    staff_member = request.user.staff_member.first()
    if staff_member.rapporteur.all().exists():
        enseignements = staff_member.rapporteur.select_related('matiere__sujet', 'classroom')
    select_form = SelectForm(request.GET, context={"request": request, 'trim': False, 'level': True,
                                                   'enseignements': enseignements})
    return render(request, "classrooms.html", {"select_form": select_form, 'level': True})


class MarksEdit(LoggedUserView):
    template_name = "marks_form.html"
    title = "Remplissage des Notes"

    def get(self, *args, **kwargs):
        cid, did, evl = self.request.GET["classroom"], self.request.GET["matiere"], int(self.request.GET["eval"])
        result = MarksEdit.check_period(self, (evl,))
        if result == 0:
            data, matiere = MarksEdit.get_object(classroom_id=cid, enseignement_id=did, evaluation=evl,
                                                 request=self.request)
            marks_form = MarksForm(context=data, method="GET")
            context = {"title": f"{self.title}", "marks_form": marks_form, "eval": evl, 'trim': False,
                       "matiere": matiere, "classe": data["classroom"].code, "error": False}
        else:
            context = {"admin": result[0], "error": True, "info": result[1], "title": self.title}
        return render(self.request, self.template_name, context)

    @classmethod
    def check_period(cls, instance, evl, trim=False):
        for evlx in evl:
            add = "cette évaluation"
            if trim:
                add = f"l'evaluation n° {evlx}"
            period = Period.objects.get(evalx=evlx)
            start, end = period.start, period.end
            plus = "veuillez contacter l'administrateur."
            if not start:
                if instance.request.user.is_admin:
                    return True, f"La période de remplissage pour {add} n'a pas encore été définie."
                else:
                    return False, f"La période de remplissage pour {add} n'a pas encore été définie, {plus}"
            else:
                if timezone.now() < start:
                    if instance.request.user.is_admin:
                        return True, f"La période de remplissage définie pour {add} n'a pas encore débutée."
                    else:
                        return False, f"La période de remplissage définie pour {add} n'a pas encore débutée, {plus}"
                elif timezone.now() > end:
                    if instance.request.user.is_admin:
                        return True, f"La période de remplissage définie pour {add} est déjà close."
                    else:
                        return False, f"La période de remplissage définie pour {add} est déjà close, {plus}"
        return 0

    @classmethod
    def get_object(cls, classroom_id, enseignement_id, evaluation, request, trim=False):
        classrooms = ClassRoom.objects.prefetch_related('students')
        classroom = get_object_or_404(classrooms, pk=classroom_id)
        enseignements = Enseignements.objects.select_related('matiere__sujet').filter(classroom_id=classroom_id)
        enseignement = get_object_or_404(enseignements, matiere__sujet_id=enseignement_id)
        data = {"classroom": classroom, "enseignement": enseignement, "eval": evaluation, 'request': request,
                'trim': trim, 'with_competences': request.user.school.with_competences}
        matiere = enseignement.matiere.sujet.label
        if matiere == "LVII":
            matiere = data["classroom"].lv2
        if matiere == "LVIII":
            matiere = data["classroom"].lv3
        matiere = (f"d'{matiere}", f"de {matiere}")[matiere[0] not in ["A", "E", "I", "H", "0", "U", "Y"]]
        return data, matiere

    def post(self, *args, **kwargs):
        cid, did, evl = self.request.POST["classroom"], self.request.POST["matiere"], int(self.request.POST["eval"])
        data, matiere = MarksEdit.get_object(classroom_id=cid, enseignement_id=did, evaluation=evl,
                                             request=self.request)
        marks_form = MarksForm(self.request.POST or None, context=data, method="POST")
        context = {"title": f"{self.title}", "marks_form": marks_form, "eval": evl, "matiere": matiere,
                   "classe": data["classroom"].code, 'trim': False}
        if marks_form.is_valid():
            if marks_form.isvalid():
                if data['with_competences']:
                    compt = marks_form.cleaned_data["competences"]
                else:
                    compt = None
                x = marks_form.save((compt,))
                y = MarksForm.marks_check(ens=data["enseignement"], evl=evl)
                if x:
                    if not y:
                        message(self.request, "Les données ont été enregistrées avec succès, aucune note enregistrée.")
                    else:
                        message(self.request, "Les données ont été enregistrées avec succès.")
                else:
                    message(self.request, "Aucune modification effectuée.", msg_type="warning")
            else:
                message(self.request, "Les notes doivent être comprises entre 0 et 20", msg_type="warning")
        else:
            message(self.request, "Veuillez entrer les compétences.", msg_type="warning")
        response = render(self.request, self.template_name, context)
        response['HX-Trigger'] = 'AJAXMessages'
        return response


def get_classrooms(enseignements: django.db.models.QuerySet, clsrms: list):
    classrooms = list()
    for classroom in clsrms:
        if get_mat_and_evals(enseignements, classroom[0], checking=True) == 1:
            classrooms.append(classroom)
    return classrooms


def get_mat_and_evals(enseignements: django.db.models.QuerySet, classroom_id: int, checking=False):
    ens = enseignements.filter(classroom_id=classroom_id)
    evals = dict()
    matieres = list()
    matieres_to = list()
    for enseignement in ens:
        mat_evals = list()
        for i in (1, 2, 3, 4, 5, 6):
            check = MarksForm.marks_check(enseignement, i)
            if check:
                if checking:
                    return 1
                mat_evals.append((i, f"Évaluation {i}"))
        if mat_evals:
            matieres.append((enseignement.id, enseignement.matiere.sujet.label))
            evals[enseignement.id] = mat_evals
        matieres_to.append((enseignement.id, enseignement.matiere.sujet.label))
    return matieres, evals, matieres_to


def get_form_context(enseignements: django.db.models.QuerySet, periods, classroom_id=None):
    clsrms = list(enseignements.values_list('classroom__id', 'classroom__code').distinct())
    classrooms = get_classrooms(enseignements, clsrms)
    matieres, mat_evals, matieres_to = get_mat_and_evals(enseignements,
                                                         classroom_id if classroom_id else classrooms[0][0])
    return {
        'classrooms': classrooms,
        'matieres': matieres,
        "mat_evals": mat_evals,
        'periods': periods,
        'matieres_to': matieres_to
    }


class ReloadCopyForm(LoggedUserView):
    def post(self, *args, **kwargs):
        classroom_id = int(self.request.POST['classe'])
        rapport, enseignements = Marks.check(self)
        form_context = get_form_context(enseignements, MarksCopy.get_periods(), classroom_id=classroom_id)
        form_context['reload'], form_context['request'] = True, self.request
        context = {'marks_copy_form': MarksCopyForm(context=form_context)}
        return render(self.request, "marks_copy_to_and_from.html", context)


class ReloadCopyFormEvals(LoggedUserView):
    def post(self, *args, **kwargs):
        classroom_id = int(self.request.POST['classe'])
        rapport, enseignements = Marks.check(self)
        form_context = get_form_context(enseignements, MarksCopy.get_periods(), classroom_id=classroom_id)
        form_context['reloadm'], form_context['request'] = True, self.request
        context = {'marks_copy_form': MarksCopyForm(context=form_context)}
        return render(self.request, "marks_copy_form_from.html", context)


class MarksCopy(LoggedUserView):
    template_name = "marks_copy.html"
    title = "Reconduction de Notes"

    @classmethod
    def get_periods(cls):
        now = timezone.now()
        periods = Period.objects.filter(start__lte=now, end__gte=now).order_by('evalx')
        return [(period.evalx, f"Évaluation {period.evalx}") for period in periods] if periods else None

    def get(self, *args, **kwargs):
        context = {'title': self.title}
        periods = MarksCopy.get_periods()
        if periods:
            rapport, enseignements = Marks.check(self)
            if rapport:
                context['rapport'] = rapport
            else:
                form_context = get_form_context(enseignements, periods)
                context['marks_copy_form'] = MarksCopyForm(context=form_context)
        else:
            rapport = "Les plages de remplissages sont closes ou n'ont pas encore débutées."
            if not self.request.user.is_admin:
                rapport += " Veuillez contacter un administrateur."
            context['rapport'] = rapport
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        context = {'title': self.title}
        periods = MarksCopy.get_periods()
        if periods:
            rapport, enseignements = Marks.check(self)
            if rapport:
                context['rapport'] = rapport
            else:
                classroom_id = self.request.POST['classe']
                form_context = get_form_context(enseignements, periods, classroom_id)
                form_context['post'], form_context['request'] = True, self.request
                marks_copy_form = MarksCopyForm(self.request.POST, context=form_context)
                context['marks_copy_form'] = marks_copy_form
                if marks_copy_form.is_valid():
                    msg = marks_copy_form.copy_notes()
                    if msg == "Aucune note copiée.":
                        message(self.request, msg, msg_type="warning")
                    else:
                        message(self.request, msg)
        else:
            rapport = "Les plages de remplissages sont closes ou n'ont pas encore débutées."
            if not self.request.user.is_admin:
                rapport += " Veuillez contacter un administrateur."
            context['rapport'] = rapport
        return render(self.request, self.template_name, context)


class MarksCheck(LoggedAdminView):
    template_name = "check_marks.html"
    title = "Vérification Remplissage des Notes"

    def get(self, *args, **kwargs):
        check_form = CheckForm(context={"check": False})
        context = {"title": self.title, "check_form": check_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        check_form = CheckForm(self.request.POST or None, context={"check": False})
        context = {"title": self.title, "check_form": check_form}
        return render(self.request, self.template_name, context)


@logged_admin_view
def check(request):
    if request.method == "POST":
        template_name = "check_result.html"
        clsrm = ClassRoom.objects.get(pk=request.POST["clsrm"])
        evl = request.POST["evl"]
        eval = (int(evl[0]), int(evl[1]))
        if 1 in eval:
            trim = "Premier Trimestre"
        elif 3 in eval:
            trim = "Deuxième Trimestre"
        else:
            trim = "Troisième Trimestre"
        result = MarksForm.cls_marks_check(classroom=clsrm, evl=int(evl[0]))
        result1 = MarksForm.cls_marks_check(classroom=clsrm, evl=int(evl[1]))
        for i in range(len(result)):
            result[i]['status1'] = result1[i]['status']
        info = f"État de remplissage des notes du {trim} en {clsrm.code}"
        context = {'result': result, 'eval': eval, 'info': info}
        return render(request, template_name, context)


class Bulletin(LoggedAdminView):
    template_name = "bulletin_form.html"
    title = "Bulletin Scolaire"

    def get(self, *args, **kwargs):
        context = {"title": self.title, "form": CheckForm(context={"transcript": True})}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        clsrm, evl = int(self.request.POST["clsrm"]), int(self.request.POST["evl"])
        with_competences = True if 'checkbox' in self.request.POST.keys() else False
        evl_in = ((((1, 2), (3, 4))[evl == 2], (5, 6))[evl == 3], (1, 2, 3, 4, 5, 6))[evl == 4]
        classroom = ClassRoom.objects.prefetch_related('matieres').get(pk=clsrm)
        rapport = "Certaines notes de "
        checks = [(evl_in[i], MarksForm.cls_marks_check(classroom, evl_in[i])) for i in range(len(evl_in))]
        for status in checks:
            i = 0
            for elt in status[1]:
                if not elt["status"]:
                    i = 1
                    break
            if i:
                rapport += f"l'évaluation n° {status[0]}"
            if rapport != "Certaines notes de " and status != checks[-1]:
                rapport += ", "
        if rapport != "Certaines notes de ":
            return JsonResponse({
                'success': False,
                'message': f"{rapport} n'ont pas été remplies en {classroom.code}."
            })
        else:
            classroom = (
                ClassRoom.objects.select_related('classe').
                prefetch_related('students__pere', 'students__mere', 'students__discipline', 'matieres__sujet').
                get(pk=clsrm)
            )
            trimestre = ((("DU PREMIER TRIMESTRE", "DU DEUXIÈME TRIMESTRE")[evl == 2], "DU TROISIÈME TRIMESTRE")
                         [evl == 3], "ANNUEL")[evl == 4]
            filename = f"Bulletin Scolaire {trimestre.title()} {classroom.code}.pdf"
            data = classroom.reportcard_data(evl_in, with_competences)
            user = User.objects.select_related('school').get(id=self.request.user.id)
            data['school_data'] = user.school.school_to_dict()
            data['trimestre'], data['annee'], data['filename'] = trimestre, school_year(), filename
            temp_filename, final_filename = generate_temp_file(filename, ReportCard(data=data))
            url = reverse("download_and_delete", args=[temp_filename])
            return JsonResponse({
                'success': True,
                'url': url,
                'display': final_filename
            })


class MarksReport(LoggedAdminView):
    template_name = "bulletin_form.html"
    title = "Relevé de Notes"

    def get(self, *args, **kwargs):
        form = CheckForm(context={"marks-report": True})
        context = {"title": self.title, "form": form, 'marks_report': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        clsrm, evl = int(self.request.POST["clsrm"]), int(self.request.POST["evl"])
        evl_in = (((1, 2), (3, 4))[evl == 2], (5, 6))[evl == 3]
        classroom = ClassRoom.objects.prefetch_related('matieres').get(pk=clsrm)
        rapport = "Certaines notes de "
        checks = [(evl_in[i], MarksForm.cls_marks_check(classroom, evl_in[i])) for i in range(len(evl_in))]
        for status in checks:
            i = 0
            for elt in status[1]:
                if not elt["status"]:
                    i = 1
                    break
            if i:
                rapport += f"l'évaluation n° {status[0]}"
            if rapport != "Certaines notes de " and status != checks[-1]:
                rapport += ", "
        if rapport != "Certaines notes de ":
            return JsonResponse({
                'success': False,
                'message': f"{rapport} n'ont pas été remplies en {classroom.code}"
            })
        else:
            classroom = (
                ClassRoom.objects.select_related('classe').
                prefetch_related('students', 'matieres__sujet').
                get(pk=clsrm)
            )
            trimestre = (("DU PREMIER TRIMESTRE", "DU DEUXIÈME TRIMESTRE")[evl == 2], "DU TROISIÈME TRIMESTRE")[evl == 3]
            filename = f"Relevé de Notes {trimestre.title()} {classroom.code}.pdf"
            data = classroom.marks_report_data(evl_in)
            user = User.objects.select_related('school').get(id=self.request.user.id)
            data['school_data'] = user.school
            data['trimestre'], data['annee'], data['filename'], data['evalx'] = trimestre, school_year(), filename, \
                (f"E{evl_in[0]}", f"E{evl_in[1]}")
            temp_filename, final_filename = generate_temp_file(filename, TMarksReport(data=data))
            url = reverse("download_and_delete", args=[temp_filename])
            return JsonResponse({
                'success': True,
                'url': url,
                'display': final_filename
            })


class ExamReport(LoggedAdminView):
    template_name = "bulletin_form.html"
    title = "Procès Verbal"

    def get(self, *args, **kwargs):
        form = CheckForm(context={"transcript": True})
        context = {"title": self.title, "form": form, 'marks_report': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        clsrm, evl = int(self.request.POST["clsrm"]), int(self.request.POST["evl"])
        pv_ordered = True if 'checkbox' in self.request.POST.keys() else False
        evl_in = ((((1, 2), (3, 4))[evl == 2], (5, 6))[evl == 3], (1, 2, 3, 4, 5, 6))[evl == 4]
        classroom = ClassRoom.objects.prefetch_related('matieres').get(pk=clsrm)
        rapport = "Certaines notes de "
        checks = [(evl_in[i], MarksForm.cls_marks_check(classroom, evl_in[i])) for i in range(len(evl_in))]
        for status in checks:
            i = 0
            for elt in status[1]:
                if not elt["status"]:
                    i = 1
                    break
            if i:
                rapport += f"l'évaluation n° {status[0]}"
            if rapport != "Certaines notes de " and status != checks[-1]:
                rapport += ", "
        if rapport != "Certaines notes de ":
            return JsonResponse({
                'success': False,
                'message': f"{rapport} n'ont pas été remplies en {classroom.code}."
            })
        else:
            classroom = (
                ClassRoom.objects.select_related('classe').
                prefetch_related('students', 'matieres').
                get(pk=clsrm)
            )
            trimestre = ((("DU PREMIER TRIMESTRE", "DU DEUXIÈME TRIMESTRE")[evl == 2], "DU TROISIÈME TRIMESTRE")
                         [evl == 3], "ANNUEL")[evl == 4]
            filename = f"Procès Verbal {trimestre.title()} {classroom.code}.pdf"
            data = classroom.marks_report_data(evl_in, pv=True, pv_ordered=pv_ordered)
            user = User.objects.select_related('school').get(id=self.request.user.id)
            data['school_data'] = user.school
            data['trimestre'], data['annee'], data['filename'] = trimestre, school_year(), filename
            temp_filename, final_filename = generate_temp_file(filename, ExamRecord(data=data))
            url = reverse("download_and_delete", args=[temp_filename])
            return JsonResponse({
                'success': True,
                'url': url,
                'display': final_filename
            })


class TableauHonneur(LoggedAdminView):
    template_name = "bulletin_form.html"
    title = "Tableau d'Honneur"

    def get(self, *args, **kwargs):
        form = CheckForm(context={"transcript": True})
        context = {"title": self.title, "form": form, 'marks_report': True, 'tableau': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        clsrm, evl = int(self.request.POST["clsrm"]), int(self.request.POST["evl"])
        evl_in = ((((1, 2), (3, 4))[evl == 2], (5, 6))[evl == 3], (1, 2, 3, 4, 5, 6))[evl == 4]
        classroom = ClassRoom.objects.prefetch_related('matieres').get(pk=clsrm)
        rapport = "Certaines notes de "
        checks = [(evl_in[i], MarksForm.cls_marks_check(classroom, evl_in[i])) for i in range(len(evl_in))]
        for status in checks:
            i = 0
            for elt in status[1]:
                if not elt["status"]:
                    i = 1
                    break
            if i:
                rapport += f"l'évaluation n° {status[0]}"
            if rapport != "Certaines notes de " and status != checks[-1]:
                rapport += ", "
        if rapport != "Certaines notes de ":
            return JsonResponse({
                'success': False,
                'message': f"{rapport} n'ont pas été remplies en {classroom.code}."
            })
        else:
            classroom = (
                ClassRoom.objects.select_related('classe').
                prefetch_related('students', 'matieres').
                get(pk=clsrm)
            )
            trim = ((("DU PREMIER TRIMESTRE", "DU DEUXIÈME TRIMESTRE")[evl == 2], "DU TROISIÈME TRIMESTRE")
                         [evl == 3], "ANNUEL")[evl == 4]
            trimestre = ((("DU PREMIER TRIMESTRE", "DU DEUXIÈME TRIMESTRE")[evl == 2], "DU TROISIÈME TRIMESTRE")
                         [evl == 3], "ANNUELLE")[evl == 4]
            filename = f"Tableaux d'honneur {trim.title()} {classroom.code}.pdf"
            data = classroom.marks_report_data(evl_in, pv=True, pv_ordered=True)
            datas = dict()
            datas['students'] = list()
            for student in data['students_data']:
                if student['moyenne'] >= 12:
                    datas['students'].append({
                        'nom': student['student']['nom'],
                        'moyenne': student['moyenne'],
                        'rang': student['rang'],
                    })
            if not datas['students']:
                return JsonResponse({
                    'success': False,
                    'message': f"Aucun élève de {classroom.code} ne mérite un tableau d'honneur pour le compte {trim.lower()}"
                })
            else:
                del data
                user = User.objects.select_related('school').get(id=self.request.user.id)
                datas['school_data'], datas['classe'] = user.school, classroom.code
                datas['trimestre'], datas['annee'], datas['filename'] = trimestre.lower(), school_year(), filename
                temp_filename, final_filename = generate_temp_file(filename, TableaudHonneur(data=datas))
                url = reverse("download_and_delete", args=[temp_filename])
                return JsonResponse({
                    'success': True,
                    'url': url,
                    'display': final_filename
                })


class TableaudHonneur(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.add_font('inter', '', settings.INTER_REGULAR)
        self.add_font('inter', 'I', settings.INTER_ITALIC)
        self.add_font('inter', 'B', settings.INTER_BOLD)
        self.add_font('inter', 'BI', settings.INTER_BOLDITALIC)
        self.set_font('inter', '', 8)
        self.data = kwargs.pop('data')
        self.school = self.data['school_data']
        self.decoration = "static/image/decoration.png"
        self.draw_tables()

    def filligranne(self, x=70, y=70, w=70):
        logo = (self.school.logo, "static/image/no_image.jpg")[self.school.logo == ""]
        if logo:
            with self.local_context(fill_opacity=0.2):
                self.image(logo, x=x, y=y, w=w, keep_aspect_ratio=True)

    def draw_tables(self):
        is_not_modulo2 = len(self.data['students']) % 2 != 0
        j = int(len(self.data['students']) / 2)
        if is_not_modulo2:
            j += 1
        for i in range(j):
            self.add_page()
            self.filligranne()
            self.filligranne(y=218.5)
            if i == j -1 and is_not_modulo2:
                end = len(self.data['students'])
            else:
                end = (i * 2) + 2
            x, y, y_img, y_deco = 6, 20, 14, -28
            for student in self.data['students'][i * 2:end]:
                self.image(self.decoration, x=6, y=y_deco, w=198, keep_aspect_ratio=True)
                self.set_xy(x, y)
                base_header(self, y_img=y_img)
                self.ln()
                self.set_font('inter', 'B', 25)
                #self.set_fill_color(75)
                self.set_text_color(255, 215, 0)
                self.cell(w=140, h=15, text="TABLEAU D'HONNEUR", fill=True, center=True, align="C")
                #self.set_fill_color(255)
                self.set_text_color(0)
                self.set_font('inter', '', 9)
                self.ln()
                texte = (f"\n      L'élève **{student['nom']}** de la classe de **{self.data['classe']}** a obtenu(e) "
                         f"**{student['moyenne']}** comme moyenne {self.data['trimestre']} de l'année scolaire "
                         f"**{self.data['annee']}**, en étant classé **{student['rang']}**. Ce résultat témoigne d'un travail "
                         f"remarquable et d'un engagement vers la quête de l'execellence scolaire. En foi de quoi le présent "
                         f"**TABLEAU D'HONNEUR** lui est remis pour servir et valoir ce que de droit.")
                self.multi_cell(w=198, h=5, align='L', center=True, text=texte, markdown=True)
                self.ln()
                self.ln()
                self.cell(w=198, h=5, align='R', center=True, text=f"Fait à {self.school.localite}, le --                          --",
                          markdown=True)
                self.ln()
                self.cell(w=188, h=10, align='R', center=True, text=f"**Le {self.school.chef}**", markdown=True)
                y += 148.5
                y_img += 148.5
                y_deco += 148.5
            self.dashed_line(x1=0, y1=148.5, x2=210, y2=148.5)

class ExamRecord(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.add_font('inter', '', settings.INTER_REGULAR)
        self.add_font('inter', 'I', settings.INTER_ITALIC)
        self.add_font('inter', 'B', settings.INTER_BOLD)
        self.add_font('inter', 'BI', settings.INTER_BOLDITALIC)
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=6)
        self.set_font('inter', '', 8)
        self.now = datetime.datetime.now().strftime("%d-%m-%Y à %H:%M")
        self.data = kwargs.pop('data')
        self.school = self.data['school_data']
        self.add_page()
        base_header(self)
        base_infos(self, f"PROCÈS VERBAL {self.data['trimestre']}", self.data['effectif'], self.data['filles'],
                   self.data['garcons'], self.data['redoublants'], self.data['label'])
        self.students_results()

    def students_results(self):
        self.ln()
        self.set_font_size(8)
        col_widths = [10, 22, 88, 11, 11, 17, 14, 11, 14]
        header = ["N°", "Identifiant", "Nom(s) et Prénom(s)", "Sexe", "Red?", "Moyenne", "Rang", "Côte", "Appr"]
        if self.data['trimestre'] == "ANNUEL":
            col_widths = [10, 21, 70, 11, 11, 13, 13, 13, 13, 13, 10]
            header = ["N°", "Identifiant", "Nom(s) et Prénom(s)", "Sexe", "Red?", "Moy1", "Moy2", "Moy3", "Moy", "Rang",
                      "DEC"]

        table = Table(self, line_height=5, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)

        th = table.row()
        self.set_fill_color(220)
        for head in header:
            th.cell(f"**{head}**")

        self.set_fill_color(0)
        students = self.data['students_data']
        for i, student in enumerate(students):
            row = table.row()
            row.cell(f"{i + 1}")
            row.cell(f"{student['student']['matricule']}")
            row.cell(student['student']['nom'], align='L')
            row.cell(student['student']['sexe'])
            row.cell(student['student']['statut'])
            if self.data['trimestre'] != "ANNUEL":
                row.cell(f"{student['moyenne']}" if student['moyenne'] else "/")
                row.cell(student['rang'])
                row.cell(student['cote'])
                row.cell(student['appr'], align='L')
            else:
                row.cell(f"{student['moy1']}" if student['moy1'] else "/")
                row.cell(f"{student['moy2']}" if student['moy2'] else "/")
                row.cell(f"{student['moy3']}" if student['moy3'] else "/")
                row.cell(f"{student['moyenne']}" if student['moyenne'] else "/")
                row.cell(student['rang'])
                decision = (("ADM", "RED")[student['moyenne'] < 10], "/")[student['moyenne'] == 0]
                row.cell(decision)
        table.render()
        self.ln(2)
        self.cell(150, 5, f"Nombre d'élèves évalués : **{self.data['nbe']} / {self.data['effectif']}**", markdown=True)
        self.cell(0, 5, f"Moyenne générale : **{self.data['moyenne_generale']}**", markdown=True)
        self.ln()
        self.cell(150, 5, f"Nombre de moyennes : **{self.data['nbr']} / {self.data['nbe']}**", markdown=True)
        self.cell(0, 5, f"Taux de réussite : **{self.data['taux']}**", markdown=True)
        self.ln()
        self.cell(0, 5, f"[Min - Max] : **{self.data['min_max']}**", markdown=True)

    def footer(self):
        self.set_y(-6)
        self.line(6, 291, 204, 291)
        self.set_font('inter', 'I', 7)
        self.cell(99, 6, f"Document généré par Oméga School Manager le {self.now}", align='L')
        self.cell(99, 6, f"PROCÈS VERBAL {self.data['trimestre'].title()} ({self.data['label']}) - Page "
                          f"{self.page_no()}/{{nb}}", align='R')


class TMarksReport(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='L')
        self.add_font('inter', '', settings.INTER_REGULAR)
        self.add_font('inter', 'I', settings.INTER_ITALIC)
        self.add_font('inter', 'B', settings.INTER_BOLD)
        self.add_font('inter', 'BI', settings.INTER_BOLDITALIC)
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=6)
        self.set_font('inter', '', 8)
        self.now = datetime.datetime.now().strftime("%d-%m-%Y à %H:%M")
        self.data = kwargs.pop('data')
        self.school = self.data['school_data']
        self.add_page()
        base_header(self, mode='Pa')
        base_infos(self, f"RELEVÉ DE NOTES {self.data['trimestre']}", self.data['effectif'], self.data['filles'],
                   self.data['garcons'], self.data['redoublants'], self.data['label'], mode='Pa')
        self.marks_table()

    def truncate_matiere_label(self, label_matiere, max_lines: int, max_width: int):
        if int(self.get_string_width(label_matiere)) <= (max_width * max_lines) - 3:
            return label_matiere
        labels = label_matiere.split()
        matiere_label = ""
        i = 0
        j = 1
        while i < len(labels) and j <= max_lines:
            label = labels[i]
            if label in ('du', 'de', 'le', 'la', 'et'):
                if i + 1 < len(labels):
                    label += f" {labels[i + 1]}"
                    i += 1
            matiere_label += truncate_str(self, label, max_with=max_width-3)
            i += 1
            if j < max_lines:
                matiere_label += "\n"
            j += 1
        return matiere_label

    def marks_table(self):
        self.ln()
        n = len(self.data['matieres_data'])
        largeur = ((((12, 11)[n == 10], 10)[n == 11], 9)[14 > n >= 12], 8)[n >= 14]
        w = 285 - 7 - (n * largeur * 2)
        col_widths = [7, w]
        header = list()
        for matiere in self.data['matieres_data']:
            header.append(self.truncate_matiere_label(matiere['label'], max_lines=self.data['max_words'],
                                                      max_width=largeur*2))
            col_widths.append(largeur)
            col_widths.append(largeur)

        table = Table(self, line_height=4, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE, num_heading_rows=2)
        th = table.row()
        self.set_fill_color(220)
        th.cell("**N°**", rowspan=2)
        th.cell("**Nom(s) et Prénom(s)**", rowspan=2)
        for head in header:
            th.cell(f"**{head}**", colspan=2)

        th1 = table.row()

        for _ in header:
            th1.cell(f"**{self.data['evalx'][0]}**")
            th1.cell(f"**{self.data['evalx'][1]}**")

        self.set_fill_color(0)
        students = self.data['students_data']
        for i, student in enumerate(students):
            row = table.row()
            row.cell(f"{i + 1}")
            nom = student['nom']
            padding = 0
            if int(self.get_string_width(nom)) <= w - 3:
                padding = (2, 0)
            elif int(self.get_string_width(nom + ".")) >= (w * 2) - 4:
                nom = truncate_str(self, str_value=nom, max_with=(w * 2) - 5)
            row.cell(nom, align='L', padding=padding)
            student_notes = student['matieres_data']
            for matiere in self.data['matieres_data']:
                note1 = "/" if not student_notes.get(matiere['id']) \
                    else student_notes[matiere['id']].get('note1', '/')
                note2 = "/" if not student_notes.get(matiere['id']) \
                    else student_notes[matiere['id']].get('note2', '/')
                row.cell(f"{note1}")
                row.cell(f"{note2}")
        table.render()

    def footer(self):
        self.set_y(-6)
        self.line(6, 204, 291, 204)
        self.set_font('inter', 'I', 7)
        self.cell(142.5, 6, f"Document généré par Oméga School Manager le {self.now}", align='L')
        self.cell(142.5, 6, f"RELEVÉ DE NOTES {self.data['trimestre'].title()} ({self.data['label']}) - Page "
                             f"{self.page_no()}/{{nb}}", align='R')


class ReportCard(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.add_fonts(self)
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=6)
        self.set_font('inter', '', 8)
        self.bold = FontFace(emphasis='B')
        self.now = datetime.datetime.now().strftime("%d-%m-%Y à %H:%M")
        data = kwargs.pop('data')
        self.set_title(data['filename'])
        school_data = data['school_data']
        school_data['logo'] = resize_image(school_data['logo'], new_width=308)
        self.student_img = resize_image("static/image/student.jpg")
        self.trimestre, annee = data.pop('trimestre'), data.pop('annee')
        moy_gen = data['moyenne_generale']
        min_max = data['min-max']
        nb = data['nb']
        nb_admis = data['nb_admis']
        taux = data['taux_reussite']
        classroom_data = data['classroom_data']
        matieres_data = data['matieres_data']
        total_coef = classroom_data['total_coef']
        with_competences = data['with_competences']
        self.nb_pages = 3
        for i in range(len(data['students_data'])):
            self.i = i
            if i == 0:
                if self.trimestre != "ANNUEL" and with_competences:
                    from pypdf import PdfReader
                    pdf = FPDF()
                    self.add_fonts(pdf)
                    pdf.set_margins(6, 6, 6)
                    pdf.set_auto_page_break(True, margin=6)
                    pdf.set_font('inter', '', 8)
                    self.draw_student_reportcard(pdf, data, 0, school_data, self.trimestre, annee, classroom_data,
                                                 matieres_data, total_coef, min_max, moy_gen, taux, nb, nb_admis,
                                                 chef=school_data['chef'])
                    buffer = BytesIO()
                    pdf.output(buffer)
                    buffer.seek(0)
                    reader = PdfReader(buffer)
                    self.nb_pages = len(reader.pages)
            # TODO
            if self.nb_pages > 1:
                self.nom = data['students_data'][0]['student']['short_name'] if i ==0 else\
                    data['students_data'][i-1]['student']['short_name']
            self.draw_student_reportcard(self, data, i, school_data, self.trimestre, annee, classroom_data,
                                         matieres_data, total_coef, min_max, moy_gen, taux, nb, nb_admis,
                                         chef=school_data['chef'])
            if self.nb_pages > 1:
                self.nom = data['students_data'][i]['student']['short_name']

    def add_fonts(self, pdf):
        pdf.add_font('inter', '', settings.INTER_REGULAR)
        pdf.add_font('inter', 'I', settings.INTER_ITALIC)
        pdf.add_font('inter', 'B', settings.INTER_BOLD)
        pdf.add_font('inter', 'BI', settings.INTER_BOLDITALIC)

    #TODO
    def footer(self):
        self.set_y(-6)
        self.line(6, 291, 204, 291)
        self.set_font('inter', 'I', 7)
        self.cell(100, 6, f"Document généré par OSM le {self.now}", align='L')
        if self.nb_pages > 1:
            page = (self.nb_pages, self.page_no() % self.nb_pages)[self.page_no() % self.nb_pages != 0]
            if page != 1:
                self.cell(98, 6, f"BULLETIN {self.trimestre.title()} ({self.nom}) - Page {page}/{self.nb_pages}",
                          align='R')
            else:
                self.cell(98, 6, f"BULLETIN {self.trimestre.title()} - Page {page}/{self.nb_pages}", align='R')
        else:
            self.cell(98, 6, f"BULLETIN {self.trimestre.title()}", align='R')

    def draw_student_reportcard(self, pdf, data, i, school_data, trimestre, annee, classroom_data, matieres_data,
                                total_coef, min_max, moy_gen, taux, nb, nb_admis, chef):
        pdf.add_page()
        pdf.set_y(6)
        self.school_infos(pdf, school_data=school_data)
        
        self.infos(pdf, trimestre, annee)
        pdf.ln()
        self.student_infos(pdf, student_data=data['students_data'][i]['student'], classroom_data=classroom_data)
        total_notes = data['students_data'][i]['total_notes']
        moyenne = data['students_data'][i]["moyenne"]
        pdf.ln(2)
        if self.trimestre == 'ANNUEL':
            moyennes = (
                data['students_data'][i]["moyenne1"] if data['students_data'][i]["moyenne1"] else "/",
                data['students_data'][i]["moyenne2"] if data['students_data'][i]["moyenne2"] else "/",
                data['students_data'][i]["moyenne3"] if data['students_data'][i]["moyenne3"] else "/"
            )
            rangs = (
                data['students_data'][i]["rang1"],
                data['students_data'][i]["rang2"],
                data['students_data'][i]["rang3"]
            )
            self.annual_student_notes(pdf, matieres_data=matieres_data, total_coef=total_coef, total_notes=total_notes,
                                      student_notes=data['students_data'][i]['matieres_data'], moyenne=moyenne,
                                      groupes=data['groupes'], moyennes=moyennes, rangs=rangs)
        else:
            if data['with_competences']:
                self.student_notes(pdf, matieres_data=matieres_data, total_coef=total_coef, total_notes=total_notes,
                                   student_notes=data['students_data'][i]['matieres_data'], moyenne=moyenne)
            else:
                self.student_notes_without_competences(pdf, matieres_data=matieres_data, total_coef=total_coef,
                                                       total_notes=total_notes,
                                                       student_notes=data['students_data'][i]['matieres_data'],
                                                       moyenne=moyenne, groupes=data['groupes'])
        rang = data['students_data'][i]['rang']
        appr = data['students_data'][i]['appr']
        appreciation = data['students_data'][i]['appreciation']
        cote = data['students_data'][i]['cote']
        pdf.ln(4)
        self.discipline(pdf, discipline=data['students_data'][i]['discipline'], total_notes=total_notes, appr=appr,
                        total_coef=total_coef, moyenne=moyenne, rang=rang, cote=cote, moy_gen=moy_gen, taux=taux,
                        min_max=min_max, nb=nb, nb_admis=nb_admis, appreciation=appreciation, chef=chef)

    def school_infos(self, pdf, school_data):
        widths = (75.25, 47.5, 75.25)
        table = Table(pdf, line_height=3, col_widths=widths, text_align="CENTER", first_row_as_headings=False,
                      borders_layout="NONE", markdown=True)
        row = table.row()
        row.cell("**RÉPUBLIQUE DU CAMEROUN**")
        row.cell("", rowspan=9)
        row.cell("**REPUBLIC OF CAMEROON**")

        row = table.row()
        pdf.set_font_size(7)
        row.cell("__**Paix - Travail - Patrie**__")
        row.cell("__**Peace - Work - Fatherland**__")
        pdf.set_font_size(8)

        row = table.row()
        row.cell("**********", style=self.bold)
        row.cell("**********", style=self.bold)

        row = table.row()
        row.cell("MINISTÈRE DES ENSEIGNEMENTS SECONDAIRES")
        row.cell("MINISTRY OF SECONDARY EDUCATION")

        row = table.row()
        row.cell("**********", style=self.bold)
        row.cell("**********", style=self.bold)

        row = table.row()
        row.cell(f"{school_data['region']}")
        row.cell(f"{school_data['rgn']}")

        row = table.row()
        row.cell("**********", style=self.bold)
        row.cell("**********", style=self.bold)

        row = table.row()
        row.cell(f"{school_data['departement']}")
        row.cell(f"{school_data['dptm']}")

        row = table.row()
        row.cell("**********", style=self.bold)
        row.cell("**********", style=self.bold)

        row = table.row()
        row.cell(f"**{school_data['nom']}**", v_align=VAlign.T)
        pdf.set_font_size(7)
        row.cell(f"**{school_data['immatriculation']}**\n__Tél : {school_data['contact']}__")
        pdf.set_font_size(8)
        row.cell(f"**{school_data['name']}**", v_align=VAlign.T)

        pdf.image(school_data['logo'], x=92, y=6, w=26, keep_aspect_ratio=True)
        table.render()

    def infos(self, pdf, trimestre, annee):
        pdf.set_font("inter", 'B', 12)
        pdf.set_text_color(0, 0, 255)
        pdf.cell(0, 7, f"BULLETIN SCOLAIRE {trimestre}", align='C')
        pdf.set_text_color(0)
        pdf.ln()
        pdf.set_font("inter", '', 8)
        pdf.cell(0, 2, f"__**Année scolaire : {annee}**__", align='C', markdown=True)
        pdf.ln()

    def student_infos(self, pdf, student_data, classroom_data):
        widths = (29, 70, 39, 20, 40)
        table = Table(pdf, line_height=4, col_widths=widths, text_align="LEFT", first_row_as_headings=False,
                      markdown=True)
        row = table.row()
        row.cell(
            img=resize_image(student_data['photo']) if student_data['photo'] else self.student_img,
            padding=(2, 2, 2, 2), rowspan=4, border=CellBordersLayout.NONE)
        row.cell(f"Nom(s) et Prénom(s) de l'élève : **{student_data['nom']}**", colspan=3)
        row.cell(f"Classe : **{classroom_data['label']}**")

        row = table.row()
        row.cell(
            f"Date et lieu de naissance : {student_data['date_lieu_naissance']}", colspan=2)
        row.cell(f"Genre : {student_data['sexe']}")
        row.cell(f"Effectif : {classroom_data['effectif']}")

        row = table.row()
        row.cell(f"Identifiant Unique : **{student_data['matricule']}**")
        row.cell("Redoublant(e) : ",
                 align="RIGHT", border=CellBordersLayout.TOP | CellBordersLayout.BOTTOM | CellBordersLayout.LEFT)
        self.draw_tic_orx(row, student_data['statut'], align="L",
                          border=CellBordersLayout.TOP | CellBordersLayout.BOTTOM | CellBordersLayout.RIGHT)
        row.cell(f"Professeur principal : {classroom_data['titulaire']}", rowspan=2)

        row = table.row()
        row.cell(f"Nom(s) et contact(s) de Parents/Tuteurs :\n{student_data['pere']}\n{student_data['mere']}\n",
                 colspan=3, v_align=VAlign.T)
        table.render()

    def student_notes(self, pdf, matieres_data, total_coef, total_notes, student_notes, moyenne):
        header = ["MATIÈRE ET\nNOM DE L'ENSEIGNANT", "COMPÉTENCES ÉVALUÉES", "N/20", "M/20", "Coef", "M x Coef",
                  "Côte", "[Min - Max]", "Appréciation et Visa de l'enseignant"]
        widths = [34.2, 62, 11.7, 13.2, 9.8, 15.7, 9.8, 15.6, 28]
        table = Table(pdf, line_height=4, col_widths=widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.NONE)
        th = table.row()
        self.set_fill_color(220)
        for head in header:
            th.cell(f"**{head}**")
        self.set_fill_color(0)
        for matiere_data in matieres_data:
            tr1 = table.row()
            tr1.cell(f"**{matiere_data['label']}**\n{matiere_data['enseignant']}", align="LEFT", rowspan=2)
            if not matiere_data['compt2']:
                tr1.cell(f"{matiere_data['compt1']}", rowspan=2, align="LEFT")
            else:
                tr1.cell(f"{matiere_data['compt1']}", align="LEFT")
            note1 = "/" if not student_notes.get(matiere_data['id'])\
                else student_notes[matiere_data['id']].get('note1', '/')
            self.colored_cell(tr1, note1)
            moy = "/" if not student_notes.get(matiere_data['id']) \
                else student_notes[matiere_data['id']].get('moy', '/')
            self.colored_cell(tr1, moy, rowspan=2)
            tr1.cell(f"{matiere_data['coef']}", rowspan=2)
            moy_coef = "/" if not student_notes.get(matiere_data['id']) \
                else student_notes[matiere_data['id']].get('moy*coef', '/')
            tr1.cell(f"{moy_coef}", rowspan=2)
            cote = "/" if not student_notes.get(matiere_data['id']) \
                else student_notes[matiere_data['id']].get('cote', '/')
            tr1.cell(f"{cote}", rowspan=2)
            tr1.cell(f"{matiere_data['min-max']}", rowspan=2)
            appr = "/" if not student_notes.get(matiere_data['id']) \
                else student_notes[matiere_data['id']].get('appr', '/')
            tr1.cell(f"{appr}", rowspan=2, align="LEFT")

            tr2 = table.row()
            if matiere_data['compt2']:
                tr2.cell(f"{matiere_data['compt2']}", align="LEFT")
            note2 = "/" if not student_notes.get(matiere_data['id']) \
                else student_notes[matiere_data['id']].get('note2', '/')
            self.colored_cell(tr2, note2)
        trn = table.row()
        trn.cell("**TOTAL**", colspan=4, align='R', padding=(0.5, 0))
        trn.cell(f"**{total_coef}**")
        trn.cell(f"**{total_notes}**")
        trn.cell(f"**MOYENNE : {moyenne if moyenne else '/'}**", align="L", colspan=3)
        table.render()

    def annual_student_notes(self, pdf, matieres_data, total_coef, total_notes, student_notes, moyenne, groupes,
                             moyennes, rangs):
        header = ["MATIÈRE", "NOM DE L'ENSEIGNANT", "TRIM1", "TRIM2", "TRIM3", "MOY", "Coef", "MOY x Coef",
                  "Côte", "[Min - Max]", "Appr"]
        widths = [35, 35, 13.5, 13.5, 13.5, 13.5, 10, 16, 10, 26, 12]
        table = Table(pdf, line_height=5, col_widths=widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.NONE)
        th = table.row()
        self.set_fill_color(220)
        for head in header:
            th.cell(f"**{head}**")
        self.set_fill_color(0)
        i = 0
        matiere_data = matieres_data[0]
        for groupe in groupes:
            total_notesg = 0
            total_coefg = 0
            while matiere_data['groupe'] == groupe:
                tr = table.row()
                label = truncate_str(pdf, matiere_data['label'], 34)
                tr.cell(f"**{label}**", align="LEFT")
                enseignant = truncate_str(self, matiere_data['enseignant'], 34)
                tr.cell(f"{enseignant}", align="LEFT")
                moy1 = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('moy1', '/')
                self.colored_cell(tr, moy1)
                moy2 = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('moy2', '/')
                self.colored_cell(tr, moy2)
                moy3 = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('moy3', '/')
                self.colored_cell(tr, moy3)
                moy = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('moy', '/')
                self.colored_cell(tr, moy)
                tr.cell(f"{matiere_data['coef']}")
                moy_coef = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('moy*coef', '/')
                tr.cell(f"{moy_coef}")
                cote = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('cote', '/')
                tr.cell(f"{cote}")
                tr.cell(f"{matiere_data['min-max']}")
                appr = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('appr', '/')
                tr.cell(f"{appr}", align="LEFT")
                if moy_coef != "/":
                    total_notesg += moy_coef
                total_coefg += matiere_data['coef']
                if matiere_data != matieres_data[-1]:
                    i += 1
                    matiere_data = matieres_data[i]
                else:
                    break
            moyenneg = formated_float(total_notesg / total_coefg)
            trg = table.row()
            trg.cell(f"**{groupe}**", colspan=6, align='R')
            trg.cell(f"**{total_coefg}**")
            trg.cell(f"**{formated_float(total_notesg)}**")
            trg.cell(f"**MOYENNE : {moyenneg if moyenneg else '/'}**", align="L", colspan=3)
        trn = table.row()
        trn.cell(f"**Trim1 : {moyennes[0]}; {rangs[0]} | Trim2 : {moyennes[1]}; {rangs[1]} | Trim3 : {moyennes[2]}; "
                 f"{rangs[2]}**", colspan=5, align='L', padding=(0.5, 0))
        trn.cell("**TOTAL**", align='R')
        trn.cell(f"**{total_coef}**")
        trn.cell(f"**{total_notes}**")
        trn.cell(f"**MOYENNE : {moyenne if moyenne else '/'}**", align="L", colspan=3)
        table.render()
        # trim1 trim2 trim3

    def student_notes_without_competences(self, pdf, matieres_data, total_coef, total_notes, student_notes, moyenne,
                                          groupes):
        header = ["MATIÈRE", "NOM DE L'ENSEIGNANT", "ÉVAL1", "ÉVAL2", "MOY", "Coef", "MOY x Coef", "Côte",
                  "[Min - Max]", "Appr"]
        widths = [38, 38, 15, 15, 15, 11, 16, 11, 26, 13]
        table = Table(pdf, line_height=5, col_widths=widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.NONE)
        th = table.row()
        self.set_fill_color(220)
        for head in header:
            th.cell(f"**{head}**")
        self.set_fill_color(0)
        i = 0
        matiere_data = matieres_data[0]
        for groupe in groupes:
            total_notesg = 0
            total_coefg = 0
            while matiere_data['groupe'] == groupe:
                tr = table.row()
                label = truncate_str(self, matiere_data['label'], 34)
                tr.cell(f"**{label}**", align="LEFT")
                enseignant = truncate_str(self, matiere_data['enseignant'], 34)
                tr.cell(f"{enseignant}", align="LEFT")
                note1 = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('note1', '/')
                self.colored_cell(tr, note1)
                note2 = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('note2', '/')
                self.colored_cell(tr, note2)
                moy = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('moy', '/')
                self.colored_cell(tr, moy)
                tr.cell(f"{matiere_data['coef']}")
                moy_coef = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('moy*coef', '/')
                tr.cell(f"{moy_coef}")
                cote = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('cote', '/')
                tr.cell(f"{cote}")
                tr.cell(f"{matiere_data['min-max']}")
                appr = "/" if not student_notes.get(matiere_data['id']) \
                    else student_notes[matiere_data['id']].get('appr', '/')
                tr.cell(f"{appr}", align="LEFT")
                if moy_coef != "/":
                    total_notesg += moy_coef
                total_coefg += matiere_data['coef']
                if matiere_data != matieres_data[-1]:
                    i += 1
                    matiere_data = matieres_data[i]
                else:
                    break
            moyenneg = formated_float(total_notesg / total_coefg)
            trg = table.row()
            trg.cell(f"**{groupe}**", colspan=5, align='R')
            trg.cell(f"**{total_coefg}**")
            trg.cell(f"**{formated_float(total_notesg) if total_notesg else '/'}**")
            trg.cell(f"**MOYENNE : {moyenneg if moyenneg else '/'}**", align="L", colspan=3)
        trn = table.row()
        trn.cell("**TOTAL**", colspan=5, align='R', padding=(0.5, 0))
        trn.cell(f"**{total_coef}**")
        trn.cell(f"**{total_notes}**")
        trn.cell(f"**MOYENNE : {moyenne if moyenne else '/'}**", align="L", colspan=3)
        table.render()

    def discipline(self, pdf, discipline, total_notes, appr, total_coef, moyenne, rang, cote, moy_gen, taux,
                         min_max, nb, nb_admis, appreciation, chef):
        if pdf.get_y() + 58.5 > 291:
            pdf.add_page()
        widths = (25, 9.9, 24.7, 9.9, 19.5, 21.2, 24.5, 15.4, 31.5, 15.4)
        table = Table(pdf, line_height=4.5, col_widths=widths, text_align="L", markdown=True,
                      repeat_headings=TableHeadingsDisplay.NONE)
        th = table.row()
        th.cell("Discipline", colspan=4, align='C')
        th.cell("Travail de l'élève", colspan=4, align='C')
        th.cell("Profil de la classe", colspan=2, align='C')

        tr = table.row()
        tr.cell("Abs. non J (h)")
        tr.cell(f"**{discipline['absnj']}**", align='C')
        tr.cell("Avertissement")
        self.draw_tic_orx(tr, discipline['avert'])
        tr.cell("TOTAL")
        self.colored_cell(tr, total_notes, align='C', condition=moyenne < 10)
        tr.cell("**APPRÉCIATIONS**", colspan=2, align='C')
        tr.cell("Moyenne générale")
        self.colored_cell(tr, moy_gen, align='C')

        tr = table.row()
        tr.cell("Abs just. (h)", rowspan=2)
        tr.cell(f"**{discipline['absj']}**", align='C', rowspan=2)
        tr.cell("Blàme de conduite", rowspan=2)
        self.draw_tic_orx(tr, discipline['blame'], rowspan=2)
        tr.cell("COEF")
        tr.cell(f"{total_coef}", align='C')
        tr.cell("CTBA")
        self.draw_tic_orx(tr, appr == "CTBA")
        tr.cell("**[Min - Max]**", rowspan=2)
        tr.cell(f"**{min_max}**", align='C', rowspan=2)

        tr = table.row()
        tr.cell(f"MOYENNE {'ANNUELLE' if self.trimestre == 'ANNUEL' else 'TRIM'}", rowspan=2)
        self.colored_cell(tr, moyenne if moyenne else "/", align='C', rowspan=2)
        tr.cell("CBA")
        self.draw_tic_orx(tr, appr == "CBA")

        tr = table.row()
        tr.cell("Retards (nb de fois)", rowspan=2)
        tr.cell(f"**{discipline['retards']}**", align='C', rowspan=2)
        tr.cell("Exclusions (jours)", rowspan=2)
        tr.cell(f"**{discipline['excl']}**", align='C', rowspan=2)
        tr.cell("CA")
        self.draw_tic_orx(tr, appr == "CA")
        tr.cell("Nombre de moyennes >= 10", rowspan=2)
        tr.cell(f"**{nb_admis}**", align='C', rowspan=2)

        tr = table.row()
        tr.cell("RANG")
        if rang == "/":
            tr.cell(f"**{rang}**", align='C')
        else:
            tr.cell(f"**{rang} / {nb}**", align='C')
        tr.cell("CMA")
        self.draw_tic_orx(tr, appr == "CMA")

        tr = table.row()
        tr.cell("Consignes (h)")
        tr.cell(f"**{discipline['consignes']}**", align='C')
        tr.cell("Exclusion déf")
        self.draw_tic_orx(tr, discipline['excl_def'])
        tr.cell("COTE")
        tr.cell(f"{cote}", align='C')
        tr.cell("CNA")
        self.draw_tic_orx(tr, appr == "CNA")
        tr.cell("Taux de réussite")
        tr.cell(f"**{taux}**", align='C')

        tr = table.row()
        tr.cell(f"Appréciation du travail de l'élève (points forts et poins à améliorer) : "
                f"**__{appreciation}__**", colspan=4, v_align=VAlign.T)
        tr.cell("Visa du Parent/\nTuteur\n\n\n\n\n", align='C', colspan=2, v_align=VAlign.T)
        tr.cell("Nom et visa du professeur principal", align='C', colspan=2, v_align=VAlign.T)
        tr.cell(f"Le {chef}", align='C', colspan=2, v_align=VAlign.T)

        table.render()

    def draw_tic_orx(self, tr, condition, align="C", **kwargs):
        current_font, current_style, current_size = self.font_family, self.font_style, 8
        self.set_font("ZapfDingbats", '', current_size)
        if condition:
            self.set_text_color(0, 0, 255)
            tr.cell(chr(52), align=align, **kwargs)
        else:
            self.set_text_color(255, 0, 0)
            tr.cell(chr(54), align=align, **kwargs)
        self.set_font(current_font, current_style, current_size)
        self.set_text_color(0)

    def colored_cell(self, tr, moy, **kwargs):
        condition = kwargs.pop('condition') if 'condition' in kwargs.keys() else False
        if moy != "/":
            if moy < 10 or condition:
                self.set_text_color(255, 0, 0)
            else:
                self.set_text_color(0, 0, 255)
        tr.cell(f"**{moy}**", **kwargs)
        self.set_text_color(0)
