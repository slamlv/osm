from celery import shared_task
from django_tenants.utils import schema_context

from osm.utils import delete_image_name


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 3},
)
def delete_student_old_photo(schema_name, image_name):
    """Supprime une ancienne photo hors de la requête HTTP."""
    if not schema_name or not image_name:
        return

    with schema_context(schema_name):
        deleted = delete_image_name(image_name)

        if not deleted:
            raise RuntimeError(
                f"Impossible de supprimer l'ancienne photo : {image_name}"
            )
