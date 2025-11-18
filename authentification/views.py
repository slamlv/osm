# Create your views here.
from datetime import datetime

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from osm.utils import one_escape, greet, message, wraps
from .models import User, School
from staff.models import Personnel
from .forms import UserForm, LoginForm, PasswordForm, ResetForm, CodeForm
from mail.utils import send_the_mail
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.sites.shortcuts import get_current_site
from .tokens import generate_token
from django_tenants.utils import schema_context


def with_school_schema(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        with schema_context(School.objects.get(code=request.session.get('code')).schema_name):
            return view_func(request, *args, **kwargs)

    return _wrapped_view


def anonymous_required(view):
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("index")
        return view(request, *args, **kwargs)
    return wrapper


# Vérification du code
@anonymous_required
def code(request):
    form = CodeForm(context={'request': request})
    if request.method == "POST":
        form = CodeForm(request.POST or None, context={'request': request})
        if form.is_valid():
            code_ets = form.cleaned_data['code']
            request.session['code'] = code_ets
            return redirect("signup")
    return render(request, "signup.html", {"form": form, 'coded': False, 'title': "Création de Compte"})


# Création de compte
@anonymous_required
@with_school_schema
def signup(request):
    school_code = request.session.get('code')
    form = UserForm(context={'request': request})
    if request.method == "POST":
        form = UserForm(request.POST or None, context={'request': request})
        if form.is_valid():
            first_name = one_escape(form.cleaned_data.get("prenom")).title()
            last_name = one_escape(form.cleaned_data.get("nom")).upper()
            email = form.cleaned_data.get("mail")
            civilite = form.cleaned_data.get("civilite")
            poste = form.cleaned_data.get("poste")
            username = form.cleaned_data.get("username")
            contact = form.cleaned_data.get("contact")
            school = School.objects.get(code=school_code)
            mdp = form.cleaned_data.get("mdp")
            new_user = User(first_name=first_name, last_name=last_name, username=username, email=email,
                            civilite=civilite, poste=poste, contact=contact, school=school, is_active=False)
            new_user.set_password(mdp)
            new_user.save()
            salutation = f"{greet()} {f'{new_user.first_name.split()[0]} ' if new_user.first_name else ''}{new_user.last_name.split()[0]}"
            domain = get_current_site(request).domain
            uid = urlsafe_base64_encode(force_bytes(new_user.pk))
            token = generate_token.make_token(new_user)
            context = {"salutation": salutation, "domain": domain, "uid": uid, "token": token}
            has_send = send_the_mail(subject="Confirmez votre email pour Oméga School Manager", receivers=[email, ],
                                     template="confirmation_email.html", context=context)
            if has_send:
                staff_member = Personnel.objects.get(user_id=new_user.pk)
                Personnel.add_disciplines(staff_member,
                                          Personnel.get_disciplines(form.cleaned_data.get("discipline")))
                message(request, """Compte créé avec succès, veillez consulter votre boîte mail pour
                                    confirmer votre compte. Vérifiez vos spams si vous ne retrouvez pas le message""")
                del request.session['code']
                return redirect("signin")
            else:
                new_user.delete()
                message(request, "L'envoi de mail a échoué, veuillez re-essayer", msg_type="warning")
    return render(request, "signup.html", {"form": form, 'coded': True, 'title': "Création de Compte"})


# Connexion
@anonymous_required
def signin(request):
    form = LoginForm(request=request)
    if request.method == "POST":
        form = LoginForm(request.POST or None, request=request)
        if form.is_valid():
            username = form.cleaned_data.get("username")
            mdp = form.cleaned_data.get("mdp")
            user = authenticate(username=username, password=mdp)
            if datetime.today().date() > user.school.licence:
                return render(request, "404_unauthenticated.html", {'license': True if user.is_admin else False})
            if user:
                login(request, user)
                return redirect("index")
    return render(request, "signin.html", {"form": form, 'title': "Connexion"})


# Activation du compte
@anonymous_required
def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user is not None and generate_token.check_token(user, token) and not user.is_active:
        user.is_active = True
        user.save()
        message(request, "Compte activé avec succès, vous pouvez désormais vous connecter.")
    elif user is not None and user.is_active:
        message(request, "Votre compte a déjà été activé, vous pouvez vous connecter.")
    else:
        message(request, "L'activation a échouée!", msg_type="warning")
    return redirect("signin")


# Déconnexion
@login_required(login_url="signin")
def signout(request):
    logout(request)
    message(request, "Vous êtes déconnecté.")
    return redirect("signin")


# Réinitialisation du mot de passe
@anonymous_required
def reset_password(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        pass
    else:
        if user is None or not generate_token.check_token(user, token):
            message(request, "Ce lien n'est plus valide.", msg_type="warning")
            return redirect("signin")
        form = PasswordForm(context={'is_auth': False})
        base_template = "unauthenticated_base.html"
        if request.method == "POST":
            form = PasswordForm(request.POST or None, context={'is_auth': False, 'request': request})
            if form.is_valid():
                mdp = form.cleaned_data.get("mdp")
                user.set_password(mdp)
                user.save()
                message(request, "Mot de passe redéfini avec succès.")
                return redirect("signin")
        context = {"form": form, 'title': "Nouveau mot de passe", 'base_template': base_template, 'is_auth': False}
        return render(request, "password.html", context)
    return render(request, "404.html")


@login_required(login_url="signin")
def change_password(request):
    form = PasswordForm(context={'is_auth': True})
    user = request.user
    base_template = "base.html"
    if request.method == "POST":
        form = PasswordForm(request.POST or None, context={'is_auth': True, 'request': request})
        if form.is_valid():
            mdp = form.cleaned_data.get("mdp")
            user.set_password(mdp)
            user.save()
            message(request, "Mot de passe redéfini avec succès.")
            return redirect("user-details")
    context = {"form": form, 'title': "Nouveau mot de passe", 'base_template': base_template, 'is_auth': True}
    return render(request, "password.html", context)


# Initialisation de la réinitialisation du mot de passe
@anonymous_required
def reset(request):
    form = ResetForm(context={'reqeust': request})
    if request.method == "POST":
        form = ResetForm(request.POST or None, context={'request': request})
        if form.is_valid():
            username = form.cleaned_data.get("username")
            email = form.cleaned_data.get("email")
            user = User.objects.get(username=username, email=email)
            if not user.is_active:
                message(request, "Compte non activé, vous ne pouvez pas changer de mot de passe.", msg_type="warning")
                return redirect("signin")
            salutation = f"{greet()} {f'{user.first_name.split()[0]} ' if user.first_name else ''}{user.last_name.split()[0]}"
            domain = get_current_site(request).domain
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = generate_token.make_token(user)
            context = {"salutation": salutation, "domain": domain, "uid": uid, "token": token}
            has_send = send_the_mail(subject="Réinitialisation de mot de passe", receivers=[email, ],
                                     template="password_reset_email.html", context=context)
            if has_send:
                message(request, "Veillez consulter votre boîte mail pour définir un nouveau mot de passe."
                                 " Vérifiez vos spams si vous ne retrouvez pas le message")
                return redirect("signin")
            else:
                message(request, "L'envoi de mail a échoué, veuillez re-essayer", msg_type="warning")
    return render(request, "reset.html", {"form": form, 'title': "Réinitialisation de mot de passe"})
