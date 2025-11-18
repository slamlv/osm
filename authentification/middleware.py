from django.utils.deprecation import MiddlewareMixin
from django_tenants.utils import get_public_schema_name, schema_context
from authentification.models import School
from django.db import connection


class RequestMiddleware(MiddlewareMixin):
    def process_request(self, request):
        pass
