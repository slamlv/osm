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
from osm.utils import message, one_escape, LoggedUserView, LoggedAdminView, logged_admin_view, ListView, DeleteView, \
    DetailView, ADetailView, BaseStaffMemberTimetable, AdminRequired, WithUsersSchoolSchema, LoginRequired, \
    NonAdminListView, logged_super_admin_view, pdf_response, school_year, add_fonts, base_header, filigrane, \
    logged_user_view, safe_redirect_back
from datetime import date as _date
from fpdf import FPDF


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


"""
=============================================================================
 DOCUMENTS ADMINISTRATIFS — vue de génération
=============================================================================
 Un formulaire unique pour les trois documents. Les mentions se pré-remplissent
 depuis la fiche du personnel (côté navigateur, sans rechargement) et restent
 corrigeables. Une case répercute les valeurs saisies dans la fiche, afin que
 la donnée se fiabilise à l'usage.

 ANNÉE SCOLAIRE : librement choisie ou saisie — le document peut concerner une
 année ANTÉRIEURE à l'adoption d'OSM. Une case permet aussi de ne rien
 imprimer et de laisser un trait à compléter à la main.

 Une seule requête sur le personnel, limitée aux colonnes réellement
 affichées (`only`), et les propositions d'années sont calculées
 sans toucher la base.
=============================================================================
"""
#: nombre d'années proposées en plus de l'année courante (documents anciens)
YEARS_BACK = 15


def _parse_date(raw):
    try:
        return _date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _clean(raw):
    return (raw or "").strip()


def _year_choices(current):
    """Années proposées : l'année courante puis les précédentes.

    Calculées et non lues en base : un certificat peut porter sur une année
    bien antérieure à l'adoption d'OSM, pour laquelle aucune donnée n'existe.
    Le champ reste de toute façon libre (liste de suggestions, pas de select).
    """
    try:
        start = int(str(current).split("-")[0])
    except (ValueError, AttributeError):
        start = _date.today().year
    return [f"{y}-{y + 1}" for y in range(start, start - YEARS_BACK, -1)]


def _staff_queryset():
    """Colonnes strictement nécessaires à l'affichage et au pré-remplissage.
    `only` évite de charger photos, salaires et le reste de la fiche."""
    fields = ["id", "nom", "prenom", "civilite", "poste", "grade", "matricule", "provenance", "note_service_number",
              "note_service_date", "discipline_formation"]
    qs = Personnel.objects.exclude(poste="Chef d'Établissement").order_by("nom", "prenom")
    try:
        return qs.only(*fields)
    except Exception:          # un champ manque encore : on charge tout
        return qs


# ---------------------------------------------------------------------------
#  VUE
# ---------------------------------------------------------------------------
@logged_user_view
def service_documents(request):
    """GET : le formulaire. POST : génère le PDF (ou la version vierge)."""
    current = school_year()

    if request.method == "POST":
        kind = request.POST.get("kind") or "PRISE"
        if kind not in SERVICE_DOCS:
            message(request, "Type de document inconnu.", msg_type="error")
            return redirect("service_documents")
        pdf_class, label = SERVICE_DOCS[kind]
        blank = request.POST.get("blank") == "on"

        # année : imprimée seulement si la case est cochée
        year = (_clean(request.POST.get("year")) if request.POST.get("print_year") == "on" else "")

        # ---------- version vierge : aucun agent désigné ----------
        if blank:
            pdf = pdf_class(None, request.user.school, year, {}, blank=True)
            return pdf_response(pdf, f"{label} vierge.pdf")

        try:
            person = Personnel.objects.filter(pk=request.POST.get("personnel")).first()
        except Exception:
            person = None
        if person is None:
            message(request, "Veuillez choisir un membre du personnel.", msg_type="error")
            return redirect("service_documents")

        data = {
            "matricule":   _clean(request.POST.get("matricule")),
            "grade":       _clean(request.POST.get("grade")),
            "origin":      _clean(request.POST.get("origin")),
            "discipline":  _clean(request.POST.get("discipline")),
            "note_number": _clean(request.POST.get("note_number")),
            "note_date":   _parse_date(request.POST.get("note_date")),
            "duty_date":   _parse_date(request.POST.get("duty_date")),
            "qualite":     _clean(request.POST.get("qualite")),
        }

        # ---------- mise à jour facultative de la fiche ----------
        if request.POST.get("save_to_profile") == "on":
            mapping = [
                ("matricule",   "matricule",            data["matricule"]),
                ("grade",       "grade",                data["grade"]),
                ("provenance",  "provenance",           data["origin"]),
                ("note_number", "note_service_number",  data["note_number"]),
                ("note_date",   "note_service_date",    data["note_date"]),
                ("discipline",  "discipline_formation", data["discipline"]),
            ]
            fields = []
            for _key, attr, value in mapping:
                if not value or not hasattr(person, attr):
                    continue
                if getattr(person, attr) != value:
                    setattr(person, attr, value)
                    fields.append(attr)
            if fields:
                person.save(update_fields=fields)

        pdf = pdf_class(person, request.user.school, year, data)
        return pdf_response(pdf, f"{label} {person.short_name}.pdf")

    # ---------- GET : formulaire ----------
    rows = []
    staff_members = _staff_queryset()
    if not request.user.is_min_admin:
        staff_members = staff_members.filter(pk=request.user.staff_member.id)
    for p in staff_members:
        rows.append({
            "p": p,
            "matricule":   getattr(p, "matricule", "") or "",
            "grade":       getattr(p, "grade", "") or "",
            "provenance":  getattr(p, "provenance", "") or "",
            "note_number": getattr(p, "note_service_number", "") or "",
            "note_date":   (getattr(p, "note_service_date", None).isoformat() if getattr(p, "note_service_date", None) else ""),
            "discipline":  getattr(p, "discipline_formation", "") or "",
            "qualite":     default_qualite(p),
            # le formulaire n'affiche la discipline QUE pour un enseignant, et propose sinon le poste comme « En qualité de »
            "poste":       p.poste_display() or "",
            "teacher":     "1" if is_teacher(p) else "",
            "fem":         "1" if str(getattr(p, "civilite", "")) == "Madame" else "",
        })

    return render(request, "service_documents.html", {
        'title': "Documents Administratifs", "rows": rows, "year": current, "years": _year_choices(current),
        "today": _date.today().isoformat(), "kinds": [(k, v[1]) for k, v in SERVICE_DOCS.items()],
    })


"""
=============================================================================
 DOCUMENTS ADMINISTRATIFS DE CARRIÈRE
=============================================================================
   ServiceDocument        (classe de base — toute la mise en page)
     ├─ PriseDeService      « A pris service le … »
     ├─ RepriseDeService    « A repris service le … »
     └─ PresenceEffective   « Est effectivement présent(e) … »

 Les trois documents partagent l'intégralité de la mise en page : les
 sous-classes ne fournissent que des libellés et deux drapeaux.

 PRINCIPE DE REMPLISSAGE — chaque mention suit la même cascade :
     valeur saisie au formulaire  >  valeur de la fiche du personnel  >  ligne
 Une information absente n'est jamais une erreur : elle devient un trait à
 compléter à la main. Le document reste donc toujours utilisable.

 IMPORTANT — aucun cachet numérique : ce sont des pièces de carrière, elles
 doivent être signées et cachetées à la main. Titre en bleu marine.
=============================================================================
"""
DARK   = (30, 40, 55)
NAVY   = (10, 61, 98)
GREEN  = (10, 125, 63)
RED    = (200, 30, 45)
YELLOW = (249, 214, 22)

MONTHS_FR = ["", "JANVIER", "FÉVRIER", "MARS", "AVRIL", "MAI", "JUIN",
             "JUILLET", "AOÛT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DÉCEMBRE"]


# ---------------------------------------------------------------------------
#  POSTE ET « EN QUALITÉ DE » — source de vérité UNIQUE
# ---------------------------------------------------------------------------
#  Ces deux fonctions sont importées par la vue : la règle métier n'existe
#  qu'ici, donc le formulaire et le PDF ne peuvent pas diverger.
# ---------------------------------------------------------------------------
def is_teacher(personnel):
    """L'agent est-il enseignant ? Le test porte sur le libellé du poste et
    couvre « Enseignant », « Enseignante », « Enseignant vacataire »…"""
    return str(getattr(personnel, "poste", "") or "") == "Enseignant"


def default_qualite(personnel):
    """Mention « En qualité de » déduite de la fiche.
      • poste enseignant  -> « Enseignant(e) de <discipline> »
                             (ou « Enseignant(e) » seul si la discipline manque)
      • tout autre poste  -> le poste lui-même (Gardien, Secrétaire, Censeur…)
    La discipline n'a de sens que pour un enseignant : c'est pourquoi le
    formulaire masque ce champ dans les autres cas.
    """
    if not personnel:
        return ""
    poste = str(getattr(personnel, "poste", "") or "").strip()
    if not is_teacher(personnel):
        return poste
    fem = str(getattr(personnel, "civilite", "")) == "Madame"
    base = "Enseignante" if fem else "Enseignant"
    disc = str(getattr(personnel, "discipline_formation", "") or "").strip()
    plus = "de "
    if disc:
        if disc[0].lower() in ["a", "e", "h", "i", "o", "u", "y", "é", "è", "ê"]:
            plus = "d'"
    return (f"{base} {plus}{disc}" if disc else base).upper()


def fr_date_long(d):
    """date(2022, 1, 10) -> '10 JANVIER 2022' (forme des actes administratifs)."""
    if not d:
        return ""
    try:
        day = "1er" if d.day == 1 else d.day
        return f"{day} {MONTHS_FR[d.month]} {d.year}"
    except Exception:
        return str(d)


# ===========================================================================
#  CLASSE DE BASE
# ===========================================================================
class ServiceDocument(FPDF):
    """pdf = PriseDeService(personnel, school, year, data) -> pdf_response(...)

    `data` — toutes les clés sont facultatives :
        matricule    matricule de l'agent          (défaut : fiche du personnel)
        grade        grade administratif           (défaut : fiche)
        origin       provenance / poste précédent  (défaut : fiche)
        discipline   discipline de formation       (défaut : fiche)
        note_number  N° de la décision d'affectation
        note_date    date de la décision                        (date)
        duty_date    date de prise / reprise / présence         (date)
        qualite      mention « En qualité de »

    `year` — libellé de l'année scolaire, ou None / "" pour laisser un trait
    (le document peut concerner une année antérieure à l'adoption d'OSM).

    `blank=True` — version vierge : toutes les mentions deviennent des traits.
    """

    # --- à surcharger dans les sous-classes ---------------------------
    TITLE_FR = ""
    TITLE_EN = ""
    DUTY_FR  = ""
    DUTY_EN  = ""
    OBJECT_FR = ""            # complète la formule de délivrance
    SHOW_ORIGIN = True        # afficher « Venant de »
    SHOW_DECISION = True      # afficher le bloc décision / note de service
    REF_PREFIX = "N°"

    L, R = 12, 198
    GREY = (120, 130, 142)

    def __init__(self, personnel, school, year=None, data=None, blank=False):
        super().__init__(orientation="P", unit="mm", format="A4")
        add_fonts(self)
        self.set_auto_page_break(False)
        self.set_margins(6, 16, 6)
        self.personnel = personnel
        self.school = school
        self.year = year or ""
        self.data = data or {}
        self.blank = blank
        # le signataire est cherché UNE seule fois (et non à chaque mention)
        self._chef = self._find_chef()
        self.add_page()
        try:
            filigrane(self, x=50, y=100, w=110)
        except Exception:
            pass
        self.set_font("inter", "", 8)
        base_header(self, mode="P", y_img=10)
        self._title()
        self._body()

    # ------------------------------------------------------------------
    #  HELPERS
    # ------------------------------------------------------------------
    def _find_chef(self):
        if self.blank:
            return None
        try:
            return Personnel.objects.filter(poste="Chef d'Établissement").only("nom", "prenom").first()
        except Exception:
            return None

    def _attr(self, *names):
        """Premier attribut non vide du personnel parmi `names`."""
        p = self.personnel
        if not p:
            return ""
        for n in names:
            v = getattr(p, n, None)
            if v not in (None, ""):
                return v
        return ""

    def _pick(self, key, *fallback_attrs):
        """CASCADE : valeur du formulaire, sinon fiche du personnel, sinon "".
        C'est elle qui garantit qu'un champ non saisi devient un trait."""
        v = (self.data.get(key) or "")
        if isinstance(v, str):
            v = v.strip()
        return v or self._attr(*fallback_attrs)

    def _label(self, x, y, fr, en):
        self.set_font("inter", "", 10)
        self.set_text_color(*DARK)
        w_fr = self.get_string_width(fr)
        self.set_xy(x, y)
        self.cell(w_fr + 1, 4.6, fr)
        if en:
            self.set_font("inter", "I", 8)
            self.set_text_color(*self.GREY)
            w_en = self.get_string_width(en)
            self.set_xy(x, y + 4.3)
            self.cell(w_en + 1, 3.4, en)
        else:
            w_en = 0
        return max(w_fr, w_en) + 3

    def _rule(self, x, y, w):
        self.set_draw_color(*self.GREY)
        self.set_line_width(0.25)
        self.line(x, y + 4.4, x + max(10, w) if w else self.R, y + 4.4)

    def _value(self, x, y, text, size=10.5, color=NAVY, line_w=None, end=False):
        """Valeur en gras — ou TRAIT si version vierge / valeur absente."""
        if self.blank or text in (None, ""):
            self._rule(x, y, line_w)
            return
        self.set_font("inter", "B", size)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.cell(0, 4.6, str(text))

    def _field(self, x, y, fr, en, value, size=10.5, line_w=None):
        w = self._label(x, y, fr, en)
        self._value(x + w, y, value, size, line_w=line_w)
        return w

    # ------------------------------------------------------------------
    #  TITRE  (bleu marine — convention des documents de personnel)
    # ------------------------------------------------------------------
    def _title(self):
        y = 58
        self.set_font("inter", "B", 16)
        self.set_text_color(*NAVY)
        self.set_xy(self.L, y)
        self.cell(self.R - self.L, 8, self.TITLE_FR, align="C")
        if self.TITLE_EN:
            self.set_font("inter", "BI", 9.5)
            self.set_text_color(*self.GREY)
            self.set_xy(self.L, y + 8)
            self.cell(self.R - self.L, 5, self.TITLE_EN, align="C")
        cx = (self.L + self.R) / 2
        self.set_line_width(1)
        self.set_draw_color(*GREEN)
        self.line(cx - 35, y + 15, cx - 35 + 70 / 3, y + 15)
        self.set_draw_color(*RED)
        self.line(cx - 35 + 70 / 3, y + 15, cx - 35 + 140 / 3, y + 15)
        self.set_draw_color(*YELLOW)
        self.line(cx - 35 + 140 / 3, y + 15, cx + 35, y + 15)

    # ------------------------------------------------------------------
    #  CORPS
    # ------------------------------------------------------------------
    def _body(self):
        p = self.personnel
        s = self.school
        L, R = self.L, self.R

        # --- numéro d'enregistrement du document (toujours manuscrit) ----
        y = 80
        self.set_font("inter", "", 9.5)
        self.set_text_color(*DARK)
        ref_lbl = f"{self.REF_PREFIX} "
        w_lbl = self.get_string_width(ref_lbl)
        x = (L + R) / 2 - (w_lbl + 50) / 2
        self.set_xy(x, y)
        self.cell(w_lbl, 5, ref_lbl)
        self._rule(x + w_lbl + 2, y - 0.4, 60)

        # --- année scolaire : imprimée OU laissée en trait ----------------
        #     Le document peut concerner une année antérieure à l'adoption
        #     d'OSM : elle est alors saisie librement, ou complétée à la main.
        y += 10
        self.set_font("inter", "B", 10.5)
        self.set_text_color(*DARK)
        lbl = "ANNÉE SCOLAIRE "
        w_y = self.get_string_width(lbl)
        val = "" if self.blank else self.year
        if val:
            total = w_y + self.get_string_width(val)
            xs = (L + R) / 2 - total / 2
            self.set_xy(xs, y)
            self.cell(w_y, 5, lbl)
            self.set_text_color(*NAVY)
            self.cell(0, 5, val)
        else:
            total = w_y + 40
            xs = (L + R) / 2 - total / 2
            self.set_xy(xs, y)
            self.cell(w_y, 5, lbl)
            self._rule(xs + w_y + 2, y - 0.4, 35)

        # --- 1. le signataire --------------------------------------------
        y += 12
        chef = self._chef
        chef_name = chef.__str__().upper() if chef else ""
        accord = ("e" if chef.civilite == "Madame" else "") if (not self.blank and chef) else "(e)"
        w = self._label(L, y, f"Je soussigné{accord},", "I the undersigned,")
        self._value(L + w, y, chef_name, line_w=0)

        y += 12
        poste = getattr(s, "chef", "") or "Chef d'établissement"
        self.set_font("inter", "", 10)
        self.set_text_color(*DARK)
        self.set_xy(L, y)
        certify = "atteste" if self.TITLE_FR == "ATTESTATION DE PRÉSENCE EFFECTIVE" else "certifie"
        self.cell(0, 4.6, f"{poste} du {s.nom} {certify} que :", markdown=True)
        self.set_font("inter", "I", 8)
        self.set_text_color(*self.GREY)
        self.set_xy(L, y + 4.3)
        self.cell(0, 3.4, f"The Principal of {s.name} certify that:")

        # --- 2. l'agent ---------------------------------------------------
        y += 12
        civilite = ("Mme." if str(self._attr("civilite")) == "Madame" else "M.") if not self.blank else "M. / Mme."
        civility = ("Mrs" if civilite == "Mme." else "Mr") if not self.blank else "Mr / Mrs"
        w = self._label(L, y, civilite, civility)
        self._value(L + w, y, (f"{p.nom} {p.prenom}" if p.prenom else f"{self.nom}") if (p and not self.blank) else "",
                    size=11, line_w=0)

        # matricule et grade : saisis au formulaire, sinon repris de la fiche
        y += 12
        w = self._field(L, y, "Matricule", "Registration number",
                        self._pick("matricule", "matricule", "unique_id"), line_w=50)
        x2 = L + 88
        self._field(x2, y, "Grade", "Grade", self._pick("grade", "grade"), line_w=0)

        # --- 3. provenance (masquée pour la présence effective) -----------
        if self.SHOW_ORIGIN:
            y += 12
            self._field(L, y, "Venant de", "Coming from",
                        self._pick("origin", "provenance"), line_w=0)

        # --- 4. décision d'affectation ------------------------------------
        if self.SHOW_DECISION:
            y += 12
            prefix = ("Affecté ou Nommé" if p.civilite == "Monsieur"
                      else "Affectée ou Nommée") if not self.blank else "Affecté(e) ou Nommé(e)"
            fr = f"{prefix} par Décision, Arrêté, Note de service N°"
            self._label(L, y, fr, "Transferred to this school by decision n°")
            self.set_font("inter", "", 10)
            w = self.get_string_width(fr) + 4
            self._value(L + w, y, self._pick("note_number", "note_service_number"),
                        size=10, line_w=0)

            y += 12
            note_date = self.data.get("note_date") or self._attr("note_service_date")
            self._field(L, y, "Du", "Of", fr_date_long(note_date), size=10, line_w=0)

        # --- 5. prise / reprise / présence --------------------------------
        y += 12
        add = (("e" if self.personnel.civilite == "Madame" else "") if not self.blank
               else "(e)") if self.TITLE_FR == "ATTESTATION DE PRÉSENCE EFFECTIVE" else ""
        w = self._label(L, y, self.DUTY_FR.replace("#", add), self.DUTY_EN)
        self._value(L + w, y, fr_date_long(self.data.get("duty_date")), size=10.5, line_w=0)

        # --- 6. qualité ----------------------------------------------------
        #  Cascade habituelle : saisie du formulaire, sinon valeur déduite du
        #  poste (et de la discipline si l'agent est enseignant), sinon trait.
        y += 12
        qualite_label = "Date de reprise de service en qualité" if self.TITLE_FR == "ATTESTATION DE PRÉSENCE EFFECTIVE" \
            else "En qualité"
        quality_label = "Date of assumption of duty as" if qualite_label != "En qualité de" else "As"
        qualite = (self.data.get("qualite") or "").strip() or default_qualite(p)
        plus = (" d'" if qualite[0].lower() in ["a", "e", "h", "i", "o", "u", "y", "é", "è", "ê"] else " de") if qualite else " de"
        self._field(L, y, qualite_label + plus, quality_label, qualite, line_w=0)
        # --- 7. formule de délivrance --------------------------------------
        y += 14
        self.set_font("inter", "", 10)
        self.set_text_color(*DARK)
        self.set_xy(L, y)
        self.multi_cell(R - L, 4.6, f"En foi de quoi {self.OBJECT_FR} lui est "
                                    f"délivré{'e' if self.TITLE_FR == "ATTESTATION DE PRÉSENCE EFFECTIVE" else ''} pour "
                                    f"servir et valoir ce que de droit.", align="J")
        self.set_font("inter", "I", 8)
        self.set_text_color(*self.GREY)
        self.set_xy(L, self.get_y() + 0.5)
        self.multi_cell(R - L, 4.3, "This present attestation is issued to serve the purpose for which it is "
                                    "intended and where need arises.", align="J")

        # --- 8. lieu, date, signature (JAMAIS de cachet numérique) --------
        y = self.get_y() + 14
        localite = getattr(s, "localite", "") or ""
        w = self._label(R - 84, y, f"Fait à {localite}, le", f"Done in {localite}, on the")
        self._rule(R - 84 + w, y, 30)          # toujours un trait : signé à la main

        y += 12
        self.set_font("inter", "B", 10)
        self.set_text_color(*NAVY)
        self.set_xy(R - 84, y)
        self.cell(84, 5, f"Le {poste}", align="C")
        self.set_font("inter", "I", 7)
        self.set_text_color(*self.GREY)
        self.set_xy(R - 84, y + 4.6)
        self.cell(84, 4, "The Principal", align="C")
        """self.set_draw_color(*self.GREY)
        self.set_line_width(0.2)
        self.line(R - 84, y + 30, R - 10, y + 30)
        self.set_font("inter", "I", 6.5)
        self.set_text_color(*self.GREY)
        self.set_xy(R - 84, y + 30.5)
        self.cell(84, 3.5, "Signature et cachet", align="C")"""


# ===========================================================================
#  LES TROIS DOCUMENTS
# ===========================================================================
class PriseDeService(ServiceDocument):
    TITLE_FR = "CERTIFICAT DE PRISE DE SERVICE"
    TITLE_EN = "CERTIFICATE OF ASSUMPTION OF DUTY"
    DUTY_FR  = "A pris service le"
    DUTY_EN  = "Has assumed his/her duty on the"
    OBJECT_FR = "le présent certificat de prise de service"
    SHOW_ORIGIN = True


class RepriseDeService(ServiceDocument):
    TITLE_FR = "CERTIFICAT DE REPRISE DE SERVICE"
    TITLE_EN = "CERTIFICATE OF RESUMPTION OF DUTY"
    DUTY_FR  = "A repris service le"
    DUTY_EN  = "Has resumed his/her duty on the"
    OBJECT_FR = "le présent certificat de reprise de service"
    SHOW_ORIGIN = False


class PresenceEffective(ServiceDocument):
    TITLE_FR = "ATTESTATION DE PRÉSENCE EFFECTIVE"
    TITLE_EN = "ATTESTATION OF EFFECTIVE PRESENCE"
    DUTY_FR  = "Est effectivement présent# à son poste depuis le"
    DUTY_EN  = "Has been effectively present at his/her post since"
    OBJECT_FR = "la présente attestation de présence effective"
    SHOW_ORIGIN = False


#: Registre utilisé par la vue (clé -> classe + libellé)
SERVICE_DOCS = {
    "PRISE":    (PriseDeService, "Certificat de prise de service"),
    "REPRISE":  (RepriseDeService, "Certificat de reprise de service"),
    "PRESENCE": (PresenceEffective, "Attestation de présence effective"),
}
