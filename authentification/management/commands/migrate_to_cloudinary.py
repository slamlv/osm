# Dans n'importe quelle app partagée, ex: authentification/management/commands/migrate_to_cloudinary.py

import os
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django_tenants.utils import schema_context, get_tenant_model


class Command(BaseCommand):
    help = "Migre toutes les images vers Cloudinary (School, Personnel, Student)"

    def handle(self, *args, **kwargs):
        total_migrated = 0
        total_errors = 0

        # ──────────────────────────────────────────
        # 1. SCHEMA PUBLIC → School.logo
        # ──────────────────────────────────────────
        self.stdout.write(self.style.HTTP_INFO("\n📁 Migration des logos School (schéma public)..."))
        m, e = self.migrate_model_images(
            model_path="authentification.School",
            field_name="logo",
            label="School",
        )
        total_migrated += m
        total_errors += e

        # ──────────────────────────────────────────
        # 2. CHAQUE TENANT → Personnel.photo + Student.photo
        # ──────────────────────────────────────────
        TenantModel = get_tenant_model()
        tenants = TenantModel.objects.exclude(schema_name='public')

        for tenant in tenants:
            self.stdout.write(
                self.style.HTTP_INFO(f"\n🏫 Tenant : {tenant.nom} (schéma: {tenant.schema_name})")
            )

            with schema_context(tenant.schema_name):

                self.stdout.write("  → Personnel.photo")
                m, e = self.migrate_model_images(
                    model_path="staff.Personnel",
                    field_name="photo",
                    label=f"Personnel [{tenant.schema_name}]",
                )
                total_migrated += m
                total_errors += e

                self.stdout.write("  → Student.photo")
                m, e = self.migrate_model_images(
                    model_path="student.Student",
                    field_name="photo",
                    label=f"Student [{tenant.schema_name}]",
                )
                total_migrated += m
                total_errors += e

        # ──────────────────────────────────────────
        # Résumé final
        # ──────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Migration terminée : {total_migrated} image(s) migrée(s), {total_errors} erreur(s)."
        ))

    def migrate_model_images(self, model_path, field_name, label):
        from django.apps import apps
        from django.conf import settings

        app_label, model_name = model_path.split(".")
        Model = apps.get_model(app_label, model_name)

        filter_kwargs = {
            f"{field_name}__isnull": False,
            f"{field_name}__gt": "",
        }
        queryset = Model.objects.filter(**filter_kwargs)
        count = queryset.count()

        if count == 0:
            self.stdout.write(f"    Aucune image à migrer pour {label}.")
            return 0, 0

        self.stdout.write(f"    {count} image(s) trouvée(s) pour {label}...")
        migrated, errors = 0, 0

        for instance in queryset:
            field = getattr(instance, field_name)

            # Construire le chemin local manuellement
            photo_path = os.path.join(settings.MEDIA_ROOT, field.name)

            # Vérifier si le fichier est déjà sur Cloudinary
            # (les URLs Cloudinary contiennent 'cloudinary' ou 'res.cloudinary.com')
            if 'cloudinary' in field.name:
                self.stdout.write(f"    ↩ {instance} — déjà sur Cloudinary, ignoré.")
                continue

            if not os.path.exists(photo_path):
                self.stdout.write(self.style.WARNING(
                    f"    ⚠ Fichier introuvable : {photo_path} ({instance})"
                ))
                errors += 1
                continue

            try:
                filename = os.path.basename(photo_path)
                with open(photo_path, "rb") as f:
                    content = ContentFile(f.read())

                field.save(filename, content, save=True)
                migrated += 1
                self.stdout.write(self.style.SUCCESS(
                    f"    ✓ {instance} → {field.url}"
                ))
            except Exception as ex:
                self.stdout.write(self.style.ERROR(
                    f"    ✗ Erreur pour {instance} : {ex}"
                ))
                errors += 1

        return migrated, errors