# Create your models here.

from django.db import models
from authentification.models import User, Civilite, Poste
from django.db.models import When, Case, Value, IntegerField, F, UniqueConstraint, Q


Poste_Fem = {
    'Censeur': "Censeure",
    'Surveillant Général': "Surveillante Générale",
    'Conseiller d\'orientation': "Conseillère d'orientation",
    'Surveillant de secteur': "Surveillante de secteur",
    'Intendant': "Intendante",
    'Infirmier': "Infirmière",
    'Enseignant': "Enseignante",
    'Technicien de surface': "Technicienne de surface",
}


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
    def personnels_tries(self):
        """
        Tout le personnel, enseignants en tête (poste='Enseignant'), puis par nom.
        """
        return (
            self.annotate(ens=Case(
                When(poste="Enseignant", then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ))
            .order_by("ens", "nom", "prenom")
        )

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
            'Surveillant Général': 3,
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


class StaffAllManager(models.Manager.from_queryset(StaffQuerySet)):
    """Tout le personnel (en poste + partis)."""
    pass


class StaffEnPosteManager(models.Manager.from_queryset(StaffQuerySet)):
    """Par défaut : seulement le personnel EN POSTE."""
    def get_queryset(self):
        return super().get_queryset().filter(en_poste=True)


class Personnel(models.Model):
    class SalaryMode(models.TextChoices):
        FIXE = "FIXE", "Salaire fixe (forfait)"
        HORAIRE = "HORAIRE", "À l'heure (taux × heures)"

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
    photo = models.ImageField(upload_to="image/staff", null=True, blank=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name="staff_member")
    en_poste = models.BooleanField(default=True)
    salary_mode = models.CharField(max_length=8, choices=SalaryMode.choices, null=True, blank=True,
                                   help_text="Vide = non rémunéré par l'établissement.")
    salaire = models.PositiveIntegerField(null=True, blank=True,
                                          help_text="Salaire mensuel FIXE (FCFA). Utilisé si mode = FIXE.")
    hourly_rate = models.PositiveIntegerField(null=True, blank=True,
                                              help_text="Taux horaire négocié (FCFA/h). Utilisé si mode = HORAIRE.")
    default_hours = models.PositiveSmallIntegerField(null=True, blank=True,
        help_text="Nombre d'heures mensuel habituel (pré-remplit la paie ; ajustable chaque mois).")
    # --- identité administrative ---
    matricule = models.CharField(max_length=10, blank=True, default="",
        help_text="Matricule administratif du membre du personnel.")
    provenance = models.CharField(max_length=120, blank=True, default="",
        help_text="École de formation ou poste précédent (ex. ENS de Yaoundé, Lycée de XXX).")
    # --- décision d'affectation ---
    note_service_number = models.CharField(max_length=80, blank=True, default="",
        help_text="N° de la décision / note de service / arrêté / d'affectation ou de nomination.")
    note_service_date = models.DateField(null=True, blank=True, help_text="Date de la décision / note de service.")
    # --- formation ---
    discipline_formation = models.CharField(max_length=60, blank=True, default="",
        help_text="Discipline de formation (ex. Informatique, Mathématiques). Sert (uniquement si poste est Enseignant) "
                  "à la mention « En qualité de » — distincte des matières effectivement enseignées cette année.")

    objects = StaffEnPosteManager()
    objects_all = StaffAllManager()

    @property
    def is_paid(self):
        return self.salary_mode is not None

    @property
    def progression(self):
        return Personnel.enseignements_progression(self)

    def enseignements_progression(self, classroom=None):
        from osm.utils import formated_float
        result = list()
        already = set()
        if classroom:
            enseignements = classroom.enseignement.select_related('matiere__sujet', 'classroom').order_by_domain_and_coef()
        else:
            enseignements = self.enseignant.select_related('matiere__sujet', 'classroom').order_by('classroom')
        nlp1 = nlf1 = nlp2 = nlf2 = nlp3 = nlf3 = nlp = nlf = nlpt1 = nlpt2 = nlpt3 = nlpt = nlpp1 = nlpp2 = nlpp3 = nlpp = nlft1 = nlft2 = nlft3 = nlft = nlfp1 = nlfp2 = nlfp3 = nlfp = 0
        for ens in enseignements:
            label = ens.true_name
            if label not in already:
                already.add(label)
                ens_progression = ens.progression(classroom)
                result.append(ens_progression)
                nlpt1 += int(ens_progression['nlpt1']) if ens_progression['nlpt1'] != "/" else 0
                nlpt2 += int(ens_progression['nlpt2']) if ens_progression['nlpt2'] != "/" else 0
                nlpt3 += int(ens_progression['nlpt3']) if ens_progression['nlpt3'] != "/" else 0
                nlpt += int(ens_progression['nlpt']) if ens_progression['nlpt'] != "/" else 0
                nlpp1 += int(ens_progression['nlpp1']) if ens_progression['nlpp1'] != "/" else 0
                nlpp2 += int(ens_progression['nlpp2']) if ens_progression['nlpp2'] != "/" else 0
                nlpp3 += int(ens_progression['nlpp3']) if ens_progression['nlpp3'] != "/" else 0
                nlpp += int(ens_progression['nlpp']) if ens_progression['nlpp'] != "/" else 0
                nlft1 += int(ens_progression['nlft1']) if ens_progression['nlft1'] != "/" else 0
                nlft2 += int(ens_progression['nlft2']) if ens_progression['nlft2'] != "/" else 0
                nlft3 += int(ens_progression['nlft3']) if ens_progression['nlft3'] != "/" else 0
                nlft += int(ens_progression['nlft']) if ens_progression['nlft'] != "/" else 0
                nlfp1 += int(ens_progression['nlfp1']) if ens_progression['nlfp1'] != "/" else 0
                nlfp2 += int(ens_progression['nlfp2']) if ens_progression['nlfp2'] != "/" else 0
                nlfp3 += int(ens_progression['nlfp3']) if ens_progression['nlfp3'] != "/" else 0
                nlfp += int(ens_progression['nlfp']) if ens_progression['nlfp'] != "/" else 0
                nlp1 += int(ens_progression['nlp1']) if ens_progression['nlp1'] != "/" else 0
                nlp2 += int(ens_progression['nlp2']) if ens_progression['nlp2'] != "/" else 0
                nlp3 += int(ens_progression['nlp3']) if ens_progression['nlp3'] != "/" else 0
                nlf1 += int(ens_progression['nlf1']) if ens_progression['nlf1'] != "/" else 0
                nlf2 += int(ens_progression['nlf2']) if ens_progression['nlf2'] != "/" else 0
                nlf3 += int(ens_progression['nlf3']) if ens_progression['nlf3'] != "/" else 0
                nlp += int(ens_progression['nlp']) if ens_progression['nlp'] != "/" else 0
                nlf += int(ens_progression['nlf']) if ens_progression['nlf'] != "/" else 0
        plt1 = formated_float((nlft1 / nlpt1) * 100) if nlpt1 else 0
        plt2 = formated_float((nlft2 / nlpt2) * 100) if nlpt2 else 0
        plt3 = formated_float((nlft3 / nlpt3) * 100) if nlpt3 else 0
        plt = formated_float((nlft / nlpt) * 100) if nlpt else 0
        plp1 = formated_float((nlfp1 / nlpp1) * 100) if nlpp1 else 0
        plp2 = formated_float((nlfp2 / nlpp2) * 100) if nlpp2 else 0
        plp3 = formated_float((nlfp3 / nlpp3) * 100) if nlpp3 else 0
        plp = formated_float((nlfp / nlpp) * 100) if nlpp else 0
        pl1 = formated_float((nlf1 / nlp1) * 100) if nlp1 else 0
        pl2 = formated_float((nlf2 / nlp2) * 100) if nlp2 else 0
        pl3 = formated_float((nlf3 / nlp3) * 100) if nlp3 else 0
        pl = formated_float((nlf / nlp) * 100) if nlp else 0

        total = {
            'label': "Total",
            'nlpt1': nlpt1 if nlpt1 else "/",
            'nlpt2': nlpt2 if nlpt2 else "/",
            'nlpt3': nlpt3 if nlpt3 else "/",
            'nlpt': nlpt if nlpt else "/",
            'nlpp1': nlpp1 if nlpp1 else "/",
            'nlpp2': nlpp2 if nlpp2 else "/",
            'nlpp3': nlpp3 if nlpp3 else "/",
            'nlpp': nlpp if nlpp else "/",
            'nlft1': nlft1 if nlft1 else "/",
            'nlft2': nlft2 if nlft2 else "/",
            'nlft3': nlft3 if nlft3 else "/",
            'nlft': nlft if nlft else "/",
            'nlfp1': nlfp1 if nlfp1 else "/",
            'nlfp2': nlfp2 if nlfp2 else "/",
            'nlfp3': nlfp3 if nlfp3 else "/",
            'nlfp': nlfp if nlfp else "/",
            'nlp1': nlp1 if nlp1 else "/",
            'nlp2': nlp2 if nlp2 else "/",
            'nlp3': nlp3 if nlp3 else "/",
            'nlf1': nlf1 if nlf1 else "/",
            'nlf2': nlf2 if nlf2 else "/",
            'nlf3': nlf3 if nlf3 else "/",
            'nlp': nlp if nlp else "/",
            'nlf': nlf if nlf else "/",
            'plt1': f"{plt1}%" if plt1 else "/",
            'plt2': f"{plt2}%" if plt2 else "/",
            'plt3': f"{plt3}%" if plt3 else "/",
            'plt': f"{plt}%" if plt else "/",
            'plp1': f"{plp1}%" if plp1 else "/",
            'plp2': f"{plp2}%" if plp2 else "/",
            'plp3': f"{plp3}%" if plp3 else "/",
            'plp': f"{plp}%" if plp else "/",
            'pl1': f"{pl1}%" if pl1 else "/",
            'pl2': f"{pl2}%" if pl2 else "/",
            'pl3': f"{pl3}%" if pl3 else "/",
            'pl': f"{pl}%" if pl else "/",
        }
        total['nlt1'] = f"{total['nlft1']} sur {total['nlpt1']}"
        total['nlt2'] = f"{total['nlft2']} sur {total['nlpt2']}"
        total['nlt3'] = f"{total['nlft3']} sur {total['nlpt3']}"
        total['nlt'] = f"{total['nlft']} sur {total['nlpt']}"
        total['nlpr1'] = f"{total['nlfp1']} sur {total['nlpp1']}"
        total['nlpr2'] = f"{total['nlfp2']} sur {total['nlpp2']}"
        total['nlpr3'] = f"{total['nlfp3']} sur {total['nlpp3']}"
        total['nlpr'] = f"{total['nlfp']} sur {total['nlpp']}"
        total['nl1'] = f"{total['nlf1']} sur {total['nlp1']}"
        total['nl2'] = f"{total['nlf2']} sur {total['nlp2']}"
        total['nl3'] = f"{total['nlf3']} sur {total['nlp3']}"
        total['nl'] = f"{total['nlf']} sur {total['nlp']}"
        result.append(total)
        return result

    def poste_display(self):
        if self.civilite == Civilite.MME:
            return Poste_Fem.get(self.poste, self.poste)
        return self.poste

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
            return tranches_horaires, school
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
        """for _, liste in matrice.items():
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
                i += rowspan"""
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
            return time_table, infos, school, recap(classrooms, mp)
        return time_table, recap(classrooms, mp)

    @property
    def is_admin(self):
        if self.user:
            return self.user.is_admin
        return False

    class Meta:
        db_table = '"Personnel"'
        base_manager_name = "objects_all"
        constraints = [
            UniqueConstraint(fields=['email'], condition=Q(email__isnull=False), name='unique_notnull_email')
        ]

    def delete(self, *args, **kwargs):
        from osm.utils import delete_image
        from finance.models import Transaction
        if Transaction.objects.filter(beneficiary=self).exists():
            nom = self.short_name
            Transaction.objects.filter(beneficiary=self).update(beneficiary_name=nom)
        if self.photo:
            delete_image(self.photo)
        return super().delete(*args, **kwargs)

    def leave_school(self):
        """Quitter l'établissement : en_poste=False."""
        if self.en_poste:
            self.en_poste = False
            self.save(update_fields=["en_poste"])

    def reinstate(self):
        """Réintégrer (en_poste=True)."""
        if not self.en_poste:
            self.en_poste = True
            self.save(update_fields=["en_poste"])

    @property
    def post(self):
        if self.poste == "Chef d'Établissement":
            if self.user:
                return self.user.post
            from django.db import connection
            from authentification.models import School
            return School.objects.get(schema_name=connection.schema_name).chef
        if self.civilite == Civilite.MME:
            return Poste_Fem.get(self.poste, self.poste)
        return self.poste

    @property
    def short_name(self):
        civilite = "M." if self.civilite == "Monsieur" else "Mme."
        short = f"{self.nom.split()[0]} {self.prenom.split()[0]}" if self.prenom else self.nom
        return f"{civilite} {short}"\

    @property
    def short_firstname(self):
        civilite = "M." if self.civilite == "Monsieur" else "Mme."
        return f"{civilite} {self.nom.split()[0]}"

    def __str__(self):
        civilite = "M." if self.civilite == "Monsieur" else "Mme."
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
