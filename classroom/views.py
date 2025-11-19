# Create your views here.
from io import BytesIO

from django.urls import reverse
from fpdf.enums import TableHeadingsDisplay

from authentification.models import TrancheHoraire, School
from osm.utils import message, resized_image, formated_float, school_year, LoggedAdminView, LoggedUserView, \
    logged_admin_view, logged_user_view, ListView, DeleteView, resize_image, generate_temp_file, truncate_str
from django.db.models import Q
from django.forms import model_to_dict
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from staff.models import Discipline
from student.models import Student
from note.forms import CheckForm, MarksForm, SelectForm
from note.models import Note
from .forms import MatiereAddForm, SubjectsForm, ClassroomForm, MatTeachsForm, DisciplineForm, ProgrammationForm
from osm.forms import SearchForm
from .models import ClassRoom, Matieres, Class, Enseignements, Programmation
from fpdf import FPDF
from fpdf.fonts import FontFace
from fpdf.table import CellBordersLayout, VAlign, Table
import datetime
from collections import OrderedDict
from django.core import signing
from django.forms import ValidationError


@logged_admin_view
def reload_teachers(request):
    mp = request.user.school.mergedprogrammations
    programmation_form = ProgrammationForm(context={'request': request, 'classroom': None, 'mp': mp})
    return render(request, "enseignants.html", context={'form': programmation_form})


class SetProgrammation(LoggedAdminView):
    template_name = "programmation.html"

    def title(self, jour, tranches_horaires):
        day = dict(Programmation.days)[jour]
        start_end = f"{tranches_horaires[0].debut} - {tranches_horaires[-1].fin}"
        return f"{day} : {start_end}"

    def get_tranches(self, jour, tranche_id, nb_tranches, classroom_id, programmation_id, delete=False):
        school_tranches = self.request.user.school.tranches_horaires
        mergedprogrammations = self.request.user.school.mergedprogrammations
        tranches_horaires = list()
        programmations = list()
        tranche_horaire = school_tranches.get(id=tranche_id)
        tranches_horaires.append(tranche_horaire)
        if nb_tranches > 1:
            for i in range(1, nb_tranches):
                tranches_horaires.append(school_tranches.get(number=tranche_horaire.number + i))
        classroom = (
            ClassRoom.objects.prefetch_related('matieres__sujet', 'classe', 'programmations').
            get(id=classroom_id)
        )
        if programmation_id:
            for tranche in tranches_horaires:
                if not mergedprogrammations:
                    programmations.append(classroom.programmations.get(jour=jour, tranche_horaire=tranche))
                else:
                    programmations.append(classroom.mergedprogrammations.get(jour=jour, tranche_horaire=tranche))
        if delete:
            return programmations, mergedprogrammations, classroom
        return tranches_horaires, classroom, programmations, mergedprogrammations

    def get(self, *args, **kwargs):
        jour = int(self.request.GET.get('jour'))
        tranche_id = int(self.request.GET.get('tranche'))
        nb_tranches = int(self.request.GET.get('nb_tranches'))
        classroom_id = int(self.request.GET['classroom_id'])
        programmation_id = self.request.GET.get('programmation_id')
        tranches_horaires, classroom, programmations, mp = (
            self.get_tranches(jour, tranche_id, nb_tranches, classroom_id, programmation_id)
        )
        programmation = programmations[0] if programmations else None
        initials = {'jour': signing.dumps(jour),
                    'tranche_horaire': signing.dumps(tranche_id), 'classroom': signing.dumps(classroom.pk),
                    'nb_tranches': signing.dumps(nb_tranches), 'programmation_id': signing.dumps(programmation_id)}
        programmation_form = ProgrammationForm(instance=programmation, initial=initials,
                                               context={'request': self.request, 'classroom': classroom, 'mp': mp})
        context = {'form': programmation_form, 'title': f"{self.title(jour, tranches_horaires)} ({classroom.code})",
                   'edit': programmation_id is not None}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        if self.request.POST.get('_method') == "DELETE":
            return self.delete(*args, **kwargs)
        try:
            jour = signing.loads(self.request.POST.get('jour'))
            tranche_id = signing.loads(self.request.POST.get('tranche_horaire'))
            nb_tranches = signing.loads(self.request.POST.get('nb_tranches'))
            programmation_id = signing.loads(self.request.POST.get('programmation_id'))
            classroom_id = signing.loads(self.request.POST['classroom'])
            tranches_horaires, classroom, programmations, mp = (
                self.get_tranches(jour, tranche_id, nb_tranches, classroom_id, programmation_id)
            )
            programmation = programmations[0] if programmations else None
            initials = {'jour': jour, 'tranche_horaire': tranche_id, 'classroom': classroom.pk,
                        'nb_tranches': nb_tranches,
                        'programmation_id': programmation_id}
            programmation_form = ProgrammationForm(self.request.POST, instance=programmation,
                                                   context={'request': self.request, 'classroom': classroom,
                                                            'programmations': programmations,
                                                            'tranches': tranches_horaires, 'mp': mp}, initial=initials)
            title, msg = self.title(jour, tranches_horaires), None
            enseignant = programmation.enseignant if programmation else None
            ex_enseignant_id = enseignant.pk if enseignant else None
            if programmation_form.is_valid():
                if programmation and programmation.matiere_id == int(programmation_form.cleaned_data['matiere']) \
                        and enseignant == programmation_form.cleaned_data['enseignant']:
                    final_message = "Aucune modification effectuée"
                    msg_type = "warning"
                else:
                    matiere_id = int(programmation_form.cleaned_data['matiere'])
                    new_enseignant = programmation_form.cleaned_data['enseignant']
                    enseignant_id = new_enseignant.pk if new_enseignant else None
                    if programmation:
                        for programmation in programmations:
                            if mp:
                                Programmation.update_mergedprogrammation(programmation, jour,
                                                                         programmation.tranche_horaire_id, matiere_id,
                                                                         ex_enseignant_id, enseignant_id, classroom)
                            else:
                                programmation.matiere_id = matiere_id
                                programmation.enseignant = new_enseignant
                                programmation.save()
                    else:
                        for tranche_horaire in tranches_horaires:
                            if mp:
                                Programmation.create_mergedprogrammation(jour, tranche_horaire.pk, matiere_id,
                                                                         enseignant_id, classroom)
                            else:
                                Programmation.objects.create(jour=jour, tranche_horaire=tranche_horaire,
                                                             matiere_id=matiere_id, classroom_id=classroom_id,
                                                             enseignant=new_enseignant)
                    final_message = "Programmation sauvegardée avec succès"
                    msg_type = "success"
                message(self.request, final_message, msg_type)
                response = HttpResponse()
                response['HX-Trigger'] = "programmation-saved, AJAXMessages"
                return response
        except signing.BadSignature:
            programmation_form, programmation_id, title, msg = None, None, None, "Erreur : Une valeur a été altérée"
        context = {'form': programmation_form, 'title': title, 'msg': msg, 'edit': programmation_id is not None}
        response = render(self.request, self.template_name, context)
        response['HX-Trigger'] = "AJAXMessages"
        return response

    def delete(self, *args, **kwargs):
        try:
            jour = signing.loads(self.request.POST.get('jour'))
            tranche_id = signing.loads(self.request.POST.get('tranche_horaire'))
            nb_tranches = signing.loads(self.request.POST.get('nb_tranches'))
            programmation_id = signing.loads(self.request.POST.get('programmation_id'))
            classroom_id = signing.loads(self.request.POST['classroom'])
            programmations, mp, classroom = (
                self.get_tranches(jour, tranche_id, nb_tranches, classroom_id, programmation_id, delete=True)
            )
            for programmation in programmations:
                if mp:
                    programmation.classrooms.remove(classroom)
                    if not programmation.classrooms.exists():
                        programmation.delete()
                else:
                    programmation.delete()
            message(self.request, "Programmation supprimée avec succès")
            response = HttpResponse()
            response['HX-Trigger'] = "programmation-saved, AJAXMessages"
            return response
        except signing.BadSignature:
            return render(self.request, self.template_name, {'msg': "Erreur : Une valeur a été altérée"})


class TimeTableForm(LoggedAdminView):
    template_name = "time_table_select_form.html"
    title = "Emploi du temps"

    def get(self, *args, **kwargs):
        classrooms = ClassRoom.objects.exists()
        context = {'title': self.title, 'classrooms': classrooms}
        if classrooms:
            plages = TrancheHoraire.objects.filter(school_id=self.request.user.school.pk).exists()
            context['plages'] = plages
            if plages:
                context['form'] = CheckForm(context={'time_table': True})
        return render(self.request, self.template_name, context=context)

    def post(self, *args, **kwargs):
        classrooms = ClassRoom.objects.exists()
        context = {'title': self.title, 'classrooms': classrooms}
        if classrooms:
            plages = TrancheHoraire.objects.filter(school_id=self.request.user.school.pk).exists()
            context['plages'] = plages
            if plages:
                context['form'] = CheckForm(self.request.POST, context={'time_table': True})
        return render(self.request, self.template_name, context=context)


class TimeTable(LoggedAdminView):
    template_name = "time_table.html"
    days = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi")
    days_indexes = (1, 2, 3, 4, 5)

    def get_time_table(self, classroom_id, download=False, empty=False):
        school = School.objects.prefetch_related('tranches_horaires').get(id=self.request.user.school.pk)
        tranches_horaires = school.tranches_horaires.all()
        if empty:
            return tranches_horaires, school.school_to_dict()
        mp = school.mergedprogrammations
        if mp:
            classroom = (
                ClassRoom.objects.
                prefetch_related('mergedprogrammations__matiere__sujet', 'mergedprogrammations__enseignant',
                                 'matieres__sujet', 'matieres__programmations').get(id=classroom_id)
            )
            programmations = classroom.mergedprogrammations.order_by('jour', 'tranche_horaire__number')
        else:
            classroom = (
                ClassRoom.objects.
                prefetch_related('programmations__enseignant', 'matieres__programmations', 'matieres__sujet',
                                 'programmations__matiere__sujet').get(id=classroom_id)
            )
            programmations = classroom.programmations.order_by('jour', 'tranche_horaire__number')
        matrice = dict()
        for day in self.days_indexes:
            matrice[day] = [
                {'matiere': None,
                 'enseignant': None,
                 'rowspan': 1,
                 'is_pause': not tranche.is_cours,
                 'jour': day,
                 'tranche': tranche.pk
                 } for tranche in tranches_horaires
            ]
        for programmation in programmations:
            day = programmation.jour
            index_tranche = next(
                i for i, t in enumerate(tranches_horaires) if t.id == programmation.tranche_horaire_id
            )
            if not download:
                matrice[day][index_tranche]['programmation_id'] = programmation.pk
                matrice[day][index_tranche]['colors'] = classroom.subject_color(programmation.matiere)
            matrice[day][index_tranche]['matiere'] = programmation.short(classroom)
            matrice[day][index_tranche]['enseignant'] = programmation.enseignant
        # Fusion
        for _, liste in matrice.items():
            i = 0
            while i < len(liste):
                current = liste[i]
                if current is None or current['is_pause'] or current['matiere'] is None:
                    i += 1
                    continue
                rowspan = 1
                while (i + rowspan < len(liste)) and not liste[i + rowspan]['is_pause'] and liste[i + rowspan][
                    'matiere'] == current['matiere'] and liste[i + rowspan]['enseignant'] == current['enseignant']:
                    liste[i + rowspan] = None
                    rowspan += 1
                current['rowspan'] = rowspan
                i += rowspan
        time_table = list()
        for tranche_horaire in tranches_horaires:
            if not tranche_horaire.is_cours:
                time_table.append((tranche_horaire, False))
            else:
                time_table.append((
                    tranche_horaire,
                    matrice[1][tranche_horaire.number - 1],
                    matrice[2][tranche_horaire.number - 1],
                    matrice[3][tranche_horaire.number - 1],
                    matrice[4][tranche_horaire.number - 1],
                    matrice[5][tranche_horaire.number - 1]
                ))
        if download:
            return time_table, classroom.code, school.school_to_dict()
        return time_table, f"Emploi du temps {classroom.code}", classroom.timetable_recap(mp)

    def get(self, *args, **kwargs):
        classroom_id = int(self.request.GET['clsrm']) if 'clsrm' in self.request.GET.keys() else int(
            self.request.headers['X-ClassroomId'])
        time_table, title, recap = self.get_time_table(classroom_id)
        context = {'time_table': time_table, 'days': self.days, 'recap': recap, 'classroom_id': classroom_id,
                   't_title': title, 'signed': signing.dumps(classroom_id)}
        return render(self.request, self.template_name, context=context)

    def post(self, *args, **kwargs):
        try:
            classroom_id = signing.loads(self.request.POST["signed"])
            empty_timetable = True if 'timetable_checkbox' in self.request.POST.keys() else False
            data = {'filename': "Emploi du temps", 'annee': school_year()}
            if empty_timetable:
                data['tranches_horaires'], data['school_data'] = self.get_time_table(classroom_id, empty=True)
            else:
                data['time_table'], data['classroom'], data['school_data'] = (
                    self.get_time_table(classroom_id, download=True)
                )
                data['filename'] += f" {data['classroom']}"
            temp_filename, final_filename = generate_temp_file(f"{data['filename']}.pdf", ClassroomTimeTable(data=data))
            url = reverse("download_and_delete", args=[temp_filename])
            return JsonResponse({
                'success': True,
                'url': url,
                'display': final_filename
            })
        except signing.BadSignature:
            return JsonResponse({
                'success': False,
                'message': f"Une valeur a été altérée"
            })


class StatsCheck(LoggedAdminView):
    template_name = "stats.html"
    title = "Statistiques"

    def get(self, *args, **kwargs):
        check_form = CheckForm(context={'transcript': True})
        context = {"title": self.title, "check_form": check_form, "stats": False}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        check_form = CheckForm(self.request.POST or None, context={'transcript': True})
        context = {"title": self.title, "check_form": check_form, "stats": False}
        return render(self.request, self.template_name, context)


@logged_admin_view
def stats(request):
    if request.method == "POST":
        template_name = "statistiques.html"
        classroom = (
            ClassRoom.objects.select_related('classe').
            prefetch_related('students', 'matieres__sujet').
            get(pk=request.POST['clsrm'])
        )
        evl = int(request.POST["evl"])
        trim = ((("du premier trimestre", "du deuxième trimesre")[evl == 2], "du troisième trimeste")[evl == 3],
                "annuelles")[evl == 4]
        evl_in = ((([1, 2], [3, 4])[evl == 2], [5, 6])[evl == 3], [1, 2, 3, 4, 5, 6])[evl == 4]
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
            status = False
            rapport += f" n'ont pas été remplies en {classroom.code}."
            data = None
        else:
            rapport = None
            status = True
            data = classroom.marks_report_data(evl_in, for_stats=True)
            # Statistiques Établissement
        context = {'status': status, 'rapport': rapport, 'trim': trim, 'data': data}
        return render(request, template_name, context)


# Attribution des enseignants pour une salle de classe
class ClassRoomTeachers(LoggedAdminView):
    template_name = "classroom_config.html"
    title = "Configuration des Enseignants"

    def get(self, *args, **kwargs):
        mateachs_form = MatTeachsForm(request=self.request, method="GET", id=self.kwargs['id'])
        return render(self.request, self.template_name, context={"title": self.title, "mateachs_form": mateachs_form})

    def post(self, *args, **kwargs):
        mateachs_form = MatTeachsForm(request=self.request, method="POST", id=self.kwargs['id'])
        i = mateachs_form.save()
        if not i:
            message(self.request, "Aucune modification effectuée.", msg_type="warning")
        else:
            message(self.request, "Modifications effectuées avec succès.")
        return redirect("classrooms")


@logged_admin_view
def reload(request):
    id = int(request.POST['classe'])
    matiere_form = MatiereAddForm(context={'request': request, 'id': id})
    return render(request, "reload.html", {'matiere_form': matiere_form})


class MatiereAdd(LoggedAdminView):
    template_name = "add_matiere.html"
    title = "Ajout d'une Matière"

    def get(self, *args, **kwargs):
        classe = ClassRoom.objects.get(id=self.kwargs['id']).classe
        matiere_form = MatiereAddForm(context={'request': self.request, 'id': classe.pk})
        context = {"title": self.title, 'matiere_form': matiere_form, 'id': self.kwargs['id']}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        classe = ClassRoom.objects.get(id=self.kwargs['id']).classe
        matiere_form = MatiereAddForm(self.request.POST, context={'request': self.request, 'id': classe.pk})
        if matiere_form.is_valid():
            coeff, classe, idd = matiere_form.cleaned_data['coeff'], matiere_form.cleaned_data['classe'], \
                matiere_form.cleaned_data['discipline']
            discipline = Discipline.objects.get(pk=idd)
            Class.add_matiere(classe, discipline, coeff)
            message(self.request, f"{discipline.label}, coefficient : {coeff} ajouté avec succès pour les classes de "
                                  f"{classe}")
            return redirect("class-subjects", id=self.kwargs['id'])
        context = {"title": self.title, 'matiere_form': matiere_form, 'id': self.kwargs['id']}
        return render(self.request, self.template_name, context)


class RemoveMatiere(DeleteView):
    title = "Retirer un Matière"
    model = Matieres
    alerte = "? Cette action supprimera d'éventuelles notes enregistrées pour ce niveau et cette matière."


class ClassMatieres(LoggedAdminView):
    template_name = "classroom_config.html"
    title = "Configuration des Matières"

    def get(self, *args, **kwargs):
        mateachs_form = MatTeachsForm(request=self.request, method="GET", id=self.kwargs['id'], coeff=True)
        context = {"title": self.title, "mateachs_form": mateachs_form, 'subjects': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        mateachs_form = MatTeachsForm(request=self.request, method="POST", id=self.kwargs['id'], coeff=True)
        i = mateachs_form.save()
        if not i:
            message(self.request, "Aucune modification effectuée.", msg_type="warning")
            i += 1
        else:
            message(self.request, "Modifications effectuées avec succès.")
            i += 1
        if i:
            return redirect("classrooms")
        context = {"title": self.title, "mateachs_form": mateachs_form, 'subjects': True}
        return render(self.request, self.template_name, context)


class Subjects(ListView):
    template_name = "subjects.html"
    model = Discipline
    title = "Disciplines"
    objects = "disciplines"


class SubjectAdd(LoggedAdminView):
    title = "Ajouter une Discipline"
    template_name = "add_subject.html"
    matieres, groupes = tuple(), tuple()

    @classmethod
    def matgp(cls):
        qs = Discipline.objects
        matiere = qs.distinct("matiere")
        groupe = qs.distinct("groupe")
        return tuple([mat.matiere for mat in matiere if mat.matiere]), tuple([mat.groupe for mat in groupe])

    def get(self, *args, **kwargs):
        discipline_form = DisciplineForm(context={'request': self.request})
        self.matieres, self.groupes = SubjectAdd.matgp()
        context = {"form": discipline_form, "title": self.title, "reset": "Tout Effacer", "mat": self.matieres,
                   "gp": self.groupes}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        discipline_form = DisciplineForm(self.request.POST, context={'request': self.request})
        context = {"form": discipline_form, "title": self.title, "reset": "Tout Effacer", "mat": self.matieres,
                   "gp": self.groupes}
        if discipline_form.is_valid():
            discipline_form.save()
            message(self.request, "Discipline ajoutée avec succès !")
            return redirect("subjects")
        return render(self.request, self.template_name, context)


class SubjectEdit(LoggedAdminView):
    title = "Modifier une Discipline"
    template_name = "add_subject.html"
    matieres, groupes = tuple(), tuple()

    def get(self, *args, **kwargs):
        instance = self.get_object()
        discipline_form = DisciplineForm(context={'request': self.request, 'instance': instance})
        self.matieres, self.groupes = SubjectAdd.matgp()
        context = {"form": discipline_form, "title": self.title, "reset": "Réinitialiser", "mat": self.matieres,
                   "gp": self.groupes}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        instance = self.get_object()
        default = self.get_object()
        discipline_form = DisciplineForm(self.request.POST, context={'request': self.request, 'instance': instance})
        context = {"form": discipline_form, "title": self.title, "reset": "Réinitialiser", "mat": self.matieres,
                   "gp": self.groupes}
        if discipline_form.is_valid():
            save = discipline_form.save()
            if model_to_dict(save) != model_to_dict(default):
                message(self.request, "Discipline modifiée avec succès !")
            return redirect("subjects")
        return render(self.request, self.template_name, context)

    def get_object(self):
        subject_id = self.kwargs.get("id")
        subjects = Discipline.objects
        subject = get_object_or_404(subjects, pk=subject_id)
        return subject


class ClassRoomStudents(ListView):
    template_name = "students_list.html"
    title = "Liste des Élèves"
    model = Student
    objects = "élève(s)"
    id = True


# Affichage des salles de classe
class ClassRooms(ListView):
    template_name = "classrooms_list.html"
    title = "Salles de Classe"
    objects = "salle(s) de classe"
    model = ClassRoom


# Ajout d'une salle de classe
class ClassroomAdd(LoggedAdminView):
    template_name = "add_classroom.html"
    title = "Ajouter une Salle de Classe"

    def get(self, *args, **kwargs):
        classroom_form = ClassroomForm(context={"request": self.request})
        context = {"title": self.title, "classroom_form": classroom_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        classroom_form = ClassroomForm(self.request.POST, context={"request": self.request})
        if classroom_form.is_valid():
            classroom = classroom_form.save_classroom()
            success_message = f"La salle {classroom.__str__()} a été crée avec succès !"
            message(self.request, success_message)
            return redirect("classrooms")
        context = {"title": self.title, "classroom_form": classroom_form}
        return render(self.request, self.template_name, context)


# Modification d'une salle de classe
class ClassroomEdit(LoggedAdminView):
    template_name = "add_classroom.html"
    title = "Modifier une Salle de Classe"

    def get(self, *args, **kwargs):
        instance = self.get_object()
        classroom_form = ClassroomForm(context={"request": self.request, "instance": instance})
        context = {"title": self.title, "classroom_form": classroom_form, 'pk': instance.pk}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        instance = self.get_object()
        default = self.get_object()
        classroom_form = ClassroomForm(self.request.POST, context={"request": self.request, "instance": instance})
        if classroom_form.is_valid():
            classroom = classroom_form.save_classroom()
            if model_to_dict(default) != model_to_dict(classroom):
                success_message = f"La salle {default} a été modifiée en {classroom} avec succès !"
                message(self.request, success_message)
            return redirect("classrooms")
        context = {"title": self.title, "classroom_form": classroom_form, "pk": instance.pk}
        return render(self.request, self.template_name, context)

    def get_object(self):
        classroom_id = self.kwargs.get("id")
        classrooms = ClassRoom.objects.all()
        classroom = get_object_or_404(classrooms, pk=classroom_id)
        return classroom


# La vue ci-dessous permet d'afficher dynamiquement le formulaire de création d'une salle de classe
@logged_admin_view
def classroom_form_reload(request, key):
    if not key:
        classroom_form = ClassroomForm(context={"request": request, 'reload': True})
    else:
        classrooms = ClassRoom.objects.all()
        classroom = get_object_or_404(classrooms, pk=key)
        classroom_form = ClassroomForm(context={"request": request, 'instance': classroom})
    return render(request, "classroom_form.html", {"classroom_form": classroom_form})


# Suppression d'une salle de classe
class ClassroomDelete(DeleteView):
    success_url = "classrooms"
    model = ClassRoom
    title = "Suppression d'une Salle de Classe"
    alerte = "des salles de classe ?"
    message = "Salle de Classe supprimée avec succès."


class SubjectDelete(DeleteView):
    success_url = "subjects"
    model = Discipline
    alerte = "des disciplines ?"
    title = "Suppression d'une Discipline"
    message = "Discipline supprimée avec succès."


class MarksSheet(LoggedUserView):
    template_name = "edit_marks.html"
    title = "Fiche de Notes"

    def check(self):
        staff_member = self.request.user.staff_member.all()[0]
        msg, enseignements = "", None
        if staff_member.is_admin:
            if not ClassRoom.objects.all().exists():
                msg = "Aucune classe disponible."
        else:
            if staff_member.rapporteur.all().exists():
                enseignements = Enseignements.objects.select_related('matiere__sujet', 'classroom').filter(
                    rapporteur_id=staff_member.pk)
            else:
                msg = "Vous n'êtes affectés à aucune salle de classe."
        return msg, enseignements

    def get(self, *args, **kwargs):
        msg, enseignements = self.check()
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(context={
                "request": self.request, 'trim': False, 'marks_sheet': True, 'enseignements': enseignements})
            context = {'marks_sheet': True, 'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        msg, enseignements = self.check()
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(self.request.POST, context={
                "request": self.request, 'trim': False, 'marks_sheet': True, 'enseignements': enseignements})
            context = {'marks_sheet': True, 'title': self.title, 'select_form': select_form}
            if select_form.is_valid():
                classroom = (
                    ClassRoom.objects.prefetch_related('students').
                    get(pk=select_form.cleaned_data["classroom"])
                )
                if classroom.students.exists():
                    filename = f"Fiche de Notes {classroom.code}.pdf"
                    marks_report = PDFMarksSheet(classroom=classroom, annee=school_year(),
                                                 school=self.request.user.school)
                    buffer = BytesIO()
                    marks_report.output(buffer)
                    buffer.seek(0)
                    response = HttpResponse(buffer, content_type="application/pdf")
                    response['Content-Disposition'] = f"attachment; filename={filename}"
                    return response
                else:
                    message(self.request, "Aucun élève dans cette salle de classe.", msg_type="warning")
        return render(self.request, self.template_name, context)


class PDFMarksSheet(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.add_font('inter', '', 'static/fonts/Inter-regular.ttf')
        self.add_font('inter', 'I', 'static/fonts/Inter-Italic.ttf')
        self.add_font('inter', 'B', 'static/fonts/Inter-Bold.ttf')
        self.add_font('inter', 'BI', 'static/fonts/Inter-BoldItalic.ttf')
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=10)
        self.set_font('inter', '', 9)
        self.now = datetime.datetime.now().strftime("%d-%m-%Y à %H:%M")
        self.annee = kwargs['annee']
        self.classroom = kwargs['classroom']
        self.school = kwargs['school']
        self.add_page()
        self.head()
        self.infos()
        self.sheet()

    def sheet(self):
        self.ln()
        col_widths = [10, 24, 70, 10, 14, 14, 14, 14, 14, 14]
        header = ["N°", "Identifiant", "Nom(s) et Prénom(s)", "Sex", "Eval1", "Eval2", "Eval3",
                  "Eval4", "Eval5", "Eval6"]

        table = Table(self, line_height=6.5, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(220)
        for head in header:
            th.cell(f"**{head}**")
        self.set_fill_color(0)

        i = 1
        for student in self.classroom.students.all().order_by("nom", "prenom"):
            row = table.row()
            row.cell(f"{i}")
            row.cell(f"{student.unique_id}")
            row.cell(f"{student.__str__()}", align="L")
            row.cell(f"{student.genre}", align="C")
            row.cell()
            row.cell()
            row.cell()
            row.cell()
            row.cell()
            row.cell()
            i += 1
        table.render()

    def infos(self):
        self.set_font_size(13)
        self.ln()
        self.cell(0, 8, "**FICHE DE NOTES**", align='C', markdown=True)
        self.set_font_size(9)
        self.ln()
        self.cell(99, 9, f"**Classe : {self.classroom.code}**", align='L', markdown=True)
        students = self.classroom.students
        effectif = students.count()
        filles = students.filter(sexe="Fille").count()
        garcons = effectif - filles
        redoublants = students.filter(statut="Redoublant").count()
        info = f"Effectif : {effectif}, Filles : {filles}, Garçons : {garcons}, Redoublants : {redoublants}"
        self.cell(99, 9, f"__{info}__", align='R', markdown=True)
        self.ln()
        self.cell(82, 7, "Enseignant(e) : --                                                  --",
                  align='L', markdown=True)
        self.cell(40, 7, f"Coefficient : --                    --", align='C', markdown=True)
        self.cell(76, 7, f"Matière : --                                                      --",
                  align='R', markdown=True)

    def head(self):
        hwidths = (84, 30, 84)
        table = Table(self, line_height=5, col_widths=hwidths, text_align="CENTER", first_row_as_headings=False,
                      borders_layout="NONE", markdown=True)
        #
        logo = (self.school.logo, "static/image/no_image.jpg")[self.school.logo == ""]
        self.image(resize_image(logo, new_width=308), x=86, y=6, w=26, keep_aspect_ratio=True)

        row = table.row()
        row.cell("**RÉPUBLIQUE DU CAMEROUN**")
        row.cell("", rowspan=5)
        self.set_font_size(11)
        row.cell(f"**{self.school.nom}**")
        self.set_font_size(8)

        row = table.row()
        pobox = self.school.pobox if self.school.pobox else "/"
        row.cell("__Paix - Travail - Patrie__", v_align=VAlign.T)
        row.cell(f"B.P : {pobox} - Tél : {self.school.contact}")

        row = table.row()
        row.cell("MINISTÈRE DES ENSEIGNEMENTS SECONDAIRES")
        row.cell(f"N° Immatriculation : {self.school.immatriculation}")

        row = table.row()
        row.cell(f"{self.school.region}")
        self.set_font_size(9)
        row.cell(f"__**Année scolaire {self.annee}**__", rowspan=2)
        self.set_font_size(8)

        row = table.row()
        row.cell(f"{self.school.departement}")
        table.render()

    def footer(self):
        self.set_y(-10)
        self.line(6, 289, 204, 289)
        self.set_font('inter', 'I', 8)
        self.cell(99, 10, f"Document généré par Oméga School Manager le {self.now}", align='L')
        self.cell(99, 10, f"FICHE DE NOTES ({self.classroom.code}) - Page {self.page_no()}/{{nb}}", align='R')


@logged_admin_view
def classroom_list(request, id):
    annee = school_year()
    classroom = (
        ClassRoom.objects.prefetch_related('students').
        get(pk=id))
    filename = f"Liste des élèves {classroom.code}.pdf"
    cls_list = ClassroomList(classroom=classroom, annee=annee, school=request.user.school)
    cls_list.set_title(filename)
    buffer = BytesIO()
    cls_list.output(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    response['Content-Disposition'] = f"attachment; filename={filename}"
    return response


class ClassroomList(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.add_font('inter', '', 'static/fonts/Inter-regular.ttf')
        self.add_font('inter', 'I', 'static/fonts/Inter-Italic.ttf')
        self.add_font('inter', 'B', 'static/fonts/Inter-Bold.ttf')
        self.add_font('inter', 'BI', 'static/fonts/Inter-BoldItalic.ttf')
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=10)
        self.set_font('inter', '', 9)
        self.now = datetime.datetime.now().strftime("%d-%m-%Y à %H:%M")
        self.annee = kwargs['annee']
        self.classroom = kwargs['classroom']
        self.school = kwargs['school']
        self.add_page()
        self.head()
        self.infos()
        self.list()

    def list(self):
        self.ln()
        col_widths = [10, 24, 75, 25, 41, 11.5, 11.5]
        header = ["N°", "Identifiant", "Nom(s) et Prénom(s)", "Né(e) le", "A", "Sexe", "Red?"]

        table = Table(self, line_height=6, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(220)
        for head in header:
            th.cell(f"**{head}**")
        self.set_fill_color(0)

        i = 1
        for student in self.classroom.students.all().order_by("nom", "prenom"):
            row = table.row()
            row.cell(f"{i}")
            row.cell(f"{student.unique_id}")
            row.cell(f"{student.__str__()}", align="L")
            row.cell(f"{student.date_naissance.strftime('%d-%m-%Y')}")
            row.cell(f"{student.lieu_naissance}", align="L")
            sexe = "M" if student.sexe == "Garçon" else "F"
            row.cell(sexe)
            red = "Oui" if student.statut == "Redoublant" else "Non"
            row.cell(red)
            i += 1
        table.render()

    def infos(self):
        self.set_font_size(13)
        self.ln()
        self.cell(0, 8, "**LISTE DES ÉLÈVES**", align='C', markdown=True)
        self.set_font_size(9)
        self.ln()
        self.cell(99, 5, f"**Classe : {self.classroom.code}**", align='L', markdown=True)
        students = self.classroom.students
        effectif = students.count()
        filles = students.filter(sexe="Fille").count()
        garcons = effectif - filles
        redoublants = students.filter(statut="Redoublant").count()
        info = f"Effectif : {effectif}, Filles : {filles}, Garçons : {garcons}, Redoublants : {redoublants}"
        self.cell(99, 5, f"__{info}__", align='R', markdown=True)

    def head(self):
        hwidths = (84, 30, 84)
        table = Table(self, line_height=5, col_widths=hwidths, text_align="CENTER", first_row_as_headings=False,
                      borders_layout="NONE", markdown=True)
        #
        logo = (self.school.logo, "static/image/no_image.jpg")[self.school.logo == ""]
        self.image(resize_image(logo, new_width=308), x=86, y=6, w=26, keep_aspect_ratio=True)

        row = table.row()
        row.cell("**RÉPUBLIQUE DU CAMEROUN**")
        row.cell("", rowspan=5)
        self.set_font_size(11)
        row.cell(f"**{self.school.nom}**")
        self.set_font_size(8)

        row = table.row()
        pobox = self.school.pobox if self.school.pobox else "/"
        row.cell("__Paix - Travail - Patrie__", v_align=VAlign.T)
        row.cell(f"B.P : {pobox} - Tél : {self.school.contact}")

        row = table.row()
        row.cell("MINISTÈRE DES ENSEIGNEMENTS SECONDAIRES")
        row.cell(f"N° Immatriculation : {self.school.immatriculation}")

        row = table.row()
        row.cell(f"{self.school.region}")
        self.set_font_size(9)
        row.cell(f"__**Année scolaire {self.annee}**__", rowspan=2)
        self.set_font_size(8)

        row = table.row()
        row.cell(f"{self.school.departement}")
        table.render()

    def footer(self):
        self.set_y(-10)
        self.line(6, 289, 204, 289)
        self.set_font('inter', 'I', 8)
        self.cell(99, 10, f"Document généré par Oméga School Manager le {self.now}", align='L')
        self.cell(99, 10, f"LISTE DES ÉLÈVES ({self.classroom.code}) - Page {self.page_no()}/{{nb}}", align='R')


class ClassroomTimeTable(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='L')
        self.add_font('inter', '', 'static/fonts/Inter-Regular.ttf')
        self.add_font('inter', 'I', 'static/fonts/Inter-Italic.ttf')
        self.add_font('inter', 'B', 'static/fonts/Inter-Bold.ttf')
        self.add_font('inter', 'BI', 'static/fonts/Inter-BoldItalic.ttf')
        self.alias_nb_pages()
        self.set_margins(12, 10, 12)
        self.set_auto_page_break(auto=True, margin=12)
        self.set_font('inter', '', 10)
        self.data = kwargs.pop('data')
        self.add_page()
        self.head()
        self.infos()
        self.timetable()

    def timetable(self):
        self.ln()
        col_widths = (33, 48, 48, 48, 48, 48)
        header = ("HORAIRES", "LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI")

        table = Table(self, line_height=5, col_widths=col_widths, text_align="CENTER", markdown=True)
        th = table.row()
        self.set_fill_color(220)
        padding = (2.5, 0, 2.5, 0)
        for head in header:
            th.cell(f"**{head}**", padding=padding)
        if 'tranches_horaires' in self.data.keys():
            for tranche in self.data['tranches_horaires']:
                row = table.row()
                self.set_fill_color(220)
                colspan = 1 if tranche.is_cours else 6
                row.cell(f"**{'' if colspan == 1 else 'Pause : '}{tranche.start_end}**", colspan=colspan,
                         padding=padding if colspan == 1 else (1.5, 0, 1.5, 0))
                self.set_fill_color(0)
                if colspan == 1:
                    row.cell()
                    row.cell()
                    row.cell()
                    row.cell()
                    row.cell()
        else:
            for elt in self.data['time_table']:
                row = table.row()
                self.set_fill_color(220)
                colspan = 1 if elt[0].is_cours else 6
                row.cell(f"**{'' if colspan == 1 else 'Pause : '}{elt[0].start_end}**", colspan=colspan,
                         padding=padding if colspan == 1 else (1.5, 0, 1.5, 0))
                self.set_fill_color(0)
                if colspan == 1:
                    for programmation in elt[1:]:
                        if programmation is not None and programmation['matiere'] is None:
                            row.cell()
                        elif programmation is not None:
                            enseignant = f"\n{programmation['enseignant'].short_firstname}" if programmation['enseignant'] else ""
                            row.cell(f"**{programmation['matiere']}**{enseignant}", rowspan=programmation['rowspan'])
        table.render()
        self.ln(1)
        self.set_x(14)
        self.cell(134.5, 8, "**L'Administration**", align='L', markdown=True)
        self.cell(134.5, 8, f"Fait à {self.data['school_data']['localite']}, le --                    --", align='R', markdown=True)
        self.ln()
        self.cell(269, 8, f"**Le {self.data['school_data']['chef']}**", align='R', markdown=True)

    def infos(self):
        self.set_font_size(16)
        self.ln(3)
        self.cell(273, 12, f"**EMPLOI DU TEMPS**", align='C', markdown=True)
        self.set_font_size(10)
        self.ln()
        classroom = (
            self.data['classroom'] if 'classroom' in self.data.keys()
            else "--                                        --")
        self.cell(136.5, 8, f"**Classe : **{classroom}", align='L', markdown=True)

    def head(self):
        school_data = self.data['school_data']
        hwidths = (111.5, 50, 111.5)
        table = Table(self, line_height=5, col_widths=hwidths, text_align="CENTER", first_row_as_headings=False,
                      borders_layout="NONE", markdown=True)
        logo = resize_image(school_data['logo'], new_width=308)
        self.image(logo, x=135.5, y=10, w=26, keep_aspect_ratio=True)

        row = table.row()
        row.cell("**RÉPUBLIQUE DU CAMEROUN**")
        row.cell("", rowspan=5)
        self.set_font_size(12)
        row.cell(f"**{school_data['nom']}**")
        self.set_font_size(9)

        row = table.row()
        row.cell("__Paix - Travail - Patrie__", v_align=VAlign.T)
        row.cell(f"B.P : {school_data['po_box']} - Tél : {school_data['contact']}")

        row = table.row()
        row.cell("MINISTÈRE DES ENSEIGNEMENTS SECONDAIRES")
        row.cell(f"N° Immatriculation : {school_data['immatriculation']}")

        row = table.row()
        row.cell(f"{school_data['region']}")
        self.set_font_size(10)
        row.cell(f"__**Année scolaire : {self.data['annee']}**__", rowspan=2)
        self.set_font_size(9)

        row = table.row()
        row.cell(f"{school_data['departement']}")
        table.render()

    def footer(self):
        self.set_y(-10)
        self.line(12, 202, 285, 202)
        self.set_font('inter', 'I', 8)
        self.set_x(12)
        self.cell(136.5, 10, f"Document généré par Oméga School Manager le"
                             f" {datetime.datetime.now().strftime('%d-%m-%Y à %H:%M')}", align='L')
        title = "EMPLOI DU TEMPS" + f" - {self.data['classroom']}" if 'classroom' in self.data.keys() else ""
        self.cell(136.5, 10, f"{title}", align='R')


class StaffMemberTimeTable(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='L')
        self.add_font('inter', '', 'static/fonts/Inter-Regular.ttf')
        self.add_font('inter', 'I', 'static/fonts/Inter-Italic.ttf')
        self.add_font('inter', 'B', 'static/fonts/Inter-Bold.ttf')
        self.add_font('inter', 'BI', 'static/fonts/Inter-BoldItalic.ttf')
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=12)
        self.set_font('inter', '', 10)
        self.data = kwargs.pop('data')
        self.add_page()
        self.head()
        self.infos()
        self.timetable()

    def timetable(self):
        self.ln()
        current_y = self.y

        recap_table = Table(self, width=45, line_height=8, col_widths=(32, 13), text_align="CENTER", markdown=True,
                            align='L')
        th = recap_table.row()
        self.set_fill_color(220)
        th.cell(f"**HEURES FAITES**", colspan=2)
        self.set_fill_color(0)
        i = 0
        if 'recap_and_total' in self.data.keys():
            recap, total = self.data['recap_and_total']
            for elt in recap:
                i += 1
                row = recap_table.row()
                row.cell(f"**{truncate_str(self, elt['matiere'], 32)} : {elt['nb_heures']}h**", colspan=2)
                for classe_recap in elt['matiere_recap']:
                    i += 1
                    row = recap_table.row()
                    row.cell(f"{truncate_str(self, classe_recap['classes'], 28)}")
                    row.cell(f"{classe_recap['nb_heures']}h")
                    if i == 15:
                        break
                if i == 15:
                    break
        else:
            total = ""
        for _ in range(15 - i):
            row = recap_table.row()
            row.cell()
            row.cell()
        row = recap_table.row()
        row.cell("**Total**")
        row.cell(f"**{total}{'h' if total else ' '}**")
        recap_table.render()

        self.set_xy(53, current_y)
        col_widths = (28, 42, 42, 42, 42, 42)
        header = ("HORAIRES", "LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI")

        table = Table(self, width=238, line_height=5, col_widths=col_widths, text_align="CENTER", markdown=True,
                      align='R')
        th = table.row()
        self.set_fill_color(220)
        padding = (2.5, 0, 2.5, 0)
        for head in header:
            th.cell(f"**{head}**", padding=padding)
        self.set_fill_color(0)
        if 'tranches_horaires' in self.data.keys():
            for tranche in self.data['tranches_horaires']:
                row = table.row()
                self.set_fill_color(220)
                colspan = 1 if tranche.is_cours else 6
                row.cell(f"**{'' if colspan == 1 else 'Pause : '}{tranche.start_end}**", colspan=colspan,
                         padding=padding if colspan == 1 else (0.5, 0, 0.5, 0))
                self.set_fill_color(0)
                if colspan == 1:
                    row.cell()
                    row.cell()
                    row.cell()
                    row.cell()
                    row.cell()
        else:
            for elt in self.data['time_table']:
                row = table.row()
                self.set_fill_color(220)
                colspan = 1 if elt[0].is_cours else 6
                row.cell(f"**{'' if colspan == 1 else 'Pause : '}{elt[0].start_end}**", colspan=colspan,
                         padding=padding if colspan == 1 else (1.5, 0, 1.5, 0))
                self.set_fill_color(0)
                if colspan == 1:
                    for programmation in elt[1:]:
                        if programmation is not None and programmation['matiere'] is None:
                            row.cell()
                        elif programmation is not None:
                            matiere = f"\n{truncate_str(self, programmation['matiere'], 38)}" if programmation['matiere'] else ""
                            row.cell(f"**{truncate_str(self, programmation['classes'], 37)}**{matiere}",
                                     rowspan=programmation['rowspan'])
        table.render()
        self.ln(1)
        self.set_x(57)
        self.cell(113, 8, "**L'Administration**", align='L', markdown=True)
        self.cell(113, 8, f"Fait à {self.data['school_data']['localite']}, le --                    --", align='R', markdown=True)
        self.ln()
        self.set_x(57)
        self.cell(226, 8, f"**Le {self.data['school_data']['chef']}**", align='R', markdown=True)

    def infos(self):
        self.set_font_size(16)
        self.ln(3)
        self.cell(273, 10, f"**EMPLOI DU TEMPS INDIVIDUEL**", align='C', markdown=True)
        self.set_font_size(10)
        self.ln()
        nom, grade = (f"**{self.data['infos']['nom']}**", self.data['infos']['grade']) if 'infos' in self.data.keys() \
            else (f"--{' ' * 156}--", f"--{' ' * 62}--")
        matieres = ""
        if 'recap_and_total' in self.data.keys():
            matieres = ""
            for elt in self.data['recap_and_total'][0]:
                matieres += elt['matiere']
                if elt != self.data['recap_and_total'][0][-1]:
                    matieres += ", "
        matieres = f"**{matieres}**" if matieres else f"--{' ' * 150}--"
        grade = f"**{grade}**" if grade not in ["", f"--{' ' * 62}--"] else f"--{' ' * 62}--"
        self.set_x(12)
        self.cell(200, 8, f"NOM(S) ET PRÉNOM(S) : {nom}", align='L', markdown=True)
        self.cell(73, 8, f"Grade : {grade}", align='L', markdown=True)
        self.ln()
        self.set_x(12)
        self.cell(200, 8, f"MATIÈRE(S) ENSEIGNÉE(S) : {matieres}", align='L', markdown=True)
        self.cell(73, 8, f"NOMBRE D'HEURES DUES : --{" " * 28}--", align='L', markdown=True)

    def head(self):
        school_data = self.data['school_data']
        hwidths = (111.5, 50, 111.5)
        table = Table(self, line_height=5, col_widths=hwidths, text_align="CENTER", first_row_as_headings=False,
                      borders_layout="NONE", markdown=True)
        logo = resize_image(school_data['logo'], new_width=308)
        self.image(logo, x=135.5, y=10, w=26, keep_aspect_ratio=True)

        row = table.row()
        row.cell("**RÉPUBLIQUE DU CAMEROUN**")
        row.cell("", rowspan=5)
        self.set_font_size(12)
        row.cell(f"**{school_data['nom']}**")
        self.set_font_size(9)

        row = table.row()
        row.cell("__Paix - Travail - Patrie__", v_align=VAlign.T)
        row.cell(f"B.P : {school_data['po_box']} - Tél : {school_data['contact']}")

        row = table.row()
        row.cell("MINISTÈRE DES ENSEIGNEMENTS SECONDAIRES")
        row.cell(f"N° Immatriculation : {school_data['immatriculation']}")

        row = table.row()
        row.cell(f"{school_data['region']}")
        self.set_font_size(10)
        row.cell(f"__**Année scolaire : {self.data['annee']}**__", rowspan=2)
        self.set_font_size(9)

        row = table.row()
        row.cell(f"{school_data['departement']}")
        table.render()

    def footer(self):
        self.set_y(-10)
        self.line(12, 202, 285, 202)
        self.set_font('inter', 'I', 8)
        self.set_x(12)
        self.cell(136.5, 10, f"Document généré par Oméga School Manager le"
                             f" {datetime.datetime.now().strftime('%d-%m-%Y à %H:%M')}", align='L')
        self.cell(136.5, 10, f"{self.data['filename']}", align='R')
