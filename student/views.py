# Create your views here.
import os

from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.decorators.http import condition
from django.views.generic import DeleteView, DetailView
from django.forms.models import model_to_dict
from django.db import IntegrityError
from django.conf import settings
from fpdf import FPDF
from fpdf.enums import VAlign
from fpdf.table import Table
from babel.dates import format_date

from note.models import Note, Enseignements
from classroom.models import ClassRoom
from note.views import ReportCard
from .forms import StudentForm, ParentForm, DForm
from osm.forms import SearchForm
from osm.forms import SearchForm
from note.forms import CheckForm, MarksForm, SelectForm
from .models import Parent, Student, StudentDiscipline
from osm.utils import formated_float, message, logged_admin_view, LoggedAdminView, ListView, DeleteView, ADetailView, \
    with_users_school_schema, school_year, generate_temp_file, resize_image
from pandas import DataFrame, read_excel, ExcelWriter
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Font
from openpyxl import load_workbook
from io import BytesIO
from datetime import datetime
from os import path


class StudentsIdCards(LoggedAdminView):
    template_name = "edit_marks.html"
    title = "Cartes d'Identité Scolaire"

    def get(self, *args, **kwargs):
        select_form = SelectForm(context={
            "request": self.request, 'trim': False, 'marks_sheet': True, 'enseignements': None})
        context = {'marks_sheet': True, 'csi': True, 'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        empty_csi = True if 'csi_checkbox' in self.request.POST.keys() else False
        data = {'annee': school_year(), 'school_data': self.request.user.school.school_to_dict()}
        filename = self.title
        if not empty_csi:
            classroom = (
                ClassRoom.objects.prefetch_related('students__pere', 'students__mere').
                get(pk=int(self.request.POST['classroom'])))
            if classroom.students.exists():
                data['students'] = list(classroom.students.order_by('nom', 'prenom'))
                filename += f" {classroom.code}"
            else:
                return JsonResponse({
                    'success': False,
                    'message': "Aucun élève dans cette salle de classe"
                })
        temp_filename, final_filename = generate_temp_file(f"{filename}.pdf", StudentsIdentityCards(data=data))
        url = reverse("download_and_delete", args=[temp_filename])
        return JsonResponse({
            'success': True,
            'url': url,
            'display': final_filename
        })


# Exportation de la liste des élèves dans un fichier Excel
@logged_admin_view
def students_export(request, cls_id):
    queryset = Student.objects.select_related('classe').order_by_classroom_level()
    classroom = None
    columns = ['Matricule', 'Noms', 'Prénoms', 'Date de naissance', 'Lieu de Naissance', 'Sexe', 'Statut']
    if cls_id:
        classroom = ClassRoom.objects.get(pk=cls_id)
        students = (
            queryset.filter(classe_id=classroom.pk)
            .values('unique_id', 'nom', "prenom", 'date_naissance', 'lieu_naissance', 'sexe', 'statut')
        )
        details = f"Effecif : {classroom.effectif}, {classroom.kind_numbers}"
    else:
        students = (
            queryset.values('unique_id', 'nom', "prenom", 'date_naissance', 'lieu_naissance', 'sexe', 'classe__code',
                            'statut')
        )
        columns.insert(-1, 'Classe')
        details = f"Effectif : {request.user.school.effectif}, {request.user.school.kind_numbers}"
    data_frame = DataFrame(students)
    data_frame.columns = columns
    buffer  = BytesIO()
    with ExcelWriter(buffer, engine='openpyxl') as writer:
        data_frame.to_excel(writer, index=False, startrow=3, sheet_name="Élèves")

    buffer.seek(0)
    workbook = load_workbook(buffer)
    worksheet = workbook.active
    title = "Liste des élèves"
    center = Alignment(horizontal='center', vertical='center')
    if cls_id:
        title += f" de {classroom.code}"
        worksheet.merge_cells('A1:G1')
        worksheet.merge_cells('A2:G2')
        worksheet.merge_cells('A3:G3')
    else:
        worksheet.merge_cells('A1:H1')
        worksheet.merge_cells('A2:H2')
        worksheet.merge_cells('A3:H3')
        worksheet.column_dimensions['H'].width = 10
    worksheet['A1'] = f"{request.user.school.nom} / {request.user.school.name}"
    worksheet['A1'].font = Font(size=15, bold=True)
    worksheet['A1'].alignment = center
    worksheet.row_dimensions[1].height = 30
    worksheet['A2'] = title
    worksheet['A2'].font = Font(size=13, italic=True)
    worksheet['A2'].alignment = center
    worksheet.row_dimensions[2].height = 20
    worksheet['A3'] = details
    worksheet['A3'].font = Font(size=12, italic=True)
    worksheet['A3'].alignment = center

    worksheet.column_dimensions['A'].width = 12
    worksheet.column_dimensions['B'].width = 25
    worksheet.column_dimensions['C'].width = 20
    worksheet.column_dimensions['D'].width = 20
    worksheet.column_dimensions['E'].width = 20
    worksheet.column_dimensions['F'].width = 8
    worksheet.column_dimensions['G'].width = 12

    for col_mumber in range(1, len(data_frame.columns)+1):
        col_letter = get_column_letter(col_mumber)
        cell = worksheet[f"{col_letter}4"]
        cell.font = Font(bold=True)
        cell.alignment = center

    final_buffer = BytesIO()
    workbook.save(final_buffer)
    final_buffer.seek(0)

    response = HttpResponse(final_buffer.getvalue(),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename={title}.xlsx'
    return response


# Importation d'une liste d'élèves à partir d'un fichier excel
class StudentsImport(LoggedAdminView):
    title = "Importation d'une liste d'Élèves"
    template_name = "students_import.html"
    required_fiels = ['matricule', 'noms', 'prénoms', 'date de naissance', 'lieu de naissance', 'sexe']

    def get(self, *args, **kwargs):
        return render(self.request, self.template_name, context={'title': self.title})

    def post(self, *args, **kwargs):
        rapport = list
        file = self.request.FILES.get('file')
        if file:
            rapport = self.import_students(file)
        return render(self.request, self.template_name, context={'title': self.title, 'rapport': rapport})

    # Détecter la ligne des en-têtes dans la 10 premières lignes maximum
    def detect_header_row(self, df: DataFrame):
        for i in range(min(10, len(df))):
            row = df.iloc[i].fillna('').astype(str).str.lower()
            if all(field in row.tolist() for field in self.required_fiels):
                return i
        return None

    def import_students(self, file):
        rapport = list()
        required_fields = ['matricule', 'noms', 'date de naissance', 'lieu de naissance', 'sexe']
        try:
            df = read_excel(file, header=None, engine="openpyxl")
            header_row = self.detect_header_row(df)
            if not header_row:
                rapport.append([False, f"Entêtes introuvables : {self.required_fiels}"])
            else:
                from osm.utils import one_escape, is_alphanumeric
                from pandas import isnull, to_datetime, NaT, notna
                df.columns = df.iloc[header_row].fillna('').astype(str).str.lower()
                df = df[(header_row + 1):].reset_index(drop=True)
                saved_lines = 0
                for index, line in df.iterrows():
                    line_number = header_row + 2 + index
                    if line.isnull()[required_fields].any():
                        empty_fields = line[required_fields].isnull()
                        empty_fields_list = empty_fields[empty_fields].index.tolist()
                        if len(empty_fields_list) == 1:
                            error = f"Valeur manquante d'un champ obligatoire : {empty_fields_list[0]}"
                        else:
                            error = f"Valeur manquante de {len(empty_fields_list)} champs obligatoires : " \
                                    f"{empty_fields_list}"
                        rapport.append([False, f"Ligne {line_number} : {error}"])
                    else:
                        matricule = line['matricule']
                        matricule_str = str(matricule)
                        if len(matricule_str) != 9 or not matricule_str.isnumeric():
                            rapport.append([False, f"Ligne {line_number} : Le matricule doit être une suite de 9 "
                                                   f"chiffres"])
                            continue
                        if Student.objects.filter(unique_id=matricule).exists():
                            rapport.append([False, f"Ligne {line_number} : Ce matricule a déjà été enregistré pour un "
                                                   f"autre élève"])
                            continue
                        nom = one_escape(str(line['noms'])).upper()
                        if not is_alphanumeric(nom):
                            rapport.append([False, f"Ligne {line_number} : Le nom doit être une chaîne alphanumérique"])
                            continue
                        prenom = one_escape(str(line['prénoms'])).title() if not isnull(line.get('prénoms')) else ''
                        if not is_alphanumeric(prenom):
                            rapport.append([False, f"Ligne {line_number} : Le prénom doit être une chaîne "
                                                   f"alphanumérique"])
                            continue
                        date_naissance = to_datetime(line['date de naissance'], errors='coerce').date()
                        if date_naissance is NaT:
                            rapport.append([False, f"Ligne {line_number} : La date de naissance est incorrecte"])
                            continue
                        now = datetime.now().year
                        min_year, max_year = now - 30, now - 8
                        if not (min_year < date_naissance.year < max_year):
                            rapport.append([False, f"Ligne {line_number} : L'année de naissance doit être comprise "
                                                   f"entre {min_year} et {max_year}"])
                            continue
                        if Student.objects.filter(nom=nom, prenom=prenom, date_naissance=date_naissance).exists():
                            rapport.append([False, f"Ligne {line_number} : Un(e) élève du même nom et né le même jour "
                                                   f"a déjà été enregistré"])
                            continue
                        lieu_naissance = str(line['lieu de naissance']).title()
                        sexe = ''
                        if str(line['sexe']).lower() in ["fille", "féminin", "femme", "f"]:
                            sexe = "Fille"
                        elif str(line['sexe']).lower() in ["garçon", "masculin", "homme", "h", "g", 'm']:
                            sexe = "Garçon"
                        if not sexe:
                            rapport.append([False, f"Ligne {line_number} : La valeur du sexe est incorrecte"])
                            continue
                        classe_id = None
                        if 'classe' in df.columns and notna(line['classe']):
                            try:
                                classe_id = ClassRoom.objects.get(code__iexact=str(line['classe']).strip()).id
                            except:
                                rapport.append([False, f"Ligne {line_number} : La classe indiquée n'existe pas"])
                                continue
                        statut = "Nouveau"
                        if 'statut' in df.columns and notna(line['statut']):
                            if str(line['statut']).lower() in ["redoublant", "redoublante", "r"]:
                                statut = "Redoublant"
                        Student.objects.create(nom=nom, prenom=prenom, statut=statut, sexe=sexe, classe_id=classe_id,
                                               date_naissance=date_naissance, lieu_naissance=lieu_naissance,
                                               unique_id=matricule)
                        saved_lines += 1
                if saved_lines:
                    rapport.insert(0, [True,f"{'Une ligne insérée' if saved_lines == 1 else f'{saved_lines} lignes insérées'} avec succès"])
                elif not rapport:
                    rapport.append([False, "Il semble que ce fichier ne contienne aucune donnée d'élève"])
        except:
            rapport.append((False, "Fichier illisible, vérifier qu'il soit bien au format xls, xlsx ou odt"))
        return rapport


# Affichage de la liste des élèves
class Students(ListView):
    model = Student
    template_name = "students_list.html"
    title = "Liste des Élèves"
    objects = "élève(s)"


class Parents(ListView):
    template_name = "parents_list.html"
    title = "Liste des Parents d'Élèves"
    model = Parent
    objects = "parents d'élève(s)"


class StudentAdd(LoggedAdminView):
    template_name = "add_student.html"
    title = "Ajout d'un Élève"

    def get(self, *args, **kwargs):
        student_form = StudentForm(context={'request': self.request})
        context = {"title": self.title, "form": student_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        student_form = StudentForm(self.request.POST, self.request.FILES, context={'request': self.request})
        context = {"title": self.title, "form": student_form}
        if student_form.is_valid():
            student_form.save()
            message(self.request, "Élève ajouté avec succès.")
            return redirect("students")
        return render(self.request, self.template_name, context)


class ParentAdd(LoggedAdminView):
    template_name = "add_parent.html"
    title = "Ajout d'un Parent d'Élève"

    def get(self, *args, **kwargs):
        parent_form = ParentForm(context={'request': self.request})
        context = {"title": self.title, "form": parent_form, "reset": "Tout effacer"}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        parent_form = ParentForm(self.request.POST, context={'request': self.request})
        context = {"title": self.title, "form": parent_form, "reset": "Tout effacer"}
        if parent_form.is_valid():
            parent_form.save()
            message(self.request, "Parent ajouté avec succès.")
            return redirect("parents")
        return render(self.request, self.template_name, context)


class ParentEdit(LoggedAdminView):
    template_name = "add_parent.html"
    title = "Modification des informations"

    def get(self, *args, **kwargs):
        form = ParentForm(context={'request': self.request}, instance=self.get_object())
        return render(self.request, self.template_name, {"title": self.title, "form": form,
                                                         "reset": "Annuler les changements"})

    def get_object(self):
        parent_id = self.kwargs.get("id")
        parents = Parent.objects
        return get_object_or_404(parents, pk=parent_id)

    def post(self, *args, **kwargs):
        instance = self.get_object()
        default = model_to_dict(instance)
        form = ParentForm(self.request.POST, context={'request': self.request}, instance=instance)
        if form.is_valid():
            parent = form.save()
            parent = model_to_dict(parent)
            if parent != default:
                message(self.request, "Informations du parent modifiées avec succès !")
            return redirect("parents")
        return render(self.request, self.template_name, {"form": form, "title": self.title,
                                                         "reset": "Annuler les changements"})


class StudentEdit(LoggedAdminView):
    template_name = "add_student.html"
    title = "Modification des informations"
    nb = "NB : Si vous modifiez la salle de classe d'un élève, toutes ses notes préalablement enregistrées " \
         "seront perdues."

    def get(self, *args, **kwargs):
        form = StudentForm(context={'request': self.request}, instance=self.get_object())
        return render(self.request, self.template_name, {"title": self.title, "form": form, "reset": "Par défaut",
                                                         "nb": self.nb})

    def get_object(self):
        student_id = self.kwargs.get("id")
        students = Student.objects.select_related('classe', 'pere', 'mere')
        return get_object_or_404(students, pk=student_id)

    def post(self, *args, **kwargs):
        default = self.object()
        old_image = default.photo
        form = StudentForm(self.request.POST, self.request.FILES, context={'request': self.request},
                           instance=default)
        default_classroom = default.classe.classe.__str__() if default.classe else None
        if form.is_valid():
            student = form.save()
            image = form.cleaned_data["photo"]
            if old_image and old_image != image:
                if os.path.exists(old_image.path):
                    os.remove(old_image.path)
            """
            TODO
            """
            if student.classe and (student.classe.classe.__str__() != default_classroom):
                notes = Note.objects.filter(eleve=student)
                notes.delete()
            student = model_to_dict(student)
            default = model_to_dict(default)
            if student != default:
                message(self.request, "Élève modifié avec succès.")
            else:
                message(self.request, "Aucune modification effectuée.", msg_type="warning")
            return redirect("students")
        return render(self.request, self.template_name, {"form": form, "title": self.title, "reset": "Par défaut",
                                                         "nb": self.nb})


class ParentDelete(DeleteView):
    success_url = "parents"
    alerte = "des parents d'élèves ?"
    model = Parent
    title = "Suppression d'un Parent d'Élève"
    message = "Parent d'Élève supprimé avec succès."


class StudentDelete(DeleteView):
    success_url = "students"
    alerte = "des élèves ?"
    model = Student
    title = "Suppression d'un Élève"
    message = "Élève supprimé avec succès."


class StudentDetails(ADetailView):
    title = "Détails sur l'Élève"
    template_name = "student_details.html"
    model = Student


class ParentDetails(ADetailView):
    title = "Détails sur le Parent d'Élève"
    template_name = "parent_details.html"
    model = Parent


@with_users_school_schema
def discipline(request):
    def student_list(search):
        students_set = list()
        students_list = Student.objects.filter(Q(unique_id__icontains=search) | Q(nom__icontains=search) |
                                               Q(prenom__icontains=search),
                                               classe__isnull=False).order_by_classroom_level()
        for student in students_list:
            students_set.append(student.dstd)
        return students_set

    students, info, trim = [], "", 0
    search_form = SearchForm(context={'trim': True})
    if request.method == "POST":
        search_form = SearchForm(request.POST or None, context={'trim': True})
        if search_form.is_valid() and search_form.cleaned_data['search']:
            students = student_list(search=search_form.cleaned_data['search'])
            trim = search_form.cleaned_data['trimestre']
            info = (f"{len(students)} élève(s) trouvé(s).", "Aucun(e) élève trouvé")[len(students) == 0]
    context = {'students': students, 'info': info, 'title': "Gestion de la discipline", 'trim': trim,
               'form': search_form}
    return render(request, "discipline.html", context)


class Discipline(LoggedAdminView):
    template_name = "discipline_edit.html"

    # TODO check period
    def check_period(self):
        pass

    def get(self, *args, **kwargs):
        sid, trim = self.kwargs.get('id'), self.kwargs.get('trim')
        student = Student.objects.get(pk=sid)
        std = student.std(trim)
        std_info = f"Données disciplinaires pour le trimestre {trim} de l'élève {student.dstd['nom']}"
        if std:
            dform = DForm(instance=std)
        else:
            dform = DForm()
        context = {'form': dform, 'sid': sid, 'trim': trim, 'std_info': std_info, 'show': True}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        sid, trim = self.kwargs.get('id'), self.kwargs.get('trim')
        student = Student.objects.get(pk=sid)
        std = student.std(trim)
        std_info = f"Données disciplinaires pour le trimestre {trim} de l'élève {student.dstd['nom']}"
        if std:
            dform = DForm(self.request.POST, instance=std, context={'request': self.request})
        else:
            dform = DForm(self.request.POST, context={'request': self.request})
        if dform.is_valid() and dform.has_changed():
            avert, blame, excl = False, False, 0
            cons, absnj = dform.cleaned_data['cons'], dform.cleaned_data['abs'] - dform.cleaned_data['absj']
            if (6 <= absnj <= 9) or (6 <= cons <= 9):
                avert = True
            elif (10 <= absnj <= 14) or (10 <= cons <= 14):
                blame = True
            elif (15 <= absnj <= 18) or (15 <= cons <= 18):
                excl = 3
            elif (19 <= absnj <= 25) or (19 <= cons <= 25):
                excl = 5
            elif (25 <= absnj <= 29) or (25 <= cons <= 29):
                excl = 8
            if std:
                std.avert, std.retards = avert, dform.cleaned_data['retards']
                std.excl, std.excl_def = excl, dform.cleaned_data['excl_def']
                std.blame, std.cons = blame, dform.cleaned_data['cons']
                std.abs, std.absj = dform.cleaned_data['abs'], dform.cleaned_data['absj']
                std.save()
            else:
                dstd = StudentDiscipline(trim=trim, student=student, avert=avert,
                                         excl_def=dform.cleaned_data['excl_def'],
                                         excl=excl, blame=blame, cons=dform.cleaned_data['cons'],
                                         abs=dform.cleaned_data['abs'], absj=dform.cleaned_data['absj'],
                                         retards=dform.cleaned_data['retards'])
                dstd.save()
            message(self.request, "Données enregistrées avec succès.")
        else:
            message(self.request, "Aucune donnée modifiée ou enregistrée.", msg_type="warning")
        context = {'form': dform, 'sid': sid, 'trim': trim, 'std_info': std_info, 'show': False}
        response = render(self.request, self.template_name, context)
        response['HX-Trigger'] = 'AJAXMessages'
        return response


class StudentsIdentityCards(FPDF):

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='P')
        self.add_font('inter', '', settings.INTER_REGULAR)
        self.add_font('inter', 'I', settings.INTER_ITALIC)
        self.add_font('inter', 'B', settings.INTER_BOLD)
        self.add_font('inter', 'BI', settings.INTER_BOLDITALIC)
        self.alias_nb_pages()
        self.set_margins(5, 5, 5)
        self.set_auto_page_break(auto=True, margin=12)
        self.set_font('inter', '', 8)
        self.data = kwargs.pop('data')
        logo, height = resize_image(self.data['school_data']['logo'], new_width=475, return_height=True) \
            if self.data['school_data']['logo'] != "media/image/no_image.jpg" else None
        height = int((height * 25.4) / 300) + 20 if height else 65
        height = height if self.data['school_data']['motto'] else None
        if 'students' in self.data.keys():
            self.id_cards(logo, height)
        else:
            self.second_page()
            self.third_page((1, 2, 3))
            self.first_and_last_pages((1, 2, 3), logo, height)

    def id_cards(self, logo, height):
        students = self.data['students']
        is_not_modulo3 = len(students) % 3 != 0
        j = int(len(students) / 3)
        if is_not_modulo3:
            j += 1
        for i in range(j):
            if i == j -1 and is_not_modulo3:
                end = len(students)
            else:
                end = (i *3) + 3
            students_set = students[i * 3:end]
            self.add_page()
            x = 5
            y = 2.5
            for student in students_set:
                self.set_xy(x, y)
                self.line(x1=105, y1=y, x2=105, y2=y+90)
                table = Table(self, line_height=4, col_widths=(35, 60), text_align="L", first_row_as_headings=False,
                              borders_layout="NONE", markdown=True, align='L', width=96)
                row = table.row()
                row.cell("**Nom(s) :**")
                self.set_font_size(9)
                row.cell(f"**{student.nom}**", rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Name(s)__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Préom(s) :**")
                self.set_font_size(9)
                row.cell(f"**{student.prenom if student.prenom else '/'}**", rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Surname(s)__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Né(e) le :**")
                self.set_font_size(9)
                row.cell(f"**{format_date(student.date_naissance, format="long", locale="fr_FR")}**", rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Born on__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**À :**")
                self.set_font_size(9)
                row.cell(f"**{student.lieu_naissance}**", rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__At__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Nationalité :**")
                self.set_font_size(9)
                row.cell("**Camerounaise**", rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Nationality__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Fils ou Fille de :**")
                self.set_font_size(9)
                pere = f"**{student.pere.name}**" if student.pere else f"--{' ' * 65}--"
                row.cell(pere, rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Son or Daughter of__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Et de :**")
                self.set_font_size(9)
                mere = f"**{student.mere.name}**" if student.mere else f"--{' ' * 65}--"
                row.cell(mere, rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__And of__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Adresse des Parents :**")
                self.set_font_size(9)
                contact = student.pere.contact if student.pere else ""
                if student.mere:
                    contact += f" / {student.mere.contact}" if contact else student.mere.contact
                contact = f"**{contact}**" if contact else f"--{' ' * 65}--"
                row.cell(contact, rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Parent's adress__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Classe :**")
                self.set_font_size(9)
                row.cell(f"**{student.classe.code if student.classe else ' '}**", rowspan=2)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Classroom__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**N° Matricule :**")
                self.set_text_color(255, 0, 0)
                self.set_font_size(9)
                row.cell(f"**{student.unique_id if student.unique_id else ' '}**", rowspan=2)
                self.set_text_color(0)
                row = table.row()
                self.set_font_size(7)
                row.cell("__Register number__")
                self.set_font_size(8)

                row = table.row()
                row.cell("**Signature ou empreinte de l'Élève**\n", colspan=2, align='C')
                row = table.row()
                self.set_font_size(7)
                row.cell("__Student's signature__\n", colspan=2, align='C')
                self.set_font_size(8)

                table.render()
                self.dashed_line(x1=0, y1=y+92.5, x2=210, y2=y+92.5)
                y += 95
            self.third_page(students_set)
            self.first_and_last_pages(students_set, logo, height)

    def second_page(self):
        self.add_page()
        x = 5
        y = 2.5
        for _ in range(3):
            self.set_xy(x, y)
            self.line(x1=105, y1=y, x2=105, y2=y + 90)
            table = Table(self, line_height=4, col_widths=(35, 60), text_align="L", first_row_as_headings=False,
                          borders_layout="NONE", markdown=True, align='L', width=96)
            row = table.row()
            row.cell("**Nom(s) :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Name(s)__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Préom(s) :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Surname(s)__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Né(e) le :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Born on__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**À :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__At__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Nationalité :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Nationality__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Fils ou Fille de :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Son or Daughter of__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Et de :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__And of__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Adresse des Parents :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Parent's adress__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Classe :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Classroom__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**N° Matricule :**")
            self.set_font_size(9)
            row.cell(f"--{' ' * 65}--", rowspan=2)
            row = table.row()
            self.set_font_size(7)
            row.cell("__Register number__")
            self.set_font_size(8)

            row = table.row()
            row.cell("**Signature ou empreinte de l'Élève**\n", colspan=2, align='C')
            row = table.row()
            self.set_font_size(7)
            row.cell("__Student's signature__\n", colspan=2, align='C')
            self.set_font_size(8)

            table.render()
            self.dashed_line(x1=0, y1=y + 92.5, x2=210, y2=y + 92.5)
            y += 95

    def third_page(self, elts):
        x, y = 110, 2.5
        for elt in elts:
            photo = "" if isinstance(elt, int) else elt.photo
            if photo:
                self.image(resize_image(photo, id_card=True), x=140, y=y, w=35, h=40)
            else:
                self.set_xy(140, y)
                self.cell(w=35, h=40, text="__Photo__", border=True, align='C', markdown=True)
            self.set_xy(x, y+44)
            self.set_font_size(9)
            self.cell(w=95, h=3, text=f"**Fait à {self.data['school_data']['localite']}, le **--{' ' * 20}--", align='C', markdown=True)
            self.set_xy(x, y + 49)
            self.cell(w=95, h=4, text=f"**LE {self.data['school_data']['chef'].upper()}**", align='C', markdown=True)
            self.set_font_size(8)
            self.set_xy(x, y + 53)
            self.cell(w=95, h=3, text=f"__The Principal", align='C', markdown=True)
            self.set_font_size(7)
            self.line(x1=110, y1=y+77.5, x2=205, y2=y+77.5)
            self.set_xy(x, y + 78)
            self.cell(w=95, h=3, text="CETTE CARTE EST STRICTEMENT INDIVIDUELLE ET PERSONNELLE", align='C')
            self.set_xy(x, y + 81)
            self.cell(w=95, h=3, text="ELLE NE PEUT EN AUCUN CAS ËTRE PRËTÉE OU CÉDÉE", align='C')
            self.set_xy(x, y + 86)
            self.cell(w=95, h=3, text="__THIS CARD IS STRICTLY INDIVIDUAL AND PERSONNAL__", align='C', markdown=True)
            self.set_xy(x, y + 89)
            self.cell(w=95, h=3, text="__IT CAN NOT BE RENT OR GIVEN OUT__", align='C', markdown=True)
            self.set_font_size(8)

            y += 95

    def first_and_last_pages(self, elts, logo, height):
        self.add_page()
        x, y, yi, ym = 110, 2.5, 15, height
        """yd = 8.5
        for _ in elts:
            self.image("media/image/drapeau.jpeg", x=142.5, y=yd, w=30, keep_aspect_ratio=True)
            yd += 95"""
        for elt in elts:
            if logo:
                self.image(logo, x=32.5, y=yi, w=40, keep_aspect_ratio=True)
                yi += 95
            if height:
                self.set_xy(5, ym)
                self.set_font_size(10)
                self.cell(w=95, h=10, text=f"**__{self.data['school_data']['motto']}__**", markdown=True, align='C')
                self.set_font_size(8)
                ym += 95
            self.set_xy(x, y)
            self.line(x1=105, y1=y, x2=105, y2=y + 90)
            table = Table(self, line_height=4, col_widths=(1, 1), text_align="R", first_row_as_headings=False,
                          borders_layout="NONE", markdown=True, align='L', width=95)
            row = table.row()
            row.cell("**RÉPUBLIQUE DU CAMEROUN**", align='C')
            row.cell("**REPUBLIC OF CAMEROON**", align='C')
            self.set_font_size(7)
            row = table.row()
            row.cell("__Paix - Travail - Patrie__", align='C')
            row.cell("__Peace - Work - Fatherland__", align='C')
            self.set_font_size(6)
            row = table.row()
            row.cell("*********", align='C', v_align=VAlign.T)
            row.cell("*********", align='C', v_align=VAlign.T)
            self.set_font_size(8)

            row = table.row()
            row.cell("**MINISTÈRE DES ENSEIGNEMENTS SECONDAIRES**", align='C', colspan=2)
            self.set_font_size(7)
            row = table.row()
            row.cell("__MINISTRY OF SECONDARY EDUCATION__", align='C', colspan=2)
            self.set_font_size(6)
            row = table.row()
            row.cell("************", align='C', v_align=VAlign.T, colspan=2)
            self.set_font_size(8)

            row = table.row()
            row.cell(f"**{self.data['school_data']['region']}**", align='C', colspan=2)
            self.set_font_size(7)
            row = table.row()
            row.cell(f"__{self.data['school_data']['rgn']}__", align='C', colspan=2)
            self.set_font_size(6)
            row = table.row()
            row.cell("************", align='C', v_align=VAlign.T, colspan=2)
            self.set_font_size(8)

            row = table.row()
            row.cell(f"**{self.data['school_data']['departement']}**", align='C', colspan=2)
            self.set_font_size(7)
            row = table.row()
            row.cell(f"__{self.data['school_data']['dptm']}__", align='C', colspan=2)
            self.set_font_size(6)
            row = table.row()
            row.cell("************", align='C', v_align=VAlign.T, colspan=2)
            row = table.row()
            self.set_fill_color(75)
            self.set_text_color(255)
            row.cell(" ", colspan=2)
            self.set_font_size(12)

            row = table.row()
            nom = f"**{self.data['school_data']['nom']}**"
            row.cell(nom, align='C', colspan=2)
            if self.get_string_width(nom, markdown=True) < 96:
                self.set_font_size(10)
                row = table.row()
                row.cell(f"__{(self.data['school_data']['name'])}__", align='C', colspan=2)
            self.set_font_size(8)
            row = table.row()
            row.cell(f"B.P. {self.data['school_data']['po_box']}", align='C', v_align=VAlign.T, colspan=2)
            self.set_text_color(0)
            self.set_fill_color(255)
            row = table.row()
            row.cell(" ", colspan=2)

            self.set_font_size(9)
            row = table.row()
            row.cell("**CARTE D'IDENTITÉ SCOLAIRE**", align='C', colspan=2)
            self.set_font_size(8)
            row = table.row()
            row.cell("__STUDENT IDENTITY CARD__", align='C', v_align=VAlign.T, colspan=2)
            row = table.row()
            number = f"--{' ' * 20}--" if isinstance(elt, int) else f"**{self.data['annee'][-2:]}{elt.csi_number}**"
            row.cell("**N°**", align='R')
            if not isinstance(elt, int):
                self.set_text_color(255, 0, 0)
            row.cell(number, align='L')
            self.set_text_color(0)

            row = table.row()
            row.cell(" ", colspan=2)
            row = table.row()
            row.cell("**ANNÉE SCOLAIRE**", align='R')
            row.cell(f"**{self.data['annee']}**", align='L')
            row = table.row()
            self.set_font_size(7)
            row.cell("__SCHOOL YEAR__", align='R')
            self.set_font_size(8)

            table.render()
            self.dashed_line(x1=0, y1=y + 92.5, x2=210, y2=y + 92.5)
            y += 95
