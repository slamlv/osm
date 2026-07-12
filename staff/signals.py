from django.db.models.signals import post_save, pre_delete, post_delete
from django.dispatch import receiver
from authentification.models import User
from staff.models import Personnel
from django.db.models import Max
from django_tenants.utils import schema_context
from django.db import transaction


def _get_linked_staff(user):
    """Personnel lié au compte, ou None (OneToOne -> objet unique)."""
    try:
        with transaction.atomic():
            return user.staff_member
    except Personnel.DoesNotExist:
        return None
    except Exception:
        return None


def _get_linked_user(staff):
    """Compte lié au personnel, ou None (compte optionnel)."""
    return staff.user if staff.user_id else None


@receiver(post_save, sender=User, dispatch_uid="sync_user_to_staff")
def sync_user_to_staff(sender, instance, **kwargs):
    """User.is_active -> Personnel.en_poste (si différent)."""
    if instance.is_superuser:
        return
    with schema_context(instance.school.schema_name):
        staff = _get_linked_staff(instance)
        if staff is None:
            return

        if instance.is_active and not staff.en_poste:
            staff.en_poste = True
            staff.save(update_fields=["en_poste"])      # déclenchera l'autre signal,
                                                        # qui ne fera RIEN (déjà alignés)
        elif not instance.is_active and staff.en_poste:
            staff.en_poste = False
            staff.save(update_fields=["en_poste"])


@receiver(post_save, sender=Personnel, dispatch_uid="sync_staff_to_user")
def sync_staff_to_user(sender, instance, **kwargs):
    """Personnel.en_poste -> User.is_active (si différent)."""
    user = _get_linked_user(instance)
    if user is None:
        return

    if instance.en_poste and not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])      # déclenche l'autre signal,
                                                    # qui ne fera RIEN (déjà alignés)
    elif not instance.en_poste and user.is_active:
        user.is_active = False
        user.save(update_fields=["is_active"])


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
