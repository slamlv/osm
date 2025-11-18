# Create your views here.

from django.db.models import Q
from django.forms import model_to_dict
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from authentification.models import School, User
from authentification.tokens import generate_token
from authentification.forms import UserForm
from classroom.models import Enseignements
from osm.forms import SearchForm
from .forms import MemberForm, ActivityForm
from .models import Personnel, Discipline, Activities
from osm.utils import message, one_escape, LoggedUserView, LoggedAdminView, logged_admin_view, ListView, DeleteView,\
    DetailView, ADetailView, BaseStaffMemberTimetable, AdminRequired, WithUsersSchoolSchema, LoginRequired,\
    NonAdminListView
import os


class StaffMemberTimetable(AdminRequired, WithUsersSchoolSchema, BaseStaffMemberTimetable):
    pass


class UserTimetable(LoginRequired, WithUsersSchoolSchema, BaseStaffMemberTimetable):
    pass


# Liste des activités
class ActivitiesList(NonAdminListView):
    template_name = "activities.html"
    title = "Liste des Activités"
    objects = "activité(s)"
    model = Activities


# Ajout d'une activité
class ActivityAdd(LoggedAdminView):
    template_name = "activity_form.html"
    title = "Ajout d'une Activité"

    def get(self, *args, **kwargs):
        form = ActivityForm(context={'request': self.request})
        context = {"form": form, "title": self.title, "reset": "Tout effacer", 'back': reverse("activities")}
        return render(self.request, self.template_name, context=context)

    def post(self, *args, **kwargs):
        form = ActivityForm(self.request.POST, context={'request': self.request})
        context = {"form": form, "title": self.title, "reset": "Tout effacer", 'back': reverse("activities")}
        if form.is_valid():
            form.save()
            message(self.request, "Activité ajoutée avec succès.")
            return redirect("activities")
        return render(self.request, self.template_name, context=context)


# Modification d'une activité
class ActivityEdit(LoggedAdminView):
    template_name = "activity_form.html"
    title = "Mofifier une Activité"

    def get_object(self):
        activity_id = self.kwargs.get("id")
        activities = Activities.objects
        return get_object_or_404(activities, pk=activity_id)

    def get(self, *args, **kwargs):
        form = ActivityForm(context={'request': self.request}, instance=self.get_object())
        context = {"form": form, "title": self.title, "reset": "Tout effacer", 'back': reverse("activities")}
        return render(self.request, self.template_name, context=context)

    def post(self, *args, **kwargs):
        form = ActivityForm(self.request.POST, context={'request': self.request}, instance=self.get_object())
        context = {"form": form, "title": self.title, "reset": "Tout effacer", 'back': reverse("activities")}
        if form.is_valid():
            form.save()
            message(self.request, "Activité modifiée avec succès.")
            return redirect("activities")
        return render(self.request, self.template_name, context=context)


# Suppression d'une activité
class ActivityDelete(DeleteView):
    success_url = "activities"
    template_name = "delete.html"
    model = Activities
    alerte = "des activités programmées ?"
    title = "Suppression d'une activité"
    message = "Activité supprimée avec succès."


# Ajout d'un membre du Personnel
class StaffMemberAdd(LoggedAdminView):
    template_name = "add_staff_member.html"
    title = "Ajout d'un membre du Personnel"

    def get(self, *args, **kwargs):
        form = MemberForm(context={'request': self.request})
        context = {"form": form, "title": self.title, "reset": "Tout effacer", 'back': reverse("staff")}
        return render(self.request, self.template_name, context=context)

    def post(self, *args, **kwargs):
        form = MemberForm(self.request.POST, context={'request': self.request})
        context = {"form": form, "title": self.title, "reset": "Tout effacer", 'back': reverse("staff")}
        if form.is_valid():
            member = form.save()
            Personnel.add_disciplines(member, form.cleaned_data.get("discipline"))
            message(self.request, "Membre du personnel ajouté avec succès.")
            return redirect("staff")
        return render(self.request, self.template_name, context=context)


class Staff(ListView):
    template_name = "staff_list.html"
    title = "Membres du Personnel"
    objects = "membre(s) du personnel"
    model = Personnel


# Modification des informations d'un membre du Personnel
class StaffMemberEdit(LoggedAdminView):
    template_name = "add_staff_member.html"
    title = "Modification des informations"

    def get(self, *args, **kwargs):
        member = self.get_object()
        form = MemberForm(context={'request': self.request}, instance=member)
        context = {"form": form, "title": self.title, 'reset': "Annuler les changements", 'back': reverse("staff")}
        return render(self.request, self.template_name, context)

    def get_object(self):
        member_id = self.kwargs.get("id")
        members = Personnel.objects.select_related('user')
        return get_object_or_404(members, pk=member_id)

    def post(self, *args, **kwargs):
        before = self.get_object().discipline.all().__str__()
        default = self.get_object()
        form = MemberForm(self.request.POST, context={'request': self.request}, instance=self.get_object())
        if form.is_valid():
            member = form.save()
            Personnel.update_disciplines(member, form.cleaned_data.get("discipline"))
            if (model_to_dict(default) != model_to_dict(member)) or (before != member.discipline.all().__str__()):
                if member.user:
                    User.objects.filter(pk=member.user.pk).update(last_name=member.nom, first_name=member.prenom,
                                                                  contact=member.contact, email=member.email,
                                                                  civilite=member.civilite, poste=member.poste)
                message(self.request, "Informations du membre du personnel modifiées avec succès !")
            return redirect("staff")
        context = {"form": form, "title": self.title, 'reset': "Annuler les changements", 'back': reverse("staff")}
        return render(self.request, self.template_name, context)


# Suppression d'un membre du personnel
class StaffMemberDelete(DeleteView):
    success_url = "staff"
    template_name = "delete.html"
    model = Personnel
    alerte = "des membres du Personnel ?"
    title = "Suppression d'un membre du Personnel"
    message = "Membre du Personnel supprimé avec succès."


# Suppression d'un utilisateur
class UserDelete(DeleteView):
    success_url = "users"
    template_name = "delete.html"
    alerte = "des utilisateurs ?"
    model = User
    title = "Suppression d'un Utilisateur"
    message = "Utilisateur supprimé avec succès."


# Affichage des informations d'un membre du personnel
class StaffDetails(ADetailView):
    title = "Détails sur le membre du Personnel"
    template_name = "staff_member_details.html"
    model = Personnel


# Affichage des informations de l'utilisateur connecté
class UserDetails(DetailView):
    title = "Mes informations"
    template_name = "user_details.html"
    model = Personnel


# Liste des utilisateurs
class Users(ListView):
    template_name = "users.html"
    title = "Comptes utilisateurs"
    model = User
    objects = "utilisateur(s)"


# Informations sur l'utilisateur
class Details(ADetailView):
    title = "Informations sur l'utilisateur"
    template_name = "details.html"
    model = User


# Edition des informations de l'utilisateur connecté
class UserEdit(LoggedUserView):
    template_name = "add_staff_member.html"
    title = "Modifier mes informations"

    def get(self, *args, **kwargs):
        form_context = {'request': self.request, 'user': True, 'pp': True}
        form = MemberForm(context=form_context, instance=self.get_object())
        context = {"title": self.title, "form": form, 'reset': "Annuler les changements",
                   'back': reverse('user-details')}
        return render(self.request, self.template_name, context)

    def get_object(self):
        members = Personnel.objects.select_related('user')
        return get_object_or_404(members, user_id=self.request.user.pk)

    def post(self, *args, **kwargs):
        old_image = self.get_object().photo
        form_context = {'request': self.request, 'user': True, 'pp': True}
        form = MemberForm(self.request.POST, self.request.FILES, instance=self.get_object(), context=form_context)
        if form.is_valid():
            if form.has_changed():
                user = self.request.user
                user.username = form.cleaned_data['username']
                user.first_name, user.last_name = form.cleaned_data['prenom'], form.cleaned_data['nom']
                user.email = form.cleaned_data['email']
                user.save()
                member = form.save()
                image = form.cleaned_data["photo"]
                if old_image and old_image != image:
                    if os.path.exists(old_image.path):
                        os.remove(old_image.path)
                Personnel.update_disciplines(member, form.cleaned_data.get("discipline"))
                message(self.request, "Vos informations ont étés modifiées avec succès.")
            return redirect("user-details")
        context = {"title": self.title, "form": form, 'reset': "Annuler les changements",
                   'back': reverse('user-details')}
        return render(self.request, self.template_name, context)


def has_changed(instance, cleaned_data):
    instance_dict = model_to_dict(instance)
    values = list()
    for field, value in instance_dict.items():
        if field == 'first_name':
            values.append(('prenom', value.title()))
        elif field == 'last_name':
            values.append(('nom', value.upper()))
    if values:
        for value in values:
            instance_dict[value[0]] = value[1]
    for field, new_value in cleaned_data.items():
        if field not in instance_dict:
            continue
        old_value = instance_dict.get(field)
        if old_value != new_value:
            return True
    for field in instance._meta.get_fields():
        if field.many_to_many and not field.auto_created:
            print(field.name)
            old_ids = list(getattr(instance, field.name).values_list('id', flat=True))
            new_ids = cleaned_data.get(field.name)
            if new_ids is None:
                continue
            new_ids = list(new_ids.values_list('id', flat=True)) if hasattr(new_ids, 'values_list') else list(new_ids)
            if sorted(old_ids) != sorted(new_ids):
                return True
    return False


class AddUser(LoggedAdminView):
    title = "Ajouter un utilisateur"
    template = "add_staff_member.html"

    def get(self, *args, **kwargs):
        form = MemberForm(context={'request': self.request, 'user': True})
        context = {"form": form, 'title': self.title, 'reset': "Tout Effacer", 'back': reverse("users")}
        return render(self.request, self.template, context=context)

    def post(self, *args, **kwargs):
        form = MemberForm(self.request.POST, context={'request': self.request, 'user': True})
        context = {"form": form, 'title': self.title, 'reset': "Tout Effacer", 'back': reverse("users")}
        if form.is_valid():
            first_name = one_escape(form.cleaned_data.get("prenom")).title()
            last_name = one_escape(form.cleaned_data.get("nom")).upper()
            civilite = form.cleaned_data.get("civilite")
            poste = form.cleaned_data.get("poste")
            username = form.cleaned_data.get("username")
            contact = form.cleaned_data.get("contact")
            email = form.cleaned_data.get("email")
            school = self.request.user.school
            new_user = User(first_name=first_name, last_name=last_name, username=username, email=email,
                            civilite=civilite, poste=poste, contact=contact, school=school, is_active=True)
            new_user.set_password("123456")

            new_user.save()
            Personnel.add_disciplines(Personnel.objects.get(user=new_user),
                                      Personnel.get_disciplines(form.cleaned_data.get("discipline")))
            Personnel.objects.filter(user=new_user).update(grade=form.cleaned_data.get('grade'),
                                                           since=form.cleaned_data.get('since'))
            message(self.request, "Compte utilisateur crée avec succès")
            return redirect("users")
        return render(self.request, self.template, context=context)


@logged_admin_view
def admin(request, pk: int):
    user = User.objects.prefetch_related('staff_member__enseignant__matiere__sujet').get(pk=pk)
    member = user.staff_member.all()[0]
    if user.is_admin:
        user.is_admin = False
    else:
        user.is_admin = True
    user.save()
    return render(request, "reload_details.html", {"object": member, 'm_user': user})


@logged_admin_view
def active(request, pk: int):
    user = User.objects.prefetch_related('staff_member__enseignant__matiere__sujet').get(pk=pk)
    member = user.staff_member.all()[0]
    if user.is_active:
        user.is_active = False
    else:
        user.is_active = True
    user.save()
    return render(request, "reload_details.html", {"object": member, 'm_user': user})
