# Register your models here.

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.db import transaction, connection
from django_tenants.utils import schema_context
from .models import User, School, SchoolYear


class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "civilite", "last_name", "first_name", "is_active", "is_admin", "school",
                    "poste", "contact")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.set_password(obj.password)
        else:
            if 'password' in form.changed_data:
                obj.set_password(obj.password)
        obj.save()

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)

        if obj is None:
            return self._get_obj_does_not_exist_redirect(
                request, self.model._meta, object_id
            )

        if request.method == "POST":
            with transaction.atomic():
                # 1. Supprimer le Personnel dans le schéma de l'école
                if obj.school_id:
                    with schema_context(obj.school.schema_name):
                        from staff.models import Personnel
                        Personnel.objects.filter(user_id=obj.pk).delete()

                # 2. Revenir au schéma public et supprimer directement le User
                User.objects.filter(pk=obj.pk)._raw_delete(using="default")

            self.message_user(
                request,
                f"{obj} a été supprimé avec succès.",
                messages.SUCCESS,
            )

            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist"
                )
            )

        return render(
            request,
            "admin/delete_confirmation.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Supprimer {obj}",
                "object": obj,
                "object_name": str(obj),
                "opts": self.model._meta,
                "deletable_objects": [],
                "perms_lacking": [],
                "protected": [],
                "is_popup": False,
                "to_field": None,
                "preserved_filters": self.get_preserved_filters(request),
            },
        )


class SchoolAdmin(admin.ModelAdmin):
    list_display = (
        "nom", "name", "type_ets", "contact", "contact1", "code"
    )

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)

        if obj is None:
            return self._get_obj_does_not_exist_redirect(
                request, self.model._meta, object_id
            )

        if request.method == "POST":
            schema_name = obj.schema_name

            # 1. Supprimer Personnel + Users
            with transaction.atomic():
                user_ids = list(
                    User.objects
                    .filter(school_id=obj.pk)
                    .values_list("pk", flat=True)
                )

                if user_ids:
                    # Personnel est dans le schéma tenant
                    from staff.models import Personnel
                    with schema_context(schema_name):
                        Personnel.objects.filter(
                            user_id__in=user_ids
                        ).delete()

                    # User est dans public
                    User.objects.filter(
                        pk__in=user_ids
                    )._raw_delete(using="default")

            # À ce stade la première transaction est COMMITÉE.

            # 2. Supprimer le schéma tenant
            with connection.cursor() as cursor:
                cursor.execute(
                    'DROP SCHEMA IF EXISTS "{}" CASCADE'.format(
                        schema_name.replace('"', '""')
                    )
                )

            # 3. Supprimer School de public
            School.objects.filter(
                pk=obj.pk
            )._raw_delete(using="default")

            self.message_user(
                request,
                f"{obj} a été supprimée avec succès.",
                messages.SUCCESS,
            )

            return HttpResponseRedirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist"
                )
            )

        return render(
            request,
            "admin/delete_confirmation.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Supprimer {obj}",
                "object": obj,
                "object_name": str(obj),
                "opts": self.model._meta,
                "deletable_objects": [],
                "perms_lacking": [],
                "protected": [],
                "is_popup": False,
                "to_field": None,
                "preserved_filters": self.get_preserved_filters(request),
            },
        )


class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ("libelle", "annee_debut", "is_current", "date_ouverture", "date_cloture")


admin.site.register(User, UserAdmin)
admin.site.register(School, SchoolAdmin)
admin.site.register(SchoolYear, SchoolYearAdmin)
