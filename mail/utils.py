"""
    Ce fichier contient la fonction qui permet d'envoyer l'email
"""

import logging
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_the_mail(subject: str, receivers: list, template: str, context: dict):
    try:
        message = render_to_string(template, context)
        send_mail(subject, message, settings.EMAIL_HOST_USER, receivers, fail_silently=False, html_message=message)
        return True
    except Exception as exception:
        logger.error(exception)
        return False
