# Register your models here.

from django.contrib import admin
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


class SchoolAdmin(admin.ModelAdmin):
    list_display = ("nom", "name", "type_ets", "contact", "contact1", "code")


class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ("libelle", "annee_debut", "is_current", "date_ouverture", "date_cloture")


admin.site.register(User, UserAdmin)
admin.site.register(School, SchoolAdmin)
admin.site.register(SchoolYear, SchoolYearAdmin)
