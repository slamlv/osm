"""
=============================================================================
 archives/tasks.py — Préchauffage des bulletins (Celery)
=============================================================================
   1. CONTEXTE TENANT — un worker Celery ne connaît aucun schéma par défaut.
      Sans schema_context(), la tâche lèverait "relation ClassRoom does not
      exist". Le nom du schéma est donc transmis à la tâche et activé en tout
      premier, AVANT toute requête.

   2. Le reste (on_commit, verrou en double vérification, contrôle de
      version avant/après génération).

 "Best effort" assumé de bout en bout : si cette tâche échoue ou n'est
 jamais exécutée, le téléchargement normal génère le bulletin à la demande,
 exactement comme aujourd'hui.
=============================================================================
"""
import logging
from celery import shared_task
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

#: valeurs par défaut, surchargeables dans settings.py sans toucher au code
LOCK_TIMEOUT = getattr(settings, "PREWARM_BULLETIN_LOCK_TIMEOUT", 300)


@shared_task(ignore_result=True)
def maybe_prewarm_bulletin(schema_name, classroom_id, term_index):
    """Point d'entrée Celery : active le schéma du tenant, puis délègue."""
    from django_tenants.utils import schema_context

    try:
        with schema_context(schema_name):
            from authentification.models import School
            school = School.objects.filter(schema_name=schema_name).first()
            if term_index is not None:
                _maybe_prewarm_bulletin(classroom_id, term_index, school)
                _maybe_prewarm_bulletin(classroom_id, 0, school)
            else:
                _maybe_prewarm_bulletin(classroom_id, 1, school)
                _maybe_prewarm_bulletin(classroom_id, 2, school)
                _maybe_prewarm_bulletin(classroom_id, 3, school)
                _maybe_prewarm_bulletin(classroom_id, 0, school)
    except Exception:
        # Best effort : une erreur ici ne doit jamais remonter bruyamment.
        # Elle reste visible dans les logs Celery pour diagnostic.
        logger.exception("Préchauffage du bulletin en échec (schema=%s, classroom=%s, trimestre=%s)",
                         schema_name, classroom_id, term_index)


def _maybe_prewarm_bulletin(classroom_id, term_index, school):
    """Corps de la tâche, DÉJÀ dans le bon schéma. Vérifie la complétude,
    verrouille, génère, contrôle qu'aucune note n'a changé entre-temps,
    archive."""
    from classroom.models import ClassRoom
    from archives.models import DocType, ArchiveRef
    from archives.services import missing_marks_for_classroom, GENERATORS
    from osm.utils import school_year

    with_competences = school.with_competences if school is not None else False
    year = school.establishment_year if school is not None else school_year()

    classroom = ClassRoom.objects.filter(pk=classroom_id).first()
    if classroom is None:
        return

    # --- 1. test léger : les notes du trimestre sont-elles complètes ? -----
    if missing_marks_for_classroom(classroom, term_index):
        return

    ref = ArchiveRef(year, DocType.BULLETIN, classroom, term_index=term_index, year=year)
    if with_competences and term_index:
        ref_wc = ArchiveRef(year, DocType.BULLETIN_WITH_COMPETENCES, classroom, term_index=term_index, year=year)

    # --- 2. déjà archivé et à jour : rien à faire ---------------------------
    if ref.cached_bytes() is not None and (ref_wc.cached_bytes() is not None if (with_competences and term_index) else True):
        return

    # --- 3. verrou anti-doublon (partagé entre workers via le cache) -------
    #     Utilise un backend de cache PARTAGÉ (Redis)
    lock_key = f"bulletin-prewarm:{classroom_id}:{term_index}"
    if not cache.add(lock_key, "1", timeout=LOCK_TIMEOUT):
        return          # une autre tâche s'en occupe déjà

    try:
        # --- 4. re-vérification après acquisition du verrou -----------------
        #     Une autre tâche a pu terminer juste avant qu'on obtienne le lock.
        if ref.cached_bytes() is not None and (ref_wc.cached_bytes() is not None if (with_competences and term_index) else True):
            return

        # --- 5. version des notes AVANT génération --------------------------
        if term_index:
            classroom.refresh_from_db()
            version_field = f"notes_updated_t{term_index}"
            version_before = getattr(classroom, version_field)

        # --- 6. génération : EXACTEMENT le chemin de la vue de téléchargement
        generator = GENERATORS[DocType.BULLETIN]
        result = generator(school, year, classroom, term_index)
        if with_competences and term_index:
            generator_wc = GENERATORS[DocType.BULLETIN_WITH_COMPETENCES]
            result_wc = generator_wc(school, year, classroom, term_index)

        if not result and (not result_wc if (with_competences and term_index) else True):
            return
        data, page_map, pages = result
        if with_competences and term_index:
            data_wc, page_map_wc, pages_wc = result_wc

        # --- 7. les notes ont-elles bougé PENDANT la génération ? -----------
        #     Si oui, ce PDF correspond à un état déjà périmé : on l'abandonne
        #     sans l'archiver. La modification qui l'a périmé aura de toute
        #     façon déclenché sa propre tâche via touch_notes().
        if term_index:
            classroom.refresh_from_db(fields=[version_field])
            if getattr(classroom, version_field) != version_before:
                logger.info("Préchauffage abandonné : notes modifiées pendant la génération (classroom=%s, trimestre=%s)",
                           classroom_id, term_index)
                return

        # --- 8. archivage ----------------------------------------------------
        ref.page_map = page_map
        ref.store(data, page_count=pages)
        if with_competences and term_index:
            ref_wc.page_map = page_map_wc
            ref_wc.store(data_wc, page_count=pages_wc)
        logger.info("Bulletin préchauffé (classroom=%s, trimestre=%s, %d page(s))",
                   classroom_id, term_index, pages)

    finally:
        cache.delete(lock_key)
