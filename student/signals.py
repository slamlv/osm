"""
=============================================================================
 SIGNALS — Synchronisation automatique des StudentEnrollment
=============================================================================

Rôle :
  Un seul signal post_save sur Student couvre DEUX besoins :
    1. À la création d'un élève avec une classe -> crée son enrollment de
       l'année courante (decision="En cours").
    2. Au changement de classe en cours d'année -> met à jour la classe de
       l'enrollment courant.

Garde-fous importants :
  - On ne fait rien si l'établissement courant est en période clôturée
    (is_year_closed) : pas de création/maj pendant les vacances.
  - On ne met à jour QUE si la décision est encore "En cours" : on ne touche
    jamais à un enrollment déjà statué (protège l'historique / le parcours).
  - get_or_create rend le signal idempotent (pas de doublon).

Interaction avec la CLÔTURE :
  La bascule de fin d'année (changement de Student.classe pour les promus et éventuellement redoublants)
  se fait en bulk_update, qui NE déclenche PAS les signaux. Couplé au
  garde-fou "decision == En cours", l'historique est doublement protégé.

Multi-tenant :
  Le signal s'exécute dans le schéma du tenant courant : l'enrollment est donc
  créé dans le bon schéma. SchoolYear est partagé (lecture transverse OK).
  L'établissement courant est récupéré via connection.tenant (pas de request
  dans un signal). On accède à is_year_closed de façon défensive.
=============================================================================
"""

from django.db import connection
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Student, StudentEnrollment, EnrollmentStatus

from authentification.models import SchoolYear


def _current_school():
    """
    Établissement (tenant) courant. On reste défensif : si indisponible, on renvoie None
    et le signal s'exécutera sans le test de clôture (comportement sûr : il
    créera/mettra à jour normalement tant qu'une année courante existe).
    """
    return getattr(connection, "tenant", None)


@receiver(post_save, sender=Student, dispatch_uid="student_sync_current_enrollment")
def sync_current_enrollment(sender, instance, created, **kwargs):
    # Pas de classe attribuée -> rien à tracer pour l'année courante.
    if instance.classe_id is None:
        return

    # Période clôturée pour cet établissement -> on ne crée/maj rien.
    school = _current_school()
    if school is not None and getattr(school, "is_year_closed", False):
        return

    # Pas d'année courante définie -> on ne peut rattacher aucun enrollment.
    year = SchoolYear.current()
    if year is None:
        return

    # Crée l'enrollment de l'année courante s'il n'existe pas encore.
    enr, made = StudentEnrollment.objects.get_or_create(
        student=instance,
        school_year=year,
        defaults={
            "classroom_id": instance.classe_id,
            "decision": EnrollmentStatus.EN_COURS,
        },
    )

    # Sinon : met à jour la classe UNIQUEMENT si l'année n'est pas statuée (decision encore "En cours") et que la classe a réellement changé.
    if not made and enr.decision == EnrollmentStatus.EN_COURS and enr.classroom_id != instance.classe_id:
        enr.classroom_id = instance.classe_id
        enr.save(update_fields=["classroom"])
