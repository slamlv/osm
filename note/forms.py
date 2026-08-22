import json

from django import forms
from django.db.models import Q
from dynamic_forms import DynamicField, DynamicFormMixin
from classroom.models import ClassRoom, Class, Enseignements
from note.models import Note, Period
from osm.utils import formated_float, get_value, is_alphanumeric, one_escape, message, default_competences
from staff.models import Personnel


class PeriodForm(DynamicFormMixin, forms.ModelForm):
    class Meta:
        model = Period
        fields = ["evalx", "start", "end"]

    eval_choices = ((1, "Evaluation n° 1"), (2, "Evaluation n° 2"), (3, "Evaluation n° 3"), (4, "Evaluation n° 4"),
                    (5, "Evaluation n° 5"), (6, "Evaluation n° 6"),)
    evalx = DynamicField(forms.ChoiceField, choices=eval_choices, widget=forms.Select(attrs={
        'hx-post': "reload_period", 'hx-target': "#period_form", 'hx-include': "#evalx", 'id': "evalx",
        'class': "form-select woption fw-bold"
    }), initial=lambda form: form.initials()[1])
    start = DynamicField(forms.DateTimeField, widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={
        'type': 'datetime-local', 'id': "start", 'class': "form-control fw-bold"
    }), initial=lambda form: form.initials()[0].start)
    end = DynamicField(forms.DateTimeField, widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={
        'type': 'datetime-local', 'id': "end", 'class': "form-control fw-bold"
    }), initial=lambda form: form.initials()[0].end)

    def initials(self):
        evl = int(self.context['request'].POST['evalx']) if 'evalx' in self.context['request'].POST.keys() else 1
        return self.context['periods'].get(evalx=evl), evl


class SelectForm(DynamicFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        self.trim = kwargs['context']['trim']
        self.level = kwargs['context']['level'] if "level" in kwargs['context'].keys() else False
        self.end_year_assignment = kwargs['context']['end_year_assignment'] if "end_year_assignment" in kwargs['context'].keys() else False
        self.marks_sheet = kwargs['context']['marks_sheet'] if "marks_sheet" in kwargs['context'].keys() else False
        self.pg = self.progression = kwargs['context']['progression'] if "progression" in kwargs['context'].keys() else False
        if 'pg' in kwargs['context'].keys():
            self.pg = True if kwargs['context']['pg'] else False
        super().__init__(*args, **kwargs)
        if 'matiere' in self.fields.keys():
            self.fields['matiere'].widget.attrs.update({
                'hx-vals': json.dumps({'pg': 1 if self.pg else 0}),
            })

    evalx = ((1, "Evaluation n°1"), (2, "Evaluation n°2"), (3, "Evaluation n°3"), (4, "Evaluation n°4"),
             (5, "Evaluation n°5"), (6, "Evaluation n°6"))
    trimx = ((1, "Premier Trimestre"), (2, "Deuxième trimestre"), (3, "Troisième Trimestre"))

    matiere_level = DynamicField(forms.ChoiceField, choices=lambda form: form.matieres(), widget=forms.Select(attrs={
        'hx-get': "levels_set", 'hx-target': "#classrooms", 'class': "form-select fw-bold woption",
        'id': "matiere", 'hx-include': "#select"}), include=lambda form: form.level)
    matiere = DynamicField(forms.ChoiceField, choices=lambda form: form.matieres(), widget=forms.Select(attrs={
        'hx-get': "classrooms_set", 'hx-target': "#classrooms", 'class': "form-select fw-bold woption",
        'id': "matiere", 'hx-include': "#select", 'hx-vals': "{'pg':}"}), include=lambda form: not form.level and not form.marks_sheet)
    classroom = DynamicField(forms.ChoiceField, choices=lambda form: form.classes(), widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "classe"}))
    eval = DynamicField(forms.ChoiceField, choices=lambda form: form.choices(), widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "eval"}), include=lambda form: (not form.marks_sheet) and (not form.progression))

    def choices(self):
        if self.trim:
            return self.trimx
        return self.evalx

    def matieres(self):
        enseignements = self.context['enseignements'].distinct('matiere__sujet_id')
        if self.progression:
            matieres = list()
            french, info = False, False
            for enseignement in enseignements:
                if (enseignement.matiere.sujet.matiere != "Français" and enseignement.matiere.sujet.matiere != "Informatique") or (
                        enseignement.matiere.sujet.matiere == "Français" and not french) or (
                        enseignement.matiere.sujet.matiere == "Informatique" and not info):
                    label = enseignement.matiere.sujet.label
                    if enseignement.matiere.sujet.matiere == "Français":
                        french = True
                        label = "Français"
                    elif enseignement.matiere.sujet.matiere == "Informatique":
                        info = True
                        label = "Informatique"
                    matieres.append((label, label))
            return matieres
        return [(ens.matiere.sujet.id, ens.matiere.sujet.label) for ens in enseignements]

    def classes(self):

        def matiere():
            if self.level:
                if self.data.get("matiere_level"):
                    return self.data.get("matiere_level")
                try:
                    return self.matieres()[0][0]
                except:
                    return None
            if self.data.get("matiere"):
                return self.data.get("matiere")
            try:
                return self.matieres()[0][0]
            except:
                return None

        if self.end_year_assignment:
            user = self.context['request'].user
            if user.is_min_admin:
                classrooms =  ClassRoom.objects.all().order_by_niveau()
            else:
                classrooms =  user.staff_member.titulaire.all()
            return [(classroom.pk, classroom.code) for classroom in classrooms]
        if self.progression or self.pg:
            label = matiere()
            enseignements = (
                self.context['enseignements'].
                filter(Q(matiere__sujet__label=label) | Q(matiere__sujet__matiere=label))
            )
            classes_id = [ens.classroom.pk for ens in enseignements]
            classrooms = ClassRoom.objects.select_related('classe').filter(pk__in=classes_id).order_by_niveau()
            return [(classroom.pk, classroom.code) for classroom in classrooms]
        if self.marks_sheet:
            if self.context['request'].user.is_min_admin:
                return [("__all__", "Toutes")] + [(classroom.pk, classroom.code) for classroom in ClassRoom.objects.order_by_niveau()]
        matiere = matiere()
        enseignements = self.context['enseignements']
        if not self.marks_sheet and matiere:
            enseignements = enseignements.filter(matiere__sujet_id=matiere)
        classes_id = [ens.classroom.pk for ens in enseignements]
        classrooms = ClassRoom.objects.select_related('classe').filter(pk__in=classes_id).order_by_niveau()
        if self.level:
            levels = []
            for classroom in classrooms:
                niveau = classroom.classe.niveau
                if (niveau, niveau) not in levels:
                    levels.append((niveau, niveau))
            return levels
        if 'all' in self.context.keys():
            return [("__all__", "Toutes")] + [(classroom.pk, classroom.code) for classroom in classrooms]
        return [(classroom.pk, classroom.code) for classroom in classrooms]


class StudentMarkForm(DynamicFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        context = kwargs.get("context")
        self.student = context['student']
        self.enseignement = context["enseignement"]
        self.label = self.student.__str__()
        self.unique_id = self.student.unique_id
        self.request = context['request']
        self.trim = context['trim']
        self.eval = context['eval']
        super().__init__(*args, **kwargs)

    note = DynamicField(forms.DecimalField, max_value=20, min_value=0, widget=forms.NumberInput(attrs={
        'class': "form-control fw-bold bg-danger text-white color-changing note", 'step': "0.25"
    }), max_digits=4, decimal_places=2, initial=lambda form: form.initial_note(), required=False)
    note1 = DynamicField(forms.DecimalField, max_value=20, min_value=0, widget=forms.NumberInput(attrs={
        'class': "form-control fw-bold bg-danger text-white color-changing note", 'step': "0.25"
    }), max_digits=4, decimal_places=2, include=lambda form: form.trim, initial=lambda form: form.initial_note(code=1),
                         required=False)

    def add_prefix(self, field_name):
        field_name += f"{self.unique_id}"
        super().add_prefix(field_name)
        return field_name

    def initial_note(self, code=0):
        note = self.context['notes'].filter(eval=self.eval[code])
        if not note:
            if code == 0:
                self.note = Note(eleve=self.student, enseignement=self.enseignement, eval=self.eval[code])
            else:
                self.note1 = Note(eleve=self.student, enseignement=self.enseignement, eval=self.eval[code])
        else:
            if code == 0:
                self.note = note[0]
            else:
                self.note1 = note[0]
            x = note[0].note
            if x != -1:
                return formated_float(x)
        return None

    def clean(self):
        n = self.request.POST[f'note{self.unique_id}']
        note = float(n) if n else 0
        note1 = 0
        if self.trim:
            n1 = self.request.POST[f'note1{self.unique_id}']
            note1 = float(n1) if n1 else 0
        if (note < 0) or (note > 20) or (note1 < 0) or (note1 > 20):
            raise forms.ValidationError("")

    def mark_save(self, compt):
        n = self.request.POST[f'note{self.unique_id}']
        note = float(n) if n else -1
        if self.trim:
            n1 = self.request.POST[f'note1{self.unique_id}']
            note1 = float(n1) if n1 else -1
        exnote = self.note.note
        excompetences = self.note.competences
        self.note.note = note
        if compt[0] is not None:
            self.note.competences = compt[0]
        elif not excompetences:
            self.note.competences = "/"
        self.note.save()
        if self.trim:
            exnote1 = self.note1.note
            excompetences1 = self.note1.competences
            self.note1.note = note1
            if compt[1] is not None:
                self.note1.competences = compt[1]
            elif not excompetences1:
                self.note1.competences = "/"
            self.note1.save()
            if exnote1 != note1 or (compt[1] is not None and excompetences1 != compt[1]):
                return 1
        if exnote != note or (compt[0] is not None and excompetences != compt[0]):
            return 1
        return 0


class LevelMarksForms:

    def __init__(self, *args, **kwargs):
        self.level_marks_form = list()
        context = kwargs.pop("context")
        self.request = context['request']
        method = kwargs.pop('method')
        self.eval = context['eval']
        enseignements = context['enseignements']
        ens_cls = [(ens.classroom, ens) for ens in enseignements]
        first = True
        trim = context['trim']
        for elt in ens_cls:
            if elt[0].students.all().exists():
                data = {'classroom': elt[0], 'enseignement': elt[1], 'eval': self.eval, "request": self.request,
                        'trim': trim, 'first': first, 'with_competences': context['with_competences']}
                if method == "GET":
                    self.level_marks_form.append(MarksForm(context=data, method="GET"))
                    first = False
                else:
                    self.level_marks_form.append(
                        MarksForm(context["request"].POST or None, context=data, method="POST"))
                    first = False
        self.level_marks_form = tuple(self.level_marks_form)
        super().__init__(*args, **kwargs)

    def isvalid(self):
        for level_marks in self.level_marks_form:
            if not level_marks.isvalid():
                return False
        return True

    def save(self, compts, term_index=None, sequence=None):
        x = 0
        for level_marks_form in self.level_marks_form:
            x += level_marks_form.save(compts, term_index, sequence)
        return x

    @classmethod
    def marks_check(cls, ens, evl):
        if isinstance(evl, int):
            notes = Note.objects.filter(enseignement_id__in=[enseignement.pk for enseignement in ens], eval=evl)
        else:
            notes = Note.objects.filter(enseignement_id__in=[enseignement.pk for enseignement in ens], eval__in=evl)
        if notes:
            for note in notes:
                if note.note != -1:
                    return True
        return False


class MarksForm(DynamicFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        self.marks_form = list()
        context = kwargs.pop("context")
        self.with_competences = context['request'].user.school.with_competences
        if self.with_competences:
            self.compts = context['compts'] if 'compts' in context.keys() else []
        method = kwargs.pop("method")
        evl = int(context["eval"])
        self.enseignement = context["enseignement"]
        if self.enseignement and self.enseignement.matiere.sujet.label == "LVII":
            self.lv2 = True
        elif self.enseignement and self.enseignement.matiere.sujet.label == "LVIII":
            self.lv3 = True
        self.classroom = context["classroom"]
        self.trim = context["trim"]
        if not self.trim:
            self.evalx = (evl,)
        else:
            self.evalx = (((1, 2), (3, 4))[evl == 2], (5, 6))[evl == 3]
        self.first = context['first'] if "first" in context.keys() else True
        if self.enseignement:
            self.notes = Note.objects.filter(eleve__classe_id=self.classroom.pk, enseignement_id=self.enseignement.pk,
                                             eval__in=self.evalx)
            for student in self.classroom.students.all().order_by("nom", "prenom"):
                student_notes = self.notes.filter(eleve_id=student.pk)
                context['eval'], context['student'], context['notes'] = self.evalx, student, student_notes
                if method == "GET":
                    self.marks_form.append(StudentMarkForm(context=context))
                else:
                    self.marks_form.append(StudentMarkForm(context["request"].POST or None, context=context))
            self.marks_form = tuple(self.marks_form)
        super().__init__(*args, **kwargs)

    competences = DynamicField(forms.CharField, widget=forms.Textarea(attrs={
        'class': "form-control fw-bold overflow-hidden custom-textarea", 'id': "competences", 'rows': "1",
        'style': "min-height: 60px; max-height: 200px; resize: none;",
        'placeholder': "Entrez les compétences évaluées..."
        }), include=lambda form: form.with_competences and form.first, initial=lambda form: form.initial_competences())
    competences1 = DynamicField(forms.CharField, widget=forms.Textarea(attrs={
        'class': "form-control fw-bold overflow-hidden custom-textarea", 'id': "competences1", 'rows': "1",
        'style': "min-height: 60px; max-height: 200px; resize: none;",
        'placeholder': "Entrez les compétences évaluées..."
        }), include=lambda form: form.with_competences and form.trim and form.first,
                                initial=lambda form: form.initial_competences(code=1))

    def initial_competences(self, code=0):
        if len(self.compts):
            return self.compts[code]
        evalx = self.evalx[code]
        note = self.notes.filter(eval=evalx)
        if note:
            return note[0].competences
        else:
            level = self.classroom.classe.niveau
            matiere = self.enseignement.matiere.sujet.label
            if matiere == "LVII":
                matiere = self.classroom.lv2
            elif matiere == "LVIII":
                matiere = self.classroom.lv3
            return default_competences(level, matiere, evalx)

    def save(self, compts, term_index=None, sequence=None):
        x = 0
        for mark_form in self.marks_form:
            x += mark_form.mark_save(compts)
        if x:
            self.classroom.touch_notes(term_index=term_index, sequence=sequence)
        return x

    def isvalid(self):
        for mark_form in self.marks_form:
            if not mark_form.is_valid():
                return False
        return True

    @classmethod
    def marks_check(cls, ens: Enseignements, evl):
        if isinstance(evl, int):
            notes = Note.objects.filter(enseignement_id=ens.pk, eval=evl)
        else:
            notes = Note.objects.filter(enseignement_id=ens.pk, eval__in=evl)
        if notes:
            for note in notes:
                if note.note != -1:
                    return True
        return False

    @classmethod
    def cls_marks_check(cls, classroom: ClassRoom, evl):
        matieres = classroom.matieres.all().order_by_domain_and_coef(classroom.classe.serie)
        result = list()
        for matiere in matieres:
            ens = Enseignements.objects.get(classroom_id=classroom.pk, matiere_id=matiere.pk)
            check = MarksForm.marks_check(ens=ens, evl=evl)
            dico = {"matiere": ens.matiere.sujet.label, "rapporteur": ens.rapporteur, "status": check}
            result.append(dico)
        return result


class MarksCopyForm(DynamicFormMixin, forms.Form):
    classe = DynamicField(forms.ChoiceField, initial=lambda form: form.initial_classe,
                          choices=lambda form: form.context['classrooms'], widget=forms.Select(attrs={
            'id': "classe", 'class': "form-select fw-bold woption", 'hx-post': "reload-copy-form",
            'hx-target': "#marks_copy_form", 'hx-include': "#copy_form"
        }))
    matiere_from = DynamicField(forms.ChoiceField, choices=lambda form: form.context['matieres'],
                                initial=lambda form: form.initial_matiere, widget=forms.Select(attrs={
            'id': "matiere_from", 'class': "form-select fw-bold woption", 'hx-post': "reload-copy-form-evals",
            'hx-target': "#marks_copy_form_from", 'hx-include': "#copy_form"
        }))
    eval_from = DynamicField(forms.ChoiceField, choices=lambda form: form.eval_choices(), widget=forms.Select(attrs={
        'id': "eval_from", 'class': "form-select fw-bold woption"
    }))
    matiere_to = DynamicField(forms.ChoiceField, choices=lambda form: form.context['matieres_to'], widget=forms.Select(
        attrs={
            'id': "matiere_to", 'class': "form-select fw-bold woption"
        }))
    eval_to = DynamicField(forms.ChoiceField, choices=lambda form: form.context['periods'], widget=forms.Select(attrs={
        'id': "eval_to", 'class': "form-select fw-bold woption"
    }))

    def initial_classe(self):
        if 'reload' in self.context.keys() or 'post' in self.context.keys():
            return self.context['request'].POST['classe']
        else:
            return self.context['classrooms'][0]

    def initial_matiere(self):
        if 'reloadm' in self.context.keys() or 'post' in self.context.keys():
            return self.context['request'].POST['matiere_from']
        else:
            return self.context['matieres'][0]

    def eval_choices(self):
        if 'reloadm' in self.context.keys() or 'post' in self.context.keys():
            return self.context['mat_evals'][int(self.context['request'].POST['matiere_from'])]
        else:
            return self.context['mat_evals'][self.context['matieres'][0][0]]

    def copy_notes(self):
        matiere_from, matiere_to = int(self.cleaned_data['matiere_from']), int(self.cleaned_data['matiere_to'])
        eval_from, eval_to = int(self.cleaned_data['eval_from']), int(self.cleaned_data['eval_to'])
        classe_id = int(self.cleaned_data['classe'])
        i = 0
        if matiere_from != matiere_to or eval_from != eval_to:
            notes = Note.objects.filter(eleve__classe_id=classe_id, enseignement_id=matiere_from, eval=eval_from)
            for note in notes:
                if note.note == -1:
                    continue
                i += 1
                try:
                    note_to = (
                        Note.objects.get(eleve__id=note.eleve.id, enseignement_id=matiere_to, eval=eval_to)
                    )
                    note_to.note = note.note
                    note_to.save()
                except Note.DoesNotExist:
                    if matiere_from == matiere_to:
                        competences = note.competences
                    else:
                        competences = "/"
                    note_to = Note(eleve_id=note.eleve.id, enseignement_id=matiere_to, eval=eval_to,
                                   competences=competences, note=note.note)
                    note_to.save()
        if i == 0:
            return "Aucune note copiée."
        else:
            nb = "Une note copiée" if i == 1 else f"{i} notes copiées"
            classe = dict(self.fields['classe'].choices).get(classe_id)
            from_matiere = dict(self.fields['matiere_from'].choices).get(matiere_from)
            to_matiere = dict(self.fields['matiere_to'].choices).get(matiere_to)
            return f"{classe} : {nb} de {from_matiere}, évaluation {eval_from} vers {to_matiere}, évaluation {eval_to}"


class CheckForm(DynamicFormMixin, forms.Form):
    eval_choices = ((1, "Evaluation n° 1"), (2, "Evaluation n° 2"), (3, "Evaluation n° 3"), (4, "Evaluation n° 4"),
                    (5, "Evaluation n° 5"), (6, "Evaluation n° 6"))
    transcript_choices = ((1, "Premier Trimestre"), (2, "Deuxième Trimestre"), (3, "Troisième Trimestre"),
                          (4, "Annuel"))
    marks_choices = ((1, "Premier Trimestre"), (2, "Deuxième Trimestre"), (3, "Troisième Trimestre"))

    clsrm = DynamicField(forms.ChoiceField, choices=lambda form: form.classes(), widget=forms.Select(attrs={
        'id': "classe", 'class': "form-select fw-bold woption"
    }))
    evl = DynamicField(forms.ChoiceField, choices=lambda form: form.get_choices(), widget=forms.Select(attrs={
        'id': "eval", 'class': "form-select fw-bold woption"
    }), include=lambda form: form.include_eval())
    checkbox = DynamicField(forms.BooleanField, include=lambda form: form.include(), widget=forms.CheckboxInput(attrs={
        'class': "form-check-input", 'id': "checkbox"
    }), required=False, initial=True)

    def include_eval(self):
        if 'time_table' in self.context.keys():
            return False
        return True

    def classes(self):
        classes = ClassRoom.objects.select_related('classe').order_by_niveau()
        choices = [(classe.pk, classe.code) for classe in classes]
        if 'all' in self.context.keys():
            choices.insert(0, ("__all__", "Toutes"))
        return choices

    def get_choices(self):
        if "marks-report" in self.context.keys():
            return self.marks_choices
        if 'check' in self.context.keys():
            return ("12", "Premier Trimestre"), ("34", "Deuxième Trimestre"), ("56", "Troisième Trimestre")
        return (self.eval_choices, self.transcript_choices)[self.context["transcript"]]

    def include(self):
        if 'transcript' in self.context.keys():
            return True
        return False
