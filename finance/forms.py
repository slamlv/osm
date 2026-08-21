from django import forms
from .models import StudentPayment, FeeType
from django.utils import timezone


# ---------------------------------------------------------------------------
#  FORMULAIRE DE PAIEMENT
# ---------------------------------------------------------------------------
class StudentPaymentForm(forms.ModelForm):
    class Meta:
        model = StudentPayment
        fields = ["fee_type", "amount", "method", "date", "note"]
        widgets = {
            "fee_type": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": 1, "placeholder": "Montant (FCFA)"}),
            "method": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date", 'data-max-now': ""}),
            "note": forms.TextInput(attrs={"class": "form-control", "placeholder": "Note (facultatif)"}),
        }

    def __init__(self, *args, student=None, year=None, classroom=None, **kwargs):
        super().__init__(*args, **kwargs)
        # On ne propose QUE les types de frais applicables à CET élève (grille de son niveau/série + tous-niveaux),
        # via la méthode de modèle applicable_fees(year).
        if student is not None and year:
            fees = student.applicable_fees(year, classroom=classroom)
            self.fields["fee_type"].queryset = FeeType.objects.filter(
                id__in=[f.fee_type_id for f in fees if not student.student_fee_status(
                    year, fee_type_id=f.fee_type.id, classroom=classroom)[0]['solde']]
            )
        self.fields["date"].initial = timezone.localdate()