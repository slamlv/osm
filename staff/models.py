# Create your models here.

from django.db import models
from authentification.models import User, Civilite, Poste
from django.db.models import When, Case, Value, IntegerField, F, UniqueConstraint, Q


class Activities(models.Model):
    start = models.DateField()
    end = models.DateField()
    label = models.TextField()
    responsables = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ('start', 'end')
        db_table = '"Activities"'

    def __str__(self):
        date = self.start
        if self.end != self.start:
            date = f"{self.start} - {self.end}"
        return f'{date} : {self.label}'


class Discipline(models.Model):
    id = models.IntegerField(primary_key=True)
    label = models.CharField(max_length=100)
    matiere = models.CharField(max_length=50, blank=True, null=True)
    groupe = models.CharField(max_length=100)

    class Meta:
        db_table = '"Discipline"'

    def __str__(self):
        return self.matiere if self.matiere else self.label

    @property
    def name(self):
        return f"{self.label} " + f"({self.matiere})" if self.matiere else f"{self.label}"

    @property
    def label_or_matiere(self):
        if self.matiere:
            return self.matiere
        return self.label

    @classmethod
    def get_disciplines(cls):
        disciplines = Discipline.objects.filter(id=1)
        queryset = Discipline.objects.filter(id__gt=1)
        for q in queryset:
            i = 0
            for d in disciplines:
                if (q.label in [d.label, d.matiere]) or (q.matiere and q.matiere in [d.label, d.matiere]):
                    i = 1
                    break
            if i == 0:
                disciplines = disciplines | Discipline.objects.filter(id=q.id)
        disciplines = disciplines.order_by("id")
        return disciplines


class StaffQuerySet(models.QuerySet):
    def priorite_par_matiere(self, matiere_id):
        from collections import OrderedDict
        queryset = self.annotate(
            priorite=Case(
                When(discipline__id=matiere_id, then=Value(0)),
                default=Value(999),
                output_field=IntegerField()
            )
        ).order_by('priorite', 'nom', 'prenom')

        ids = list(queryset.values_list('id', flat=True))
        ids = list(OrderedDict.fromkeys((ids)))
        preserved = Case(
            *[When(pk=pk, then=pos) for pos, pk in enumerate(ids)],
            output_field=IntegerField()
        )
        return self.filter(pk__in=ids).order_by(preserved)

    def order_by_poste(self):
        order = {
            'Chef d\'Établissement': 1,
            'Censeur': 2,
            'Surveillant-Général': 3,
            'Intendant': 4,
            'Économe': 5,
            'Conseiller d\'orientation': 6,
            'Enseignant': 7,
            'Surveillant de secteur': 8,
            'Gardien': 9,
            'Autre': 10
        }

        return self.order_by(
            Case(
                *[When(poste=key, then=Value(value)) for key, value in order.items()],
                default=Value(999),
                output_field=IntegerField()
            ), 'nom', 'prenom'
        )


class Personnel(models.Model):

    class Grade(models.TextChoices):
        PCEG = "PCEG", "PCEG"
        PLEG = "PLEG", "PLEG"
        PCET = "PCET", "PCET"
        PLET = "PLET", "PLET"
        CO = "CO", "CO"
        CONT = "Contractuel", "Contractuel"
        OTH = "Autre", "Autre"

    nom = models.CharField(max_length=30)
    prenom = models.CharField(max_length=30, null=True)
    contact = models.CharField(max_length=9, unique=True)
    contact1 = models.CharField(max_length=9, null=True)
    email = models.EmailField(null=True, blank=True)
    civilite = models.CharField(choices=Civilite.choices, max_length=10)
    grade = models.CharField(choices=Grade.choices, default="Autre", max_length=30)
    poste = models.CharField(choices=Poste.choices, max_length=30)
    since = models.IntegerField(null=True)
    discipline = models.ManyToManyField(Discipline)
    photo = models.ImageField(upload_to="image/staff", null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, unique=True, null=True, related_name="staff_member")

    objects = StaffQuerySet.as_manager()

    def timetable(self, mp, school_id, download=False, empty=False):

        def color(classrooms, classes):
            index = classrooms.index(classes)
            if index == 0:
                return "bg-blue text-white"
            elif index == 1:
                return "text-bg-success"
            elif index == 2:
                return "text-bg-info"
            elif index == 3:
                return "text-bg-warning"
            elif index == 4:
                return "text-bg-danger"
            elif index == 5:
                return "text-bg-primary"
            elif index == 6:
                return "text-bg-dark"
            elif index == 7:
                return "bg-dark-pink text-white"
            elif index == 8:
                return "bg-green text-white"
            elif index == 9:
                return "bg-violet text-white"
            elif index == 10:
                return "bg-dark-blue text-white"
            elif index == 11:
                return "bg-dark-orange text-white"
            elif index == 12:
                return "text-bg-secondary"
            elif index == 13:
                return "bg-dark-cyan text-white"
            elif index == 14:
                return "bg-pink text-dark"
            elif index == 15:
                return "bg-yellow text-dark"
            return ""

        def recap(classes, mp):
            staff_member_recap = list()
            programmations = self.programmations.all()
            total_heures = programmations.count() if programmations.exists() else ""
            while programmations.exists():
                programmation = programmations.first()
                if mp:
                    matiere = programmation.short(programmation.classrooms.first(), recap=True)
                else:
                    matiere = programmation.short(programmation.classroom, recap=True)
                if matiere not in ['Français', 'Informatique']:
                    programmations_matiere = programmations.filter(matiere__sujet=programmation.matiere.sujet)
                else:
                    programmations_matiere = (
                        programmations.
                        filter(Q(matiere__sujet__matiere=matiere) | Q(matiere__sujet__label=matiere))
                    )
                programmations = programmations.exclude(id__in=[p.id for p in programmations_matiere])
                mrecap = {'matiere': matiere, 'nb_heures': programmations_matiere.count()}
                matiere_recap = list()
                while programmations_matiere.exists():
                    cprogrammation = programmations_matiere.first()
                    matiere_classes = cprogrammation.classes
                    if mp:
                        # TODO
                        ids = [
                            p.id for p in programmations_matiere if p.classes == matiere_classes
                        ]
                    else:
                        ids = [
                            p.id for p in programmations_matiere.filter(classroom=cprogrammation.classroom)
                        ]
                    matiere_recap.append({
                        'classes': matiere_classes,
                        'nb_heures': len(ids),
                        'colors': color(classes, matiere_classes) if not download else None
                    })
                    programmations_matiere = programmations_matiere.exclude(id__in=ids)
                mrecap['matiere_recap'] = matiere_recap
                staff_member_recap.append(mrecap)
            return staff_member_recap, total_heures

        from authentification.models import School
        school = School.objects.prefetch_related('tranches_horaires').get(id=school_id)
        tranches_horaires = school.tranches_horaires.all()
        if empty:
            return tranches_horaires, school.school_to_dict()
        programmations = list(self.programmations.order_by('jour', 'tranche_horaire__number'))
        classrooms = list()
        for programmation in programmations:
            if programmation.classes not in classrooms:
                classrooms.append(programmation.classes)
        matrice = dict()
        days_indexes = (1, 2, 3, 4, 5)
        for day in days_indexes:
            matrice[day] = [
                {'matiere': None,
                 'classes': None,
                 'rowspan': 1,
                 'is_pause': not tranche.is_cours,
                 'jour': day,
                 'tranche': tranche.pk
                 } for tranche in tranches_horaires
            ]
        for programmation in programmations:
            classes = programmation.classes
            day = programmation.jour
            index_tranche = next(
                i for i, t in enumerate(tranches_horaires) if t.id == programmation.tranche_horaire_id
            )
            if not download:
                matrice[day][index_tranche]['colors'] = color(classrooms, classes)
            matrice[day][index_tranche]['matiere'] = (
                programmation.short(programmation.classrooms.first() if mp else programmation.classroom)
            )
            matrice[day][index_tranche]['classes'] = classes
        # Fusion
        for _, liste in matrice.items():
            i = 0
            while i < len(liste):
                current = liste[i]
                if current is None or current['is_pause'] or current['matiere'] is None:
                    i += 1
                    continue
                rowspan = 1
                while (i + rowspan < len(liste)) and not liste[i + rowspan]['is_pause'] and liste[i + rowspan][
                    'matiere'] == current['matiere'] and liste[i + rowspan]['classes'] == current['classes']:
                    liste[i + rowspan] = None
                    rowspan += 1
                current['rowspan'] = rowspan
                i += rowspan
        time_table = list()
        for tranche_horaire in tranches_horaires:
            if not tranche_horaire.is_cours:
                time_table.append((tranche_horaire, False))
            else:
                time_table.append((
                    tranche_horaire,
                    matrice[1][tranche_horaire.number - 1],
                    matrice[2][tranche_horaire.number - 1],
                    matrice[3][tranche_horaire.number - 1],
                    matrice[4][tranche_horaire.number - 1],
                    matrice[5][tranche_horaire.number - 1]
                ))
        if download:
            infos = {
                'nom': f"{self.nom} {self.prenom}" if self.prenom else self.nom,
                'grade': self.grade if self.grade != "Autre" else ""
            }
            return time_table, infos, school.school_to_dict(), recap(classrooms, mp)
        return time_table, recap(classrooms, mp)

    @property
    def is_admin(self):
        if self.user:
            return self.user.is_admin
        return False

    class Meta:
        db_table = '"Personnel"'
        constraints = [
            UniqueConstraint(fields=['email'], condition=Q(email__isnull=False), name='unique_notnull_email')
        ]

    @property
    def post(self):
        if self.poste == "Chef d'Établissement":
            if self.user:
                return self.user.post
            from django.db import connection
            from authentification.models import School
            return School.objects.get(schema_name=connection.schema_name).chef
        return self.poste

    @property
    def short_name(self):
        civilite = "M." if self.civilite == "Monsieur" else "Mme"
        short = f"{self.nom.split()[0]} {self.prenom.split()[0]}" if self.prenom else self.nom
        return f"{civilite} {short}"\

    @property
    def short_firstname(self):
        civilite = "M." if self.civilite == "Monsieur" else "Mme"
        return f"{civilite} {self.nom.split()[0]}"

    def __str__(self):
        civilite = "M." if self.civilite == "Monsieur" else "Mme"
        return f"{civilite} {self.nom} {self.prenom}" if self.prenom else f"{civilite} {self.nom}"


# Indiquer que le membre du personnel dispense certaines disciplines
    @classmethod
    def add_disciplines(cls, staff_member, disciplines, call=False):

        def get_disciplines(disciplines):
            ids = list()
            for d in disciplines:
                ids.append(d.id)
                for elt in Discipline.objects.filter(id__gt=0).exclude(id__in=ids):
                    if (d.label in [elt.label, elt.matiere]) or (d.matiere and d.matiere in [elt.label, elt.matiere]):
                        ids.append(elt.id)
            return ids

        if call:
            get_disciplines(disciplines)
        if disciplines:
            ids = get_disciplines(disciplines)
            for discipline in Discipline.objects.filter(id__in=ids):
                staff_member.discipline.add(discipline)

# mise à jour des disciplines pour un enseignant
    @classmethod
    def update_disciplines(cls, staff_member, disciplines):
        staff_member.discipline.clear()
        Personnel.add_disciplines(staff_member, disciplines)

# check
    """
        check the necessary
    """
    @classmethod
    def get_disciplines(cls, queryset):
        set = Discipline.objects.all()
        ids = [discipline.id for discipline in queryset]
        disciplines = set.filter(id__in=ids)
        return disciplines
