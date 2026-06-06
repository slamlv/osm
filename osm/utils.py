"""
    Ce fichier contient des classes et des fonctions de base utilisées par les applications
"""
import os
import threading
import uuid
from datetime import datetime, time
from io import BytesIO
from urllib.parse import quote

from django.conf import settings
from django.db.models import Q, Model
from PIL import Image
from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.defaultfilters import title
from django.urls import reverse
from functools import wraps

from django.utils.termcolors import background
from django_tenants.utils import schema_context
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views import View
from fpdf.table import Table

from osm.forms import SearchForm
from staff.models import Personnel, Discipline, Activities
from student.models import Parent
from dynamic_forms import DynamicFormMixin
from classroom.models import ClassRoom, Matieres
from authentification.models import User, School, SchoolYear
from student.models import Student


def delete_image(image):
    """Supprime une image selon le backend : Cloudinary en prod, fichier local en dev."""
    if not image:
        return
    try:
        import os as _os
        public_id = _os.path.splitext(image.name)[0]
        import cloudinary.uploader
        cloudinary.uploader.destroy(public_id)
    except Exception:
        try:
            if os.path.exists(image.path):
                os.remove(image.path)
        except Exception:
            pass


def with_users_school_schema(view_func):
    @wraps(view_func)
    def _wrapped_vied(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse('signin'))
        if not request.user.is_superuser:
            with schema_context(request.user.school.schema_name):
                return view_func(request, *args, **kwargs)
        return render(request, "404_unauthenticated.html")

    return _wrapped_vied


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_vied(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse('signin'))
        if not request.user.is_superuser and request.user.is_admin:
            return view_func(request, *args, **kwargs)
        elif request.user.is_superuser:
            return render(request, "404_unauthenticated.html")
        return render(request, "404.html")

    return _wrapped_vied


class WithUsersSchoolSchema:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse('signin'))
        if not request.user.is_superuser:
            with schema_context(request.user.school.schema_name):
                return super().dispatch(request, *args, **kwargs)
        return render(request, "404_unauthenticated.html")


class LoginRequired(LoginRequiredMixin):
    login_url = "signin"


class AdminRequired:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse('signin'))
        if not request.user.is_superuser and request.user.is_admin:
            return super().dispatch(request, *args, **kwargs)
        elif request.user.is_superuser:
            return render(request, "404_unauthenticated.html")
        return render(request, "404.html")


class LoggedAdminView(LoginRequired, AdminRequired, WithUsersSchoolSchema, View):
    pass


class LoggedUserView(LoginRequired, WithUsersSchoolSchema, View):
    pass


class BaseListView(View):
    template_name: str
    title: str
    model: Model
    objects: str
    id = False

    def get(self, *args, **kwargs):
        datas = self.dataset()
        info = f"{len(datas)} {self.objects} au total."
        context = {'datas': datas, 'info': info, 'title': self.title, 'search_form': SearchForm()}
        if self.model == Student:
            pk = 0
            if self.id:
                classe = ClassRoom.objects.get(id=self.kwargs['id'])
                pk = classe.pk
                context['title'] = f"{self.title} - {classe.code}"
                if 'total' in info:
                    context['info'] += f" {classe.kind_numbers}"
            else:
                if 'total' in info:
                    context['info'] += f" {self.request.user.school.kind_numbers}"
            context['pk'] = pk
        return render(self.request, self.template_name, context=context)

    def post(self, *args, **kwargs):
        datas = self.dataset()
        info = f"{len(datas)} {self.objects} au total."
        search_btn = False
        search_form = SearchForm(self.request.POST)
        if search_form.is_valid():
            search = search_form.cleaned_data['search']
            if search:
                datas = self.dataset(search=search)
                info = f"{len(datas)} {self.objects} trouvé(s)."
                search_btn = True
        context = {"datas": datas, "info": info, "search": search_btn, 'title': self.title, 'search_form': search_form}
        if self.model == Student:
            pk = 0
            if self.id:
                classe = ClassRoom.objects.get(id=self.kwargs['id'])
                pk = classe.pk
                context['title'] = f"{self.title} - {classe.code}"
                if 'total' in info:
                    context['info'] += f" {classe.kind_numbers}"
            else:
                if 'total' in info:
                    context['info'] += f" {self.request.user.school.kind_numbers}"
            context['pk'] = pk
        return render(self.request, self.template_name, context=context)

    # Fonction qui récupère le dataset pour l'établissement de l'administrateur connecté
    def dataset(self, search=""):
        datas = self.model.objects
        if self.model == Personnel:
            datas = datas.select_related('user').order_by_poste()
        elif self.model == User:
            datas = (
                datas.prefetch_related('staff_member').filter(school_id=self.request.user.school.pk).
                exclude(is_superuser=True).order_by("-id")
            )
        elif self.model == ClassRoom:
            datas = datas.select_related('classe').order_by_niveau()
        elif self.model == Discipline:
            datas = datas.order_by('groupe', 'matiere', 'label')
        elif self.model == Student:
            datas = datas.select_related('classe', 'pere', 'mere').order_by_classroom_level()
            if self.id:
                datas = datas.filter(classe_id=self.kwargs['id'])
        else:
            datas = datas.all()
        if search:
            if self.model == Personnel:
                datas = datas.filter(
                    Q(nom__icontains=search) | Q(prenom__icontains=search) | Q(poste__icontains=search))
            elif self.model == User:
                datas = datas.filter(
                    Q(username__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
            elif self.model == ClassRoom:
                datas = datas.filter(Q(code__icontains=search) | Q(classe__niveau__icontains=search) |
                                     Q(classe__serie__icontains=search))
            elif self.model == Discipline:
                datas = datas.filter(
                    Q(label__icontains=search) | Q(matiere__icontains=search) | Q(groupe__icontains=search))
            elif self.model == Student:
                datas = datas.filter(Q(unique_id__icontains=search) | Q(nom__icontains=search) |
                                     Q(prenom__icontains=search))
            elif self.model == Parent:
                datas = datas.filter(Q(nom__icontains=search) | Q(prenom__icontains=search))
            elif self.model == Activities:
                datas = datas.filter(Q(label__icontains=search) | Q(responsables__icontains=search))
        return datas


class ListView(LoginRequired, AdminRequired, WithUsersSchoolSchema, BaseListView):
    pass


class NonAdminListView(LoginRequired, WithUsersSchoolSchema, BaseListView):
    pass


class DeleteView(LoggedAdminView):
    success_url: str
    alerte: str
    model: Model
    title: str
    message: str
    id = None

    def get(self, *args, **kwargs):
        instance = self.get_object()
        if 'cid' in self.kwargs.keys():
            self.success_url = f"class-{self.kwargs['cid']}-subjects"
        if not instance:
            return render(self.request, "404.html")
        info = f"{instance}"
        if self.model == Activities:
            info = "cette activité"
        nb = ""
        back = reverse(self.success_url) if 'cid' not in self.kwargs.keys() else self.success_url
        context = {"info": info, "title": self.title, "alerte": self.alerte, 'back': back}
        if nb:
            context['nb'] = nb
        return render(self.request, template_name="delete.html", context=context)

    def post(self, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        if 'cid' in self.kwargs.keys():
            message(self.request, instance.delete_message)
            return redirect("class-subjects", id=self.kwargs['cid'])
        message(self.request, self.message)
        return redirect(self.success_url)

    def get_object(self):
        if self.model == Personnel:
            queryset = Personnel.objects.select_related('user')
        else:
            queryset = self.model.objects
        instance = get_object_or_404(queryset, pk=self.kwargs['id'])
        if self.model == Personnel:
            if instance.user:
                if instance.user == self.request.user:
                    return None
                return instance
        elif self.model == User:
            if instance == self.request.user:
                return None
        return instance


class BaseStaffMemberTimetable(View):
    def get_object(self):
        mp = self.request.user.school.mergedprogrammations
        instance_id = self.kwargs.get('id')
        title = "Emploi du temps"
        if not instance_id:
            instance_id = self.request.user.staff_member.first().pk
        if mp:
            staffmember = (
                Personnel.objects.prefetch_related('programmations__classrooms','programmations__tranche_horaire',
                                                   'programmations__matiere__sujet').get(pk=instance_id)
            )
        else:
            staffmember = (
                Personnel.objects.prefetch_related('programmations__classroom','programmations__tranche_horaire',
                                                   'programmations__matiere__sujet').get(pk=instance_id)
            )
        title += f" {staffmember.short_firstname}"
        return staffmember, title, mp

    def get(self, *args, **kwargs):
        staffmember, title, mp = self.get_object()
        timetable, staffmember_recap = staffmember.timetable(mp, self.request.user.school.pk)
        context = {'title': title if self.kwargs.get('id') else "Mon Emploi du temps", 'time_table': timetable,
                   'days': ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"), 'recap': staffmember_recap[0],
                   'total_heures': staffmember_recap[1], 'id': self.kwargs.get('id')}
        return render(self.request, "staff_member_timetable.html", context)

    def post(self, *args, **kwargs):
        from classroom.views import StaffMemberTimeTable
        from django.http import JsonResponse
        staffmember, title, mp = self.get_object()
        empty_timetable = True if 'timetable_checkbox' in self.request.POST.keys() else False
        data = {'filename': title, 'annee': school_year()}
        school_id = self.request.user.school.pk
        if empty_timetable:
            data['tranches_horaires'], data['school'] = staffmember.timetable(mp, school_id, empty=True)
            data['filename'] = "Emploi du temps individuel"
        else:
            data['time_table'], data['infos'], data['school'], data['recap_and_total'] = (
                staffmember.timetable(mp, school_id, download=True)
            )
        return pdf_response(StaffMemberTimeTable(data=data), f"{data['filename']}.pdf")


class BaseDetailView(View):
    title: str
    template_name: str
    model: Model

    def get_object(self):
        instance_id = self.kwargs.get("id")
        queryset = self.model.objects
        if self.model == Personnel:
            queryset = queryset.select_related('user').prefetch_related('enseignant__matiere__sujet')
            if self.title == "Mes informations":
                return get_object_or_404(queryset, user_id=self.request.user.pk)
        elif self.model == User:
            queryset = queryset.prefetch_related('staff_member__enseignant__matiere__sujet')
        elif self.model == Parent:
            queryset = queryset.prefetch_related('father_children__classe', 'mother_children__classe')
        elif self.model == School:
            return get_object_or_404(queryset, id=self.request.user.school.pk)
        instance = get_object_or_404(queryset, pk=instance_id)
        return instance

    def get(self, *args, **kwargs):
        instance = self.get_object()
        if self.model == User:
            instance = instance.staff_member.all()[0]
        context = {'object': instance, 'title': self.title}
        if self.model in [Personnel, User]:
            dpc = disciplines_par_classe(instance)
            context['dpc'] = dpc
            if self.template_name in ["details.html", "user_details.html"]:
                context['m_user'] = instance.user
        if self.model == Parent:
            enfants = instance.father_children.all() if instance.civilite == "Monsieur" \
                else instance.mother_children.all()
            context['enfants'] = enfants
        return render(self.request, self.template_name, context)


class DetailView(LoginRequired, WithUsersSchoolSchema, BaseDetailView):
    pass


class ADetailView(LoginRequired, AdminRequired, WithUsersSchoolSchema, BaseDetailView):
    pass


# Matières enseignées dans les classes
def disciplines_par_classe(x):
    ens = x.enseignant.select_related('matiere__sujet', 'classroom')
    if ens:
        dpc = list()
        for enseignement in ens:
            matiere = (enseignement.matiere.sujet.matiere,
                       enseignement.matiere.sujet.label)[enseignement.matiere.sujet.matiere is None]
            status = False
            for elt in dpc:
                if matiere == elt['matiere']:
                    if enseignement.classroom not in elt['classes']:
                        elt['classes'].append(enseignement.classroom)
                    status = True
                    break
            if not status:
                d = {"matiere": matiere, "classes": [enseignement.classroom, ]}
                dpc.append(d)
        return dpc
    return None


def logged_admin_view(view_func):
    wrapped = login_required(view_func, login_url="signin")
    wrapped = admin_required(wrapped)
    wrapped = with_users_school_schema(wrapped)
    return wrapped


def logged_user_view(view_func):
    wrapped = login_required(view_func, login_url="signin")
    wrapped = with_users_school_schema(wrapped)
    return wrapped


def icon(subject):
    if "Mathématiques" in (subject.label, subject.matiere):
        return "fas fa-superscript"
    elif ("Physique" in (subject.label, subject.matiere)) or ("PCT" in (subject.label, subject.matiere)):
        return "fas fa-cogs"
    elif "Chimie" in (subject.label, subject.matiere):
        return "fas fa-flask"
    elif "Informatique" in (subject.label, subject.matiere):
        return "fas fa-desktop"
    elif ("Français" in (subject.label, subject.matiere)) or ("Anglais" in (subject.label, subject.matiere)):
        return "fas fa-book-open"
    elif "Géographie" in (subject.label, subject.matiere):
        return "fas fa-globe"
    elif "Histoire" in (subject.label, subject.matiere):
        return "fas fa-history"
    elif "Philosophie" in (subject.label, subject.matiere):
        return "fas fa-lightbulb"
    elif "EPS" in (subject.label, subject.matiere):
        return "fas fa-running"
    elif "Education Artistique" in (subject.label, subject.matiere):
        return "fas fa-brush"
    elif "Travail Manuel" in (subject.label, subject.matiere):
        return "fas fa-tools"
    elif "ECM" in (subject.label, subject.matiere):
        return "fas fa-handshake"
    elif ("LVII" in (subject.label, subject.matiere)) or ("LVIII" in (subject.label, subject.matiere)):
        return "fas fa-language"
    elif ("SVTEEHB" in (subject.label, subject.matiere)) or ("Sciences" in (subject.label, subject.matiere)):
        return "fas fa-dna"
    return "fas fa-book"


def is_alphanumeric(string):
    for char in string:
        if char in [' ', '-']:
            continue
        elif not char.isalnum():
            return False
    return True


def one_escape(string):
    string = string.strip()
    while string.count("  ") > 0:
        string = string.replace("  ", " ")
    return string


def greet():
    date_time = datetime.now()
    hour = date_time.hour
    if 0 <= hour <= 12:
        salutation = "Bonjour"
    elif 12 < hour < 18:
        salutation = "Bon après-midi"
    else:
        salutation = "Bonsoir"
    return salutation


def get_value(dico: dict, key_value: str):
    try:
        return dico[key_value]
    except KeyError:
        for key in dico.keys():
            if key_value and key_value in key:
                return dico[key]
        raise KeyError("Clé incorrecte")


def formated_float(f: float, n=2):
    sff = str(f)
    while sff[-1] in [".", "0"]:
        if sff.isnumeric():
            break
        sff = sff[0:-1]
    if "." in sff:
        pid = sff.index(".") + 1
        d = len(sff) - pid
        if d > n:
            last = sff[len(sff) - d + n]
            sff = sff[0:len(sff) - d + n]
            sff = sff if int(last) < 5 else sff[0:-1] + f"{int(sff[-1]) + 1}"
        return float(sff)
    return int(sff)


def resized_image(url):
    img = Image.open(url)
    w, h = img.width, img.height
    if w / 2 > 500:
        img.thumbnail((int(w / 2), int(h / 2)), resample=Image.LANCZOS)
    return img


def school_year():
    return SchoolYear.current().libelle


def message(request, msg: str, msg_type="success"):
    for _ in messages.get_messages(request):
        pass
    if msg_type == "warning":
        messages.warning(request, msg)
    elif msg_type == "info":
        messages.info(request, msg)
    elif msg_type == "error":
        messages.error(request, msg)
    else:
        messages.success(request, msg)


def cote_and_appr(note):
    if note <= 0 or note > 20:
        return "/", "/"
    cote = (((((("D", "C")[10 <= note < 12], "C+")[12 <= note < 14], "B")[14 <= note < 15], "B+")
             [15 <= note < 16], "A")[16 <= note < 18], "A+")[18 <= note <= 20]
    appr = ((((("CNA", "CMA")[cote == "C"], "CA")[cote == "C+"], "CBA")[cote in ["B", "B+"]]), "CTBA")[
        cote in ["A", "A+"]]
    return cote, appr


def resize_image(image_path, new_width=295, quality=80, return_height=False, id_card=False):
    img = Image.open(image_path)
    if id_card:
        new_size = (413, 472)
        new_img = img.copy()
        new_img.thumbnail(new_size, Image.LANCZOS)
        background = Image.new("RGB", new_size, (255, 255, 255))
        offset = (int((new_size[0] - new_img.width) / 2), int((new_size[1] - new_img.height) / 2))
        background.paste(new_img, offset)
        buffer = BytesIO()
        background.save(buffer, format="JPEG", dpi=(300, 300))
        buffer.seek(0)
        return buffer
    img = img.convert("RGB")
    width, height = img.size
    aspect_ratio = height / width
    new_height = int(new_width * aspect_ratio)
    img = img.resize((new_width, new_height), Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", optimize=True, quality=quality)
    buffer.seek(0)
    if return_height:
        return buffer, new_height
    return buffer


def truncate_str(pdf, str_value: str, max_with: float):
    if pdf.get_string_width(str_value) < max_with:
        return str_value
    for i in range(len(str_value), 0, -1):
        truncate_value = str_value[:i] + "."
        if pdf.get_string_width(truncate_value) <= max_with:
            return truncate_value


def pdf_response(fpdf_object, final_filename):
    """Retourne directement un FileResponse en mémoire — aucun fichier temp."""
    buffer = BytesIO()
    fpdf_object.output(buffer)
    buffer.seek(0)
    filename_ascii = final_filename.encode('ascii', 'ignore').decode('ascii')
    quoted = quote(final_filename)
    response = FileResponse(buffer, as_attachment=True, filename=filename_ascii)
    response['Content-Disposition'] = (
        f"attachment; filename='{filename_ascii}'; filename*=UTF-8''{quoted}"
    )
    return response


def add_minutes(my_time: time, minutes: int):
    hour = my_time.hour
    my_minutes = my_time.minute
    if minutes > 60:
        return None
    if minutes == 60:
        return time(hour=hour + 1, minute=my_minutes)
    new_minutes = my_minutes + minutes
    if new_minutes >= 60:
        new_minutes -= 60
        hour += 1
    return time(hour=hour, minute=new_minutes)


def default_competences(level, matiere, evalx):
    competences = {
        'Sixième': {
            'Anglais': {
                1: "Use appropriate language skills and resources to talk about oneself, the family, and school community",
                2: "Use appropriate language skills and resources to buy, sell, and explore jobs and professions",
                3: "Use appropriate language skills and resources to talk about the rights and duties of a child and basic civic duties",
                4: "Use appropriate language skills and resources to talk about the rights and duties of a child and basic civic duties",
                5: "Use appropriate language skills and resources to talk about audio-visual, print media and modern technology",
                6: "Use appropriate language skills and resources to talk about audio-visual, print media and modern technology"
            },
            'Informatique': {
                1: "Identifier les éléments matériels, logiciels d'un microordinateur et distinguer les types et rôles des différents utilisateurs",
                2: "Décrire les composants externes à l'unité centrale d'un microordinateur et se conformer aux attitudes règlementaires dans un laboratoire informatique",
                3: "Pratiquer les comportements citoyens en respectant les règles d'éthique face au numérique",
                4: "Identifier les actions proscrites et les conséquences en cas d'une utilisation non autorisée",
                5: "Identifier les données et filtrer les opérations permettant d'avoir une solution face à un problème donné",
                6: "Ordonner une série d'actions pour résoudre un poroblème donné"
            },
            'Correction Orthographique': {
                1: "Corriger des erreurs volontairement insérées dans un dialogue et une lettre privée",
                2: "Corriger des erreurs volontairement insérées dans un dialogue et une lettre privée",
                3: "Corriger des erreurs volontairement insérées dans un texte descriptif",
                4: "Corriger des erreurs volontairement insérées dans un texte descriptif",
                5: "Corriger des erreurs volontairement insérées dans un texte narratif",
                6: "Corriger des erreurs volontairement insérées dans un texte narratif"
            },
            'Orthographe': {
                1: "Orthographier correctement un dialogue et une lettre privée ou bien y corriger des erreurs volontairement insérées",
                2: "Orthographier correctement un dialogue et une lettre privée ou bien y corriger des erreurs volontairement insérées",
                3: "Orthographier correctement un texte descriptif ou bien y corriger des erreurs volontairement insérées",
                4: "Orthographier correctement un texte descriptif ou bien y corriger des erreurs volontairement insérées",
                5: "Orthographier correctement un texte narratif ou bien y corriger des erreurs volontairement insérées",
                6: "Orthographier correctement un texte narratif ou bien y corriger des erreurs volontairement insérées"
            },
            'Étude de texte': {
                1: "Répondre correctement à des questions sur un dialogue et sur une lettre privée",
                2: "Répondre correctement à des questions sur un dialogue et sur une lettre privée",
                3: "Répondre correctement à des questions sur un texte descriptif (portrait/description d'un objet ou d'un lieu)",
                4: "Répondre correctement à des questions sur un texte descriptif (portrait/description d'un objet ou d'un lieu)",
                5: "Répondre correctement à des questions sur un texte narratif",
                6: "Répondre correctement à des questions sur un texte narratif"
            },
            'Expression': {
                1: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, un dialogue et une lettre privée",
                2: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, un dialogue et une lettre privée",
                3: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, un texte descriptif",
                4: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, un texte descriptif",
                5: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, un texte narratif",
                6: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, un texte narratif"
            },
            'Expression Écrite': {
                1: "Produire à l'écrit, dans une langue correcte et usuelle, un dialogue et une lettre privée",
                2: "Produire à l'écrit, dans une langue correcte et usuelle, un dialogue et une lettre privée",
                3: "Produire à l'écrit, dans une langue correcte et usuelle, un texte descriptif",
                4: "Produire à l'écrit, dans une langue correcte et usuelle, un texte descriptif",
                5: "Produire à l'écrit, dans une langue correcte et usuelle, un texte narratif",
                6: "Produire à l'écrit, dans une langue correcte et usuelle, un texte narratif"
            },
            'Expression Orale': {
                1: "Produire à l'oral, dans une langue correcte et usuelle, un dialogue et une lettre privée",
                2: "Produire à l'oral, dans une langue correcte et usuelle, un dialogue et une lettre privée",
                3: "Produire à l'oral, dans une langue correcte et usuelle, un texte descriptif",
                4: "Produire à l'oral, dans une langue correcte et usuelle, un texte descriptif",
                5: "Produire à l'oral, dans une langue correcte et usuelle, un texte narratif",
                6: "Produire à l'oral, dans une langue correcte et usuelle, un texte narratif"
            },
            'Langues Nationales': {
                1: "Parler de la diversité linguistique camerounaise et placer les langues nationales dans les aires linguistiques auxquelles elles appartiennent",
                2: "Parler de la diversité linguistique camerounaise et placer les langues nationales dans les aires linguistiques auxquelles elles appartiennent",
                3: "Produire des messages en langues nationales en employant les consonnes simples de l'Alphabet Général des Langues Camerounaies (AGLC) dans diverses situations de vie",
                4: "Produire des messages en langues nationales en employant les consonnes complexes de l'AGLC dans diverses situations de vie",
                5: "Produire des messages en langues nationales en employant les consonnes complexes de l'AGLC dans diverses situations de vie",
                6: "Produire des messages en langues nationales en employant les consonnes complexes de l'AGLC dans diverses situations de vie"
            },
            'ECM': {
                1: "Promouvoir l'intégration à la vie familiale et sociale",
                2: "Promouvoir l'intégration à la vie familiale et sociale",
                3: "Prévenir et régler les conflits",
                4: "Prévenir et régler les conflits",
                5: "Promouvoir et protéger les droits de l'homme",
                6: "Promouvoir et protéger les droits de l'homme"
            },
            'Géographie': {
                1: "S'adapter aux influences cosmiques",
                2: "S'adapter aux influences cosmiques",
                3: "Protéger l'environnement",
                4: "Protéger l'environnement",
                5: "S'adapter aux pertubations climatiques",
                6: "Gérer les catastrophes"
            },
            'Histoire': {
                1: "Utiliser les savoirs historiques",
                2: "Découvrir les traits culturels",
                3: "Découvrir les traits culturels",
                4: "Découvrir les traits culturels",
                5: "S'adapter à une environnement multi-religieux",
                6: "S'adapter à une environnement multi-religieux"
            },
            'Mathématiques': {
                1: "Résoudre des situations problèmes relatives aux nombres (entiers naturels, décimaux arithmétiques, décimaux relatifs), aux droites et segments dans le plan et aux cercles",
                2: "Résoudre des situations problèmes relatives aux nombres (entiers naturels, décimaux arithmétiques, décimaux relatifs), aux droites et segments dans le plan et aux cercles",
                3: "Résoudre des situations problèmes relatives aux fractions, aux proportionnalités, au calcul littéral, aux angles, aux triangles, aux symétries centrales, au parallélogramme, au cube et au pavé droit",
                4: "Résoudre des situations problèmes relatives aux fractions, aux proportionnalités, au calcul littéral, aux angles, aux triangles, aux symétries centrales, au parallélogramme, au cube et au pavé droit",
                5: "Résoudre des situations problèmes relatives au repérage d'un point sur une droite, aux cylindres de révolution et aux symétries orthogonales",
                6: "Résoudre des situations problèmes relatives au repérage d'un point sur une droite, aux cylindres de révolution et aux symétries orthogonales"
            },
            'Sciences': {
                1: "Résoudre en utilisant la méthode scientifique, des situations problèmes relatives à l'insuffisances ds ressources comestibles et aux propriétés physiques de la matière",
                2: "Communiquer oralement ou à l'écrit à l'aide d'un langage et des symboles scientifiques adéquats",
                3: "Résoudre en utilisant la méthode scientifique, des situations problèmes relatives à l'utilisation de l'énergie, à l'éducation à la santé de reproduction et à l'hygiène de l'alimentation",
                4: "Communiquer scientifiquement à l'oral ou à l'écrit sur l'utilisation de l'énergie, à l'éducation à la santé de reproduction et à l'hygiène de l'alimentation",
                5: "Résoudre en utilisant la méthode scientifique, des situations problèmes relatives à la gestion durable des ressources naturelles et à la réalisation de projets techniques simples",
                6: "Communiquer scientifiquement à l'oral ou à l'écrit sur ces thèmes à l'aide d'un vocabulaire et des symboles scientifiques adéquats"
            },
            'EPS': {
                1: "Exécuter une course de vitesse et une course d'endurence-vitesse",
                2: "Manipuler et lancer le poids, exécuter le saut en hauteur",
                3: "Exécuter les différentes techniques de gymnastique au sol (déplacement, envol, rotation et renversement)",
                4: "Pratiquer les sports collectifs : Football, Basket-ball, Handball et Volley-ball (marquer les buts, conserver le ballon, se démarquer, se positionner)",
                5: "Pratiquer les sports collectifs : Football, Basket-ball, Handball et Volley-ball (empêcher de marquer, récupérer le ballon, gêner la progression de l'adversaire, servir et réceptionner le ballon et bloquer le ballon)",
                6: "Pratiquer les sports collectifs : Football, Basket-ball, Handball et Volley-ball (empêcher de marquer, récupérer le ballon, gêner la progression de l'adversaire, servir et réceptionner le ballon et bloquer le ballon)"
            },
            'Travail Manuel': {
                1: "Utiliser le matériel, les matériaux et les techniques pour dessiner le kiosque et autres objets",
                2: "Utiliser les outils et le matériel agricole pour produire une pépinière, utiliser le matériel et les matériaux pour monter une ferme et y placer des poussins",
                3: "Utiliser le matériel de dessin et les gouaches pour peindre un kiosque et autres objets",
                4: "Utiliser les outils et les méthodes pour produires du compost, utiliser le matériel avicole pour installer et entretenir une ferme",
                5: "Entretenir les objets d'art et user des techniques de vente pour écouler ces objets",
                6: "Utiliser le compost dans le jardinage et recourir aux techniques de commercialisation / vente pour écouler le compost et les poulets de chair"
            },
        },
        'Cinquième': {
            'Anglais': {
                1: "Use appropriate grammatical structures and vocabulary to discuss, read, and write about interpersonal relationship and talk about the home / habits and routines / home furniture",
                2: "Use appropriate grammatical structures and vocabulary to discuss, read, and write about different jobs ans professions",
                3: "Use appropriate grammatical structures and vocabulary to discuss, read, and write about environmental awareness, interests and hobbies in relation to health",
                4: "Use appropriate grammatical structures and vocabulary to discuss, read, and write about citizens of the nation and the world",
                5: "Use appropriate grammatical structures and vocabulary to discuss, read, and write about the use of modern technology",
                6: "Use appropriate grammatical structures and vocabulary to discuss, read, and write about the use of modern technology"
            },
            'Informatique': {
                1: "Décrire et classer par types les périphériques et interfaces d'entrée / sortie de l'unité centrale d'un microordinateur et connecter correctement chaque périphérique au port correespondant",
                2: "Classer les logiciels en donnant leus fonctions et identifier les principaux éléments d'un système d'exploitation",
                3: "Saisir et mettre en forme un texte et distinguer les logiciels utilitaires en donnant leur rôle et fonction",
                4: "Pratiquer l'éthique du numérique et protéger les équipemments et les données de l'ordinateur",
                5: "Construire une représentation mentale d'un objet, un son, une situation, une image, une émotion ou une sensation sur le plan et dans l'espace",
                6: "Représenter la solution d'un problème à partir d'un schéma 2D et 3D"
            },
            'Correction Orthographique': {
                1: "Corriger des erreurs volontairement insérées dans une lettre officielle et une description associée au récit",
                2: "Corriger des erreurs volontairement insérées dans une lettre officielle et une description associée au récit",
                3: "Corriger des erreurs volontairement insérées dans une description associée à l'expression des sentiments et un dialogue associé au récit",
                4: "Corriger des erreurs volontairement insérées dans une description associée à l'expression des sentiments et un dialogue associé au récit",
                5: "Corriger des erreurs volontairement insérées dans un texte narratif intégrant des dialogues et un texte narratif intégrant l'expression des sentiments",
                6: "Corriger des erreurs volontairement insérées dans un texte narratif intégrant des dialogues et un texte narratif intégrant l'expression des sentiments"
            },
            'Orthographe': {
                1: "Orthographier correctement une lettre officielle et une description associée au récit ou bien y corriger des erreurs volontairement insérées",
                2: "Orthographier correctement une lettre officielle et une description associée au récit ou bien y corriger des erreurs volontairement insérées",
                3: "Orthographier correctement une description associée à l'expression des sentiments et un dialogue associé au récit ou bien y corriger des erreurs volontairement insérées",
                4: "Orthographier correctement une description associée à l'expression des sentiments et un dialogue associé au récit ou bien y corriger des erreurs volontairement insérées",
                5: "Orthographier correctement un texte narratif intégrant des dialogues et un texte narratif intégrant l'expression des sentiments ou bien y corriger des erreurs volontairement insérées",
                6: "Orthographier correctement un texte narratif intégrant des dialogues et un texte narratif intégrant l'expression des sentiments ou bien y corriger des erreurs volontairement insérées"
            },
            'Étude de texte': {
                1: "Répondre correctement à des questions sur une lettre officielle et sur une description associée au récit",
                2: "Répondre correctement à des questions sur une lettre officielle et sur une description associée au récit",
                3: "Répondre correctement à des questions sur un texte descriptif intégrant l'expression des sentiments ou sur un dialogue associé au récit",
                4: "Répondre correctement à des questions sur un texte descriptif intégrant l'expression des sentiments ou sur un dialogue associé au récit",
                5: "Répondre correctement à des questions sur un texte narratif intégrant des dialogues et/ou l'expression des sentiments",
                6: "Répondre correctement à des questions sur un texte narratif intégrant des dialogues et/ou l'expression des sentiments"
            },
            'Expression': {
                1: "Produire dans une langue correcte et usuelle, une lettre officielle et une description associée au récit",
                2: "Produire dans une langue correcte et usuelle, une lettre officielle et une description associée au récit",
                3: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, une description enrichie de l'expression des sentiments et une narration associée au dialogue",
                4: "Produire à l'oral comme à l'écrit, dans une langue correcte et usuelle, une description enrichie de l'expression des sentiments et une narration associée au dialogue",
                5: "Produire à l'oral comme à l'écrit, une narration intégrant des dialogues et un texte narratif asocié à l'expression des sentiments",
                6: "Produire à l'oral comme à l'écrit, une narration intégrant des dialogues et un texte narratif asocié à l'expression des sentiments"
            },
            'Expression Écrite': {
                1: "Produire à l'écrit, dans une langue correcte et usuelle, une lettre officielle et une description associée au récit",
                2: "Produire à l'écrit, dans une langue correcte et usuelle, une lettre officielle et une description associée au récit",
                3: "Produire à l'écrit, dans une langue correcte et usuelle, une description enrichie de l'expression des sentiments et une narration associée au dialogue",
                4: "Produire à l'écrit, dans une langue correcte et usuelle, une description enrichie de l'expression des sentiments et une narration associée au dialogue",
                5: "Produire à l'écrit, une narration intégrant des dialogues et un texte narratif asocié à l'expression des sentiments",
                6: "Produire à l'écrit, une narration intégrant des dialogues et un texte narratif asocié à l'expression des sentiments"
            },
            'Expression Orale': {
                1: "Produire à l'oral, dans une langue correcte et usuelle, une lettre officielle et une description associée au récit",
                2: "Produire à l'oral, dans une langue correcte et usuelle, une lettre officielle et une description associée au récit",
                3: "Produire à l'oral, dans une langue correcte et usuelle, une description enrichie de l'expression des sentiments et une narration associée au dialogue",
                4: "Produire à l'oral, dans une langue correcte et usuelle, une description enrichie de l'expression des sentiments et une narration associée au dialogue",
                5: "Produire à l'oral, une narration intégrant des dialogues et un texte narratif asocié à l'expression des sentiments",
                6: "Produire à l'oral, une narration intégrant des dialogues et un texte narratif asocié à l'expression des sentiments"
            },
            'Langues Nationales': {
                1: "Produire des messages en langues nationales en employant la forme correcte du nom dans diverses situations de vie",
                2: "Produire des messages en langues nationales en employant correctement les déterminants du nom dans diverses situations de vie",
                3: "Produire des messages en langues nationales en employant la forme correcte du verbe dans diverses situations de vie",
                4: "Produire des messages en langues nationales en employant correctement les autres constituants du groupe verbal (adverbe et compléments) dans diverses situations de vie",
                5: "Produire des messages en langues nationales en employant correctement les phrases simples dans diverses situations de vie",
                6: "Produire des messages en langues nationales en employant correctement les phrases complexes dans diverses situations de vie"
            },
            'ECM': {
                1: "Promouvoir l'intégration nationale : manifestations et entraves",
                2: "Promouvoir l'intégration nationale : manifestations et entraves",
                3: "Promouvoir l'intégration nationale : lieux de promotion",
                4: "Promouvoir l'intégration nationale : lieux de promotion",
                5: "Rechercher la bonne information et le bon usage des TIC",
                6: "Rechercher la bonne information et le bon usage des TIC"
            },
            'Géographie': {
                1: "Contrôler la croissance démographique",
                2: "Contrôler la croissance démographique",
                3: "Adopter les comportements écologiques",
                4: "Adopter les comportements écologiques",
                5: "Limiter les migrations",
                6: "Limiter les migrations"
            },
            'Histoire': {
                1: "Promouvoir l'intégration nationale",
                2: "Promouvoir l'intégration nationale",
                3: "promouvoir l'esprit de leadership et de bâtisseur",
                4: "promouvoir l'esprit de leadership et de bâtisseur",
                5: "Protéger et renforcer l'identité africaine",
                6: "Protéger et renforcer l'identité africaine"
            },
            'Mathématiques': {
                1: "Résoudre des situations problèmes relatives à l'arithmétique, aux fractions, aux nombres décimaux, aux distances et aux triangles",
                2: "Résoudre des situations problèmes relatives à l'arithmétique, aux fractions, aux nombres décimaux, aux distances et aux triangles",
                3: "Résoudre des situations problèmes relatives au calcul littéral, aux proportionnalités, aux statistiques, aux polygones, aux symétries, aux angles, au cercle et au repérage d'un point sur une droite ou sur un quadrillage",
                4: "Résoudre des situations problèmes relatives au calcul littéral, aux proportionnalités, aux statistiques, aux polygones, aux symétries, aux angles, au cercle et au repérage d'un point sur une droite ou sur un quadrillage",
                5: "Résoudre des situations problèmes relatives aux prismes droit et à la sphère",
                6: "Résoudre des situations problèmes relatives aux prismes droits et à la sphère"
            },
            'Sciences': {
                1: "Résoudre, en utilisant la méthode scientifique, des situations problèmes relatives à l'amélioration de la production alimentaire et la pérennité de l'éspèce humaine, aux transformations physiques de la matière et à l'utilisation de l'énergie",
                2: "Communiquer scientifiquement à l'oral ou à l'écrit sur la production alimentaires et la pérennité de l'espèce humaine, aux transformations physiques de la matière et à l'utilisation de l'énergie",
                3: "Résoudre, en utilisant la méthodde scientifique, des situations problèmes relatives à l'éducation à la santé de reproduction et la prévalence des intoxications alimentaires",
                4: "Communiquer scientifiquement à l'oral ou à l'écrit sur l'éducation à la santé de reproduction et la prévalence des intoxications alimentaires",
                5: "Résoudre, en utilisant la méthodde scientifique, des situations problèmes relatives à la gestion durable des ressources naturelles et à la réalisation d'un projet technique simple",
                6: "Communiquer scientifiquement à l'oral ou à l'écrit sur la gestion durable des ressources naturelles et à la réalisation d'un projet technique simple"
            },
            'EPS': {
                1: "Exécuter une course de vitesse et une course d'endurance-vitesse",
                2: "Manipuler et lancer le poids, exécuter le saut en hauteur",
                3: "Exécuter les différentes techniques de gymnastique au sol (déplacement, envol, rotation et renversement)",
                4: "Pratiquer les sports collectifs : Football, Basket-ball, Handball et Volley-ball (marquer les buts, conserver le ballon, se démarquer, se positionner)",
                5: "Pratiquer les sports collectifs : Football, Basket-ball, Handball et Volley-ball (empêcher de marquer, récupérer le ballon, gêner la progression de l'adversaire, servir et réceptionner le ballon et bloquer le ballon)",
                6: "Pratiquer les sports collectifs : Football, Basket-ball, Handball et Volley-ball (empêcher de marquer, récupérer le ballon, gêner la progression de l'adversaire, servir et réceptionner le ballon et bloquer le ballon)"
            },
            'Travail Manuel': {
                1: "Utiliser le matériel, les matériaux et les techniques pour dessiner et peindre un paysage et les plantes",
                2: "Utiliser les outils agricoles pour semer / cultiver les légumes à feuilles et les fruits, utiliser le matériel d'élevage pour élever les pondeuses pour les œufs",
                3: "Entretenir et conserver le matériel, les matériaux et les objets d'arts",
                4: "Préparer le sol, semer et entretenir les légumes à feuilles et les fruits, installer et entretenir les pondeuses pour la production des œufs",
                5: "Utiliser les techniques de vente pour commercialiser les objets d'arts",
                6: "Utiliser les techniques de vente pour commercialiser les légumes et les fruits, les pondeuses et les œufs"
            },
        },
        'Quatrième': {
            'Anglais': {
                1: "Use appropriate language resources to listen, speak, read and write about social integration (traditions and customs of Cameroon and conflict resolution)",
                2: "Use appropriate language resources to listen, speak, read and write about future professional life and participating in leisure activities",
                3: "Use appropriate language resources to listen, speak, read and write about the protection of the environment and the fight against endemic and pandemic diseases",
                4: "Use appropriate language resources to listen, speak, read and write about gender issues and mutual acceptance",
                5: "Use appropriate language resources to listen, speak, read and write about exploring ICTs",
                6: "Use appropriate language resources to listen, speak, read and write about exploring ICTs"
            },
            'Informatique': {
                1: "Décrire les composants internes de l'unité centrale et mettre en évidence le rôle et les caractéristiques des mémoires",
                2: "Installer un logiciel applicatif et présenter son interface d'une part et mettre en évidence les fonctions des logiciels systèmes d'autre part",
                3: "Utiliser les outils TIC pour effectuer des recherches et échanger des informations sur internet",
                4: "Produire des contenus numériques en utilisant un texteur ou un tableur",
                5: "Adopter des comportements citoyens en garantissant la vie privée, la propriété intellectuelle et une navigation sécurisée sur internet",
                6: "Proposer suivant une approche non formelle une solution algorithmique à un problème en utilisant des structures de contrôle"
            },
            'Correction Orthographique': {
                1: "Corriger des erreurs volontairement insérées dans un texte",
                2: "Corriger des erreurs volontairement insérées dans un texte",
                3: "Corriger des erreurs volontairement insérées dans un texte",
                4: "Corriger des erreurs volontairement insérées dans un texte",
                5: "Corriger des erreurs volontairement insérées dans un texte",
                6: "Corriger des erreurs volontairement insérées dans un texte"
            },
            'Orthographe': {
                1: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                2: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                3: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                4: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                5: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                6: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées"
            },
            'Étude de texte': {
                1: "Répondre correctement à des questions sur un texte",
                2: "Répondre correctement à des questions sur un texte",
                3: "Répondre correctement à des questions sur un texte",
                4: "Répondre correctement à des questions sur un texte",
                5: "Répondre correctement à des questions sur un texte",
                6: "Répondre correctement à des questions sur un texte"
            },
            'Expression': {
                1: "Produire à l'écrit, un texte descriptif et à l'oral, un commentaire de l'image",
                2: "Produire à l'écrit, un texte narratif et à l'oral, un compte rendu oral",
                3: "Produire à l'écrit, un texte argumentatif et à l'oral, prononcer un discours",
                4: "Produire à l'écrit, un texte argumentatif et à l'oral, exprimer son point de vue dans un débat",
                5: "Produire à l'écrit, un texte injonctif et à l'oral, présenter un exposé",
                6: "Produire à l'écrit, divers textes informatifs et à l'oral, s'exprimer dans le cadre d'une interview"
            },
            'Expression Écrite': {
                1: "Produire à l'écrit, un texte descriptif",
                2: "Produire à l'écrit, un texte narratif",
                3: "Produire à l'écrit, un texte argumentatif",
                4: "Produire à l'écrit, un texte argumentatif",
                5: "Produire à l'écrit, un texte injonctif",
                6: "Produire à l'écrit, divers textes informatifs"
            },
            'Expression Orale': {
                1: "Produire à l'oral, un commentaire de l'image",
                2: "produire à l'oral, un compte rendu",
                3: "Prononcer un discours",
                4: "Exprimer son point de vue dans un débat",
                5: "Présenter un exposé",
                6: "S'exprimer dans le cadre d'une interview"
            },
            'Langues Nationales': {
                1: "Produire des énoncés dans la langue cible en respectant les règles orthographiques de cette langue",
                2: "Produire des énoncés dans la langue cible en respectant les règles grammaticales propres au syntagme nominal",
                3: "Produire des syntagmes nominaux dans la langue cible en respectant les accords y relatifs",
                4: "Produire des phrases en conjugant correctement les verbes aux temps du présent dans la langue nationale cible",
                5: "Produire des phrases en conjuguant correctement les verbes aux temps du futur et du passé dans la langue nationale cible",
                6: "Produire des phrases comportant des compléments d'objet direct, des compléments d'objet indirect et des compléments circonstanciels dans la langue nationale cible"
            },
            'Allemand': {
                1: "Comprendre et produire de courts énoncés / textes écrits d'au moins 40 mots, relatifs à la vie quotidienne et à la vie familiale et sociale",
                2: "Comprendre et produire de courts énoncés / textes oraux relatifs à la vie quotidienne et à la vie familiale et sociale",
                3: "Comprendre et produire de courts énoncés / textes écrits d'au moins 40 mots, relatifs à l'environnement, à la santé, au bien-être et aux médias de communication",
                4: "Comprendre et produire à l'oral de courts textes / énoncés relatifs à l'environnement, à la santé, au bien-être et aux médias de communication",
                5: "Comprendre et produire de courts énoncés / textes écrits d'au moins 40 mots, relatifs à la citoyenneté et à la vie économique",
                6: "Réception et production de courts énoncés / textes oraux relatifs à la citoyenneté et à la vie économique"
            },
            'Espagnol': {
                1: "Comprendre et produire des messages écrits d'au moins 40 mots, relatifs à la famille et la société, à l'environnement, la santé et le bien-être",
                2: "Comprendre et produire des messages oraux relatifs à la société, à l'environnement, la santé et le bien-être",
                3: "Comprendre et produire des messages écrits d'au moins 40 mots, relatifs à la citoyenneté et à la vie économique",
                4: "Comprendre et produire des messages oraux relatifs à la citoyenneté et à la vie économique",
                5: "Comprendre et produire des messages d'au moins 40 mots, relatifs aux medias et à la comunication",
                6: "Comprendre et produire des messages oraux relatifs aux medias et à la communication"
            },
            'ECM': {
                1: "Participer à la vie de l'État",
                2: "Participer à la vie de l'État",
                3: "Participer à la vie de l'État",
                4: "Participer à la vie de l'État",
                5: "Lutter contre les fléaux sociaux et les nuisances",
                6: "Lutter contre les fléaux sociaux et les nuisances"
            },
            'Géographie': {
                1: "Gérer durablement l'environnement",
                2: "Protéger les paysages naturels",
                3: "Produire des biens et des services",
                4: "Produire des biens et des services",
                5: "Produire des biens et des services",
                6: "Promouvoir la coopération sous régionale"
            },
            'Histoire': {
                1: "Protéger et promouvoir les droits",
                2: "Protéger et promouvoir les droits",
                3: "Promouvoir l'intégration régionale",
                4: "Promouvoir l'intégration régionale",
                5: "Promouvoir l'intégration régionale",
                6: "Gérer durablement les ressources naturelles"
            },
            'Mathématiques': {
                1: "Résoudre des situations problèmes relatives à l'arithmétique, aux nombres rationnels, à la distance, aux triangles et au cercle",
                2: "Communiquer à l'aide du langage mathématique dans des situations relatives aux notions précédemment étudiées",
                3: "Résoudre des situations problèmes relatives au calcul littéral, aux vecteurs, aux équations et inéquations, aux translations, au repérage et aux plans et droites de l'espace",
                4: "Communiquer à l'aide du langage mathématique dans des situations relatives aux notions précédemment étudiées",
                5: "Résoudre des situations problèmes relatives à la proportionnalité, à la pyramide, aux statistiques et au cône de révolution",
                6: "Communiquer à l'aide du langage mathématique dans des situations relatives aux notions précédemment étudiées"
            },
            'PCT': {
                1: "Résoudre, en utilisant la méthode scientifique, des situations problèmes relatives aux propriétés de la matière, à l'utilisation des instruments de dessin, à la mise en page et la cotation d'un dessin technique",
                2: "Communiquer en utilisant le langage et les symboles scientifiques, sur les propriétés de la matière, l'utilisation des instruments de dessin, la mise en page et la cotation d'un dessin technique",
                3: "Résoudre, en utilisant la méthode scientifique, des situations problèmes relatives à l'énergie électrique, à l'utilisation des produits chimiques courants et à la notion d'engrais",
                4: "Communiquer, en utilisant le langage et les symboles scientifiques, sur l'énergie électrique, sur l'utilisation des produits chimiques courants et sur la notion d'engrais",
                5: "Résoudre, en utilisant la méthode scientifique, des situations problèmes relatives à la pollution liée à l'utilisation des engrais, à des projets techniques simples faisant appel à l'exécution de la perspective cavalière et de la projection orthogonale et aux actions mécaniques",
                6: "Communiquer, en utilisant le langage et les symboles scientifiques sur pollution liée à l'utilisation des engrais, à des projets techniques simples faisant appel à l'exécution de la perspective cavalière et de la projection orthogonale et aux actions mécaniques"
            },
            'SVTEEHB': {
                1: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à la couverture des besoins alimentaires de l'Homme",
                2: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à la gestion durable de la biodiversité et l'amélioration de la santé de l'appareil moteur",
                3: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situtations problèmes relatives à l'amélioration de la santé de l'appareil moteur, de la sensibilité et de l'alimentation",
                4: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situtations problèmes relatives à l'amélioration de la santé de l'alimentation, de la reproduction, ainsi qu'à la récurrence des risques d'origine naturelle",
                5: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre des situations problèmes relatives à la récurence des risques d'origine naturelle et la gestion durable des ressources naturelles",
                6: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre des situations problèmes relatives à la gestion durable des ressources naturelles et des écosystèmes",
            },
            'EPS': {
                1: "Réaliser une course de vitesse et une course d'endurance-vitesse, manipuler, coordonner et réaliser l'un des deux types de lancer du poids (lancer en translation ou en rotation) ainsi que les différentes phases",
                2: "Exécuter un saut en hauteur en utilisant l'une des deux techniques suivantes (rouleau ventral ou Fosbury flop)",
                3: "Réaliser un enchainement sur l'agrès sol à partir d'éléments gymniques appartenant à différentes familles d'éléments gymniques",
                4: "Appliquer les stratégies d'attaque dans la pratique des sports collectifs",
                5: "Appliquer les stratégies de défense dans la pratique des sports collectifs",
                6: "Appliquer les stratégies de défense dans la pratique des sports collectifs"
            },
            'Travail Manuel': {
                1: "Utiliser les matériaux, les matériels et les techniques pour dessiner et peindre un paysage sous ciel gris ou bleu",
                2: "Maîtriser les étapes du semis et d'entretien de la plantation de légumes racines et bulbes, installer et entretenir un élevage de lapins",
                3: "Entretenir et conserver les œuvres d'art récoltées (tableaux), récolter et conserver la production de légumes racines et bulbes",
                4: "Maîtriser le processus d'abattage et de conservation de lapins produits",
                5: "Développer les techniques de vente et de commercialisation des œuvres d'art réalisées",
                6: "Développer les techniques de vente et de comemrcialisation des légumes racines et bulbes récoltés, des lapins produits"
            },
        },
        'Troisième': {
            'Anglais': {
                1: "Use appropriate language resources to listen, speak, read and write about national integration, diversity acceptance",
                2: "Use appropriate language resources to listen, speak, read and write about consumption habits and how they impact economic and social life",
                3: "Use appropriate language resources to listen, speak, read and write about climate change and maintaining hygiene and sanitation",
                4: "Use appropriate language resources to listen, speak, read and write about the quest for excellence, gender issues and democracy",
                5: "Use appropriate language resources to listen, speak, read and write about utilities of modern technology",
                6: "Use appropriate language resources to listen, speak, read and write about utilities of modern technology"
            },
            'Informatique': {
                1: "Décrire l'achitecture d'un microordinateur et y effectuer des petites tâches d'entretien",
                2: "Produire une organisation de données selon un format ou une structure de données spécifique",
                3: "Produire des contenus numériques en utilisant un texteur, un tableur ou un logiciel de publication",
                4: "Adopter des attitudes citoyennes universelles, distinguer l'information vraie de la fausse en mettant en évidence les sanctions liées à la violation de l'éthique numérique",
                5: "Écrire un algorithme en utilisant les structures de contrôle",
                6: "Choisir une approche de développement logiciel appropriée pour un projet informatique en utilisant les termes indiqués tout en justifiant son choix"
            },
            'Correction Orthographique': {
                1: "Corriger des erreurs volontairement insérées dans un texte",
                2: "Corriger des erreurs volontairement insérées dans un texte",
                3: "Corriger des erreurs volontairement insérées dans un texte",
                4: "Corriger des erreurs volontairement insérées dans un texte",
                5: "Corriger des erreurs volontairement insérées dans un texte",
                6: "Corriger des erreurs volontairement insérées dans un texte"
            },
            'Orthographe': {
                1: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                2: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                3: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                4: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                5: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées",
                6: "Orthographier correctement un texte ou bien y corriger des erreurs volontairement insérées"
            },
            'Étude de texte': {
                1: "Répondre correctement à des questions sur un texte",
                2: "Répondre correctement à des questions sur un texte",
                3: "Répondre correctement à des questions sur un texte",
                4: "Répondre correctement à des questions sur un texte",
                5: "Répondre correctement à des questions sur un texte",
                6: "Répondre correctement à des questions sur un texte"
            },
            'Expression': {
                1: "Produire à l'écrit, un texte descriptif et à l'oral, un commentaire de l'image",
                2: "Produire à l'écrit, un texte narratif et à l'oral, un compte rendu oral",
                3: "Produire à l'écrit, un texte argumentatif et à l'oral, exprimer son point de vue",
                4: "Produire à l'écrit, un texte argumentatif et à l'oral, s'exprimer dans le cadre d'un entretien d'embauche",
                5: "Produire à l'écrit, un texte injonctif et à l'oral, présenter un commentaire de l'image",
                6: "Produire à l'écrit, divers textes informatifs et à l'oral, un reportage"
            },
            'Expression Écrite': {
                1: "Produire à l'écrit, un texte descriptif",
                2: "Produire à l'écrit, un texte narratif",
                3: "Produire à l'écrit, un texte argumentatif",
                4: "Produire à l'écrit, un texte argumentatif",
                5: "Produire à l'écrit, un texte injonctif",
                6: "Produire à l'écrit, divers textes informatifs"
            },
            'Expression Orale': {
                1: "Produire à l'oral, un commentaire de l'image",
                2: "Produire à l'oral, un compte rendu",
                3: "Exprimer son point de vue",
                4: "S'exprimer dans le cadre d'un entretien d'embauche",
                5: "Présenter un commentaire de l'image",
                6: "Produire à l'oral, un reportage"
            },
            'Langues Nationales': {
                1: "Produire des messages dans la langue nationale cible en respectant les tons de cette langue",
                2: "Produire des messages comportant des pronoms (possessif, démonstratif, interrogatif ou indéfini) dans la langue nationale cible",
                3: "Produire des messages comportant des verbes conjugués aux modes indicatif, impératif et conditionnel dans la langue nationale cible",
                4: "Produire des messages comportant des phrases interrogative, négative et impérative dans la langue nationale cible",
                5: "Produire des messages comportant des adverbes, des conjonctions de coordination et de subordination dans la langue nationale cible",
                6: "Produire des messages comportant des phrases complexes dans la langue nationale cible"
            },
            'Allemand': {
                1: "Comprendre et produire de courts textes / énoncés écrits d'au moins 50 mots, relatifs à la vie quotidienne et à la vie familiale et sociale",
                2: "Comprendre et produire de courts textes / énoncés oraux relatifs à la vie quotidienne et à la vie familiale et sociale",
                3: "Comprendre et produire de courts dialogues ou énoncés / textes écrits d'au moins 50 mots, relatifs à l'environnement, à la santé, au bien-être et aux médias de communication",
                4: "Comprendre et produire de courts dialogues ou énoncés / textes oraux relatifs à l'environnement, à la santé, au bien-être et aux médias de communication",
                5: "Comprendre et produire de courts dialogues et de textes / énoncés narratifs écrits d'au moins 50 mots, relatifs à la citoyenneté et à la vie économique",
                6: "Comprendre et produire de courts dialogues et de textes / énoncés narratifs oraux relatifs à la citoyenneté et à la vie économique"
            },
            'Espagnol': {
                1: "Comprendre et produire des messages écrits d'au moins 50 mots, relatifs à la famille et la société, à l'environnement, la santé et le bien-être",
                2: "Comprendre et produire des messages oraux relatifs à la famille et la société, à l'environnement, la santé et le bien-être",
                3: "Comprendre et produire des messages écrits d'au moins 50 mots, relatifs à la citoyenneté et à la vie économique",
                4: "Comprendre et produire des messages oraux relatifs à la citoyenneté et à la vie économique",
                5: "Comprendre et produire des messages écrits d'au moins 50 mots, relatifs aux médias et à la communication",
                6: "Comprendre et produire des messages oraux relatifs aux médias et à la communication"
            },
            'ECM': {
                1: "Éduquer les masses et s'impliquer dans le processus électoral",
                2: "Éduquer les masses et s'impliquer dans le processus électoral",
                3: "Promouvoir la vie associative",
                4: "Promouvoir la vie associative",
                5: "Promouvoir l'entrepreneuriat",
                6: "Promouvoir l'entrepreneuriat"
            },
            'Géographie': {
                1: "Gérer durablement l'environnement",
                2: "Gérer les ressources humaines",
                3: "Gérer durablement les ressources naturelles",
                4: "Améliorer les conditions de vie",
                5: "Promouvoir la bonne gouvernance",
                6: "Participer à la mondialisation"
            },
            'Histoire': {
                1: "Lutter contre la domination étrangère",
                2: "Prévenir et régler les conflits",
                3: "Prévenir et régler les conflits",
                4: "Promouvoir l'intégration nationale",
                5: "Promouvoir l'intégration nationale",
                6: "Promouvoir l'intégration nationale"
            },
            'Mathématiques': {
                1: "Résoudre des situations problèmes relatives à l'arithmétique, aux nombres réels, aux propriétés de Thalès et à la trigonométrie dans le triangle rectangle",
                2: "Communiquer à l'aide du langage mathématique dans des situations relatives aux notions précédemment étudiées",
                3: "Résoudre des situations problèmes relatives au calcul littéral, à la section d'une pyramide ou d'un cône par un plan parallèle à sa base, aux vecteurs, aux équations, inéquations et systèmes et aux équations de droites",
                4: "Communiquer à l'aide du langage mathématique dans des situations relatives aux notions précédemment étudiées",
                5: "Résoudre des situations problèmes relatives aux statistiques, aux angles inscrits dans un cercle, aux polygônes réguliers, à l'homothétie et aux applications affines",
                6: "Communiquer à l'aide du langage mathématique dans des situations relatives aux notions précédemment étudiées"
            },
            'PCT': {
                1: "Résoudre, en utilisant la méthode scientifique, des situations problèmes se rapportant aux transformations chimiques de la matière, à la coupe simple et aux systèmes poulies-courroie",
                2: "Communiquer, en utilisant le langage et les symboles scientifiques, sur les transformations chimiques de la matière, à la coupe simple et aux systèmes poulies-courroie",
                3: "Résoudre, en utilisant la méthode scientifique, des situations problèmes se rapportant aux engrenages, aux machines simples, à l'utilisation de l'énergie électrique, à la gestion et l'utilisation des produits pétroliers et des matières plastiques",
                4: "Communiquer, en utilisant le langage et les symboles scientifiques et techniques, sur les engrenages, aux machines simples, sur l'utilisation de l'énergie électrique, sur la gestion et l'utilisation des produits pétroliers et des matières plastiques et sur la protection de l'environnement",
                5: "Résoudre, en utilisant la méthode scientifique, des situations problèmes se rapportant à des projets techniques simples, liés aux moteurs à combustion interne et électriques, et à l'électricité domestique",
                6: "Communiquer, en utilisant le langage et les symboles scientifiques et techniques, sur les moteurs à combustion interne, les moteurs électriques, l'électricité domestique, et les dangers du courant électrique"
            },
            'SVTEEHB': {
                1: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à la récurrence des anomalies et/ou des caractères nouveaux dans les familles",
                2: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à la récurrence des anomalies et/ou des caractères nouveaux dans les familles et l'amélioration de la santé individuelle et des collectivités",
                3: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à l'amélioration de la santé individuelle et des collectivités",
                4: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à l'amélioration de la santé individuelle et des collectivités",
                5: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à la récurrence des risques d'origine naturelle",
                6: "En utilisant une démarche scientifique, communiquer à l'oral et à l'écrit pour résoudre les situations problèmes relatives à la récurrence des risques d'origine naturelle et la gestion durable des écosystèmes"
            },
            'EPS': {
                1: "Réaliser une course de vitesse et une course d'endurance-vitesse, manipuler, coordonner et réaliser l'un des deux types de lancer du poids (lancer en translation ou en rotation) ainsi que les différentes phases",
                2: "Exécuter un saut en hauteur en utilisant l'une des deux techniques suivantes (rouleau ventral ou Fosbury flop)",
                3: "Réaliser un enchainement sur l'agrès sol à partir d'éléments gymniques appartenant à différentes familles d'éléments gymniques",
                4: "Appliquer les stratégies d'attaque dans la pratique des sports collectifs",
                5: "Appliquer les stratégies de défense dans la pratique des sports collectifs",
                6: "Appliquer les stratégies de défense dans la pratique des sports collectifs"
            },
            'Travail Manuel': {
                1: "Utiliser les matériaux, les matériels et les techniques pour modeler et mouler un pot en argile",
                2: "Maîtriser les étapes du semis et d'entretien de la plantation de légumineuses à grains, installer et entretenir un élevage de poissons",
                3: "Utiliser les techniques de finition sur les objets fabriqués",
                4: "Maîtriser et utiliser les techniques de récolte et de conservation de la production des légumineuses à grains, de la production de poissaons",
                5: "Développer les techniques de vente et de commercialisation des objets produits",
                6: "Développer les techniques de vente et de commercialisation des légumineus○es à grains et des poissons produits"
            },
        },
    }
    if level in competences.keys():
        classroom_competences = competences[level]
        if matiere in classroom_competences.keys():
            return classroom_competences[matiere][evalx]
    return None


def base_header(pdf, mode='P', y_img=0):
    from fpdf.table import Table
    from fpdf.fonts import FontFace
    from fpdf.enums import VAlign

    bold = FontFace(emphasis='B')
    hwidths = (75.25, 47.5, 75.25) if mode == 'P' else (110, 65, 110)
    table = Table(pdf, line_height=3, col_widths=hwidths, text_align="CENTER", first_row_as_headings=False,
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
    row.cell("**********", style=bold)
    row.cell("**********", style=bold)

    row = table.row()
    row.cell("MINISTÈRE DES ENSEIGNEMENTS SECONDAIRES")
    row.cell("MINISTRY OF SECONDARY EDUCATION")

    row = table.row()
    row.cell("**********", style=bold)
    row.cell("**********", style=bold)

    row = table.row()
    row.cell(f"{pdf.school.region}")
    row.cell(f"{pdf.school.rgn}")

    row = table.row()
    row.cell("**********", style=bold)
    row.cell("**********", style=bold)

    row = table.row()
    row.cell(f"{pdf.school.departement}")
    row.cell(f"{pdf.school.dptm}")

    row = table.row()
    row.cell("**********", style=bold)
    row.cell("**********", style=bold)

    row = table.row()
    row.cell(f"**{pdf.school.nom}**", v_align=VAlign.T)
    pdf.set_font_size(7)
    row.cell(f"**{pdf.school.immatriculation}**\n__Tél : {pdf.school.contact}__")
    pdf.set_font_size(8)
    row.cell(f"**{pdf.school.name}**", v_align=VAlign.T)

    logo = (pdf.school.logo, "static/image/no_image.jpg")[pdf.school.logo == ""]
    x_img = 92 if mode == 'P' else 135.5
    pdf.image(logo, x=x_img, y=y_img+6, w=26, keep_aspect_ratio=True)
    table.render()


def base_infos(pdf, nom, effectif, filles, garcons, redoublants, classroom, mode='P'):
    pdf.set_font("inter", 'B', 12)
    pdf.cell(0, 7, nom, align='C')
    pdf.ln()
    pdf.set_font("inter", '', 7)
    pdf.cell(0, 2, f"__**Année scolaire : {school_year()}**__", align='C', markdown=True)
    pdf.ln()
    pdf.set_font("inter", '', 7)
    w = 99 if mode == 'P' else 142.5
    pdf.cell(w, 5, f"**Classe : {classroom}**", align='L', markdown=True)
    info = f"Effectif : {effectif}, Filles : {filles}, Garçons : {garcons}, Redoublants : {redoublants}"
    pdf.cell(w, 5, f"__{info}__", align='R', markdown=True)
