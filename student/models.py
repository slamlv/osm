# Create your models here.
import django.db.models
from django.db import models
from django.db.models import UniqueConstraint
from classroom.models import ClassRoom
from authentification.models import Civilite
from django.db.models import Q
from django.db.models import When, Case, Value, IntegerField, F
from collections import defaultdict


class Parent(models.Model):
    nom = models.CharField(max_length=30)
    prenom = models.CharField(max_length=30, null=True)
    email = models.EmailField(max_length=30, null=True)
    contact = models.CharField(max_length=9, unique=True)
    profession = models.CharField(max_length=50, null=True)
    civilite = models.CharField(choices=Civilite.choices, max_length=10)

    class Meta:
        db_table = '"Parent"'
        constraints = [
            models.UniqueConstraint(
                fields=['email'],
                condition=~Q(email=None),
                name='unique_courriel_si_non_null'
            )
        ]

    @property
    def courriel(self):
        return self.email if self.email else "/"

    @property
    def name(self):
        return f"{self.nom} {self.prenom}" if self.prenom else self.prenom

    @property
    def boulot(self):
        return self.profession if self.profession else "/"

    def __str__(self):
        civilite = "M." if self.civilite == "Monsieur" else "Mme"
        return f"{civilite} {self.nom} {self.prenom}" if self.prenom else f"{civilite} {self.nom}"


class Statut(models.TextChoices):
    NO = "Nouveau", "Nouveau"
    RE = "Redoublant", "Redoublant"


class Sexe(models.TextChoices):
    F = "Fille", "Fille"
    G = "Garçon", "Garçon"


class StudentQuerySet(models.QuerySet):
    def order_by_classroom_level(self):
        order = {
            None: 0,
            'Sixième': 1,
            'Cinquième': 2,
            'Quatrième': 3,
            'Troisième': 4,
            'Seconde': 5,
            'Première': 6,
            'Terminale': 7,
        }

        return self.order_by(
            Case(
                *[When(classe__classe__niveau=key, then=Value(value)) for key, value in order.items()],
                default=Value(999),
                output_field=IntegerField()
            ), 'classe', 'nom', 'prenom'
        )


class Student(models.Model):
    nom = models.CharField(max_length=30)
    prenom = models.CharField(max_length=30, null=True)
    statut = models.CharField(choices=Statut.choices, max_length=15)
    date_naissance = models.DateField()
    lieu_naissance = models.CharField(max_length=50)
    sexe = models.CharField(choices=Sexe.choices)
    pere = models.ForeignKey(Parent, on_delete=models.SET_NULL, related_name="father_children", null=True)
    mere = models.ForeignKey(Parent, on_delete=models.SET_NULL, related_name="mother_children", null=True)
    classe = models.ForeignKey(ClassRoom, on_delete=models.SET_NULL, related_name="students", null=True)
    photo = models.ImageField(upload_to="image/student", blank=True, null=True)
    unique_id = models.IntegerField(unique=True)

    UniqueConstraint(name="unique_student", fields=['nom', 'prenom', 'date_naissance'])

    objects = StudentQuerySet.as_manager()

    class Meta:
        db_table = '"Student"'

    def student_to_dict(self):
        return {
            'pk': self.pk,
            'nom': self.__str__(),
            'short_name': self.short_name,
            'date_lieu_naissance': f"{self.date_naissance.strftime('%d/%m/%Y')} à {self.lieu_naissance}",
            'sexe': self.genre,
            'pere': f"{self.pere.name}, contact: {self.pere.contact}" if self.pere else "",
            'mere': f"{self.mere.name}, contact: {self.mere.contact}" if self.mere else "",
            'photo': self.photo,
            'matricule': self.unique_id,
            'statut': self.redoublant,
        }

    @property
    def csi_number(self):
        student_pk = self.pk
        n = len(str(student_pk))
        return f"{'0' * (4 - n)}{student_pk}"

    @property
    def dstd(self):
        return {'id': self.pk, 'nom': f"{self.__str__()} ({self.sexe}), classe : {self.classe.code}, identifiant : "
                                      f"{self.unique_id}"}

    def std(self, trim):
        try:
            stdd = StudentDiscipline.objects.get(student_id=self.pk, trim=trim)
        except:
            stdd = None
        return stdd

    def discipline_to_dict(self, trim):
        abst, absj, retards, consignes, excl, excl_def, avert, blame = 0, 0, 0, 0, 0, False, False, False
        trims = [1, 2, 3] if trim == 4 else [trim, ]
        for i in trims:
            discipline = self.std(trim=i)
            if discipline:
                abst, absj, retards = abst + discipline.abs, absj + discipline.absj, retards + discipline.retards
                consignes, excl = consignes + discipline.cons, excl + discipline.excl
                if not excl_def:
                    excl_def = discipline.excl_def
                if not avert:
                    avert = discipline.avert
                if not blame:
                    blame = discipline.blame
        return {
            "absnj": abst - absj,
            "absj": absj,
            "retards": retards,
            "excl": excl,
            "consignes": consignes,
            "avert": avert,
            "excl_def": excl_def,
            "blame": blame,
        }

    @property
    def short_name(self):
        return f"{self.nom.split()[0]} {self.prenom.split()[0]}" if self.prenom else self.nom

    @property
    def genre(self):
        if self.sexe == "Fille":
            return 'F'
        return 'M'

    @property
    def last_name(self):
        return self.prenom if self.prenom else "/"

    @property
    def redoublant(self):
        return True if self.statut == "Redoublant" else False

    @property
    def father(self):
        return self.pere if self.pere else "/"

    @property
    def mother(self):
        return self.mere if self.mere else "/"

    @property
    def classroom(self):
        return self.classe.code if self.classe else "/"

    def __str__(self):
        return f"{self.nom} {self.prenom}" if self.prenom else f"{self.nom}"

    def student_marks_report_data(self, evals: tuple, notes: models.QuerySet, total_coef=0, for_stats=False, pv=False):
        from osm.utils import formated_float

        matieres_data = defaultdict(dict)
        if for_stats or pv:
            total_notes = 0
        if pv and len(evals) == 6:
            total_notes1 = 0
            total_notes2 = 0
            total_notes3 = 0

        for note in notes:
            matiere = note.enseignement.matiere
            matieres_data[matiere.id]['matiere'] = matiere
            matieres_data[matiere.id].setdefault('notes', {})
            matieres_data[matiere.id]['notes'][note.eval] = note.note if note.note != -1 else 0

        for data in matieres_data.values():
            moy, n = 0, 0
            matiere = data.pop('matiere')
            notes_data = data.pop('notes')
            if len(evals) == 6:
                note1 = notes_data.pop(evals[0], 0)
                note2 = notes_data.pop(evals[1], 0)
                note3 = notes_data.pop(evals[2], 0)
                note4 = notes_data.pop(evals[3], 0)
                note5 = notes_data.pop(evals[4], 0)
                note6 = notes_data.pop(evals[5], 0)
                if pv:
                    total_notes1 += (
                        formated_float((note1 + note2) / 2) if (note1 and note2) else formated_float(note1 + note2)
                    ) * matiere.coeff
                    total_notes2 += (
                        formated_float((note3 + note4) / 2) if (note3 and note4) else formated_float(note3 + note4)
                    ) * matiere.coeff
                    total_notes3 += (
                        formated_float((note5 + note6) / 2) if (note5 and note6) else formated_float(note5 + note6)
                    ) * matiere.coeff
                for note in (note1, note2, note3, note4, note5, note6):
                    moy += note
                    if note:
                        n += 1
                if moy:
                    moy = formated_float(moy / n)
            else:
                note1 = formated_float(notes_data.pop(evals[0], 0))
                note2 = formated_float(notes_data.pop(evals[1], 0))
                if not for_stats and not pv:
                    data['note1'] = formated_float(note1) if note1 else "/"
                    data['note2'] = formated_float(note2) if note2 else "/"
                if note1 and note2:
                    moy = formated_float((note1 + note2) / 2)
                else:
                    moy = formated_float(note1 + note2)
            if for_stats:
                data["moy"] = moy if moy else "/"
            if for_stats or pv:
                total_notes += float(moy) * matiere.coeff

        if for_stats or pv:
            moyenne = formated_float(total_notes / total_coef)

        if for_stats:
            result = {
                'sexe': self.genre,
                'matieres_data': matieres_data,
                'moyenne': moyenne
            }
        elif pv:
            from osm.utils import cote_and_appr
            cote, appr = cote_and_appr(moyenne)
            result = {
                'student': {
                    'nom': self.__str__(),
                    'matricule': self.unique_id,
                    'sexe': self.genre,
                    'statut': "Oui" if self.redoublant else "Non"
                },
                'moyenne': moyenne,
                'cote': cote,
                'appr': appr
            }
            if len(evals) == 6:
                result['moy1'] = formated_float(total_notes1 / total_coef)
                result['moy2'] = formated_float(total_notes2 / total_coef)
                result['moy3'] = formated_float(total_notes3 / total_coef)
        else:
            result = {
                "sexe": self.genre,
                'nom': self.__str__(),
                'matieres_data': matieres_data
            }
        return result

    def student_reportcard_data(self, evals: tuple, total_coef: int, lv2: str, lv3: str, notes: models.QuerySet):
        from osm.utils import formated_float, cote_and_appr

        matieres_data = defaultdict(dict)
        total_notes = 0
        if evals == (1, 2):
            trim = 1
        elif evals == (3, 4):
            trim = 2
        elif evals == (5, 6):
            trim = 3
        else:
            trim = 4

        if len(evals) == 6:

            total_notes1 = 0
            total_notes2 = 0
            total_notes3 = 0

        for note in notes:
            matiere = note.enseignement.matiere
            matieres_data[matiere.id]['matiere'] = matiere
            matieres_data[matiere.id].setdefault('notes', {})
            matieres_data[matiere.id]['notes'][note.eval] = note.note if note.note != -1 else None

        efforts = "Des efforts s'imposent en :"
        for data in matieres_data.values():
            matiere = data.pop('matiere')
            notes_data = data.pop('notes')
            if len(evals) == 6:
                n = 3
                note1 = notes_data.pop(evals[0], None)
                note2 = notes_data.pop(evals[1], None)
                note3 = notes_data.pop(evals[2], None)
                note4 = notes_data.pop(evals[3], None)
                note5 = notes_data.pop(evals[4], None)
                note6 = notes_data.pop(evals[5], None)
                if note1 is not None and note2 is not None:
                    moy1 = formated_float((note1 + note2) / 2)
                elif note1 is not None:
                    moy1 = formated_float(note1)
                elif note2 is not None:
                    moy1 = formated_float(note2)
                else:
                    moy1 = 0
                    n -= 1
                data['moy1'] = moy1 if moy1 else "/"
                total_notes1 += float(moy1) * matiere.coeff
                if note3 is not None and note4 is not None:
                    moy2 = formated_float((note3 + note4) / 2)
                elif note3 is not None:
                    moy2 = formated_float(note3)
                elif note4 is not None:
                    moy2 = formated_float(note4)
                else:
                    moy2 = 0
                    n -= 1
                data['moy2'] = moy2 if moy2 else "/"
                total_notes2 += float(moy2) * matiere.coeff
                if note5 is not None and note6 is not None:
                    moy3 = formated_float((note5 + note6) / 2)
                elif note5 is not None:
                    moy3 = formated_float(note5)
                elif note6 is not None:
                    moy3 = formated_float(note6)
                else:
                    moy3 = 0
                    n -= 1
                data['moy3'] = moy3 if moy3 else "/"
                total_notes3 += float(moy3) * matiere.coeff
                moy = moy1 + moy2 + moy3
                if moy:
                    moy = formated_float(moy / n)
            else:
                note1 = notes_data.pop(evals[0], None)
                note2 = notes_data.pop(evals[1], None)
                data['note1'] = formated_float(note1) if note1 else "/"
                data['note2'] = formated_float(note2) if note2 else "/"
                if note1 is not None and note2 is not None:
                    moy = formated_float((note1 + note2) / 2)
                elif note1 is not None:
                    moy = formated_float(note1)
                elif note2 is not None:
                    moy = formated_float(note2)
                else:
                    moy = 0
            data["moy"] = moy if moy else "/"
            data['cote'], data['appr'] = cote_and_appr(moy)
            data["moy*coef"] = formated_float(moy * matiere.coeff) if moy else "/"
            total_notes += float(moy) * matiere.coeff

            if 0 < moy < 10:
                label = matiere.sujet.label
                if label == "LVII":
                    label = lv2
                elif label == "LVIII":
                    label = lv3
                efforts += f" {label},"

        moyenne = formated_float(total_notes / total_coef)
        cote, appr = cote_and_appr(moyenne)
        if appr != "/":
            appreciation = (((("Compétences non acquises.", "Compétences moyennement acquises.")[appr == "CMA"],
                              "Compétences acquises.")[appr == "CA"], "Compétences bien acquises.")[appr == "CBA"],
                            "Compétences très bien acquises.")[appr == "CBTA"]
            if efforts[-1] == ',':
                appreciation += f" {efforts[:-1]}."
        else:
            appreciation = "/"
        results = {
            'student': self.student_to_dict(),
            'matieres_data': matieres_data,
            'moyenne': moyenne,
            'cote': cote,
            'appr': appr,
            'appreciation': appreciation,
            'total_notes': formated_float(total_notes) if total_notes else "/",
            'discipline': self.discipline_to_dict(trim)
        }
        if len(evals) == 6:
            results['moyenne1'] = formated_float(total_notes1 / total_coef)
            results['moyenne2'] = formated_float(total_notes2 / total_coef)
            results['moyenne3'] = formated_float(total_notes3 / total_coef)
        return results


class StudentDiscipline(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="discipline")
    trim = models.IntegerField(default=1)
    avert = models.BooleanField(default=False)
    excl_def = models.BooleanField(default=False)
    blame = models.BooleanField(default=False)
    cons = models.IntegerField(default=0)
    abs = models.IntegerField(default=0)
    absj = models.IntegerField(default=0)
    retards = models.IntegerField(default=0)
    excl = models.IntegerField(default=0)

    UniqueConstraint(name="unique_discipline", fields=["student", "trim"],
                     violation_error_message="Cet enregistrement de discipline existe déjà")

    class Meta:
        db_table = "StudentDiscipline"
