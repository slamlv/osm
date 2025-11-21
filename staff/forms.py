from django import forms
from django.forms.models import model_to_dict
from authentification.models import School, Civilite, Poste
from osm.utils import one_escape, message
from .models import Personnel, Discipline, Activities
from authentification.models import User
from authentification.forms import valid_email, valid_contact, valid_name, valid_username, valid_password
from dynamic_forms import DynamicFormMixin, DynamicField


class ActivityForm(DynamicFormMixin, forms.ModelForm):
    class Meta:
        model = Activities
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        try:
            instance = kwargs.get("instance")
            self.instance_id = instance.id
        except:
            self.instance_id = None
        super().__init__(*args, **kwargs)

    start = forms.DateField(widget=forms.DateInput(attrs={
        'type': 'date', 'class': "form-control fw-bold", 'id': "start"
    }, format='%Y-%m-%d'))
    end = forms.DateField(widget=forms.DateInput(attrs={
        'type': 'date', 'class': "form-control fw-bold", 'id': "end"
    }, format='%Y-%m-%d'))
    label = forms.CharField(widget=forms.Textarea(attrs={
        'class': "form-control fw-bold overflow-hidden custom-textarea", 'id': "label", 'rows': "1",
        'style': "min-height: 60px; max-height: 200px; resize: none;",
        'placeholder': "Entrez l'activité progrmmée..."
    }))
    responsables = forms.CharField(max_length=30, required=False, widget=forms.Textarea(attrs={
        "placeholder": "Entrez les intervenants", 'class': "form-control fw-bold overflow-hidden custom-textarea",
        'id': "responsables", 'rows': "1", 'style': "min-height: 60px; max-height: 200px; resize: none;",
    }))

    def clean(self):
        request = self.context['request']
        activities = Activities.objects
        if self.instance_id:
            activities = activities.exclude(pk=self.instance_id)
        start = self.cleaned_data.get('start')
        end = self.cleaned_data.get('end')
        label = self.cleaned_data.get('label')
        if end < start:
            message(request, "la date de fin ne peut être antérieure à la date de début", msg_type="warning")
            raise forms.ValidationError("")
        if activities.filter(start=start, end=end, label=label).exists():
            message(request, "Cette activité a déjà été enregistrée", msg_type="warning")
            raise forms.ValidationError("")


class MemberForm(DynamicFormMixin, forms.ModelForm):
    class Meta:
        model = Personnel
        fields = ["nom", "prenom", "civilite", "poste", "grade", "discipline", "contact", "contact1", "email", "since",
                  "photo"]

    def __init__(self, *args, **kwargs):
        try:
            instance = kwargs.get("instance")
            self.member_id = instance.id
        except:
            self.member_id = None
        super().__init__(*args, **kwargs)

    nom = forms.CharField(max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le nom", 'class': "form-control fw-bold", 'id': "nom"
    }))
    prenom = forms.CharField(required=False, max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le prénom", 'class': "form-control fw-bold", 'id': "prenom"
    }))
    username = DynamicField(forms.CharField, max_length=15, widget=forms.TextInput(attrs={
        "placeholder": "Définissez un nom d'utilisateur", 'id': "username", 'class': "form-control fw-bold"}),
                            include=lambda form: form.include(), initial=lambda form: form.default())
    civilite = forms.ChoiceField(choices=Civilite.choices, widget=forms.Select(attrs={
        'id': "civilite", 'class': "form-select fw-bold woption"
    }))
    poste = forms.ChoiceField(choices=Poste.choices, widget=forms.Select(attrs={
        'id': "poste", 'class': "form-select fw-bold woption"
    }))
    grade = forms.ChoiceField(choices=Personnel.Grade.choices, widget=forms.Select(attrs={
        'id': "grade", 'class': "form-select fw-bold woption"
    }))
    discipline = DynamicField(forms.ModelMultipleChoiceField, queryset=lambda form: form.get(), required=False,
                              widget=forms.SelectMultiple(attrs={
                                  'id': "discipline", 'class': "form-select choices-multiple", 'multiple': "multiple"
                              }))
    contact = forms.CharField(max_length=9, widget=forms.TextInput(attrs={
        'placeholder': "Entrez le numéro de téléphone", 'id': "contact", 'class': "form-control fw-bold"
    }))
    contact1 = DynamicField(forms.CharField, required=False, max_length=9, widget=forms.TextInput(attrs={
        'placeholder': "Numéro de téléphone alternatif", 'id': "contact1", 'class': "form-control fw-bold"
    }), include=lambda form: form.include(False))
    email = DynamicField(forms.CharField, widget=forms.TextInput(attrs={
        'placeholder': "Entrez l'adresse email", 'id': "email", 'class': "form-control fw-bold"
    }), required=lambda form: form.required_email())
    since = forms.IntegerField(required=False, min_value=1, max_value=40, widget=forms.NumberInput(attrs={
        'placeholder': "Nombre d'années d'ancienneté du membre", 'id': "since", 'class': "form-control fw-bold"
    }))
    photo = DynamicField(forms.FileField, widget=forms.ClearableFileInput(attrs={
        'placeholder': "Votre photo de profil", 'id': "photo", 'class': "form-control w-auto bg-dark text-white fw-bold client-image",
        'accept': "image/*"
    }), include=lambda form: form.include_pp(), initial=lambda form: form.default(1), required=False)

    def include_pp(self):
        if 'pp' in self.context.keys():
            return True
        return False

    def default(self, key=0):
        if key:
            return self.instance.photo
        elif 'pp' in self.context.keys():
            return self.instance.user.username

    def include(self, key=True):
        if key:
            if 'user' in self.context.keys():
                return True
            return False
        else:
            if 'user' in self.context.keys():
                return False
            return True

    def required_email(self):
        if 'user' in self.context.keys():
            return True
        if self.instance:
            if self.instance.user:
                return True
        return False

    def get(self):
        return Discipline.get_disciplines()

    def clean(self):
        request = self.context['request']
        members = Personnel.objects
        if self.member_id:
            members = members.exclude(pk=self.member_id)
        # Contrainte pour les chefs d'établissement
        poste = self.cleaned_data.get("poste")
        if poste in "Chef d'Établissement":
            if members.filter(poste="Chef d'Établissement").exists():
                message(request, "Un chef d'établissement a déjà été enregistré pour cet établissement.",
                        msg_type="warning")
                raise forms.ValidationError("")
        # Validation du nom et du prénom
        valid_name(self.cleaned_data.get("nom"), self.cleaned_data.get("prenom"), queryset=members, request=request)

        # Validation des contacts et de l'email
        contact = self.cleaned_data.get("contact")
        valid_contact(contact, request)
        if members.filter(contact=contact).exists():
            message(request, "Ce contact a déjà été enregistré pour cet établissement.", msg_type="warning")
            raise forms.ValidationError("")
        if 'contact1' in self.cleaned_data.keys():
            contact1 = self.cleaned_data.get("contact1")
            if contact1:
                valid_contact(contact1, request)
                if members.filter(contact1=contact1).exists():
                    message(request, "Ce contact optionnel a déjà été enregistré pour cet établissement.",
                            msg_type="warning")
                    raise forms.ValidationError("")
        if self.required_email():
            email = valid_email(self.cleaned_data.get("email"), request=request)
            if members.filter(email=email).exists():
                message(request, "Cet email a déjà été enregistré pour cet établissement", msg_type="warning")
                raise forms.ValidationError("")
        else:
            self.cleaned_data['email'] = None
        if 'username' in self.cleaned_data.keys():
            username = self.cleaned_data.get('username')
            valid_username(username, request)
            users = User.objects.filter(username=username)
            if 'pp' in self.context.keys():
                users = users.exclude(username=username)
            if users.exists():
                message(request, "Nom d'utilisateur indisponible, veuillez en choisir un autre.", msg_type="warning")
                raise forms.ValidationError("")
        self.cleaned_data["nom"] = one_escape(self.cleaned_data.get("nom")).upper()
        self.cleaned_data["prenom"] = one_escape(self.cleaned_data.get("prenom")).title()
        self.cleaned_data["discipline"] = Personnel.get_disciplines(self.cleaned_data.get("discipline"))
