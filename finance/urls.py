from django.urls import path
from .views import cash_in, fee_grid, fee_delete, fee_save, fee_duplicate, fee_type_save, payment_receipt,\
    cancel_payment

urlpatterns = [
    path("fee_grid/", fee_grid, name="fee_grid"),
    path("fee_save", fee_save, name="fee_save"),
    path("fee_delete-<int:pk>/", fee_delete, name="fee_delete"),
    path("fee_duplicate", fee_duplicate, name="fee_duplicate"),
    path("fee_type_save", fee_type_save, name="fee_type_save"),
    path("cash_in", cash_in, name="cash_in"),
    path("payment_receipt-<int:pk>/", payment_receipt, name="payment_receipt"),
    path("cancel_payment-<int:pk>/", cancel_payment, name="cancel_payment"),
]
