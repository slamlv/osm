# Create your views here.

from django.db import transaction
from django.db.models import Q
from django.forms import model_to_dict
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from authentification.models import User
from classroom.models import Enseignements
from .forms import MemberForm, ActivityForm, ProgressionForm
from note.forms import SelectForm
from .models import Personnel, Activities
from osm.utils import message, one_escape, LoggedUserView, LoggedAdminView, logged_admin_view, ListView, DeleteView,\
    DetailView, ADetailView, BaseStaffMemberTimetable, AdminRequired, WithUsersSchoolSchema, LoginRequired,\
    NonAdminListView, logged_super_admin_view


"""
=============================================================================
 DÉSIGNATION DES RÔLES DÉLÉGUÉS (super_admin et financial_user)
=============================================================================
 Page unique, deux sections, chacune protégée selon le droit de désigner :
   - Super administrateurs : SEUL LE CHEF peut désigner/révoquer.
   - Responsables financiers : le CHEF ou un SUPER_ADMIN.

 On protège la VUE au niveau super_admin (accès à la page), et on filtre
 la SECTION super_admin sur le chef à l'intérieur (un super_admin voit la
 liste mais ne peut pas modifier les super_admins).
=============================================================================
"""


@logged_super_admin_view
def delegated_roles(request):
    candidates = (User.objects.filter(is_active=True, is_superuser=False, school=request.user.school)
                  .order_by("last_name", "first_name"))
    user_is_chief = request.user.is_principal

    if request.method == "POST":
        action = request.POST.get("action")
        target = get_object_or_404(User, pk=request.POST.get("user_id"))
        now = timezone.now()

        # ----- SUPER_ADMIN : réservé au CHEF -----
        if action in ("grant_super", "revoke_super"):
            if not user_is_chief:
                message(request, "Seul le chef d'établissement peut gérer les super administrateurs.", msg_type="error")
                return redirect(request.path)
            if action == "grant_super" and not target.is_super_admin:
                target.is_super_admin = True
                target.named_super_admin_by = request.user
                target.named_super_admin_at = now
                target.save(update_fields=["is_super_admin", "named_super_admin_by", "named_super_admin_at"])
                message(request, f"{target.full_name or target} est désormais super administrateur.")
            elif action == "revoke_super" and target.is_super_admin:
                target.is_super_admin = False
                target.save(update_fields=["is_super_admin"])
                message(request, f"{target.full_name or target} n'est plus super administrateur.")

        # ----- FINANCIAL_USER : chef OU super_admin -----
        elif action in ("grant_fin", "revoke_fin"):
            if action == "grant_fin" and not target.is_financial_user:
                target.is_financial_user = True
                target.named_financial_user_by = request.user
                target.named_financial_user_at = now
                target.save(update_fields=["is_financial_user", "named_financial_user_by", "named_financial_user_at"])
                message(request, f"{target.full_name or target} est désormais responsable financier.")
            elif action == "revoke_fin" and target.is_financial_user:
                target.is_financial_user = False
                target.save(update_fields=["is_financial_user"])
                message(request, f"{target.full_name or target} n'est plus responsable financier.")
        return redirect(request.path)
    return render(request, "delegated_roles.html", {
        "user_is_chief": user_is_chief, "super_admins": candidates.filter(is_super_admin=True),
        "financial_users": candidates.filter(is_financial_user=True), "non_super": candidates.filter(is_super_admin=False),
        "non_financial": candidates.filter(is_financial_user=False), 'title': "Délégation des Rôles"
    })


class StaffArchive(LoggedAdminView):
    template_name = "staff_list.html"

    def get(self, *args, **kwargs):
        datas = (
            Personnel.objects_all
            .filter(en_poste=False)
            .select_related("user")
            .order_by_poste()
        )
        return render(self.request, self.template_name, {
            "info": "Anciens membres du personnel.",
            "datas": datas,
            "search": False,
            "archive_mode": True,
            "archive_count": datas.count(),
        })


class StaffToggleEnPoste(LoggedAdminView):
    def post(self, *args, **kwargs):
        staff = get_object_or_404(Personnel.objects_all, pk=self.kwargs["id"])
        if staff.en_poste:
            staff.leave_school()
            message(self.request, f"{staff} n'apparaitra pls dans les listes. Son compte d'accès a été désactivé.")
        else:
            staff.reinstate()
            message(self.request, f"{staff} a été réintégré(e).")
        nxt = self.request.POST.get("next")
        return redirect(nxt) if nxt else redirect("staff_archive")


class DeleteArchivedStaff(LoggedAdminView):
    template_name = "students_bulk_delete.html"

    def get_targets(self):
        return Personnel.objects_all.filter(en_poste=False)

    def get(self, *args, **kwargs):
        targets = self.get_targets()
        return render(self.request, self.template_name, {
            "title": "Vider la corbeille du personnel",
            "count": targets.count(),
            "alerte": ("Cette action est IRRÉVERSIBLE : les anciens membres du personnel seront "
                       "définitivement supprimés (et leurs comptes pour ceux qui en ont)."),
            "back": "staff_archive",
        })

    def post(self, *args, **kwargs):
        targets = self.get_targets()
        n = targets.count()
        if n:
            with transaction.atomic():
                for staff in targets:
                    staff.delete()
            message(self.request, f"{n} ancien(s) membre(s) supprimé(s) définitivement.")
        else:
            message(self.request, "La corbeille du personnel est déjà vide.", msg_type="warning")
        return redirect("staff_archive")


class Progression(LoggedUserView):
    template_name = "progression.html"
    title = "Couverture des Programmes"

    def get(self, *args, **kwargs):
        i = kwargs.get("id")
        if (not self.request.user.is_admin) and i != self.request.user.staff_member.pk:
            return render(self.request, "404.html")
        msg, staff_member = ProgressionSelectForm.check(self, i)
        if i == 0 or i == self.request.user.staff_member.pk:
            titre = "Ma progression"
            is_user = True
        else:
            titre = f"État de la progression de {staff_member.short_firstname}"
        context = {'title': self.title, 'titre': titre}
        if msg:
            context['msg'] = msg
        else:
            context['progression'] = staff_member.progression
            context['is_user'] = is_user
        return render(self.request, self.template_name, context)


class ProgressionSelectForm(LoggedUserView):
    template_name = "edit_marks.html"
    title = "Couverture des Programmes"

    @classmethod
    def check(cls, self, i=None):
        if i is not None and i > 0:
            staff_member = Personnel.objects.get(pk=i)
        else:
            staff_member = self.request.user.staff_member
        msg, enseignements = "", None
        if staff_member.rapporteur.exists() or staff_member.enseignant.exists():
            if i is None:
                enseignements = staff_member.enseignant.select_related('matiere__sujet', 'classroom')
        else:
            msg = "Vous n'êtes affecté à aucune salle de classe"
            if i is not None and i > 0 and i != self.request.user.staff_member.pk:
                msg = "Ce membre du personnel n'est affecté à aucune salle de classe"
        if i is not None:
            return msg, staff_member
        return msg, enseignements

    def get(self, *args, **kwargs):
        msg, enseignements = ProgressionSelectForm.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(context={"request": self.request, 'trim': False, 'enseignements': enseignements,
                                              'progression': True})
            context = {'progression': True, 'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        msg, enseignements = ProgressionSelectForm.check(self)
        if msg:
            context = {'title': self.title, 'msg': msg}
        else:
            select_form = SelectForm(self.request.POST,
                                     context={"request": self.request, 'trim': False, 'enseignements': enseignements,
                                              'progression': True})
            context = {'progression': True, 'title': self.title, 'select_form': select_form}
        return render(self.request, self.template_name, context)


class ProgressionEdit(LoggedUserView):
    template_name = "progression_form.html"

    def get(self, *args, **kwargs):
        label, classroom_id = self.request.GET['matiere'], self.request.GET['classroom']
        enseignements = Enseignements.objects.filter(Q(matiere__sujet__label=label) | Q(matiere__sujet__matiere=label),
                                                     classroom_id=classroom_id)
        instance = enseignements.first()
        label = instance.true_name
        progression_form = ProgressionForm(instance=instance, context={'enseignements': enseignements})
        prefix = "d'" if label[0] in ['A', 'E', 'H', 'I', 'O', 'U', 'Y'] else "de "
        return render(self.request, self.template_name, context={'title': f"Progression {prefix}{label}",
                                                                 'progression_form': progression_form})

    def post(self, *args, **kwargs):
        label, classroom_id = self.request.POST['matiere'], self.request.POST['classroom']
        enseignements = Enseignements.objects.filter(Q(matiere__sujet__label=label) | Q(matiere__sujet__matiere=label),
                                                     classroom_id=classroom_id)
        instance = enseignements.first()
        label = instance.true_name
        progression_form = ProgressionForm(self.request.POST,instance=instance,
                                           context={'enseignements': enseignements, 'request': self.request})
        if progression_form.is_valid():
            if progression_form.has_changed():
                progression_form.save_progression()
                message(self.request, "Données sauvegardées avec succès")
            else:
                message(self.request, "Aucune modification effectuée", msg_type="warning")
            response =  HttpResponse()
            response['HX-Redirect'] = reverse("progression", args=[0])
            return response
        prefix = "d'" if label[0] in ['A', 'E', 'H', 'I', 'O', 'U', 'Y'] else "de "
        response =  render(self.request, self.template_name, context={'title': f"Progression {prefix}{label}",
                                                                      'progression_form': progression_form})
        response['HX-Trigger'] = 'AJAXMessages'
        return response


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
        members = Personnel.objects_all.select_related('user')
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
            return redirect("staff-details", id=default.pk)
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
        members = Personnel.objects_all.select_related('user')
        return get_object_or_404(members, user_id=self.request.user.pk)

    def post(self, *args, **kwargs):
        from osm.utils import delete_image
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
                    delete_image(old_image)
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
            Personnel.add_disciplines(Personnel.objects_all.get(user=new_user),
                                      Personnel.get_disciplines(form.cleaned_data.get("discipline")))
            Personnel.objects_all.filter(user=new_user).update(grade=form.cleaned_data.get('grade'),
                                                           since=form.cleaned_data.get('since'))
            message(self.request, "Compte utilisateur crée avec succès")
            return redirect("users")
        return render(self.request, self.template, context=context)


@logged_admin_view
def admin(request, pk: int):
    user = User.objects.prefetch_related('staff_member__enseignant__matiere__sujet').get(pk=pk)
    member = user.staff_member
    if user.is_admin:
        user.is_admin = False
    else:
        user.is_admin = True
    user.save()
    return render(request, "reload_details.html", {"object": member, 'm_user': user})


@logged_admin_view
def active(request, pk: int):
    user = User.objects.prefetch_related('staff_member__enseignant__matiere__sujet').get(pk=pk)
    member = user.staff_member
    if user.is_active:
        user.is_active = False
    else:
        user.is_active = True
    user.save()
    return render(request, "reload_details.html", {"object": member, 'm_user': user})
