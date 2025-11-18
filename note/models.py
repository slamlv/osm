# Create your models here.

from django.db import models
from django.db.models import UniqueConstraint, Case, When, Value, IntegerField, F
from student.models import Student
from classroom.models import Enseignements


class Period(models.Model):
    evalx = models.IntegerField(null=False)
    start = models.DateTimeField(null=True)
    end = models.DateTimeField(null=True)

    class Meta:
        db_table = '"Period"'

    @property
    def debut(self):
        return self.start if self.start else "Non défini"

    @property
    def fin(self):
        return self.end if self.end else "Non défini"


class NoteQuerySet(models.QuerySet):
    def order_by_domain_and_coef(self, serie=''):
        if serie in ['A1', 'A2', 'A3', 'A4', 'A5', 'ABI']:
            order = {
                'Langues et Littératures': 1,
                'Sciences Humaines': 2,
                'Sciences et Technologies': 3,
                'Arts et Cultures Nationales': 4,
                'Développement Personnel': 5,
            }
        elif serie in ['C', 'D', 'E', 'TI']:
            order = {
                'Sciences et Technologies': 1,
                'Langues et Littératures': 2,
                'Sciences Humaines': 3,
                'Arts et Cultures Nationales': 4,
                'Développement Personnel': 5,
            }
        elif serie == 'SH':
            order = {
                'Sciences Humaines': 1,
                'Langues et Littératures': 2,
                'Sciences et Technologies': 3,
                'Arts et Cultures Nationales': 4,
                'Développement Personnel': 5,
            }
        elif serie == 'AC':
            order = {
                'Arts du Cinéma': 1,
                'Langues et Littératures': 2,
                'Sciences Humaines': 3,
                'Sciences et Technologies': 4,
                'Arts et Cultures Nationales': 5,
                'Développement Personnel': 6,
            }
        else:
            order = {
                'Sciences et Technologies': 1,
                'Langues et Littératures': 2,
                'Sciences Humaines': 3,
                'Arts et Cultures Nationales': 4,
                'Développement Personnel': 5,
            }
        return self.order_by(
            Case(
                *[When(enseignement__matiere__sujet__groupe=key, then=Value(value)) for key, value in order.items()],
                default=Value(999),
                output_field=IntegerField()
            ),
            '-enseignement__matiere__coeff'
        )


class Note(models.Model):
    eleve = models.ForeignKey(Student, on_delete=models.CASCADE)
    enseignement = models.ForeignKey(Enseignements, on_delete=models.CASCADE)
    eval = models.IntegerField()
    competences = models.TextField()
    note = models.DecimalField(default=-1, max_digits=4, decimal_places=2)

    objects = NoteQuerySet.as_manager()

    UniqueConstraint(name="unique_line", fields=["eleve", "enseignement", "eval"],
                     violation_error_message="Cette ligne de note existe déjà")

    class Meta:
        db_table = '"Note"'
