from django.utils.safestring import mark_safe
from dynamic_forms import DynamicFormMixin, DynamicField
from django import forms
from authentification.models import School
from datetime import time


class MyImageInput(forms.ClearableFileInput):
    def render(self, name, value, attrs=None, renderer=None):
        input_html = super().render(name, value, attrs, renderer)
        if value and hasattr(value, 'url'):
            img_html = f'<img src="{value.url}" class="text-warning"'
            return mark_safe(input_html + img_html)

        return input_html


class SearchForm(DynamicFormMixin, forms.Form):
    search = forms.CharField(required=False, max_length=15, widget=forms.TextInput(attrs={
        'class': "form-control w-auto", 'id': "search", 'placeholder': "Recherche", 'type': "search"
    }))
    trimestre = DynamicField(forms.ChoiceField, include=lambda form: form.include_trim(), widget=forms.Select(attrs={
        'class': "form-select woption", 'id': "trim"
    }), choices=((1, "Trimestre 1"), (2, "Trimestre 2"), (3, "Trimestre 3")))

    def include_trim(self):
        if self.context:
            if 'trim' in self.context.keys():
                return True
        return False


class SchoolForm(DynamicFormMixin, forms.ModelForm):
    class Meta:
        fields = ['nom', 'name', 'type_ets', 'immatriculation', 'contact', 'contact1', 'pobox', 'motto', 'localite',
                  'with_competences', 'mergedprogrammations', 'logo', 'email']
        model = School
        widgets = {
            'nom': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "nom", 'placeholder': "Nom de l'établissement"}),
            'name': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "name", 'placeholder': "Name of the school"}),
            'type_ets': forms.Select(attrs={'class': "form-select woption fw-bold", 'id': "type"}),
            'immatriculation': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "immatriculation", 'placeholder': "N° d'immatriculation"}),
            'contact': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "contact", 'placeholder': "Contact", 'type': 'phone'}),
            'contact1': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "contact1", 'placeholder': "Contact optionnel", 'type': 'phone'}),
            'pobox': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "pobox", 'placeholder': "Boîte postale"}),
            'motto': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "motto", 'placeholder': "Devise de l'établissement"}),
            'localite': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "localite", 'placeholder': "Localité de l'établissement"}),
            'email': forms.TextInput(attrs={'class': "form-control fw-bold", 'id': "email", 'placeholder': "Adresse email", 'type': 'email'}),
            'with_competences': forms.CheckboxInput(attrs={'class': "form-check-input", 'id': "competences"}),
            'mergedprogrammations': forms.CheckboxInput(attrs={'class': "form-check-input", 'id': "programmations"}),
            'logo': forms.ClearableFileInput(attrs={'class': "form-control w-auto bg-dark text-white fw-bold client-image", 'id': "logo", 'accept': "image/*"})
        }

    def clean(self):
        from authentification.forms import valid_email, valid_contact, valid_name
        from osm.utils import message, one_escape

        request = self.context['request']
        schools = School.objects.exclude(id=self.instance.id)

        # Validation des noms
        valid_name(self.cleaned_data.get("nom"), self.cleaned_data.get("name"), queryset=None, request=request,
                   school=True)

        # Validation des contacts et de l'email
        contact = self.cleaned_data.get("contact")
        valid_contact(contact, request)
        if schools.filter(contact=contact).exists():
            message(request, "Ce contact a déjà été enregistré pour un autre établissement.", msg_type="warning")
            raise forms.ValidationError("")
        contact1 = self.cleaned_data.get("contact1")
        if contact1:
            valid_contact(contact1, request)
            if schools.filter(contact1=contact1).exists():
                message(request, "Ce contact optionnel a déjà été enregistré pour un autre établissement.", "warning")
                raise forms.ValidationError("")
        email = self.cleaned_data.get("email")
        if email:
            email = valid_email(self.cleaned_data.get("email"), request=request)
            if schools.filter(email=email).exists():
                message(request, "Cet email a déjà été enregistré pour un autre établissement", msg_type="warning")
                raise forms.ValidationError("")
        self.cleaned_data['nom'] = one_escape(self.cleaned_data.get("nom")).upper()
        self.cleaned_data['name'] = one_escape(self.cleaned_data.get("name")).upper()
        self.cleaned_data['immatriculation'] = one_escape(self.cleaned_data.get("immatriculation")).upper()


class TranchesHorairesForm(DynamicFormMixin, forms.Form):
    pause_durations = (
        (10, "10 minutes"),
        (15, "15 minutes"),
        (20, "20 minutes"),
        (25, "25 minutes"),
        (30, "30 minutes")
    )

    day_start = DynamicField(forms.TimeField, widget=forms.TimeInput(attrs={
        'class': "form-control fw-bold", 'id': "day-start", 'type': "time"
    }, format='%H:%M'), initial=lambda form: form.initials(), validators=[])
    duration = DynamicField(forms.ChoiceField, choices=((50, "50 minutes"), (55, "55 minutes"), (60, "60 minutes")),
                            widget=forms.Select(attrs={
                                'class': "form-select fw-bold", 'id': "duration"
                            }), initial=lambda form: form.initials('duration'))
    first_break = DynamicField(forms.ChoiceField, choices=((2, "2 tranches"), (3, "3 tranches")),
                               widget=forms.Select(attrs={
                                   'class': "form-select fw-bold", 'id': "first_break_after"
                               }), initial=lambda form: form.initials('first_break'))
    first_break_duration = DynamicField(forms.ChoiceField, choices=pause_durations, widget=forms.Select(attrs={
        'class': "form-select fw-bold", 'id': "first_break_duration"
    }), initial=lambda form: form.initials('fb_duration'))
    second_break_duration = DynamicField(forms.ChoiceField, choices=pause_durations, widget=forms.Select(attrs={
        'class': "form-select fw-bold", 'id': "second_break_duration"
    }), initial=lambda form: form.initials('sb_duration'))
    second_break = DynamicField(forms.ChoiceField, choices=((4, "4 tranches"), (5, "5 tranches"), (6, "6 tranches")),
                                widget=forms.Select(attrs={
                                    'class': "form-select fw-bold", 'id': "second_break_after"
                                }), initial=lambda form: form.initials('second_break'))
    nb = DynamicField(forms.ChoiceField, choices=((6, 6), (7, 7), (8, 8), (9, 9)), widget=forms.Select(attrs={
        'class': "form-select fw-bold", 'id': "nb"
    }), initial=lambda form: form.initials('nb'))

    def initials(self, key='day_start'):
        school = self.context['request'].user.school
        if key == 'nb':
            return school.nb_plages
        elif key == 'duration':
            return school.plage_duration
        elif key == 'first_break':
            return school.first_break_after
        elif key == 'second_break':
            return school.second_break_after
        elif key == 'fb_duration':
            return school.first_break_duration
        elif key == 'sb_duration':
            return school.second_break_duration
        else:
            return school.day_start

    def clean(self):
        min_hour = time(hour=7, minute=0)
        max_hour = time(hour=8, minute=0)
        day_start_hour = self.cleaned_data['day_start']
        if not (min_hour <= day_start_hour <= max_hour):
            from .utils import message
            message(self.context['request'], "L'heure de début des cours doit être comprise entre 7h00 et 8h00",
                    msg_type="error")
            raise forms.ValidationError("")

    def form_has_changed(self):
        day_start = self.cleaned_data['day_start'] != self.initials()
        duration = self.cleaned_data['duration'] != str(self.initials('duration'))
        first_break = self.cleaned_data['first_break'] != str(self.initials('first_break'))
        second_break = self.cleaned_data['second_break'] != str(self.initials('second_break'))
        fb_break_duration = self.cleaned_data['first_break_duration'] != str(self.initials('fb_duration'))
        sb_break_duration = self.cleaned_data['second_break_duration'] != str(self.initials('sb_duration'))
        nb = self.cleaned_data['nb'] != str(self.initials('nb'))
        if day_start or duration or first_break or second_break or fb_break_duration or sb_break_duration or nb:
            return True
        return False
