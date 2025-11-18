from datetime import datetime
from django import forms
from dynamic_forms import DynamicField, DynamicFormMixin
from authentification.forms import valid_name, valid_contact, valid_email
from authentification.models import Civilite
from classroom.models import ClassRoom
from osm.utils import one_escape, message
from .models import Student, Parent, Sexe, Statut, StudentDiscipline
from django.core.validators import MinValueValidator, MaxValueValidator


class DForm(DynamicFormMixin, forms.ModelForm):

    class Meta:
        model = StudentDiscipline
        fields = ['excl_def', 'cons', 'abs', 'absj', 'retards']

    excl_def = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={
        'class': "form-check-input", 'id': "excl"
    }))
    cons = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={
        'class': "form-control fw-bold", 'id': "cons"
    }))
    abs = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={
        'class': "form-control fw-bold", 'id': "abs"
    }))
    absj = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={
        'class': "form-control fw-bold", 'id': "absj"
    }))
    retards = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={
        'class': "form-control fw-bold", 'id': "retards"
    }))

    def clean(self):
        if self.instance.pk is None:
            self.cleaned_data['cons'] = self.cleaned_data['cons'] if self.cleaned_data['cons'] is not None else 0
            self.cleaned_data['abs'] = self.cleaned_data['abs'] if self.cleaned_data['abs'] is not None else 0
            self.cleaned_data['absj'] = self.cleaned_data['absj'] if self.cleaned_data['absj'] is not None else 0
            self.cleaned_data['retards'] = self.cleaned_data['retards'] if self.cleaned_data['retards'] is not None else 0
        if self.cleaned_data['abs'] < self.cleaned_data['absj']:
            message(self.context['request'], "Le nombre d'heures d'absences justifiés ne peut être supérieur au "
                                             "nombre total d'heures d'absences", msg_type="warning")
            raise forms.ValidationError("")


class ParentForm(DynamicFormMixin, forms.ModelForm):
    class Meta:
        model = Parent
        fields = ["nom", "prenom", "email", "contact", "profession", "civilite"]

    def __init__(self, *args, **kwargs):
        self.request = kwargs['context']['request']
        try:
            self.parent_id = kwargs['instance'].id
        except:
            self.parent_id = None
        super().__init__(*args, **kwargs)

    nom = forms.CharField(max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le nom", 'class': "form-control fw-bold", 'id': "nom"
    }))
    prenom = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le prénom", 'class': "form-control fw-bold", 'id': "prenom"
    }))
    email = forms.CharField(required=False, widget=forms.TextInput(attrs={
        "placeholder": "Entrez l'adresse électronique", 'class': "form-control fw-bold", 'id': "email"
    }))
    contact = forms.CharField(max_length=9, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le numéro de téléphone", 'class': "form-control fw-bold", 'id': "contact"
    }))
    profession = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={
        "placeholder": "Entrez la profession", 'class': "form-control fw-bold", 'id': "profession"
    }))
    civilite = forms.ChoiceField(choices=Civilite.choices, widget=forms.Select(attrs={
        'class': "form-select fw-bold woption", 'id': "civilite"
    }))

    def clean(self):
        nom = self.cleaned_data.get("nom")
        prenom = self.cleaned_data.get("prenom") if 'prenom' in self.cleaned_data.keys() else ""
        contact = self.cleaned_data.get("contact")
        parents = Parent.objects
        if self.parent_id:
            parents = parents.exclude(pk=self.parent_id)
        # Validation du nom et du prénom
        valid_name(nom, prenom, queryset=None, request=self.request)

        # Validation du contact et de l'email
        valid_contact(contact, request=self.request)
        if parents.filter(contact=contact).exists():
            message(self.request, "Ce contact a déjà été enregistré.", msg_type="warning")
            raise forms.ValidationError("")
        if 'email' in self.cleaned_data['email']:
            email = valid_email(self.cleaned_data.get("email"), check=True, request=self.request)
            if parents.filter(email=email).exists():
                message(self.request, "Cet email a déjà été enregistré.", msg_type="warning")
                raise forms.ValidationError("")
        if 'profession' in self.cleaned_data.keys():
            self.cleaned_data["profession"] = self.cleaned_data.get("profession").title()
        self.cleaned_data["nom"] = one_escape(self.cleaned_data.get("nom")).upper()
        self.cleaned_data["prenom"] = one_escape(self.cleaned_data.get("prenom")).title()


class StudentForm(DynamicFormMixin, forms.ModelForm):

    class Meta:
        model = Student
        fields = ["nom", "prenom", "date_naissance", "lieu_naissance", "sexe", "statut", "pere", "mere", "classe",
                  "unique_id", "photo"]

    def __init__(self, *args, **kwargs):
        try:
            self.student_id = kwargs['instance'].id
        except:
            self.student_id = None
        super().__init__(*args, **kwargs)

    nom = forms.CharField(max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le nom", 'class': "form-control fw-bold", 'id': "nom"
    }))
    prenom = forms.CharField(required=False, max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le prénom", 'class': "form-control fw-bold", 'id': "prenom"
    }))
    date_naissance = forms.DateField(widget=forms.DateInput(attrs={
        'type': 'date', 'class': "form-control fw-bold", 'id': "date"
    }, format='%Y-%m-%d'))
    lieu_naissance = forms.CharField(max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le lieu de naissance", 'class': "form-control fw-bold", 'id': "lieu"
    }))
    sexe = forms.ChoiceField(choices=Sexe.choices, widget=forms.Select(attrs={
        'class': "form-select woption fw-bold", 'id': "sexe"
    }))
    statut = forms.ChoiceField(choices=Statut.choices, widget=forms.Select(attrs={
        'class': "form-select woption fw-bold", 'id': "statut"
    }))
    pere = DynamicField(forms.ModelChoiceField, required=False, widget=forms.Select(attrs={
        'class': "form-select woption fw-bold", 'id': "pere"
    }), queryset=Parent.objects.filter(civilite="Monsieur").order_by("-id"))
    mere = DynamicField(forms.ModelChoiceField, required=False, widget=forms.Select(attrs={
        'class': "form-select woption fw-bold", 'id': "mere"
    }), queryset=Parent.objects.filter(civilite="Madame").order_by("-id"),)
    classe = DynamicField(forms.ModelChoiceField, widget=forms.Select(attrs={
        'class': "form-select woption fw-bold", 'id': "classe"
    }), required=False, queryset=ClassRoom.objects.order_by_niveau())
    unique_id = forms.CharField(max_length=9, widget=forms.TextInput(attrs={
        'placeholder': "Entrez l'identifiant unique", 'class': "form-control fw-bold", 'id': "unique_id"
    }))
    photo = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={
        'placeholder': "Photo de l'élève", 'id': "photo", 'class': "form-control w-auto bg-dark text-white fw-bold",
        'accept': "image/*"
    }))

    def clean(self):
        nom = self.cleaned_data.get("nom")
        prenom = self.cleaned_data.get("prenom") if 'prenom' in self.cleaned_data.keys() else ""
        date = self.cleaned_data.get("date_naissance")
        unique_id = self.cleaned_data.get('unique_id')
        now = datetime.now().year
        min_year, max_year = now - 30, now - 8
        if not (min_year < date.year < max_year):
            message(self.context['request'], f"L'année de naissance doit être comprise entre {min_year} et {max_year}", msg_type="warning")
            raise forms.ValidationError("")
        students = Student.objects
        if self.student_id:
            students = students.exclude(pk=self.student_id)
        # Validation du nom et du prénom
        valid_name(nom, prenom, queryset=students, request=self.context['request'], date=date)

        # Identifiant unique
        valid_contact(unique_id, self.context['request'], objet="L'identifiant unique")
        if students.filter(unique_id=unique_id).exists():
            message(self.context['request'], "Cet identifiant unique a déjà été enregistré.", msg_type="warning")
            raise forms.ValidationError("")
        self.cleaned_data["nom"] = one_escape(self.cleaned_data.get("nom")).upper()
        self.cleaned_data["prenom"] = one_escape(self.cleaned_data.get("prenom")).title()
        self.cleaned_data["lieu_naissance"] = one_escape(self.cleaned_data.get("lieu_naissance")).title()
