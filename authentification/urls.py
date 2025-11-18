from django.urls import path
from .views import signup, signin, activate, signout, reset_password, reset, code, change_password

urlpatterns = [
    path("signin", signin, name="signin"),
    path("code", code, name="code"),
    path("signup", signup, name="signup"),
    path("activate/<uidb64>/<token>", activate, name="activate"),
    path("signout", signout, name="signout"),
    path("reset", reset, name="reset"),
    path("reset_password/<uidb64>/<token>", reset_password, name="reset_password"),
    path("change_password", change_password, name="change_password")
]
