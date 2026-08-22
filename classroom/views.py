import os
from io import BytesIO

from django.urls import reverse
from fpdf.enums import TableHeadingsDisplay

from authentification.models import TrancheHoraire, School, User
from osm.utils import message, resized_image, formated_float, school_year, LoggedAdminView, LoggedUserView, \
    logged_admin_view, logged_user_view, ListView, DeleteView, resize_image, pdf_response, truncate_str, \
    base_header, base_infos, delete_image, zip_pdfs_response, check_notes, add_fonts, seuils_par_pk
from django.db.models import Q, Prefetch
from django.forms import model_to_dict
from django.http import Http404, HttpResponse, JsonResponse
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from staff.models import Discipline, Personnel
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
from PIL import Image, ImageDraw, ImageFile


"""
=============================================================================
 VIEWS — Mise à jour des photos d'une classe (en masse, ligne par ligne)
=============================================================================
Deux vues :
  1. ClassPhotosPage  -> affiche le tableau (une ligne/élève) avec, par ligne,
     un input file + aperçu + état. PAS de gros POST : chaque photo s'upload
     séparément en AJAX vers la vue ci-dessous.
  2. StudentPhotoUpload -> reçoit UNE photo (un seul élève), la sauvegarde sur
     Student.photo (Cloudinary), renvoie du JSON.

Pourquoi ligne par ligne (et pas un POST de 100 fichiers) :
  - un POST monolithique de 100 images = timeout quasi garanti sur Render ;
  - ici chaque upload est indépendant (échec isolé, réessayable), avec un
    feedback par élève. Le redimensionnement se fait côté CLIENT avant envoi
    (canvas ~500px), donc le serveur reçoit des images déjà légères.
=============================================================================
"""

# -----------------------------------------------------------------------------
# 1) Page tableau de mise à jour des photos
# -----------------------------------------------------------------------------
class ClassPhotosPage(LoggedAdminView):
    template_name = "class_photos.html"

    def get(self, *args, **kwargs):
        classroom = get_object_or_404(
            ClassRoom.objects.select_related("classe"),
            pk=self.kwargs["id"]
        )
        students = classroom.students.all().order_by("nom", "prenom")
        context = {
            "title": f"Photos — {classroom.code}",
            "classroom": classroom,
            "students": students,
        }
        return render(self.request, self.template_name, context)


# -----------------------------------------------------------------------------
# 2) Endpoint d'upload d'UNE photo (AJAX, un élève à la fois)
# -----------------------------------------------------------------------------
class StudentPhotoUpload(LoggedAdminView):
    """
    POST multipart avec :
      - le fichier dans request.FILES['photo']
    L'élève est identifié par l'URL (<int:id> = student id). On vérifie que
    l'élève a une classe (le mixin lit kwargs['id'] comme un id de CLASSE : voir la note URL,
    on passe donc l'id de la classe dans l'URL et l'id élève en second).
    """

    def post(self, *args, **kwargs):
        # kwargs : 'id' = id de la CLASSE, 'student_id' = élève.
        classroom_id = self.kwargs["id"]
        student_id = self.kwargs["student_id"]

        student = get_object_or_404(
            Student.objects.select_related("classe"),
            pk=student_id, classe_id=classroom_id   # l'élève doit bien être dans cette classe
        )

        photo = self.request.FILES.get("photo")
        if not photo:
            return JsonResponse(
                {"success": False, "message": "Aucune image reçue."}, status=400
            )

        # Garde-fou de taille (le client redimensionne déjà ; ceci protège le
        # serveur d'un envoi direct hors interface).
        max_bytes = 3 * 1024 * 1024  # 3 Mo
        if photo.size > max_bytes:
            return JsonResponse(
                {"success": False, "message": "Image trop lourde (max 3 Mo)."},
                status=400
            )

        # Type MIME basique.
        if not photo.content_type or not photo.content_type.startswith("image/"):
            return JsonResponse(
                {"success": False, "message": "Le fichier n'est pas une image."},
                status=400
            )

        # On garde une référence à l'ANCIENNE image AVANT de réassigner.
        old_photo = student.photo if student.photo else None

        # 1) On enregistre d'abord la NOUVELLE photo. Si l'upload (Cloudinary)
        #    ou le save échoue, une exception est levée ICI et l'ancienne image
        #    reste intacte -> l'élève n'est jamais laissé sans photo.
        student.photo = photo
        student.save(update_fields=["photo"])

        # 2) La nouvelle est confirmée en base : on peut supprimer l'ancienne
        #    (Cloudinary en prod, fichier en dev) sans risque d'orphelin.
        #    On ne supprime que si c'était bien une autre image.
        if old_photo and old_photo.name != student.photo.name:
            delete_image(old_photo)

        return JsonResponse({
            "success": True,
            "url": student.photo.url if student.photo else "",
            "message": "Photo mise à jour.",
        })


"""
=============================================================================
 VIEW — Attribution des titulaires aux classes (toutes les classes)
=============================================================================
FLUX :
  GET  -> tableau, une ligne par classe, select de titulaire pré-rempli.
  POST -> lit titulaire_<classroom_id> et met à jour ClassRoom.titulaire en masse
          (bulk_update). Une valeur vide = "aucun titulaire" (None).
=============================================================================
"""

class TitulaireAssignment(LoggedAdminView):
    template_name = "titulaire_assignment.html"

    def get(self, *args, **kwargs):
        classrooms = ClassRoom.objects.select_related("classe", "titulaire").order_by_niveau()
        context = {
            "title": "Attribution des titulaires",
            "classrooms": classrooms,
            "personnels": Personnel.objects.personnels_tries(),
        }
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        classrooms = list(
            ClassRoom.objects.select_related("titulaire").order_by_niveau()
        )

        # Ids de personnel valides (sécurité : on n'accepte que des ids connus).
        valid_personnel_ids = set(
            Personnel.objects.values_list("id", flat=True)
        )

        to_update, nb = [], 0
        for cls in classrooms:
            raw = self.request.POST.get(f"titulaire_{cls.id}") or None
            new_id = int(raw) if (raw and int(raw) in valid_personnel_ids) else None

            if (cls.titulaire_id or None) != new_id:
                cls.titulaire_id = new_id
                to_update.append(cls)
                nb += 1

        if to_update:
            ClassRoom.objects.bulk_update(to_update, ["titulaire"])

        if nb:
            message(self.request, f"Titulaires mis à jour pour {nb} classe(s).")
        else:
            message(self.request, "Aucune modification effectuée.", msg_type="warning")

        return redirect("titulaire_assignment")


class ClassRoomProgression(LoggedAdminView):
    template_name = "classroom_progression.html"

    def get(self, *args, **kwargs):
        i = self.request.GET.get('classroom')
        classroom = ClassRoom.objects.get(pk=i)
        titre = f"État de la progression en {classroom.code}"
        context = {'progression': classroom.progression, 'titre': titre}
        return render(self.request, self.template_name, context)


class ClassRoomProgressionSelectForm(LoggedAdminView):
    template_name = "edit_marks.html"
    title = "Couverture des programmes"

    def get(self, *args, **kwargs):
        select_form = SelectForm(context={"request": self.request, 'trim': False, 'marks_sheet': True,
                                          'enseignements': None, 'classrooms': ClassRoom.objects.all()})
        context = {'title': self.title, 'select_form': select_form, 'marks_sheet': True, 'cls_progression': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        select_form = SelectForm(context={"request": self.request, 'trim': False, 'marks_sheet': True,
                                          'enseignements': None, 'classrooms': ClassRoom.objects.all()})
        context = {'title': self.title, 'select_form': select_form, 'marks_sheet': True, 'cls_progression': True}
        return render(self.request, self.template_name, context)


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
            return tranches_horaires, school
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
        """for _, liste in matrice.items():
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
                i += rowspan"""
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
            return time_table, classroom.code, school
        return time_table, f"Emploi du temps {classroom.code}", classroom.timetable_recap(mp)

    def get(self, *args, **kwargs):
        classroom_id = int(self.request.GET['clsrm']) if 'clsrm' in self.request.GET.keys() else int(
            self.request.headers['X-ClassroomId'])
        time_table, title, recap = self.get_time_table(classroom_id)
        context = {'time_table': time_table, 'days': self.days, 'recap': recap, 'classroom_id': classroom_id,
                   't_title': title, 'signed': signing.dumps(classroom_id)}
        return render(self.request, self.template_name, context=context)

    def build_pdf_or_reason(self, classroom, annee):
        if not classroom.programmations.exists():
            return "Aucune programmation disponible pour cette classe"  # -> sautée (ZIP) ou message d'erreur (une classe)
        result = self.get_time_table(classroom.pk, download=True)
        data = {
            'filename': "Emploi du temps",
            'annee': annee,
            'time_table': result[0],
            'classroom': result[1],
            'school': result[2],
        }
        data['filename'] += f" {data['classroom']}"
        return ClassroomTimeTable(data=data)

    def post(self, *args, **kwargs):
        if 'signed' not in self.request.POST.keys():
            classrooms = (
                ClassRoom.objects.select_related('classe').
                prefetch_related('programmations')
            )
            annee = self.request.user.school.establishment_year

            def build(clsrm):
                return self.build_pdf_or_reason(clsrm, annee)

            def namer(clsrm):
                return f"{clsrm.code} Emploi du temps.pdf"

            return zip_pdfs_response(
                build_pdf_for_classroom=build,
                classrooms=classrooms,
                zip_filename=f"Emplois du temps - Toutes les classes.zip",
                per_file_namer=namer,
            )
        try:
            classroom_id = signing.loads(self.request.POST["signed"])
            empty_timetable = True if 'timetable_checkbox' in self.request.POST.keys() else False
            data = {'filename': "Emploi du temps", 'annee': self.request.user.school.establishment_year}
            if empty_timetable:
                data['tranches_horaires'], data['school'] = self.get_time_table(classroom_id, empty=True)
            else:
                data['time_table'], data['classroom'], data['school'] = (
                    self.get_time_table(classroom_id, download=True)
                )
                data['filename'] += f" {data['classroom']}"
            return pdf_response(ClassroomTimeTable(data=data), f"{data['filename']}.pdf")
        except signing.BadSignature:
            return JsonResponse({
                'success': False,
                'message': f"Une valeur a été altérée"
            })


def checks_notes(classrooms, evl_in):
    def check(classroom):
        if not classroom.students.exists():
            return f"Aucun élève en {classroom.code}"
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
            rapport += f" n'ont pas été remplies en {classroom.code}."
            return rapport
        return None

    for classroom in classrooms:
        rapport = check(classroom)
        if rapport:
            return rapport
    return None


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
        staff_member = self.request.user.staff_member
        msg, enseignements = "", None
        if self.request.user.is_min_admin:
            if not ClassRoom.objects.exists():
                msg = "Aucune classe disponible."
        else:
            if staff_member.rapporteur.exists() or staff_member.enseignant.exists():
                enseignements = Enseignements.objects.select_related('matiere__sujet', 'classroom').filter(
                    Q(rapporteur_id=staff_member.pk) | Q(enseignant_id=staff_member.pk))
            else:
                msg = "Vous n'êtes affectés à aucune salle de classe."
        return msg, enseignements

    def get(self, *args, **kwargs):
        msg, enseignements = self.check()
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(context={'all': True,
                "request": self.request, 'trim': False, 'marks_sheet': True, 'enseignements': enseignements})
            context = {'marks_sheet': True, 'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)

    @staticmethod
    def build_pdf_or_reason(classroom, annee, school):
        reason = check_notes(classroom, None, marks_sheet=True)
        if reason is not None:
            return reason  # -> sautée (ZIP) ou message d'erreur (une classe)

        return PDFMarksSheet(classroom=classroom, annee=annee, school=school)

    def post(self, *args, **kwargs):
        annee = self.request.user.school.establishment_year
        school = User.objects.select_related('school').get(id=self.request.user.id).school
        selected = self.request.POST.get("classroom")

        # -------- Cas "Toutes les classes" -> ZIP --------
        if selected == "__all__":
            if self.request.user.is_min_admin:
                classrooms = ClassRoom.objects.select_related('classe').prefetch_related('students').order_by_niveau()
            else:
                enseignements = Enseignements.objects.select_related('matiere__sujet', 'classroom').filter(
                    Q(rapporteur_id=self.request.user.staff_member.pk) | Q(enseignant_id=self.request.user.staff_member.pk))
                classes_id = [ens.classroom.pk for ens in enseignements]
                classrooms = (
                    ClassRoom.objects.select_related('classe')
                    .prefetch_related('students').filter(pk__in=classes_id).order_by_niveau()
                )

            def build(clsrm):
                return self.build_pdf_or_reason(clsrm, annee, school)

            def namer(clsrm):
                return f"{clsrm.code} Fiche de Notes.pdf"

            return zip_pdfs_response(
                build_pdf_for_classroom=build,
                classrooms=classrooms,
                zip_filename=f"Fiches de Notes - Toutes les classes.zip",
                per_file_namer=namer,
            )

        # -------- Cas "une seule classe" --------
        classroom = (
            ClassRoom.objects.prefetch_related('students').
            get(pk=int(selected))
        )
        result = self.build_pdf_or_reason(classroom, annee, school)
        filename = f"Fiche de Notes {classroom.code}.pdf"
        if isinstance(result, str):
            return JsonResponse({'success': False, 'message': result})
        return pdf_response(result, filename)


class StatsCheck(LoggedAdminView):
    template_name = "stats.html"
    title = "Statistiques"

    def get(self, *args, **kwargs):
        check_form = CheckForm(context={'transcript': True, 'stats': True, 'all':True})
        context = {"title": self.title, "check_form": check_form, "stats": False,
                   'seuils': seuils_par_pk(ClassRoom.objects.all())}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        check_form = CheckForm(self.request.POST or None, context={'transcript': True, 'stats': True, 'all':True})
        context = {"title": self.title, "check_form": check_form, "stats": False}
        return render(self.request, self.template_name, context)


class Stats(LoggedAdminView):
    template_name = "statistiques.html"

    def get(self, *args, **kwargs):
        classroom_id = 0 if self.request.GET['clsrm'] == "__all__" else int(self.request.GET['clsrm'])
        evl = int(self.request.GET["evl"])
        try:
            seuil = float(self.request.GET.get("moyenne_min_admission"))
        except:
            seuil = None
        trim = ((("du premier trimestre", "du deuxième trimesre")[evl == 2], "du troisième trimeste")[evl == 3],
                "annuelles")[evl == 4]
        evl_in = ((([1, 2], [3, 4])[evl == 2], [5, 6])[evl == 3], [1, 2, 3, 4, 5, 6])[evl == 4]
        data = None
        if classroom_id:
            classroom = (
                ClassRoom.objects.select_related('classe').
                prefetch_related('students', 'matieres__sujet').
                get(pk=classroom_id)
            )
            if not classroom.students.exists():
                status = False
                rapport = f"Aucun élève en {classroom.code}."
            else:
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
                else:
                    rapport = None
                    status = True
                    classroom.update_seuil(seuil)
                    data = classroom.marks_report_data(evl_in, for_stats=True)
        # Statistiques Établissement
        else:
            classrooms = list(
                ClassRoom.objects.select_related('classe').
                prefetch_related('students', 'matieres__sujet').order_by_niveau()
            )
            rapport = checks_notes(classrooms, evl_in)
            status = False if rapport else True
            if status:
                data = self.school_stats(classrooms, evl_in)
        context = {'status': status, 'rapport': rapport, 'trim': trim, 'data': data,
                   'global_stats': False if classroom_id else True}
        return render(self.request, self.template_name, context)

    @staticmethod
    def school_stats(classrooms, evals, download=False):
        result = [classroom.marks_report_data(evals, for_stats=True, for_global_stats=True) for classroom
                  in classrooms]
        effectif = nbfe = nbfr = nbge = nbgr = nbe = nbr = total_moyenne = nbft = nbgt = 0
        if download:
            redoublants = 0
        min_std, max_std, minim, maxim = None, None, float("inf"), float("-inf")
        min_clst, max_clst, mint, maxt = None, None, float("inf"), float("-inf")
        min_clsmg, max_clmg, min_mg, max_mg = None, None, float("inf"), float("-inf")
        for classroom_data in result:
            effectif += classroom_data["effectif"]
            nbfe += classroom_data["nbfe"]
            nbfr += classroom_data["nbfr"]
            nbge += classroom_data["nbge"]
            nbgr += classroom_data["nbgr"]
            nbr += classroom_data["nbr"]
            nbe += classroom_data["nbe"]
            nbft += classroom_data["filles"]
            nbgt += classroom_data["garcons"]
            total_moyenne += classroom_data["moyenne_generale"] * classroom_data['nbe']
            if minim > classroom_data["min"]:
                minim = classroom_data["min"]
                min_std = f"{classroom_data['min_std']} - {classroom_data['label']}"
            if maxim < classroom_data["max"]:
                maxim = classroom_data["max"]
                max_std = f"{classroom_data['max_std']} - {classroom_data['label']}"
            if mint > classroom_data["taux"]:
                mint = classroom_data["taux"]
                min_clst = classroom_data['label']
            if maxt < classroom_data["taux"]:
                maxt = classroom_data["taux"]
                max_clst = classroom_data['label']
            if min_mg > classroom_data["moyenne_generale"]:
                min_mg = classroom_data["moyenne_generale"]
                min_clsmg = classroom_data['label']
            if max_mg < classroom_data["moyenne_generale"]:
                max_mg = classroom_data["moyenne_generale"]
                max_clsmg = classroom_data['label']
            if download:
                redoublants += classroom_data["redoublants"]
        data = {
            'effectif': effectif,
            'nbfe': nbfe,
            'nbfr': nbfr,
            'pcf': formated_float((nbfr / nbfe) * 100) if nbfe else 0,
            'nbge': nbge,
            'nbgr': nbgr,
            'pcg': formated_float((nbgr / nbge) * 100) if nbge else 0,
            'nbe': nbe,
            'nbr': nbr,
            'taux': formated_float((nbr / nbe) * 100) if nbe else 0,
            'filles': nbft,
            'garcons': nbgt,
            'ppf': formated_float((nbfe / nbft) * 100) if nbft else 0,
            'ppg': formated_float((nbge / nbgt) * 100) if nbgt else 0,
            'ppt': formated_float((nbe / effectif) * 100) if effectif else 0,
            'min': minim,
            'max': maxim,
            'min_std': min_std,
            'max_std': max_std,
            'min_max': f"[{minim} - {maxim}]",
            'min_clsmg': f"{min_mg} - {min_clsmg}",
            'min_clst': f"{mint}% - {min_clst}",
            'max_clsmg': f"{max_mg} - {max_clsmg}",
            'max_clst': f"{maxt}% - {max_clst}",
            'moyenne_generale': formated_float(total_moyenne / nbe) if nbe else 0,
            'classrooms_data': result
        }
        if download:
            data['redoublants'] = redoublants
            data['label'] = "Global"
        return data

    def build_pdf_or_reason(self, classroom, evl_in, annee, school, trimestre):
        if classroom is None:
            classrooms = list(
                ClassRoom.objects.select_related('classe').
                prefetch_related('students', 'matieres__sujet').order_by_niveau()
            )
            rapport = checks_notes(classrooms, evl_in)
            if rapport:
                return rapport
            data = self.school_stats(classrooms, evl_in, download=True)
        else:
            reason = check_notes(classroom, evl_in)
            if reason is not None:
                return reason  # -> sautée (ZIP) ou message d'erreur (une classe)
            data = classroom.marks_report_data(evl_in, for_stats=True)
        data['school_data'], data['trimestre'], data['annee'] = (
            school, trimestre, annee
        )
        return Statistiques(data=data)

    def post(self, *args, **kwargs):
        from archives.models import ArchiveRef, DocType
        scope = self.request.POST.get('scope')  # 'pdf' ou 'zip'
        clsrm = self.request.POST.get('clsrm')  # '__all__' ou 'classroom.id'
        evl = int(self.request.POST['evl'])
        annee = self.request.user.school.establishment_year
        trimestre = ((("DU PREMIER TRIMESTRE", "DU DEUXIÈME TRIMESTRE")[evl == 2],
                      "DU TROISIÈME TRIMESTRE")[evl == 3], "ANNUELLES")[evl == 4]
        evl_in = ((((1, 2), (3, 4))[evl == 2], (5, 6))[evl == 3], (1, 2, 3, 4, 5, 6))[evl == 4]
        school = User.objects.select_related('school').get(id=self.request.user.id).school

        if scope == 'zip':
            # stats de TOUTES les classes + global -> ZIP (réutilise zip_pdfs_response)
            classrooms = list(
                ClassRoom.objects.select_related('classe').
                prefetch_related('students', 'matieres__sujet').order_by_niveau()
            )
            classrooms.insert(0, None)
            def build(clsrm):
                return self.build_pdf_or_reason(clsrm, evl_in, annee, school, trimestre)

            def archive_for(clsrm):
                return ArchiveRef(self.request.user.school, DocType.STATS_REUSSITE, clsrm, user=self.request.user,
                                 term_index=evl if evl != 4 else 0)

            def namer(clsrm):
                return f"{'' if clsrm is None else clsrm.code + ' '}Statistiques {'Globales' if clsrm is None else ''} {trimestre.title()}.pdf"

            return zip_pdfs_response(
                build_pdf_for_classroom=build,
                classrooms=classrooms,
                zip_filename=f"Statistques {trimestre.title()} - Toutes les classes.zip",
                per_file_namer=namer,
                archive_for=archive_for,
            )

        elif scope == 'pdf':
            if clsrm == '__all__':
                # stats GLOBALES établissement -> PDF unique
                classroom = None
            else:
                # stats d'UNE classe précise -> PDF unique
                classroom = (
                    ClassRoom.objects.select_related('classe').
                    prefetch_related('students', 'matieres__sujet').
                    get(pk=int(clsrm))
                )
            filename = f"Statistiques {'Globales' if classroom is None else ''} {trimestre.title()}{'' if classroom is None else ' ' + classroom.code}.pdf"
            archive = ArchiveRef(self.request.user.school, DocType.STATS_REUSSITE, classroom, user=self.request.user,
                                 term_index=evl if evl != 4 else 0)
            hit = archive.response(filename)
            if hit:
                return hit
            result = self.build_pdf_or_reason(classroom, evl_in, annee, school, trimestre)
            if isinstance(result, str):
                return JsonResponse({'success': False, 'message': result})
            return pdf_response(result, filename, archive=archive)
        else:
            return JsonResponse({'success': False, 'message': "Action inconnue."})


class ClassAlbum(LoggedAdminView):
    template_name = "class_photo_album.html"
    title = "Album Photo de Classe"

    def get(self, *args, **kwargs):
        select_form = SelectForm(context={
            "request": self.request, 'trim': False, 'marks_sheet': True, 'enseignements': None})
        context = {'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)

    @staticmethod
    def build_pdf_or_reason(classroom, annee, school_data):
        reason = check_notes(classroom, None, marks_sheet=True)
        if reason is not None:
            return reason  # -> sautée (ZIP) ou message d'erreur (une classe)
        data = classroom.class_album_data
        data['school_year'] = annee
        data['school_data'] = school_data
        return ClassPhotoAlbum(data=data)

    def post(self, *args, **kwargs):
        from archives.models import DocType, ArchiveRef
        classrooms = (
            ClassRoom.objects.prefetch_related(
                Prefetch(
                    'enseignement',
                    queryset=Enseignements.objects.select_related('matiere__sujet', 'enseignant')
                ),
                'students')
            .select_related('titulaire')
        )
        annee = self.request.user.school.establishment_year
        school = User.objects.select_related('school').get(id=self.request.user.id).school
        principal = Personnel.objects.filter(poste="Chef d'Établissement").first()
        school_data = {
            'nom': school.nom,
            'name': school.name,
            'logo': school.logo,
            'principal': principal
        }
        selected = self.request.POST.get("classroom")
        filename = "Album Photo"
        # -------- Cas "Toutes les classes" -> ZIP --------
        if selected == "__all__":

            def build(clsrm):
                return self.build_pdf_or_reason(clsrm, annee, school_data)

            def archive_for(clsrm):
                return ArchiveRef(self.request.user.school, DocType.ALBUM, clsrm, user=self.request.user)

            def namer(clsrm):
                return f"{clsrm.code} {filename}.pdf"

            return zip_pdfs_response(
                build_pdf_for_classroom=build,
                classrooms=classrooms,
                zip_filename=f"Albums Photos - Toutes les classes.zip",
                per_file_namer=namer,
                archive_for=archive_for,
            )

        # -------- Cas "une seule classe" --------
        classroom = classrooms.get(pk=int(selected))
        archive = ArchiveRef(self.request.user.school, DocType.ALBUM, classroom, user=self.request.user)
        hit = archive.response(f"{filename} {classroom.code}.pdf")
        if hit:
            return hit
        result = self.build_pdf_or_reason(classroom, annee, school_data)
        if isinstance(result, str):
            return JsonResponse({'success': False, 'message': result})
        return pdf_response(result, f"{filename} {classroom.code}.pdf", archive=archive)


"""
=============================================================================
 ClassPhotoAlbum — Générateur PDF "Album de classe" (souvenir) pour OSM
=============================================================================
 Format : A4 PAYSAGE. Page 1 = équipe pédagogique (titulaire en vedette,
 = teachers[0]), pages suivantes = élèves. Grille uniforme, photos en cover
 à coins arrondis (clipping parfait), code couleur par genre (M=bleu, F=rose),
 en-tête répété (logo établissement des DEUX côtés) + bande tricolore,
 compteur d'élèves, pied de page paginé. Optimisé mémoire (pour Render).

 ENTRÉE (dict) :
   {
     'school_data'   : {'nom','name','logo','principal', ...},
     'classroom_data': {'nom','effectif','filles','garcons'},
     'students_data' : [{'nom','prenom','sexe'('M'/'F'),'photo'(url), ...}, ...],
     'school_year'   : année scolaire courante,
     'teachers'      : [{'nom','prenom','matiere','sexe','photo'(url), ...}, ...],
                        # teachers[0] = professeur titulaire
   }


 DÉPENDANCES :
   - resize_image(...) : cover + ancrage visage auto (id_card=True)
   - settings.INTER_REGULAR / INTER_BOLD / INTER_ITALIC : chemins .ttf
   - 4 silhouettes par défaut dans static
=============================================================================
"""
ImageFile.LOAD_TRUNCATED_IMAGES = True

# --- Couleurs (RGB) ----------------------------------------------------------
GREEN  = (10, 125, 63)
RED    = (210, 31, 60)
YELLOW = (249, 214, 22)
NAVY   = (10, 61, 98)
DARK   = (21, 35, 59)
GREY   = (122, 134, 148)
LIGHTG = (200, 222, 210)
BLUEB  = (47, 111, 176)    # bordure garçon / homme
PINKB  = (214, 88, 143)    # bordure fille / femme
PHBG   = (205, 214, 226)


class ClassPhotoAlbum(FPDF):
    # ----- disposition -----
    TEACHERS_COLS, TEACHERS_ROWS = 5, 3   # 15 / page
    STUDENTS_COLS, STUDENTS_ROWS = 6, 3   # 18 / page

    def __init__(self, data):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.alias_nb_pages()
        self.data = data
        self.static_root = os.path.join(settings.BASE_DIR, 'static')
        self.resize_func = resize_image
        self._inter_bold_path = settings.INTER_BOLD
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)

        add_fonts(self)

        # caches
        self._logo_bytes = None       # logo établissement préchargé une fois
        self._default_cache = {}      # silhouettes par défaut : image FINALE prête

        # géométrie page A4 paysage
        self.PW, self.PH = 297.0, 210.0
        self.MX = 12.0                # marge latérale
        self.TOP = 8.0
        self.build()

    # =====================================================================
    #  API PUBLIQUE
    # =====================================================================
    def build(self):
        """Génère tout l'album"""
        teachers = self.data.get("teachers", []) or []
        students = self.data.get("students_data", []) or []

        # --- pages enseignants ---
        per = self.TEACHERS_COLS * self.TEACHERS_ROWS
        t_pages = [teachers[i:i+per] for i in range(0, max(1, len(teachers)), per)] or [[]]
        # --- pages élèves ---
        pers = self.STUDENTS_COLS * self.STUDENTS_ROWS
        s_pages = [students[i:i+pers] for i in range(0, len(students), pers)] or [[]]

        if teachers:
            for chunk in t_pages:
                self.add_page()
                self._render_header(section="L'ÉQUIPE PÉDAGOGIQUE", show_count=False)
                self._render_grid(chunk, kind="teacher")
                self._render_footer()

        for chunk in s_pages:
            self.add_page()
            self._render_header(section="LES ÉLÈVES", show_count=True)
            self._render_grid(chunk, kind="student")
            self._render_footer()

    # =====================================================================
    #  EN-TÊTE
    # =====================================================================
    def _render_header(self, section, show_count):
        sd = self.data.get("school_data", {})
        cd = self.data.get("classroom_data", {})
        cx = self.PW / 2
        y = self.TOP

        # logos établissement des DEUX côtés
        logo = self._get_logo_bytes()
        lw = 20
        if logo:
            try:
                self.image(BytesIO(logo), x=self.MX, y=y, w=lw, h=lw)
                self.image(BytesIO(logo), x=self.PW - self.MX - lw, y=y, w=lw, h=lw)
            except Exception:
                pass

        # textes centrés
        self.set_text_color(*NAVY)
        self.set_font("inter", "B", 16)
        self._centered(sd.get("nom", ""), y+1, cx)
        self.set_font("inter", "B", 9)
        self.set_text_color(*GREY)
        self._centered(sd.get("name", ""), y+7.5, cx)
        principal = sd.get("principal", "")
        if principal:
            self.set_font("inter", "", 8)
            self._centered(f"Le Chef d'établissement / The Principal : {principal}", y+12, cx)

        # nom de classe (vert) + année scolaire dessous
        self.set_font("inter", "B", 22)
        self.set_text_color(*GREEN)
        cls = cd.get("nom", "")
        self._centered(cls, y+18, cx, h=10)
        self.set_font("inter", "B", 8)
        self.set_text_color(*GREY)
        yr = self.data.get("school_year", "")
        self._centered(f"ANNÉE SCOLAIRE {yr}".upper(), y+26, cx)

        # bande tricolore (rallongée)
        fy = y + 31
        fw = 95.0
        fx = cx - fw/2
        seg = fw/3
        self.set_fill_color(*GREEN);  self.rect(fx, fy, seg, 1.8, "F")
        self.set_fill_color(*RED);    self.rect(fx+seg, fy, seg, 1.8, "F")
        self.set_fill_color(*YELLOW); self.rect(fx+2*seg, fy, seg, 1.8, "F")

        # compteur d'élèves (page élèves)
        if show_count:
            eff = cd.get("effectif", len(self.data.get("students_data", [])))
            self.set_font("inter", "B", 20)
            self.set_text_color(*GREEN)
            self.set_xy(self.PW - self.MX - 22.5, y+21)
            self.cell(25, 8, str(eff), align="C")
            self.set_font("inter", "", 8)
            self.set_text_color(*GREY)
            self.set_xy(self.PW - self.MX - 22.5, y+28)
            self.cell(25, 4, "Élèves / Students", align="C")

        # titre de section + filet décoratif
        self.set_font("inter", "B", 12)
        self.set_text_color(*GREEN)
        self._centered(section, fy+4, cx)
        self.set_draw_color(*LIGHTG)
        self.set_line_width(0.3)
        sw = self.get_string_width(section) + 30
        self.line(cx - sw/2, fy+10.5, cx + sw/2, fy+10.5)

        # mémorise le Y de départ de la grille
        self._grid_top = fy + 14

    # =====================================================================
    #  GRILLE
    # =====================================================================
    def _render_grid(self, items, kind):
        if kind == "teacher":
            cols, rows, gut = self.TEACHERS_COLS, self.TEACHERS_ROWS, 6.0
            cap_h = 11.0
        else:
            cols, rows, gut = self.STUDENTS_COLS, self.STUDENTS_ROWS, 5.0
            cap_h = 9.0

        gx = self.MX
        gy = self._grid_top
        gw = self.PW - 2*self.MX
        cell_w = (gw - (cols-1)*gut) / cols
        avail_h = self.PH - 10.0 - gy
        cell_h = (avail_h - (rows-1)*4.0) / rows

        # photo en portrait 3:4, centrée dans la cellule
        ph_h = cell_h - cap_h
        ph_w = ph_h * 3/4
        if ph_w > cell_w:
            ph_w = cell_w
            ph_h = ph_w * 4/3

        for i, item in enumerate(items):
            r, c = divmod(i, cols)
            x = gx + c*(cell_w+gut) + (cell_w-ph_w)/2
            yy = gy + r*(cell_h+4.0)
            is_titulaire = (self.data['has_titulaire'] and kind == "teacher" and self.page_no() == 1 and i == 0)
            self._render_cell(item, x, yy, ph_w, ph_h, kind, is_titulaire)
            # légende
            self._render_caption(item, x+ph_w/2, yy+ph_h+1.5, ph_w+gut, kind, is_titulaire)

    def _render_cell(self, item, x, y, w, h, kind, is_titulaire):
        sexe = (item.get("sexe") or "M").upper()
        if is_titulaire:
            border = GREEN; bw = 6
        else:
            border = PINKB if sexe == "F" else BLUEB; bw = 4

        url = item.get("photo")

        # --- PLACEHOLDER EN CACHE ------------------------------------------
        # Sans photo, l'image finale (arrondie + bordure) est calculée UNE fois
        # par (kind, sexe, bordure) puis réutilisée telle quelle. En plus,
        # fpdf2 déduplique les images au contenu identique : le PDF ne stocke
        # cette silhouette qu'UNE seule fois même répétée 15 fois.
        # -> gros gain de taille ET de temps.
        cache_key = None
        if not url:
            cache_key = (kind, sexe, border)
            cached = self._default_cache.get(cache_key)
            if cached:
                self.image(BytesIO(cached), x=x, y=y, w=w, h=h)
                return

        # 200 dpi : largement suffisant pour ~3 cm imprimés.
        # (300 dpi était surdimensionné : x2.25 de pixels pour rien)
        px_w, px_h = int(w*7.87), int(h*7.87)
        img = url or self._placeholder_path(kind, sexe)
        try:
            buf = self.resize_func(img, id_card=True, ratio=(30, 40))
            src = Image.open(buf)
        except Exception:
            src = self._placeholder_image(kind, sexe)

        rounded = self._rounded_image(src, px_w, px_h, radius=int(px_w*0.09),
                                      border_col=border, border_w=bw,
                                      badge=("TITULAIRE" if is_titulaire else None))
        bio = BytesIO()
        # JPEG (photo aplatie sur fond blanc = fond de page) : ~15x plus léger
        # que le PNG précédent, à qualité visuelle égale.
        rounded.save(bio, format="JPEG", quality=82, optimize=True)
        data = bio.getvalue()
        if cache_key:
            self._default_cache[cache_key] = data
        self.image(BytesIO(data), x=x, y=y, w=w, h=h)

    def _render_caption(self, item, cx, y, maxw, kind, is_titulaire):
        nom = (item.get("nom") or "").strip()
        prenom = (item.get("prenom") or "").strip()
        # NOM en gras (auto-shrink si trop long), puis prénom / matière
        self.set_text_color(*(GREEN if is_titulaire else DARK))
        size = self._fit_size(nom, maxw, base=9, min_size=6, style="B")
        self.set_font("inter", "B", size)
        self.set_xy(cx-maxw/2, y)
        self.cell(maxw, 4, nom, align="C")
        if kind == "teacher":
            mat = (item.get("matiere") or "").strip()
            if mat:
                self.set_text_color(*GREEN)
                s2 = self._fit_size(mat, maxw, base=8, min_size=6)
                self.set_font("inter", "B", s2)
                self.set_xy(cx-maxw/2, y+4.2)
                self.cell(maxw, 3.5, mat, align="C")
        else:
            if prenom:
                self.set_text_color(*GREY)
                s2 = self._fit_size(prenom, maxw, base=8, min_size=6)
                self.set_font("inter", "", s2)
                self.set_xy(cx-maxw/2, y+4.2)
                self.cell(maxw, 3.5, prenom, align="C")

    # =====================================================================
    #  PIED DE PAGE
    # =====================================================================
    def _render_footer(self):
        cd = self.data.get("classroom_data", {})
        yr = self.data.get("school_year", "")
        self.set_draw_color(230, 235, 240)
        self.set_line_width(0.2)
        self.line(self.MX, self.PH-8, self.PW-self.MX, self.PH-8)
        self.set_font("inter", "", 7)
        self.set_text_color(*GREY)
        left = f"Omega School Manager • Album de classe • {cd.get('nom','')} {yr}"
        self.set_xy(self.MX, self.PH-7)
        self.cell(150, 4, left, align="L")
        right = f"Page {self.page_no()} / {{nb}}"
        self.set_xy(self.PW-self.MX-50, self.PH-7)
        self.cell(50, 4, right, align="R")

    # =====================================================================
    #  HELPERS IMAGE
    # =====================================================================
    def _rounded_image(self, src_img, w_px, h_px, radius, border_col, border_w, badge=None):
        """Cadre arrondi + bordure sans débord, APLATI SUR FOND BLANC (couleur
        du fond de page) -> exportable en JPEG léger. Renvoie une Image RGB.
        Un seul resize, directement à la taille intérieure (gain de temps)."""
        out = Image.new("RGBA", (w_px, h_px), (0, 0, 0, 0))
        od = ImageDraw.Draw(out)
        # 1) bordure = rectangle arrondi PLEIN (tout le cadre, couleur de bordure)
        od.rounded_rectangle([0, 0, w_px-1, h_px-1], radius=radius, fill=border_col)
        # 2) photo collée EN RETRAIT de border_w, masque de rayon réduit
        inset = border_w
        inner_w, inner_h = w_px-2*inset, h_px-2*inset
        inner_r = max(1, radius-inset)
        photo_in = src_img.convert("RGB").resize((inner_w, inner_h), Image.LANCZOS)
        mask = Image.new("L", (inner_w, inner_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, inner_w-1, inner_h-1], radius=inner_r, fill=255)
        out.paste(photo_in, (inset, inset), mask)
        # 3) masque global arrondi (coins extérieurs nets)
        gmask = Image.new("L", (w_px, h_px), 0)
        ImageDraw.Draw(gmask).rounded_rectangle([0, 0, w_px-1, h_px-1], radius=radius, fill=255)
        out.putalpha(gmask)

        if badge:
            bh = int(h_px*0.13)
            band = Image.new("RGBA", (w_px, bh), (GREEN[0], GREEN[1], GREEN[2], 235))
            bd = ImageDraw.Draw(band)
            try:
                from PIL import ImageFont
                fnt = ImageFont.truetype(self._inter_bold_path, int(bh*0.46)) \
                      if self._inter_bold_path else ImageFont.load_default()
            except Exception:
                from PIL import ImageFont
                fnt = ImageFont.load_default()
            bb = bd.textbbox((0, 0), badge, font=fnt)
            bd.text(((w_px-(bb[2]-bb[0]))//2, (bh-(bb[3]-bb[1]))//2 - bb[1]), badge, font=fnt, fill="white")
            bm = Image.new("L", (w_px, bh), 0)
            ImageDraw.Draw(bm).rounded_rectangle([0, -radius, w_px-1, bh-1], radius=inner_r, fill=255)
            out.paste(band, (0, h_px-bh), bm)

        # 4) APLATIR sur fond blanc (= fond de page) : les coins deviennent
        # blancs opaques, invisibles sur la page blanche -> JPEG possible.
        flat = Image.new("RGB", (w_px, h_px), (255, 255, 255))
        flat.paste(out, (0, 0), out)
        return flat

    def _load_photo(self, item, kind, sexe):
        """Renvoie une source image exploitable par resize_func.
        Photo via URL (déjà gérée par resize_image dans OSM) sinon placeholder."""
        url = item.get("photo")
        if url:
            return url   # resize_image sait ouvrir une URL (comme dans le reste d'OSM)
        return self._placeholder_path(kind, sexe)

    def _placeholder_path(self, kind, sexe):
        if kind == "teacher":
            name = "default_enseignant_f.png" if sexe == "F" else "default_enseignant_h.png"
        else:
            name = "default_eleve_fille.png" if sexe == "F" else "default_eleve_garcon.png"
        return os.path.join(self.static_root, "image", "album", name)

    def _placeholder_image(self, kind, sexe):
        p = self._placeholder_path(kind, sexe)
        try:
            return Image.open(p)
        except Exception:
            return Image.new("RGB", (300, 400), PHBG)

    def _get_logo_bytes(self):
        if self._logo_bytes is not None:
            return self._logo_bytes or None
        sd = self.data.get("school_data", {})
        url = sd.get("logo")
        if not url:
            self._logo_bytes = b""
            return None
        try:
            # logo via URL : on précharge une fois en bytes (évite "seek of closed file")
            if self.resize_func:
                buf = self.resize_func(url, new_width=200)   # léger
                self._logo_bytes = buf.getvalue()
            else:
                self._logo_bytes = url   # laisser fpdf gérer si chemin local
        except Exception:
            self._logo_bytes = b""
        return self._logo_bytes or None

    # =====================================================================
    #  HELPERS TEXTE
    # =====================================================================
    def _centered(self, txt, y, cx, h=5):
        if not txt:
            return
        w = self.get_string_width(txt)
        self.set_xy(cx - w/2, y)
        self.cell(w, h, txt, align="C")

    def _fit_size(self, text, max_w, base, min_size, style=""):
        """Réduit la taille de police jusqu'à ce que le texte tienne dans max_w."""
        if not text:
            return base
        size = base
        self.set_font("inter", style, size)
        while self.get_string_width(text) > max_w - 2 and size > min_size:
            size -= 0.1
            self.set_font("inter", style, size)
        return size


class Statistiques(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='L')
        add_fonts(self)
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=6)
        self.set_font('inter', '', 8)
        self.data = kwargs.pop('data')
        self.school = self.data['school_data']
        self.add_page()
        base_header(self, mode='Pa')
        base_infos(self, f"STATISTIQUES {self.data['trimestre']}", self.data['effectif'], self.data['filles'],
                   self.data['garcons'], self.data['redoublants'], self.data['label'], mode='Pa', year=self.data['annee'])
        self.stats_table()
        self.stats_summary()

    def stats_summary(self):
        """Bloc de synthèse affiché sous le tableau principal"""
        self.ln(2)

        is_global = self.data['label'] == "Global"

        # Données selon le mode
        if is_global:
            items_left = [
                ("Meilleur élève", self.data.get('max_std'), self.data.get('max')),
                ("Élève le plus faible", self.data.get('min_std'), self.data.get('min')),
            ]
            items_mid = [
                ("Moyenne la plus élevée", self.data.get('max_clsmg')),
                ("Moyenne la plus faible", self.data.get('min_clsmg')),
            ]
            items_right = [
                ("Taux de réussite le plus élevé", self.data.get('max_clst')),
                ("Taux de réussite le plus faible", self.data.get('min_clst')),
            ]
        else:
            items_left = [
                ("Premier de la classe", self.data.get('max_std'), self.data.get('max')),
                ("Dernier de la classe", self.data.get('min_std'), self.data.get('min')),
            ]
            items_mid = None
            items_right = None

        col_widths_global = (95, 95, 95)
        col_widths_class = (142.5, 142.5)
        col_widths = col_widths_global if is_global else col_widths_class

        # Alternatives couleurs de fond :
        # (230, 245, 235) → vert menthe très doux
        # (245, 235, 255) → lavande très pâle
        # (255, 243, 230) → pêche très doux
        # (235, 245, 255) → bleu ciel très pâle
        BG_COLOR = (242, 240, 236)

        table = Table(self, line_height=3.7, col_widths=col_widths, text_align="LEFT", markdown=True)

        def make_cell(tr, label_top, value):
            self.set_fill_color(*BG_COLOR)
            text = f"__{label_top}__\n**{value}**"
            tr.cell(text, padding=(0, 2))

        if is_global:
            # Ligne 1 : meilleurs
            tr = table.row()
            make_cell(tr,
                      "Meilleur élève", f"{items_left[0][1]} ({items_left[0][2]})")
            make_cell(tr,
                      "Moyenne générale la plus élevée", items_mid[0][1])
            make_cell(tr,
                      "Taux de réussite le plus élevé", items_right[0][1])

            # Ligne 2 : plus faibles
            tr = table.row()
            make_cell(tr,
                      "Élève le plus faible", f"{items_left[1][1]} ({items_left[1][2]})")
            make_cell(tr,
                      "Moyenne générale la plus faible", items_mid[1][1])
            make_cell(tr,
                      "Taux de réussite le plus faible", items_right[1][1])
        else:
            tr = table.row()
            make_cell(tr, "Premier de la classe", f"{items_left[0][1]} - Moyenne : {items_left[0][2]}")
            make_cell(tr, "Dernier de la classe", f"{items_left[1][1]} - Moyenne : {items_left[1][2]}")

        table.render()

    def stats_table(self):
        self.set_font_size(8)
        self.ln()
        col_widths = (70, 27, 27, 27, 31, 22, 27, 27, 27)

        table = Table(self, line_height=3.7, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE, num_heading_rows=2)

        th = table.row()
        self.set_fill_color(242, 240, 236)
        cls_or_mat = "CLASSE" if self.data['label'] == "Global" else "MATIÈRE"
        ens_or_tit = "\nTITULAIRE" if self.data['label'] == "Global" else "\nENSEIGNANT"
        th.cell(f"**{cls_or_mat}**{ens_or_tit}", rowspan=2, padding=(0.5, 0), align="L")
        th.cell("**TAUX DE RÉUSSITE**", colspan=3, padding=(0.5, 0))
        th.cell("**[MIN - MAX]**", rowspan=2, padding=(0.5, 0))
        th.cell("**MOY GEN**", rowspan=2, padding=(0.5, 0))
        th.cell("**TAUX DE PARTICIPATION**", colspan=3, padding=(0.5, 0))

        th = table.row()
        th.cell("**FILLES**", padding=(0.5, 0))
        th.cell("**GARÇONS**", padding=(0.5, 0))
        th.cell("**TOTAL**", padding=(0.5, 0))
        th.cell("**FILLES**", padding=(0.5, 0))
        th.cell("**GARÇONS**", padding=(0.5, 0))
        th.cell("**TOTAL**", padding=(0.5, 0))

        tr = table.row()
        self.set_fill_color(255, 248, 200)
        tr.cell("**Global**", align="L")
        self.colored_cell(tr, value=self.data['pcf'],
                          text=f"**{str(self.data['pcf']) + '%' if self.data['nbfe'] else '/'}**\n{self.data['nbfr']} / {self.data['nbfe']}", percent=True)
        self.colored_cell(tr, value=self.data['pcg'],
                          text=f"**{str(self.data['pcg']) + '%' if self.data['nbge'] else '/'}**\n{self.data['nbgr']} / {self.data['nbge']}", percent=True)
        self.colored_cell(tr, value=self.data['taux'],
                          text=f"**{self.data['taux']}%**\n{self.data['nbr']} / {self.data['nbe']}", percent=True)
        tr.cell(f"**{self.data['min_max']}**")
        self.colored_cell(tr, value=self.data['moyenne_generale'],
                          text=f"**{self.data['moyenne_generale']}**", percent=False)
        self.colored_cell(tr, value=self.data['ppf'],
                          text=f"{str(self.data['ppf']) + '%' if self.data['filles'] else '/'}\n{self.data['nbfe']} / {self.data['filles']}", percent=True)
        self.colored_cell(tr, value=self.data['ppg'],
                          text=f"{str(self.data['ppg']) + '%' if self.data['garcons'] else '/'}\n{self.data['nbge']} / {self.data['garcons']}", percent=True)
        self.colored_cell(tr, value=self.data['ppt'],
                          text=f"{self.data['ppt']}%\n{self.data['nbe']} / {self.data['effectif']}", percent=True)

        self.set_fill_color(0)
        stats = self.data['classrooms_data'] if self.data['label'] == "Global" else self.data['matieres_data']

        for stat in stats:
            tr = table.row()
            tr.cell(f"**{stat['label']}**\n{stat['titulaire'] if self.data['label'] == 'Global' else stat['enseignant']}", align="L")
            self.colored_cell(tr, value=stat['pcf'],
                              text=f"**{str(stat['pcf']) + '%' if stat['nbfe'] else '/'}**\n{stat['nbfr']} / {stat['nbfe']}", percent=True)
            self.colored_cell(tr, value=stat['pcg'],
                              text=f"**{str(stat['pcg']) + '%' if stat['nbge'] else '/'}**\n{stat['nbgr']} / {stat['nbge']}", percent=True)
            taux = stat['taux'] if self.data['label'] == "Global" else stat['pct']
            nbe = stat['nbe'] if self.data['label'] == "Global" else stat['nbte']
            nbr = stat['nbr'] if self.data['label'] == "Global" else stat['nbtr']
            self.colored_cell(tr, value=taux,
                              text=f"**{taux}%**\n{nbr} / {nbe}", percent=True)
            tr.cell(f"**{stat['min_max']}**")
            moyenne_generale = stat['moyenne_generale'] if self.data['label'] == "Global" else stat['moyenne']
            self.colored_cell(tr, value=moyenne_generale, text=f"**{moyenne_generale}**", percent=False)
            filles = self.data['filles'] if self.data['label'] != "Global" else stat['filles']
            garcons = self.data['garcons'] if self.data['label'] != "Global" else stat['garcons']
            effectif = self.data['effectif'] if self.data['label'] != "Global" else stat['effectif']
            self.colored_cell(tr, value=stat['ppf'],
                              text=f"{str(stat['ppf']) + '%' if filles else '/'}\n{stat['nbfe']} / {filles}", percent=True)
            self.colored_cell(tr, value=stat['ppg'],
                              text=f"{str(stat['ppg']) + '%' if garcons else '/'}\n{stat['nbge']} / {garcons}", percent=True)
            self.colored_cell(tr, value=stat['ppt'],
                              text=f"{stat['ppt']}%\n{nbe} / {effectif}", percent=True)
        table.render()

    def colored_cell(self, tr, value, text, percent, **kwargs):
        if type(value) in [int, float]:
            if (percent and value < 50) or (not percent and value < 10):
                self.set_text_color(210, 31, 60)
        tr.cell(text, **kwargs)
        self.set_text_color(0)

    def footer(self):
        self.set_y(-6)
        self.set_draw_color(230, 235, 240)
        self.set_text_color(*GREY)
        self.set_line_width(0.2)
        self.line(6, 204, 291, 204)
        self.set_font('inter', 'I', 7)
        self.cell(142.5, 6, "Document généré par Oméga School Manager", align='L')
        self.cell(142.5, 6, f"STATISTIQUES {self.data['trimestre'].title()} • {self.data['label']} • Page "
                             f"{self.page_no()}/{{nb}}", align='R')


class PDFMarksSheet(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__()
        add_fonts(self)
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=10)
        self.set_font('inter', '', 8)
        self.annee = kwargs['annee']
        self.classroom = kwargs['classroom']
        self.school = kwargs['school']
        self.add_page()
        base_header(self)
        self.infos()
        self.sheet()

    def sheet(self):
        self.ln()
        self.set_font_size(9)
        col_widths = [10, 24, 70, 10, 14, 14, 14, 14, 14, 14]
        header = ["N°", "Identifiant", "Nom(s) et Prénom(s)", "Sex", "Eval1", "Eval2", "Eval3",
                  "Eval4", "Eval5", "Eval6"]

        table = Table(self, line_height=6, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(242, 240, 236)
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
        students = self.classroom.students
        effectif = students.count()
        filles = students.filter(sexe="Fille").count()
        garcons = effectif - filles
        redoublants = students.filter(statut="Redoublant").count()
        base_infos(self, 'FICHE DE NOTES', effectif, filles, garcons, redoublants, self.classroom.code, year=self.data['annee'])
        self.ln()
        self.cell(82, 7, "Enseignant(e) : --                                                  --",
                  align='L', markdown=True)
        self.cell(40, 7, f"Coefficient : --                    --", align='C', markdown=True)
        self.cell(76, 7, f"Matière : --                                                      --",
                  align='R', markdown=True)

    def footer(self):
        self.set_y(-6)
        self.set_draw_color(230, 235, 240)
        self.set_text_color(*GREY)
        self.set_line_width(0.2)
        self.line(6, 291, 204, 291)
        self.set_font('inter', 'I', 7)
        self.cell(99, 6, "Document généré par Oméga School Manager", align='L')
        self.cell(99, 6, f"FICHE DE NOTES • {self.classroom.code} • Page {self.page_no()}/{{nb}}", align='R')


class ClassroomsLists(LoggedAdminView):
    @staticmethod
    def build_pdf_or_reason(classroom, annee, school):
        reason = check_notes(classroom, None, marks_sheet=True)
        if reason is not None:
            return reason  # -> sautée (ZIP) ou message d'erreur (une classe)

        filename = f"Liste des élèves {classroom.code}.pdf"
        cls_list = ClassroomList(classroom=classroom, annee=annee, school=school)
        return cls_list

    def post(self, *args, **kwargs):
        annee = self.request.user.school.establishment_year
        school = User.objects.select_related('school').get(id=self.request.user.id).school
        classrooms = ClassRoom.objects.select_related('classe').prefetch_related('students').order_by_niveau()

        def build(clsrm):
            return self.build_pdf_or_reason(clsrm, annee, school)

        def archive_for(clsrm):
            from archives.models import DocType, ArchiveRef
            return ArchiveRef(self.request.user.school, DocType.CLASS_LIST, clsrm, user=self.request.user)

        def namer(clsrm):
            return f"{clsrm.code} Liste des élèves.pdf"

        return zip_pdfs_response(
            build_pdf_for_classroom=build,
            classrooms=classrooms,
            zip_filename=f"Liste des élèves - Toutes les classes.zip",
            per_file_namer=namer,
            archive_for=archive_for,
        )


@logged_admin_view
def classroom_list(request, id):
    from archives.models import DocType, ArchiveRef
    annee = self.request.user.school.establishment_year
    classroom = (
        ClassRoom.objects.prefetch_related('students').
        get(pk=id))
    filename = f"Liste des élèves {classroom.code}.pdf"
    archive = ArchiveRef(request.user.school, DocType.CLASS_LIST, classroom, user=request.user)
    hit = archive.response(filename)
    if hit:
        return hit
    cls_list = ClassroomList(classroom=classroom, annee=annee, school=request.user.school)
    return pdf_response(cls_list, filename, archive)


class ClassroomList(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__()
        add_fonts(self)
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=6)
        self.set_font('inter', '', 8)
        self.annee = kwargs['annee']
        self.classroom = kwargs['classroom']
        self.school = kwargs['school']
        self.set_title(f"Liste des élèves {self.classroom.code}")
        self.add_page()
        base_header(self)
        students = self.classroom.students
        effectif = students.count()
        filles = students.filter(sexe="Fille").count()
        garcons = effectif - filles
        redoublants = students.filter(statut="Redoublant").count()
        base_infos(self, "LISTE DES ÉLÈVES", effectif, filles, garcons, redoublants, self.classroom.code, year=self.data['annee'])
        self.list()

    def list(self):
        self.ln()
        col_widths = [10, 24, 75, 25, 41, 11.5, 11.5]
        header = ["N°", "Identifiant", "Nom(s) et Prénom(s)", "Né(e) le", "A", "Sexe", "Red?"]

        table = Table(self, line_height=5, col_widths=col_widths, text_align="CENTER", markdown=True,
                      repeat_headings=TableHeadingsDisplay.ON_TOP_OF_EVERY_PAGE)
        th = table.row()
        self.set_fill_color(242, 240, 236)
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

    def footer(self):
        self.set_y(-6)
        self.set_draw_color(230, 235, 240)
        self.set_text_color(*GREY)
        self.set_line_width(0.2)
        self.line(6, 291, 204, 291)
        self.set_font('inter', 'I', 7)
        self.cell(100, 6, "Document généré par Oméga School Manager", align='L')
        self.cell(98, 6, f"LISTE DES ÉLÈVES • {self.classroom.code} • Page {self.page_no()}/{{nb}}", align='R')


class ClassroomTimeTable(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='L')
        add_fonts(self)
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=12)
        self.set_font('inter', '', 8)
        self.data = kwargs.pop('data')
        self.classroom = self.data['classroom'] if 'classroom' in self.data.keys() else ""
        self.school = self.data['school']
        self.add_page()
        base_header(self, mode='Pa')
        self.infos()
        self.timetable()

    def timetable(self):
        self.ln()
        col_widths = (35, 50, 50, 50, 50, 50)
        header = ("HORAIRES", "LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI")

        table = Table(self, line_height=4, col_widths=col_widths, text_align="CENTER", markdown=True)
        th = table.row()
        self.set_fill_color(242, 240, 236)
        padding = (3, 0, 3, 0)
        for head in header:
            th.cell(f"**{head}**", padding=(2.5, 0, 2.5, 0))
        if 'tranches_horaires' in self.data.keys():
            for tranche in self.data['tranches_horaires']:
                row = table.row()
                self.set_fill_color(242, 240, 236)
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
                self.set_fill_color(242, 240, 236)
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
                            row.cell(f"**{programmation['matiere']}**__{enseignant}__", rowspan=programmation['rowspan'])
        table.render()
        self.ln(1)
        self.set_x(14)
        par = ("Le Surveillant Général" if self.data['school'].type_ets in (
            "CES", "CES Bilingue", "CETIC") else "Le Censeur") if self.data['school'].type_ets != "Collège" else "Le Chargé des Études"
        self.cell(134.5, 8, f"**{par}**", align='L', markdown=True)
        self.cell(134.5, 8, f"Fait à {self.data['school'].localite}, le --                    --", align='R', markdown=True)
        self.ln()
        self.cell(269, 8, f"**Le {self.data['school'].chef}**", align='R', markdown=True)

    def infos(self):
        self.set_font_size(15)
        self.ln(3)
        self.cell(285, 7, f"**EMPLOI DU TEMPS**", align='C', markdown=True)
        self.set_font_size(8)
        self.ln()
        classroom = (
            self.data['classroom'] if 'classroom' in self.data.keys()
            else "--                                        --")
        self.cell(142.5, 7, f"**Classe : **{classroom}", align='L', markdown=True)
        self.cell(142.5, 7, f"**Année scolaire : {self.data['annee']}**", align='R', markdown=True)

    def footer(self):
        self.set_y(-6)
        self.set_draw_color(230, 235, 240)
        self.set_text_color(*GREY)
        self.set_line_width(0.2)
        self.line(6, 204, 294, 204)
        self.set_font('inter', 'I', 7)
        self.cell(142.5, 6, "Document généré par Oméga School Manager", align='L')
        title = "EMPLOI DU TEMPS" + f" • {self.data['classroom']}" if 'classroom' in self.data.keys() else ""
        self.cell(142.5, 6, f"{title}", align='R')


class StaffMemberTimeTable(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='L')
        add_fonts(self)
        self.alias_nb_pages()
        self.set_margins(6, 6, 6)
        self.set_auto_page_break(auto=True, margin=6)
        self.set_font('inter', '', 8)
        self.data = kwargs.pop('data')
        self.school = self.data['school']
        self.add_page()
        base_header(self, mode='Pa')
        self.infos()
        self.timetable()

    def timetable(self):
        self.ln()
        current_y = self.y

        recap_table = Table(self, width=45, line_height=7, col_widths=(32, 13), text_align="CENTER", markdown=True,
                            align='L')
        th = recap_table.row()
        self.set_fill_color(242, 240, 236)
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
                    if i == 18:
                        break
                if i == 18:
                    break
        else:
            total = ""
        for _ in range(18 - i):
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
        self.set_fill_color(242, 240, 236)
        padding = (2.5, 0, 2.5, 0)
        for head in header:
            th.cell(f"**{head}**", padding=(2, 0, 2, 0))
        self.set_fill_color(0)
        if 'tranches_horaires' in self.data.keys():
            for tranche in self.data['tranches_horaires']:
                row = table.row()
                self.set_fill_color(242, 240, 236)
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
                self.set_fill_color(242, 240, 236)
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
                            row.cell(f"**{truncate_str(self, programmation['classes'], 37)}**__{matiere}__",
                                     rowspan=programmation['rowspan'])
        table.render()
        self.ln(1)
        self.set_x(57)
        par = ("Le Surveillant Général" if self.data['school'].type_ets in (
            "CES", "CES Bilingue", "CETIC") else "Le Censeur") if self.data['school'].type_ets != "Collège" else "Le Chargé des Études"
        self.cell(113, 8, f"**{par}**", align='L', markdown=True)
        self.cell(113, 8, f"Fait à {self.data['school'].localite}, le --                    --", align='R', markdown=True)
        self.ln()
        self.set_x(57)
        self.cell(226, 8, f"**Le {self.data['school'].chef}**", align='R', markdown=True)

    def infos(self):
        self.set_font_size(15)
        self.ln(3)
        self.cell(285, 7, f"**EMPLOI DU TEMPS INDIVIDUEL**", align='C', markdown=True)
        self.set_font_size(8)
        self.ln()
        nom, grade = (f"**{self.data['infos']['nom']}**", self.data['infos']['grade']) if 'infos' in self.data.keys() \
            else (f"--{' ' * 165}--", f"--{' ' * 70}--")
        matieres = ""
        if 'recap_and_total' in self.data.keys():
            matieres = ""
            for elt in self.data['recap_and_total'][0]:
                matieres += elt['matiere']
                if elt != self.data['recap_and_total'][0][-1]:
                    matieres += ", "
        matieres = f"**{matieres}**" if matieres else f"--{' ' * 159}--"
        grade = f"**{grade}**" if grade not in ["", f"--{' ' * 70}--"] else f"--{' ' * 70}--"
        self.set_x(10)
        self.cell(202, 7, f"NOM(S) ET PRÉNOM(S) : {nom}", align='L', markdown=True)
        self.cell(75, 7, f"Grade : {grade}", align='L', markdown=True)
        self.ln()
        self.set_x(10)
        self.cell(202, 7, f"MATIÈRE(S) ENSEIGNÉE(S) : {matieres}", align='L', markdown=True)
        self.cell(75, 7, f"NOMBRE D'HEURES DUES : --{" " * 36}--", align='L', markdown=True)

    def footer(self):
        self.set_y(-6)
        self.set_draw_color(230, 235, 240)
        self.set_text_color(*GREY)
        self.set_line_width(0.2)
        self.line(6, 204, 294, 204)
        self.set_font('inter', 'I', 7)
        self.cell(142.5, 6, "Document généré par Oméga School Manager", align='L')
        self.cell(142.5, 6, f"{self.data['filename']}", align='R')
