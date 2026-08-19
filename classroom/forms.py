from django import forms
from osm.utils import message, icon, one_escape, get_value, is_alphanumeric
from django.db.models import Q
from dynamic_forms import DynamicField, DynamicFormMixin
from authentification.models import User
from .models import ClassRoom, Class, Enseignements, Programmation, Matieres
from staff.models import Personnel, Discipline
from django.core import signing


class ProgrammationForm(DynamicFormMixin, forms.ModelForm):
    class Meta:
        model = Programmation
        fields = ["enseignant"]

    jour = forms.CharField(widget=forms.HiddenInput())
    classroom = forms.CharField(widget=forms.HiddenInput())
    tranche_horaire = forms.CharField(widget=forms.HiddenInput())
    nb_tranches = forms.CharField(widget=forms.HiddenInput())
    programmation_id = forms.CharField(widget=forms.HiddenInput(), required=False)
    matiere = DynamicField(forms.ChoiceField, widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "matiere",
        'hx-target': "#enseignants", 'hx-post': "reload_teachers"
    }), choices=lambda form: form.matieres_choices(),
                           initial=lambda form: form.initial_subject())
    enseignant = DynamicField(forms.ModelChoiceField, widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "enseignant"
    }), queryset=lambda form: form.enseignants(), required=False, initial=lambda form: form.initial_enseignant())

    def initial_subject(self):
        if self.context['mp'] and self.instance.pk:
            return Matieres.objects.get(sujet=self.instance.matiere.sujet, classe=self.context['classroom'].classe).pk
        elif self.instance:
            return self.instance.matiere_id
        return None


    def enseignants(self):
        matiere_id = self.context['request'].POST.get('matiere')
        if matiere_id:
            matiere = Matieres.objects.get(id=int(matiere_id))
            return Personnel.objects.priorite_par_matiere(matiere.sujet.pk)
        return Personnel.objects.order_by('nom', 'prenom')

    def clean(self):
        request = self.context['request']
        self.cleaned_data['jour'] = signing.loads(request.POST.get('jour'))
        self.cleaned_data['tranche_horaire'] = signing.loads(request.POST.get('tranche_horaire'))
        self.cleaned_data['classroom'] = signing.loads(request.POST['classroom'])
        enseignant = self.cleaned_data.get('enseignant')
        if enseignant:
            programmations = (
                enseignant.programmations.
                filter(jour=self.cleaned_data['jour'], tranche_horaire_id__in=[t.id for t in self.context['tranches']])
            )
            if self.instance:
                programmations = programmations.exclude(id__in=[p.id for p in self.context['programmations']])
            if programmations.exists():
                programmation = programmations.first()
                if not self.context['mp']:
                    message(request, f"{enseignant.short_name} est déjà programmé le {dict(Programmation.days)[programmation.jour]} en"
                                     f" {programmation.classroom.code} de {programmation.tranche_horaire.debut} à "
                                     f"{programmation.tranche_horaire.fin}", "error")
                    raise forms.ValidationError("")
                elif self.context['mp'] and (Matieres.objects.get(id=int(self.cleaned_data['matiere'])).sujet !=
                                             Matieres.objects.get(id=programmation.matiere_id).sujet):
                    clsrm = programmation.classrooms.first()
                    message(request, f"{enseignant.short_name} est déjà programmé le {dict(Programmation.days)[programmation.jour]} en"
                                     f" {clsrm.code} de {programmation.tranche_horaire.debut} à "
                                     f"{programmation.tranche_horaire.fin} pour enseigner {programmation.short(clsrm)}",
                            "error")
                    raise forms.ValidationError("")

    def matieres_choices(self):
        matieres = [(None, "---------")]
        classroom = self.context['classroom']
        if classroom:
            for matiere in classroom.subjects:
                label = matiere.sujet.label
                if matiere.sujet.matiere == "Français":
                    label = "Français"
                elif matiere.sujet.matiere == "Informatique":
                    label = "Informatique"
                elif label == "LVII":
                    label = classroom.lv2
                elif label == "LVIII":
                    label = classroom.lv3
                matieres.append((matiere.pk, label))
            return matieres
        return None

    def initial_enseignant(self):
        matiere_id = self.context['request'].POST.get('matiere')
        if matiere_id:
            return (
                Enseignements.objects.get(classroom_id=signing.loads(self.context['request'].POST['classroom']),
                                          matiere_id=matiere_id)).enseignant
        if self.instance:
            return self.instance.matiere_id
        return None


# TODO: Reloading
class MatiereAddForm(DynamicFormMixin, forms.Form):
    classe = DynamicField(forms.ModelChoiceField, queryset=lambda form: form.cqueryset(),
                          widget=forms.Select(attrs={
                              'class': "form-select woption fw-bold", 'id': "classe", 'hx-post': "reload",
                              'hx-target': "#reload"
                          }), initial=lambda form: Class.objects.get(pk=form.context['id']))
    discipline = DynamicField(forms.ChoiceField, choices=lambda form: form.dchoices(),
                              widget=forms.Select(attrs={
                                  'class': "form-select woption fw-bold", 'id': "discipline"}))
    coeff = forms.IntegerField(min_value=1, max_value=10, widget=forms.NumberInput(attrs={
        'class': "form-control bg-danger text-white fw-bold color-changing", 'id': "coeff"}))

    def cqueryset(self):
        classes = Class.objects.all()
        if self.context['request'].user.school.type_ets == "CES":
            classes.filter(serie="")
        elif self.context['request'].user.school.type_ets == "CES Bilingue":
            classes.filter(serie__in=["", "Bilingue"])
        return classes

    def dchoices(self):
        disciplines = Discipline.objects.all()
        dclasses = Class.objects.get(pk=self.context['id']).disciplines.all()
        disciplines = disciplines.exclude(id__in=[x.pk for x in dclasses]).order_by("label")
        return ((d.pk, d.label) for d in disciplines)


class ClassroomForm(DynamicFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        self.request = kwargs["context"]["request"]
        try:
            self.instance = kwargs["context"]["instance"]
        except KeyError:
            self.instance = None
        super().__init__(*args, **kwargs)

    level_choices = {
        "Premier Cycle": [
            ("Sixième", "Sixième"), ("Sixième Bilingue", "Sixième Bilingue"), ("Cinquième", "Cinquième"),
            ("Cinquième Bilingue", "Cinquième Bilingue"), ("Quatrième", "Quatrième"),
            ("Quatrième Bilingue", "Quatrième Bilingue"), ("Troisième", "Troisième"),
            ("Troisième Bilingue", "Troisième Bilingue")],
        "Second Cycle": [
            ("Seconde", "Seconde"), ("Première", "Première"), ("Terminale", "Terminale")]
    }
    seconde = [
        ("C", "C : Mathématiques, Physique-Chimie"), ("E", "E : Mathématiques et Techniques"),
        ("A1", "A1 : Lettres-Philosophie (Latin et Grec)"), ("A2", "A2 : Lettres-Philosophie (Latin et LVII)"),
        ("A3", "A3 : Lettres-Philosophie (Latin)"), ("A4", "A4 : Lettres-Philosophie (LVII)"),
        ("A5", "A5 : Lettres-Philosophie (LVII et LVIII)"), ("ABI", "ABI: A4 Bilingue"),
        ("AC", "AC : Arts Cinématographiques"), ("SH", "SH : Sciences Humaines")
    ]
    premiere_terminale = [
                             ("D", "D : Mathématiques, SVTEEHB"),
                             ("TI", "TI : Technologies de l'Information")
                         ] + seconde
    options_choices = {
        "Seconde": seconde, "Première Terminale": premiere_terminale
    }
    lvii = [
        ("Allemand", "Allemand"), ("Espagnol", "Espagnol"), ("Chinois", "Chinois"), ("Arabe", "Arabe")
    ]
    lviii = [
        ("Russe", "Russe"), ("Italien", "Italien")
    ]

    cycle = DynamicField(forms.ChoiceField, widget=forms.Select(attrs={
        'hx-post': "form-reload-0", 'hx-target': "#classroom_form", 'hx-include': "#classroom_form", 'id': "cycle",
        'class': "form-select fw-bold woption"}), choices=lambda form: form.set_cycle(),
                         initial=lambda form: form.set_cycle(initial=True))
    niveau = DynamicField(forms.ChoiceField, widget=forms.Select(attrs={
        'hx-post': "form-reload-0", 'hx-target': "#classroom_form", 'hx-include': "#classroom_form", 'id': "niveau",
        'class': "form-select fw-bold woption"}), choices=lambda form: form.set_levels(),
                          initial=lambda form: form.set_levels(initial=True))
    lv2 = DynamicField(forms.ChoiceField, widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "lv2"}), choices=lambda form: form.lvii,
                       include=lambda form: form.include_lv2(), initial=lambda form: form.initial_lv2())
    lv3 = DynamicField(forms.ChoiceField, widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "lv3"}), choices=lambda form: form.lviii,
                       include=lambda form: form.include_lv3(), initial=lambda form: form.initial_lv3())
    titulaire = DynamicField(forms.ModelChoiceField, widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "titulaire"}), queryset=lambda form: form.staff(), required=False,
                             initial=lambda form: form.initial_titulaire())
    option = DynamicField(forms.ChoiceField, widget=forms.Select(attrs={
        'hx-post': "form-reload-0", 'hx-target': "#classroom_form", 'hx-include': "#classroom_form", 'id': "option",
        'class': "form-select fw-bold woption"}), choices=lambda form: form.set_options(),
                          include=lambda form: form.include_option(),
                          initial=lambda form: form.set_options(initial=True))
    code = DynamicField(forms.CharField, max_length=15, widget=forms.TextInput(attrs={
        "placeholder": "Attribuez un nom à cette classe", 'class': "form-control fw-bold"}),
                        initial=lambda form: form.initial_code())

    def staff(self):
        return Personnel.objects.filter(poste__in=['Enseignant', 'Surveillant Général']).order_by('nom', 'prenom')

    def initial_titulaire(self):
        if self.instance:
            return self.instance.titulaire
        if 'reload' in self.context.keys():
            return self.request.POST['titulaire']
        return None

    def include_option(self):
        if 'option' in self.data.keys():
            return True
        if 'reload' in self.context.keys():
            if self.request.POST["cycle"] == "Second Cycle":
                return True
        if self.instance:
            if "ième" not in self.instance.classe.niveau:
                return True
        return False

    def include_lv2(self):
        if 'lv2' in self.data.keys():
            return True
        levels = ["Quatrième", "Troisième", "Quatrième Bilingue", "Troisième Bilingue"]
        if 'reload' in self.context.keys():
            option = (self.request.POST["option"] in ["A2", "A4", "A5",
                                                      "ABI"]) if 'option' in self.request.POST.keys() else False
            cycle = self.request.POST["cycle"]
            niveau = (self.request.POST["niveau"] in levels)
            if (cycle == "Premier Cycle" and niveau) or (cycle == "Second Cycle" and option):
                return True
        if self.instance:
            if self.instance.lv2:
                return True
        return False

    def initial_lv2(self):
        if self.instance:
            return self.instance.lv2
        if 'reload' in self.context.keys():
            if 'lv2' in self.request.POST.keys():
                return self.request.POST['lv2']
        return None

    def initial_lv3(self):
        if self.instance:
            return self.instance.lv3
        if 'reload' in self.context.keys():
            if 'lv3' in self.request.POST.keys():
                return self.request.POST['lv3']
        return None

    def initial_code(self):
        if self.instance:
            return self.instance.code
        if 'reload' in self.context.keys():
            return self.request.POST['code']
        return None

    def include_lv3(self):
        if 'lv3' in self.data.keys():
            return True
        if 'reload' in self.context.keys():
            option = (self.request.POST["cycle"] == "Second Cycle" and
                      self.request.POST["option"] == "A5") if 'option' in self.request.POST.keys() else False
            return option
        if self.instance:
            if self.instance.lv3:
                return True
        return False

    def set_cycle(self, initial=False):
        cycle_choices = ((("Premier Cycle", "Premier Cycle"),),
                         (("Premier Cycle", "Premier Cycle"),
                          ("Second Cycle", "Second Cycle")))[
            self.request.user.school.type_ets not in ["CES", "CES Bilingue"]]
        if initial:
            if 'reload' in self.context.keys():
                return self.request.POST['cycle']
            if self.instance:
                if "ième" in self.instance.classe.niveau:
                    return "Premier Cycle"
                else:
                    return "Second Cycle"
            return cycle_choices[0][0]
        return cycle_choices

    def set_levels(self, initial=False):
        levels = self.level_choices[self.data['cycle']] if 'cycle' in self.data.keys() else self.level_choices[
            'Premier Cycle']
        if self.instance:
            if "ième" in self.instance.classe.niveau:
                levels = self.level_choices["Premier Cycle"]
            else:
                levels = self.level_choices["Second Cycle"]
        if 'reload' in self.context.keys():
            levels = self.level_choices[self.request.POST["cycle"]]
        if initial:
            if self.instance:
                x = self.instance.classe.niveau
                if self.instance.classe.serie == "Bilingue":
                    x = f"{x} {self.instance.classe.serie}"
                return x
            if 'reload' in self.context.keys():
                return self.request.POST['niveau']
            return levels[0][0]
        return levels

    def set_options(self, initial=False):
        options = self.seconde
        if self.data:
            niveau = self.data['niveau']
        elif 'reload' in self.context.keys():
            niveau = self.request.POST['niveau']
        elif self.instance:
            niveau = self.instance.classe.niveau
        else:
            niveau = "Seconde"
        if niveau in ["Première", "Terminale"]:
            options = self.premiere_terminale
        if initial:
            if self.instance:
                return self.instance.classe.serie
            if 'reload' in self.context.keys():
                if 'option' in self.request.POST.keys():
                    return self.request.POST['option']
            return options[0][0]
        return options

    def clean(self):
        code = one_escape(self.cleaned_data.get("code"))
        if not is_alphanumeric(code):
            message(self.request, "L'intitulé (le nom) de la salle de classe doit être une chaîne "
                                  "alphanumérique.", msg_type="warning")
            raise forms.ValidationError("")
        code_value = code.split()
        n = len(code_value)
        if n != 1:
            code = (f"{code_value[0].title()}", f"{code_value[0]}")[code_value[0][0].isnumeric()]
            for i in range(1, n):
                code += f" {code_value[i].upper()}"
        else:
            code = (code_value[0].title(), code_value[0])[code_value[0][0].isnumeric()]
        classrooms = ClassRoom.objects
        if self.instance:
            classrooms = classrooms.exclude(pk=self.instance.id)
        if classrooms.filter(code=code).exists():
            message(self.request, "Une autre salle de classe a déjà le même intitulé.", msg_type="warning")
            raise forms.ValidationError("")
        self.cleaned_data["code"] = code

    def save_classroom(self):

        def clsrm_data():
            data = {"code": self.cleaned_data["code"],
                    'lv2': self.cleaned_data['lv2'] if 'lv2' in self.cleaned_data.keys() else None,
                    'lv3': self.cleaned_data['lv3'] if 'lv3' in self.cleaned_data.keys() else None,
                    "niveau": self.cleaned_data["niveau"], "titulaire": self.cleaned_data["titulaire"]}
            if self.cleaned_data["cycle"] == "Premier Cycle":
                if "Bilingue" in data["niveau"]:
                    data["niveau"] = data["niveau"].split()[0]
                    data["serie"] = "Bilingue"
                else:
                    data["serie"] = None
            else:
                data["serie"] = self.cleaned_data["option"]
            return data

        classroom_data = clsrm_data()
        classe = Class.objects.get(niveau=classroom_data["niveau"], serie=classroom_data["serie"])
        if self.instance:
            if classe == self.instance.classe:
                self.instance.code = classroom_data["code"]
                self.instance.lv2 = classroom_data["lv2"]
                self.instance.lv3 = classroom_data["lv3"]
                self.instance.titulaire = classroom_data["titulaire"]
                self.instance.save()
                return self.instance
        classroom = ClassRoom(classe=classe, code=classroom_data["code"], lv2=classroom_data["lv2"],
                              lv3=classroom_data["lv3"], titulaire=classroom_data["titulaire"])

        ClassRoom.save_classroom(classroom)
        if self.instance:
            self.instance.delete()
        return classroom


class SubjectForm(DynamicFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        self.label = kwargs.pop("label")
        self.url = kwargs.pop("url")
        self.classroom = kwargs.pop("classroom")
        super().__init__(*args, **kwargs)

    enseignant = DynamicField(forms.ModelChoiceField, initial=lambda form: form.initial_member(),
                              queryset=lambda form: form.enseignants(), required=False)
    rapporteur = DynamicField(forms.ModelChoiceField, initial=lambda form: form.initial_member(key="rapporteur"),
                              queryset=lambda form: form.rapporteurs(), required=False)

    def add_prefix(self, field_name):
        field_name += self.label
        super().add_prefix(field_name)
        return field_name

    def attr_enseignant(self):
        return f"enseignant{self.label}".replace(" ", "")

    def enseignants(self):
        enseignants = Personnel.objects.all()
        ids = []
        for enseignant in enseignants:
            disciplines_enseignant = enseignant.discipline.all()
            i = 0
            for discipline in disciplines_enseignant:
                if self.label in [discipline.label, discipline.matiere]:
                    i = 1
                    break
            if i == 0:
                ids.append(enseignant.pk)
        enseignants = enseignants.exclude(pk__in=ids)
        return enseignants

    def rapporteurs(self):
        return Personnel.objects.filter(user_id__gt=0)

    def initial_member(self, key="enseignant"):
        enseignement = self.get_enseignements()[0]
        if key == "enseignant":
            return enseignement.enseignant
        elif key == "rapporteur":
            return enseignement.rapporteur

    def get_enseignements(self):
        matieres = self.classroom.matieres.all().filter()
        ids = list()
        for matiere in matieres:
            if self.label in [matiere.sujet.label, matiere.sujet.matiere]:
                ids.append(matiere.pk)
        enseignements = Enseignements.objects.filter(matiere_id__in=ids, classroom=self.classroom)
        return enseignements

    def save_teachers(self):
        enseignements = self.get_enseignements()
        enseignant = self.cleaned_data.get("enseignant")
        rapporteur = self.cleaned_data.get("rapporteur")
        ex_rapporteur = enseignements[0].rapporteur
        ex_enseignant = enseignements[0].enseignant
        for enseignement in enseignements:
            if enseignant != ex_enseignant:
                enseignement.enseignant = enseignant
                if enseignant.user_id != 0:
                    enseignement.rapporteur = enseignant
            if rapporteur != ex_rapporteur:
                enseignement.rapporteur = rapporteur
            enseignement.save()


class SubjectsForm:

    def __init__(self, *args, **kwargs):
        self.subjects_form = list()
        request = kwargs.pop("request")
        labels = kwargs.pop("labels")
        method = kwargs.pop("method")
        classroom = kwargs.pop("classroom")
        for label in labels:
            if method == "GET":
                self.subjects_form.append(SubjectForm(label=label, url=request.user.school.url,
                                                      classroom=classroom))
            else:
                self.subjects_form.append(SubjectForm(request.POST,
                                                      label=label, url=request.user.school.url,
                                                      classroom=classroom))
        self.subjects_form = tuple(self.subjects_form)

    def is_valid(self):
        for subject_form in self.subjects_form:
            if not subject_form.is_valid():
                return False
        return True

    def save(self):
        for subject_form in self.subjects_form:
            subject_form.save_teachers()


class MatTeachForm(DynamicFormMixin, forms.Form):

    def __init__(self, *args, **kwargs):
        self.icon = kwargs['context']['icon']
        if 'coeff' in kwargs['context'].keys():
            self.matiere = kwargs['context']['matiere']
            self.id = self.matiere.pk
            self.label = self.matiere.sujet.label
        else:
            self.enseignement = kwargs['context']['enseignement']
            self.label = self.enseignement.matiere.sujet.label
            if self.enseignement.matiere.sujet.matiere == "Français":
                self.label = "Français"
            if self.enseignement.matiere.sujet.matiere == "Informatique":
                self.label = "Informatique"
            self.enseignants = kwargs['context']['enseignants']
            self.rapporteurs = kwargs['context']['rapporteurs']
        super().__init__(*args, **kwargs)

    coeff = DynamicField(forms.IntegerField, initial=lambda form: form.matiere.coeff, max_value=10, min_value=1,
                         widget=forms.NumberInput(attrs={
                             'class': "form-control bg-danger text-white fw-bold color-changing", 'id': "coeff"
                         }), include=lambda form: form.include(True))
    enseignant = DynamicField(forms.ModelChoiceField, queryset=lambda form: form.enseignants, widget=forms.Select(
        attrs={
            'class': "form-select woption", 'id': "enseignant"
        }), include=lambda form: form.include(), required=False, initial=lambda form: form.enseignement.enseignant_id)
    rapporteur = DynamicField(forms.ModelChoiceField, queryset=lambda form: form.rapporteurs, widget=forms.Select(
        attrs={
            'class': "form-select woption", 'id': "rapporteur"
        }), include=lambda form: form.include(), required=False, initial=lambda form: form.enseignement.rapporteur_id)

    def include(self, k=False):
        if k:
            if 'coeff' in self.context.keys():
                return True
        else:
            if 'coeff' not in self.context.keys():
                return True
        return False

    def save_form(self):
        i = 0
        if 'coeff' not in self.context.keys():
            if self.is_valid():
                if self.enseignement.matiere.sujet.matiere == "Français":
                    enseignements = list(
                        Enseignements.objects.select_related('enseignant', 'rapporteur').
                        filter(classroom_id=self.enseignement.classroom.pk, matiere__sujet__matiere="Français")
                    )
                elif self.enseignement.matiere.sujet.matiere == "Informatique":
                    enseignements = list(
                        Enseignements.objects.select_related('enseignant', 'rapporteur').
                        filter(classroom_id=self.enseignement.classroom.pk, matiere__sujet__matiere="Informatique")
                    )
                else:
                    enseignements = [self.enseignement]
                enseignant = (self.cleaned_data.get("enseignant"), None)[self.cleaned_data.get("enseignant") == ""]
                rapporteur = (self.cleaned_data.get("rapporteur"), None)[self.cleaned_data.get("rapporteur") == ""]
                ex_rapporteur = self.enseignement.rapporteur
                ex_enseignant = self.enseignement.enseignant
                for ens in enseignements:
                    if enseignant != ex_enseignant:
                        ens.enseignant = enseignant
                        if enseignant and enseignant.user:
                            ens.rapporteur = enseignant
                        i += 1
                    if rapporteur != ex_rapporteur:
                        ens.rapporteur = rapporteur
                        i += 1
                    ens.save()
        else:
            if self.is_valid():
                coeff = self.cleaned_data["coeff"]
                ex_coeff = self.matiere.coeff
                if coeff != ex_coeff:
                    self.matiere.coeff = coeff
                    self.matiere.save()
                    i += 1
        return i

    def add_prefix(self, field_name):
        field_name += self.label
        super().add_prefix(field_name)
        return field_name

    def valid(self):
        if 'coeff' in self.context.keys():
            if self.is_valid():
                coeff = self.cleaned_data["coeff"]
                if coeff > 1:
                    return True
            return False
        return True


class MatTeachsForm:

    def __init__(self, *args, **kwargs):
        self.mateachs_form = list()
        request = kwargs.pop("request")
        method = kwargs.pop("method")
        classroom = ClassRoom.objects.select_related('classe').prefetch_related('matieres__sujet').get(
            id=kwargs.pop('id'))
        self.classe = classroom.classe if 'coeff' in kwargs.keys() else classroom.code
        matieres = classroom.matieres.order_by_domain_and_coef(classroom.classe.serie)
        french = False
        info = False
        for matiere in matieres:
            matiere_icon = icon(matiere.sujet)
            if 'coeff' in kwargs.keys():
                self.id = classroom.id
                context = {'coeff': True, 'matiere': matiere, 'icon': matiere_icon}
            else:
                if (matiere.sujet.matiere == "Français" and french) or (
                        matiere.sujet.matiere == "Informatique" and info):
                    continue
                if matiere.sujet.matiere == "Français":
                    french = True
                elif matiere.sujet.matiere == "Informatique":
                    info = True
                enseignement = Enseignements.objects.select_related('enseignant', 'rapporteur').\
                    get(classroom_id=classroom.pk, matiere_id=matiere.pk)
                qs = Personnel.objects
                enseignants = qs.priorite_par_matiere(matiere.sujet.pk).distinct()
                rapporteurs = qs.filter(user_id__isnull=False)
                context = {'enseignement': enseignement, 'enseignants': enseignants, 'rapporteurs': rapporteurs,
                           'icon': matiere_icon}
            if method == "GET":
                self.mateachs_form.append(MatTeachForm(context=context))
            else:
                self.mateachs_form.append(MatTeachForm(request.POST, context=context))
        self.mateachs_form = tuple(self.mateachs_form)

    def is_valid(self):
        for mateach_form in self.mateachs_form:
            if not mateach_form.valid():
                return mateach_form.label
        return 0

    def save(self):
        i = 0
        for mateach_form in self.mateachs_form:
            i += mateach_form.save_form()
        return i


class DisciplineForm(DynamicFormMixin, forms.Form):
    label = DynamicField(forms.CharField, initial=lambda form: form.initlab(), widget=forms.TextInput(attrs={
        'placeholder': "Entrez l'intitulé", 'class': "form-control fw-bold", 'id': "label"}))
    matiere = DynamicField(forms.CharField, required=False, initial=lambda form: form.initmat(),
                           widget=forms.TextInput(attrs={
                               'list': "mat_list", 'class': "form-control fw-bold", 'id': "matiere",
                               'placeholder': "Entrez la discipline principale"}))
    groupe = DynamicField(forms.CharField, initial=lambda form: form.initgp(), widget=forms.TextInput(attrs={
        'list': "group_list", 'placeholder': "Entrez le domaine d'apprentissage", 'id': "domaine",
        'class': "form-control fw-bold"}))

    def initmat(self):
        if 'instance' in self.context.keys():
            return self.context['instance'].matiere

    def initlab(self):
        if 'instance' in self.context.keys():
            return self.context['instance'].label

    def initgp(self):
        if 'instance' in self.context.keys():
            return self.context['instance'].groupe

    def clean(self):

        def reform(arg: str):
            mots = arg.split(" ")
            for i in range(len(mots)):
                if mots[i] not in ["du", "de", "des", "le", "la", "les", "l'", "d'", "et", "ou", "à"]:
                    mots[i] = mots[i].title()
            return " ".join(mots)

        disciplines = Discipline.objects
        if 'instance' in self.context.keys():
            disciplines = disciplines.exclude(pk=self.context['instance'].id)
        if disciplines.filter(label__iexact=self.cleaned_data["label"]).exists():
            message(self.context['request'], "Une discipline du même nom existe déjà.", msg_type="warning")
            raise forms.ValidationError("")
        self.cleaned_data["label"] = reform(self.cleaned_data["label"])
        self.cleaned_data["matiere"] = reform(self.cleaned_data["matiere"])
        self.cleaned_data["groupe"] = reform(self.cleaned_data["groupe"])

    def save(self, commit=True):
        if 'instance' not in self.context.keys():
            from django.db.models import Max
            subject_id = Discipline.objects.aggregate(max_id=Max('id'))['max_id'] + 1 or 1
        else:
            subject_id = self.context['instance'].id
        discipline = Discipline(id=subject_id, label=self.cleaned_data["label"], matiere=self.cleaned_data["matiere"],
                                groupe=self.cleaned_data["groupe"])
        discipline.save()
        return discipline
