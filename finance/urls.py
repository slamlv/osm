from django.urls import path
from .views import cash_in

urlpatterns = [
    path("cash_in", cash_in, name="cash_in"),
]
