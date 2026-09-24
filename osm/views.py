import os

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from authentification.views import anonymous_required
from .forms import TranchesHorairesForm, SchoolForm
from .utils import with_users_school_schema, ADetailView, LoggedAdminView, add_minutes, greet, logged_user_view
from authentification.models import School, TrancheHoraire
from staff.models import Personnel
from student.models import Student
from classroom.models import ClassRoom
from datetime import time, datetime
from staff.models import Activities


@logged_user_view
def user_guide(request):
    return render(request, "guide_utilisateur.html")


@anonymous_required
def offline_index(request):
    schools_infos = [
        {
            'nom': school.nom,
            'logo': school.logo,
            'localite': school.localite
        } for school in School.objects.exclude(schema_name__in=["demo", "public"])
    ]
    return render(request, "offline_index.html", context={'schools_infos': schools_infos})


# Page d'accueil après connexion
@login_required(login_url="signin")
@with_users_school_schema
def index(request):
    from archives.services import missing_marks
    from archives.models import YearClosure
    activities = []
    exists = False
    if Activities.objects.exists():
        exists = True
        for activity in Activities.objects.filter(start__gte=datetime.now()):
            activities.append(activity)
            if len(activities) == 3:
                break
    remind = False
    if not missing_marks():
        year = request.user.school.establishment_year
        closure = YearClosure.objects.filter(school_year=year).first()
        if not closure:
            remind = f"Le remplissage des notes est déjà complet, vous pouvez clôturer l'année scolaire {year}."
        else:
            remind = f"Veuillez poursuivre la clôture de l'année scolaire {year}."
    context = {'activities': activities, 'exists': exists, 'remind': remind,
               'greet': f"{greet()} {request.user.staff_member.short_firstname}",
               'nb_classes': ClassRoom.objects.count(),
               'nb_staff': Personnel.objects.count(),
               'nb_students': Student.objects.count(),
    }
    return render(request, "index.html", context)


def ajax_messages(request):
    return render(request, "messages.html")


class SchoolDetails(ADetailView):
    title = "Informations Établissement"
    model = School
    template_name = "school_details.html"


class TranchesHorairesEdit(LoggedAdminView):
    title = "Plages Horaires"
    template_name = "tranches_horaires.html"

    def get_plages(self):
        state = list()
        plages = TrancheHoraire.objects.filter(school_id=self.request.user.school.pk)
        if plages.exists():
            i, j = 1, 1
            for tranche in plages:
                if tranche.is_cours:
                    state.append([True, f"Tranche n° {i}: {tranche.start_end}"])
                    i += 1
                else:
                    state.append([False, f"Pause n° {j}: {tranche.start_end}"])
                    j += 1
        else:
            state.append("Aucune plage définie pour le moment")
        return state

    def save_plages(self, form):
        from .utils import message
        school = self.request.user.school
        tranches_horaires = TrancheHoraire.objects.filter(school_id=school.pk)
        if not tranches_horaires.exists() or (tranches_horaires.exists() and form.form_has_changed()):
            school.nb_plages = nb = int(form.cleaned_data['nb'])
            nb += 2
            if nb + 2 < tranches_horaires.count():
                tranches_horaires.filter(number__gt=nb + 2).delete()
            school.plage_duration = duration = int(form.cleaned_data["duration"])
            school.first_break_after = first_break_after = int(form.cleaned_data["first_break"])
            school.first_break_duration = first_break_duration = int(form.cleaned_data["first_break_duration"])
            school.second_break_after = second_break_after = int(form.cleaned_data["second_break"])
            school.second_break_duration = second_break_duration = int(form.cleaned_data["second_break_duration"])
            school.day_start = start = form.cleaned_data['day_start']
            school.save()
            for i in range(1, nb + 1):
                if i == first_break_after + 1:
                    end = add_minutes(start, first_break_duration)
                    is_cours = False
                elif i == second_break_after + 2:
                    end = add_minutes(start, second_break_duration)
                    is_cours = False
                else:
                    end = add_minutes(start, duration)
                    is_cours = True
                TrancheHoraire.objects.update_or_create(school_id=school.pk, number=i,
                                                        defaults={'start': start, 'end': end, 'is_cours': is_cours})
                start = end
            message(self.request, "Données sauvegardées avec succès")
        else:
            message(self.request, "Aucune modification effectuée", msg_type="warning")

    def get(self, *args, **kwargs):
        tranches_horaires_form = TranchesHorairesForm(context={'request': self.request})
        state = self.get_plages()
        context = {'title': self.title, 'form': tranches_horaires_form, 'state': state}
        return render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        tranches_horaires_form = TranchesHorairesForm(self.request.POST, context={'request': self.request})
        if tranches_horaires_form.is_valid():
            self.save_plages(tranches_horaires_form)
        state = self.get_plages()
        context = {'title': self.title, 'form': tranches_horaires_form, 'state': state}
        return render(self.request, self.template_name, context)


class SchoolInformations(LoggedAdminView):
    template_name = 'school_infos_form.html'
    title = "Informations Établissement"

    def get(self, *args, **kwargs):
        context = {'form': SchoolForm(instance=self.request.user.school, context={'request': self.request}),
                   'title': self.title}
        return  render(self.request, self.template_name, context)

    def post(self, *args, **kwargs):
        from .utils import message, delete_image
        old_logo = self.request.user.school.logo
        old_cachet = self.request.user.school.cachet
        old_visa = self.request.user.school.visa
        school_form = SchoolForm(self.request.POST, self.request.FILES, instance=self.request.user.school,
                                 context={'request': self.request})
        if school_form.is_valid():
            school_form.save()
            logo = school_form.cleaned_data['logo']
            cachet = school_form.cleaned_data['cachet']
            visa = school_form.cleaned_data['visa']
            if old_logo and old_logo != logo:
                delete_image(old_logo)
            if old_cachet and old_cachet != cachet:
                delete_image(old_cachet)
            if old_visa and old_visa != visa:
                delete_image(old_visa)
            message(self.request, 'Informations sauvegardées avec succès')
            return redirect("school_details")
        context = {'form': school_form, 'title': self.title}
        return render(self.request, self.template_name, context)
