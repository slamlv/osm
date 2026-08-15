from django import forms
from email_validator import validate_email, EmailNotValidError
from .models import User, School, Civilite, Poste
from staff.models import Discipline
from staff.models import Personnel
from osm.utils import is_alphanumeric, one_escape, message
from dynamic_forms import DynamicField, DynamicFormMixin
from django_tenants.utils import schema_context


# Validation de l'email
def valid_email(email, request, check=False):
    try:
        infos = validate_email(email, check_deliverability=check)
    except EmailNotValidError as error:
        message(request, "Veillez renseigner une adresse email valide", msg_type="warning")
        raise forms.ValidationError("")
    else:
        return infos.normalized


# Validation simple du mot de passe
def valid_password(mdp, request):
    if len(mdp) < 4:
        message(request, "Le mot de passe doit contenir au moins 4 caractères.", msg_type="warning")
        raise forms.ValidationError("")


# Validation des mots de passe
def valid_passwords(mdp, mdp_confirm, request):
    valid_password(mdp, request)
    valid_password(mdp_confirm, request)
    if mdp != mdp_confirm:
        message(request, "Les deux mots de passe doivent êtres identiques.", msg_type="warning")
        raise forms.ValidationError("")


# Validation partielle du nom d'utilisateur
def valid_username(username, request):
    if not username.isalnum():
        message(request, "Le nom d'utilisateur doit être une chaîne alphanumérique.", msg_type="warning")
        raise forms.ValidationError("")
    elif username[0].isdigit():
        message(request, "Le nom d'utilisateur ne peut pas commencer par un chiffre.", msg_type="warning")
        raise forms.ValidationError("")
    elif len(username) < 4:
        message(request, "Le nom d'utilisateur doit contenir au moins 4 caractères.", msg_type="warning")
        raise forms.ValidationError("")
    else:
        return False


# Validation du Contact téléphonique
def valid_contact(contact, request, objet="Le contact"):
    if not contact.isnumeric() or len(contact) < 9:
        message(request, f"{objet} doit être une suite de 9 chiffres.", msg_type="warning")
        raise forms.ValidationError("")


# TODO: Deux membres du personnel ou deux élèves avec les mêmes noms
# Validation du nom et du prénom
def valid_name(nom, prenom, queryset, request, date=None, school=False):
    if not is_alphanumeric(nom) or not is_alphanumeric(prenom):
        if school:
            message(request, "Nom et Name doivent être des chaînes alphanumériques.", msg_type="warning")
        else:
            message(request, "Le nom et le prénom doivent être des chaînes alphanumériques.", msg_type="warning")
        raise forms.ValidationError("")
    if date:
        member = queryset.filter(nom=one_escape(nom).upper(), prenom=one_escape(prenom).title(), date_naissance=date)
        if member.exists():
            message(request, f"Un élève du même nom et né le même jour a déjà été enregistré.", msg_type="warning")
            raise forms.ValidationError("")


class CodeForm(DynamicFormMixin, forms.Form):

    code = forms.CharField(label="Code Établissement", max_length=10, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le code de votre établissement", 'class': "form-control", 'id': "code"
    }))

    def clean(self):
        # Validation du code
        if not School.objects.filter(code=self.cleaned_data.get("code")).exists():
            message(self.context['request'], "Code établissement non reconnu, veuillez contacter votre administrateur.",
                    msg_type="warning")
            raise forms.ValidationError("")


class UserForm(DynamicFormMixin, forms.Form):

    nom = forms.CharField(max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le nom", 'id': "nom", 'class': "form-control fw-bold"}))
    prenom = forms.CharField(max_length=30, widget=forms.TextInput(attrs={
        "placeholder": "Entrez le prénom", 'id': "prenom", 'class': "form-control fw-bold"}), required=False)
    civilite = forms.ChoiceField(choices=Civilite.choices, widget=forms.Select(attrs={
        'id': "civilite", 'class': "form-select woption fw-bold"}))
    poste = forms.ChoiceField(choices=Poste.choices, widget=forms.Select(attrs={
        'id': "poste", 'class': "form-select woption fw-bold"}))
    discipline = DynamicField(forms.ModelMultipleChoiceField, widget=forms.SelectMultiple(attrs={
        'class': "form-select choices-multiple", 'multiple': "multiple"}), queryset=lambda form: form.get(),
                              required=False)
    contact = forms.CharField(max_length=9, widget=forms.TextInput(attrs={
        'placeholder': "Numéro de téléphone", 'id': "contact", 'class': "form-control fw-bold"}))
    mail = DynamicField(forms.CharField, widget=forms.TextInput(attrs={
        'placeholder': "Entrez l'adresse email", 'id': "mail", 'class': "form-control fw-bold"}))
    username = forms.CharField(max_length=15, widget=forms.TextInput(attrs={
        "placeholder": "Choisissez un nom d'utilisateur", 'id': "username", 'class': "form-control fw-bold"}))
    mdp = forms.CharField(max_length=15, widget=forms.PasswordInput(attrs={
        "placeholder": "Choisissez un mot de passe", 'id': "mdp", 'class': "form-control fw-bold"}))
    mdp_confirm = DynamicField(forms.CharField, max_length=15, widget=forms.PasswordInput(attrs={
        "placeholder": "Répétez le mot de passe", 'id': "cmdp", 'class': "form-control fw-bold"}))

    def get(self):
        return Discipline.get_disciplines()

    def clean(self):
        nom = self.cleaned_data.get("nom")
        prenom = self.cleaned_data.get("prenom")
        contact = self.cleaned_data.get("contact")
        mdp = self.cleaned_data.get("mdp")
        mdp_confirm = self.cleaned_data.get("mdp_confirm")
        username = self.cleaned_data.get("username")
        staff = Personnel.objects_all

        # Contrainte pour les chefs d'établissement
        poste = self.cleaned_data.get("poste")
        if poste in "Chef d'Établissement":
            if staff.filter(poste="Chef d'Établissement").exists():
                message(self.context['request'], "Un chef d'établissement a déjà été enregistré pour cet "
                                                 "établissement", msg_type="warning")
                raise forms.ValidationError("")

        # Validation du nom et du prénom
        valid_name(nom, prenom, queryset=staff.all(), request=self.context['request'])

        # Validation du contact et de l'email
        valid_contact(contact, self.context['request'])
        if staff.filter(contact=contact).exists():
            message(self.context['request'], "Ce contact a déjà été enregistré pour cet établissement.", msg_type="warning")
            raise forms.ValidationError("")
        email = valid_email(self.cleaned_data.get("mail"), check=True, request=self.context['request'])
        if staff.filter(email=email).exists():
            message(self.context['request'], "cet email a déjà été enregistré pour cet établissement.", msg_type="warning")
            raise forms.ValidationError("")

        # Validation du nom d'utilisateur
        if not valid_username(username, request=self.context['request']):
            if User.objects.filter(username=username).exists():
                message(self.context['request'], "Nom d'utilisateur indisponible, veuillez en choisir un autre.", msg_type="warning")
                raise forms.ValidationError("")

        # Validation des mots de passe
        valid_passwords(mdp, mdp_confirm, request=self.context.get('request'))


class LoginForm(forms.Form):

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    username = forms.CharField(required=True, max_length=15, widget=forms.TextInput(attrs={
        'placeholder': "Entrez votre nom d'utilisateur", 'class': "form-control fw-bold", 'id': "username"
    }))
    mdp = forms.CharField(required=True, max_length=15, widget=forms.PasswordInput(attrs={
        "placeholder": "Entrez votre mot de passe", 'class': "form-control fw-bold pwd-input", 'id': "mdp"
    }))

    def clean(self):
        username = self.cleaned_data.get("username")
        mdp = self.cleaned_data.get("mdp")

        # Validation du nom d'utilisateur
        if not valid_username(username, self.request):
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                message(self.request, "Nom d'utilisateur introuvable.", msg_type="warning")
                raise forms.ValidationError("")
            else:
                if user.is_superuser:
                    message(self.request, "Utilisateur non autorisé.", msg_type="warning")
                    raise forms.ValidationError("")
                else:
                    # Validation du mot de passe
                    valid_password(mdp, self.request)
                    if not user.check_password(mdp):
                        message(self.request, "Combinaison nom d'utilisateur/mot de passe incorrecte.",
                                msg_type="warning")
                        raise forms.ValidationError("")
                    elif not user.is_active:
                        message(self.request, "Compte non activé ou désactivé, veuillez vérifier votre adresse email "
                                              "ou contacter un administrateur.", msg_type="warning")
                        raise forms.ValidationError("")


class ResetForm(DynamicFormMixin, forms.Form):
    username = forms.CharField(max_length=15, widget=forms.TextInput(attrs={
        "placeholder": "Entrez votre nom d'utilisateur", 'id': "username", 'class': "form-control fw-bold"}))
    email = forms.CharField(label="Votre email", required=True, widget=forms.TextInput(attrs={
        "placeholder": "Entrez votre adresse électronique", 'class': "form-control fw-bold", 'id': "email"}))

    def clean(self):
        user = None
        username = self.cleaned_data.get("username")

        # Validation du nom d'utilisateur
        if not valid_username(username, self.context['request']):
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                message(self.context['request'], "Nom d'utilisateur introuvable.", msg_type="warning")
                raise forms.ValidationError("")
            else:
                if user.is_superuser:
                    message(self.context['request'], "Nom d'utilisateur introuvable.", msg_type="warning")
                    raise forms.ValidationError("")

        # Validation de l'email
        email = self.cleaned_data['email']
        email = valid_email(email, self.context['request'])
        if email and user:
            from django_tenants.utils import schema_context
            with schema_context(user.school.schema_name):
                if not Personnel.objects_all.filter(email=email).exists():
                    message(self.context['request'], "Adresse électronique (email) introuvable.", msg_type="warning")
                    raise forms.ValidationError("")


class PasswordForm(DynamicFormMixin, forms.Form):
    old_mdp = DynamicField(forms.CharField, required=True, max_length=15, widget=forms.PasswordInput(attrs={
        "placeholder": "Mot de passe actuel", 'class': "form-control fw-bold", 'id': "old_mdp"
    }), include=lambda form: form.context['is_auth'])
    mdp = forms.CharField(required=True, max_length=15, widget=forms.PasswordInput(attrs={
        "placeholder": "Choisissez un nouveau mot de passe", 'class': "form-control fw-bold pwd-input", 'id': "mdp"
    }))
    mdp_confirm = forms.CharField(required=True, max_length=15, widget=forms.PasswordInput(attrs={
        "placeholder": "Répétez le mot de passe", 'class': "form-control fw-bold pwd-input", 'id': "mdp_confirm"
    }))

    def clean(self):
        if self.context['is_auth']:
            old_mdp = self.cleaned_data['old_mdp']
            valid_password(old_mdp, self.context['request'])
            user = self.context['request'].user
            if not user.check_password(old_mdp):
                message(self.context['request'], 'Le mot de passe actuel ne correspond pas.', msg_type="warning")
                raise forms.ValidationError("")
        mdp = self.cleaned_data.get("mdp")
        mdp_confirm = self.cleaned_data.get("mdp_confirm")

        # Validation des mots de passe
        valid_passwords(mdp, mdp_confirm, self.context['request'])
