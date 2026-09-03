# Create your models here.
import inspect

import django.db.models
from django.db import models
from django.db.models import UniqueConstraint, Sum, Q, When, Case, Value, IntegerField
from classroom.models import ClassRoom
from authentification.models import Civilite, SchoolYear
from collections import defaultdict


class Parent(models.Model):
    nom = models.CharField(max_length=30)
    prenom = models.CharField(max_length=30, null=True)
    courriel = models.EmailField(max_length=30, null=True, blank=True)
    contact = models.CharField(max_length=9, unique=True)
    profession = models.CharField(max_length=50, null=True)
    civilite = models.CharField(choices=Civilite.choices, max_length=10)

    class Meta:
        db_table = '"Parent"'
        constraints = [
            models.UniqueConstraint(
                fields=['courriel'],
                condition=Q(courriel__isnull=False, courriel__gt=""),
                name='unique_courriel_si_non_null'
            )
        ]

    @property
    def email(self):
        return self.courriel if self.courriel else "/"

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
            'Sixième': 0, 'Cinquième': 1, 'Quatrième': 2, 'Troisième': 3,
            'Seconde': 4, 'Première': 5, 'Terminale': 6, None: 7
        }
        return self.order_by(
            Case(
                *[When(classe__classe__niveau=key, then=Value(value)) for key, value in order.items()],
                default=Value(8),
                output_field=IntegerField()
            ), 'classe', 'nom', 'prenom'
        )


class StudentAllManager(models.Manager.from_queryset(StudentQuerySet)):
    pass


class StudentActiveManager(models.Manager.from_queryset(StudentQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


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
    is_active = models.BooleanField(default=True)

    objects = StudentActiveManager()  # actifs only (usage courant)
    objects_all = StudentAllManager()  # tout (actifs + désactivés)

    UniqueConstraint(name="unique_student", fields=['nom', 'prenom', 'date_naissance'])

    class Meta:
        db_table = '"Student"'
        base_manager_name = "objects_all"  # accès liés / admin voient TOUT

    # ------------------------------------------------------------------
    # Suppression DÉFINITIVE : on retire aussi la photo du stockage.
    # Centraliser ici garantit que TOUTE suppression (DeleteView unitaire,
    # suppression groupée, admin) nettoie l'image -> pas d'orphelin Cloudinary.
    # ------------------------------------------------------------------
    def delete(self, *args, **kwargs):
        from osm.utils import delete_image
        from finance.models import StudentPayment
        if StudentPayment.objects.filter(student=self).exists():
            nom = self.short_name
            StudentPayment.objects.filter(student=self).update(student_name=nom)
        if self.photo:
            delete_image(self.photo)
        return super().delete(*args, **kwargs)

    def deactivate(self):
        if self.is_active:
            self.is_active = False
            self.save(update_fields=["is_active"])

    def activate(self):
        if not self.is_active:
            self.is_active = True
            self.save(update_fields=["is_active"])

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
    def contacts_parent(self):
        contacts = list()
        if self.pere and self.pere.contact:
            contacts.append(self.pere.contact)
        if self.mere and self.mere.contact:
            contacts.append(self.mere.contact)
        return contacts

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
    def name_for_livret(self):
        nom = self.nom.upper()
        return f"{nom} {self.prenom.upper()}" if self.prenom else nom

    @property
    def classroom(self):
        return self.classe.code if self.classe else "/"

    def __str__(self):
        return f"{self.nom} {self.prenom}" if self.prenom else f"{self.nom}"

    def student_marks_report_data(self, evals: tuple, notes, total_coef=0, for_stats=False, pv=False, annual=False,
                                  mentions=True, year=None):
        from note.deliberation import student_decision, conduct_mention, merit_mention
        from osm.utils import formated_float, cote_and_appr
        from collections import defaultdict

        matieres_data = defaultdict(dict)

        total_notes = 0
        if (pv or for_stats) and len(evals) == 6:
            total_notes1 = total_notes2 = total_notes3 = 0

        # =========================
        # 1️⃣ Regroupement des notes
        # =========================
        for note in notes:
            matiere = note.enseignement.matiere
            data = matieres_data[matiere.id]
            data['matiere'] = matiere
            data.setdefault('notes', {})[note.eval] = note.note if note.note != -1 else None

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

                moys = []

                for i in range(0, 6, 2):
                    a, b = vals[i], vals[i + 1]
                    if a is not None and b is not None:
                        m = (a + b) / 2
                    elif a is not None:
                        m = a
                    elif b is not None:
                        m = b
                    else:
                        m = None
                    moys.append(m)

                if pv or for_stats:
                    total_notes1 += float(moys[0]) * matiere.coeff if moys[0] is not None else 0
                    total_notes2 += float(moys[1]) * matiere.coeff if moys[1] is not None else 0
                    total_notes3 += float(moys[2]) * matiere.coeff if moys[2] is not None else 0

                n = t = 0
                for m in moys:
                    if m is not None:
                        t += float(m)
                        n += 1
                moy = t / n if n else 0

            else:
                note1 = notes_data.get(evals[0])
                note2 = notes_data.get(evals[1])

                if not for_stats and not pv:
                    data['note1'] = formated_float(note1) if note1 is not None else "/"
                    data['note2'] = formated_float(note2) if note2 is not None else "/"

                if note1 is not None and note2 is not None:
                    moy = (note1 + note2) / 2
                elif note1 is not None:
                    moy = note1
                elif note2 is not None:
                    moy = note2
                else:
                    moy = 0

            if for_stats:
                data["moy"] = formated_float(moy) if moy else "/"

            if for_stats or pv:
                total_notes += float(moy) * matiere.coeff

        if for_stats or pv:
            if len(evals) == 6:
                moyenne1 = total_notes1 / total_coef
                moyenne2 = total_notes2 / total_coef
                moyenne3 = total_notes3 / total_coef
                n = t = 0
                for moy in [moyenne1, moyenne2, moyenne3]:
                    if moy:
                        t += moy
                        n += 1
                moyenne = t / n if n else 0
            else:
                moyenne = total_notes / total_coef

        # =========================
        # 3️⃣ Résultats
        # =========================
        if for_stats:
            return {
                'sexe': self.genre,
                'matieres_data': matieres_data,
                'moyenne': formated_float(moyenne),
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
                'moyenne': formated_float(moyenne),
                'cote': cote,
                'appr': appr
            }
            if annual:
                result["decision"], result['next'], result["divergente"] = student_decision(self, year, moyenne, self.classe.moyenne_min_admission)
                if mentions:
                    result["conduite"] = conduct_mention(self.discipline_to_dict(4))
                    result["merite"] = merit_mention(moyenne)
                else:
                    result["mention"] = ""  # colonne à remplir
            if len(evals) == 6:
                result['moy1'] = formated_float(moyenne1)
                result['moy2'] = formated_float(moyenne2)
                result['moy3'] = formated_float(moyenne3)
            return result

        return {
            "sexe": self.genre,
            'nom': self.__str__(),
            'matieres_data': matieres_data
        }

    def student_reportcard_data(self, evals: tuple, total_coef: int, lv2: str, lv3: str, notes, for_livret=False):
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

        if not for_livret:
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
                        m = (a + b) / 2
                    elif a is not None:
                        m = a
                    elif b is not None:
                        m = b
                    else:
                        m = None
                    if not for_livret:
                        data[f'moy{i // 2 + 1}'] = formated_float(m) if m is not None else "/"
                    moys.append(m)

                total_notes1 += float(moys[0]) * matiere.coeff if moys[0] is not None else 0
                total_notes2 += float(moys[1]) * matiere.coeff if moys[1] is not None else 0
                total_notes3 += float(moys[2]) * matiere.coeff if moys[2] is not None else 0

                n = t = 0
                for m in moys:
                    if m is not None:
                        t += m
                        n += 1
                moy = t / n if n else 0

            else:
                note1 = notes_data.get(evals[0])
                note2 = notes_data.get(evals[1])

                data['note1'] = formated_float(note1) if note1 is not None else "/"
                data['note2'] = formated_float(note2) if note2 is not None else "/"

                if note1 is not None and note2 is not None:
                    moy = (note1 + note2) / 2
                elif note1 is not None:
                    moy = note1
                elif note2 is not None:
                    moy = note2
                else:
                    moy = 0

            data["moy"] = formated_float(moy) if moy else "/"
            if not for_livret:
                data['cote'], data['appr'] = cote_and_appr(moy)
                data["moy*coef"] = formated_float(moy * matiere.coeff) if moy else "/"

            total_notes += float(moy) * matiere.coeff

            if 0 < moy < 10 and not for_livret:
                label = matiere.sujet.label
                if label == "LVII":
                    label = lv2
                elif label == "LVIII":
                    label = lv3
                efforts += f" {label},"

        # =========================
        # 3️⃣ Résultat final
        # =========================
        if len(evals) == 6:
            moyenne1 = total_notes1 / total_coef
            moyenne2 = total_notes2 / total_coef
            moyenne3 = total_notes3 / total_coef
            n = t = 0
            for moy in [moyenne1, moyenne2, moyenne3]:
                if moy:
                    t += moy
                    n += 1
            moyenne = t / n if n else 0
        else:
            moyenne = total_notes / total_coef
        if not for_livret:
            cote, appr = cote_and_appr(moyenne)

        if not for_livret:
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
            'student': self.student_to_dict() if not for_livret else f"{self.name_for_livret} né(e) le "
                                                                     f"{self.date_naissance.strftime("%d/%m/%Y")} à "
                                                                     f"{self.lieu_naissance.upper()}",
            'matieres_data': matieres_data,
            'moyenne': formated_float(moyenne),
            'total_notes': formated_float(total_notes) if total_notes else "/",

        }

        if not for_livret:
            results['cote'], results['appr'], results['appreciation'] = cote, appr, appreciation
            results['discipline'] = self.discipline_to_dict(trim)
            if len(evals) == 6:
                results['discipline_t1'] = self.discipline_to_dict(1)
                results['discipline_t2'] = self.discipline_to_dict(2)
                results['discipline_t3'] = self.discipline_to_dict(3)

        if len(evals) == 6:
            results['moyenne1'] = formated_float(moyenne1)
            results['moyenne2'] = formated_float(moyenne2)
            results['moyenne3'] = formated_float(moyenne3)

        return results

    def student_level(self, classroom=None):
        """(niveau, serie) de l'élève, ex. ("Terminale", "C") — serie peut être
        None/'' — ou (None, None) si l'élève est sans classe."""
        classe = classroom or self.classe
        if not classe:
            return None, None
        cls = classe.classe  # ClassRoom -> Class
        return cls.niveau, (cls.serie or None)

    def applicable_fees(self, school_year, fee_type_id=None, classroom=None):
        from finance.models import SchoolFee
        """Lignes de grille applicables à l'élève pour l'année.
        CASCADE DE SPÉCIFICITÉ par type de frais : (niveau+série) > (niveau) >
        (tous niveaux). Ex. frais de labo : ligne "Terminale"+"C" -> ne touche
        que les Tle C ; un élève de Tle A4 n'a AUCUNE ligne labo -> pas concerné."""
        niveau, serie = self.student_level(classroom=classroom)
        qs = (SchoolFee.objects
              .filter(school_year=school_year, fee_type__is_active=True)
              .filter(Q(level__isnull=True)
                      | Q(level=niveau, serie__isnull=True)
                      | Q(level=niveau, serie=serie))
              .select_related("fee_type")
              .prefetch_related("installments"))
        if fee_type_id:
            qs = qs.filter(fee_type_id=fee_type_id)
        by_type = {}
        for fee in qs:
            cur = by_type.get(fee.fee_type_id)
            if cur is None or fee.specificity > cur.specificity:
                by_type[fee.fee_type_id] = fee
        return list(by_type.values())

    def student_fee_status(self, school_year, today=None, fee_type_id=None, classroom=None):
        from datetime import date as _date
        from finance.models import StudentPayment, FeeDiscount
        """Situation complète de l'élève : une entrée par type de frais applicable.

        Chaque entrée :
          fee_type, du_brut, remise, du_net, paye, reste,
          jalons_echus (cumul des tranches dont la date est passée, plafonné au dû net),
          retard (ce qui aurait dû être payé à ce jour et ne l'est pas),
          solde (True si reste == 0)

        Les paiements étant LIBRES (avances), le retard se calcule par cumul :
          retard = max(0, min(jalons_echus, du_net) - paye)
        Sans jalons définis (cas APEE), jalons_echus = du_net dès le 1er jour ?
        NON : sans jalons, on considère le dû exigible à l'année -> retard = 0
        tant que l'année n'est pas close ; l'insolvabilité se juge sur `reste`.
        """
        today = today or _date.today()

        # paiements et remises de l'année, agrégés en 2 requêtes
        payments = dict(
            StudentPayment.objects
            .filter(student=self, school_year=school_year, cancelled=False)
            .values_list("fee_type").annotate(total=Sum("amount")))
        if fee_type_id:
            payments = dict(
                StudentPayment.objects
                .filter(student=self, school_year=school_year, cancelled=False, fee_type_id=fee_type_id)
                .values_list("fee_type").annotate(total=Sum("amount")))
        discounts = dict(
            FeeDiscount.objects
            .filter(student=self, school_year=school_year)
            .values_list("fee_type").annotate(total=Sum("amount")))

        rows = []
        for fee in self.applicable_fees(school_year, fee_type_id=fee_type_id, classroom=classroom):
            du_brut = fee.amount
            remise = discounts.get(fee.fee_type_id, 0)
            du_net = max(0, du_brut - remise)
            paye = payments.get(fee.fee_type_id, 0)
            reste = max(0, du_net - paye)

            jalons = [i for i in fee.installments.all() if i.due_date <= today]
            jalons_echus = min(sum(i.amount for i in jalons), du_net) if jalons else 0
            retard = max(0, jalons_echus - paye)

            rows.append({
                "fee_type": fee.fee_type,
                "affects_cashbox": fee.fee_type.affects_cashbox,
                "du_brut": du_brut, "remise": remise, "du_net": du_net,
                "paye": paye, "reste": reste,
                "jalons_echus": jalons_echus, "retard": retard,
                "solde": reste == 0,
            })
        return rows


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


class EnrollmentStatus(models.TextChoices):
    """
    Décision prise pour l'élève à la fin de l'année.

    - EN_COURS  : valeur par défaut tant que l'année n'est pas clôturée.
    - PROMU     : passe en classe supérieure (next_classroom rempli).
    - REDOUBLE  : refait la même classe (next_classroom = même niveau).
    - TRANSFERE : quitte pour un autre établissement.
    - SORTI     : a quitté l'établissement (ex: après le bac) ou est exclu.
    """
    EN_COURS = "En cours", "Année en cours"
    PROMU = "Promu", "Promu (classe supérieure)"
    REDOUBLE = "Redoublant", "Redoublant"
    TRANSFERE = "Transféré", "Transféré (autre établissement)"
    SORTI = "Sorti", "A terminé son cursus"
    EXCLU = "Exclu", "Exclu"
    NON_STATUE = "Non statué", "Décision non saisie"


class StudentEnrollment(models.Model):
    """
    Trace le passage d'un élève dans une classe pour une année scolaire donnée.

    C'est l'historique du parcours : un élève a un enrollment par année passée
    dans l'établissement. On peut ainsi reconstituer tout son cursus, et après
    la clôture (qui nettoie les notes), l'essentiel reste consultable ici
    (classe, moyenne figée, décision).
    """

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollments"
    )

    school_year = models.ForeignKey(
        # PROTECT : on interdit la suppression d'une année tant qu'il existe des
        # inscriptions rattachées -> on ne perd jamais l'historique par accident.
        SchoolYear,
        on_delete=models.PROTECT,
        related_name="enrollments"
    )

    # Classe occupée par l'élève PENDANT cette année.
    classroom = models.ForeignKey(
        ClassRoom,
        on_delete=models.SET_NULL,
        related_name="enrollments",
        null=True
    )

    # Classe prévue pour l'année SUIVANTE, saisie par le prof principal en fin
    # d'année AVANT la clôture. Reste vide si l'élève est transféré/sorti.
    next_classroom = models.ForeignKey(
        ClassRoom,
        on_delete=models.SET_NULL,
        related_name="future_enrollments",
        null=True,
        blank=True
    )

    # Décision de fin d'année (saisie par le prof principal, appliquée à la clôture).
    decision = models.CharField(
        choices=EnrollmentStatus.choices,
        max_length=15,
        default=EnrollmentStatus.EN_COURS
    )

    # Moyennes et tangs FIGÉESau moment de la clôture. On la stocke ici pour
    # garder une trace consultable même après le nettoyage des notes en base.
    moyenne_t1 = models.FloatField(null=True, blank=True)
    rang_t1 = models.CharField(max_length=8, null=True, blank=True)
    moyenne_t2 = models.FloatField(null=True, blank=True)
    rang_t2 = models.CharField(max_length=8, null=True, blank=True)
    moyenne_t3 = models.FloatField(null=True, blank=True)
    rang_t3 = models.CharField(max_length=8, null=True, blank=True)
    moyenne_annuelle = models.FloatField(null=True, blank=True)
    rang_annuel = models.CharField(max_length=8, null=True, blank=True)
    discipline_t1 = models.JSONField(null=True, blank=True)
    discipline_t2 = models.JSONField(null=True, blank=True)
    discipline_t3 = models.JSONField(null=True, blank=True)
    discipline = models.JSONField(null=True, blank=True)

    # Traçabilité de la décision : qui l'a prise et quand.
    decided_by = models.CharField(max_length=80, null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = '"StudentEnrollment"'
        ordering = ['-school_year__annee_debut']
        constraints = [
            # Un élève ne peut avoir qu'UNE inscription par année scolaire.
            models.UniqueConstraint(
                fields=["student", "school_year"],
                name="unique_enrollment_per_year"
            )
        ]

    def __str__(self):
        classe = self.classroom.code if self.classroom else "—"
        return f"{self.student} — {classe} ({self.school_year})"
