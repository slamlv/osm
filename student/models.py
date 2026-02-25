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

    def student_marks_report_data(self, evals: tuple, notes, total_coef=0, for_stats=False, pv=False):
        from osm.utils import formated_float, cote_and_appr
        from collections import defaultdict

        matieres_data = defaultdict(dict)

        total_notes = 0
        if pv and len(evals) == 6:
            total_notes1 = total_notes2 = total_notes3 = 0

        # =========================
        # 1️⃣ Regroupement des notes
        # =========================
        for note in notes:
            matiere = note.enseignement.matiere
            data = matieres_data[matiere.id]
            data['matiere'] = matiere
            data.setdefault('notes', {})[note.eval] = note.note if note.note != -1 else 0

        # =========================
        # 2️⃣ Calculs
        # =========================
        for data in matieres_data.values():
            matiere = data.pop('matiere')
            notes_data = data.pop('notes')

            moy = 0
            n = 0

            if len(evals) == 6:
                vals = [notes_data.get(e, 0) for e in evals]

                if pv:
                    total_notes1 += formated_float(
                        (vals[0] + vals[1]) / 2 if vals[0] and vals[1] else vals[0] + vals[1]
                    ) * matiere.coeff
                    total_notes2 += formated_float(
                        (vals[2] + vals[3]) / 2 if vals[2] and vals[3] else vals[2] + vals[3]
                    ) * matiere.coeff
                    total_notes3 += formated_float(
                        (vals[4] + vals[5]) / 2 if vals[4] and vals[5] else vals[4] + vals[5]
                    ) * matiere.coeff

                for v in vals:
                    if v:
                        moy += v
                        n += 1

                if n:
                    moy = formated_float(moy / n)

            else:
                note1 = formated_float(notes_data.get(evals[0], 0))
                note2 = formated_float(notes_data.get(evals[1], 0))

                if not for_stats and not pv:
                    data['note1'] = note1 if note1 else "/"
                    data['note2'] = note2 if note2 else "/"

                moy = formated_float((note1 + note2) / 2) if note1 and note2 else formated_float(note1 + note2)

            if for_stats:
                data["moy"] = moy if moy else "/"

            if for_stats or pv:
                total_notes += float(moy) * matiere.coeff

        if for_stats or pv:
            moyenne = formated_float(total_notes / total_coef)

        # =========================
        # 3️⃣ Résultats
        # =========================
        if for_stats:
            return {
                'sexe': self.genre,
                'matieres_data': matieres_data,
                'moyenne': moyenne,
                'nom': self.__str__()
            }

        if pv:
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
            return result

        return {
            "sexe": self.genre,
            'nom': self.__str__(),
            'matieres_data': matieres_data
        }

    def student_reportcard_data(self, evals: tuple, total_coef: int, lv2: str, lv3: str, notes):
        from osm.utils import formated_float, cote_and_appr
        from collections import defaultdict

        matieres_data = defaultdict(dict)
        total_notes = 0

        trim = {(1, 2): 1, (3, 4): 2, (5, 6): 3}.get(evals, 4)

        if len(evals) == 6:
            total_notes1 = total_notes2 = total_notes3 = 0

        # =========================
        # 1️⃣ Regroupement des notes
        # =========================
        for note in notes:
            matiere = note.enseignement.matiere
            data = matieres_data[matiere.id]
            data['matiere'] = matiere
            data.setdefault('notes', {})[note.eval] = None if note.note == -1 else note.note

        efforts = "Des efforts s'imposent en :"

        # =========================
        # 2️⃣ Calculs
        # =========================
        for data in matieres_data.values():
            matiere = data.pop('matiere')
            notes_data = data.pop('notes')

            if len(evals) == 6:
                vals = [notes_data.get(e) for e in evals]
                moys = []

                for i in range(0, 6, 2):
                    a, b = vals[i], vals[i + 1]
                    if a is not None and b is not None:
                        m = formated_float((a + b) / 2)
                    elif a is not None:
                        m = formated_float(a)
                    elif b is not None:
                        m = formated_float(b)
                    else:
                        m = 0
                    data[f'moy{i // 2 + 1}'] = m if m else "/"
                    moys.append(m)

                total_notes1 += float(moys[0]) * matiere.coeff
                total_notes2 += float(moys[1]) * matiere.coeff
                total_notes3 += float(moys[2]) * matiere.coeff

                moy = formated_float(sum(m for m in moys if m) / len([m for m in moys if m])) if any(moys) else 0

            else:
                note1 = notes_data.get(evals[0])
                note2 = notes_data.get(evals[1])

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

        # =========================
        # 3️⃣ Résultat final
        # =========================
        moyenne = formated_float(total_notes / total_coef)
        cote, appr = cote_and_appr(moyenne)

        if appr != "/":
            appreciation = (
                (((("Compétences non acquises.", "Compétences moyennement acquises.")[appr == "CMA"],
                   "Compétences acquises.")[appr == "CA"],
                  "Compétences bien acquises.")[appr == "CBA"],
                 "Compétences très bien acquises.")[appr == "CBTA"]
            )
            if efforts.endswith(','):
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
