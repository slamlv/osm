from django.db.models.signals import post_save, pre_delete, post_delete
from django.dispatch import receiver
from authentification.models import User
from staff.models import Personnel
from django.db.models import Max
from django_tenants.utils import schema_context


# Signal qui permet d'enregistrer un membre du personnel dans son établissement à la création de son compte
@receiver(post_save, sender=User, dispatch_uid="create_staff_member_id")
def create_staff_member(sender, instance, created, *args, **kwargs):
    if created and not instance.is_superuser:
        with schema_context(instance.school.schema_name):
            first_name = instance.first_name.title()
            last_name = instance.last_name.upper()
            email = instance.email
            civilite = instance.civilite
            poste = instance.poste
            contact = instance.contact
            new = Personnel(nom=last_name, prenom=first_name, contact=contact, email=email, civilite=civilite,
                            poste=poste, user_id=instance.pk)
            new.save()
