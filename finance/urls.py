from django.urls import path
from .views import cash_in, fee_grid, fee_delete, fee_save, fee_duplicate, fee_type_save, payment_receipt,\
    cancel_payment, discounts, discount_save, discount_delete, emargement_sheet, payroll, salary_assignment,\
    cashbox, transaction_save, cancel_transaction, cashbox_settings, reports, recovery_pdf, journal_pdf, expenses_pdf,\
    defaulters_pdf, convocations_pdf

urlpatterns = [
    path("fee_grid/", fee_grid, name="fee_grid"),
    path("fee_save", fee_save, name="fee_save"),
    path("fee_delete-<int:pk>/", fee_delete, name="fee_delete"),
    path("fee_duplicate", fee_duplicate, name="fee_duplicate"),
    path("fee_type_save", fee_type_save, name="fee_type_save"),
    path("cash_in", cash_in, name="cash_in"),
    path("payment_receipt-<int:pk>/", payment_receipt, name="payment_receipt"),
    path("cancel_payment-<int:pk>/", cancel_payment, name="cancel_payment"),
    path("discounts", discounts, name="discounts"),
    path("discount_save", discount_save, name="discount_save"),
    path("discount_delete-<int:pk>/", discount_delete, name="discount_delete"),
    path("salary_assignment", salary_assignment, name="salary_assignment"),
    path("payroll", payroll, name="payroll"),
    path("emargement_sheet", emargement_sheet, name="emargement_sheet"),
    path("cashbox", cashbox, name="cashbox"),
    path("transaction_save", transaction_save, name="transaction_save"),
    path("cashbox_settings", cashbox_settings, name="cashbox_settings"),
    path("cancel_transaction-<int:pk>/", cancel_transaction, name="cancel_transaction"),
    path("reports", reports, name="reports"),
    path("defaulters-<int:classroom_id>/", defaulters_pdf, name="defaulters_pdf"),
    path("convocations-<int:classroom_id>/", convocations_pdf, name="convocations_pdf"),
    path("recovery", recovery_pdf, name="recovery_pdf"),
    path("journal", journal_pdf, name="journal_pdf"),
    path("expenses", expenses_pdf, name="expenses_pdf"),
]
