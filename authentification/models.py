from django_tenants.models import TenantMixin, DomainMixin
from django.db import models
from django.contrib.auth.models import AbstractUser
from datetime import time

# Create your models here.


class Poste(models.TextChoices):
    AU = "Autre", "Autre"
    EN = "Enseignant", "Enseignant"
    CH = "Chef d'Établissement", "Chef d'Établissement"
    CE = "Censeur", "Censeur"
    SG = "Surveillant-Général", "Surveillant-Général"
    SS = "Surveillant de secteur", "Surveillant de secteur"
    GD = "Gardien", "Gardien"
    IN = "Intendant", "Intendant"
    EC = "Économe", "Économe"
    CO = "Conseiller d'orientation", "Conseiller d'orientation"


class Civilite(models.TextChoices):
    MR = "Monsieur", "Monsieur"
    MME = "Madame", "Madame"


class School(TenantMixin):

    """
    Cette classe définit la table qui va contenir les informations de nos différents établissements
    """
    class Type(models.TextChoices):
        GHS = "Lycée", "Lycée"
        GSS = "CES", "CES"
        GBSS = "CES Bilingue", "CES Bilingue"
        GBHS = "Lycée Bilingue", "Lycée Bilingue"
        GTSS = "CETIC", "CETIC"
        GTHS = "Lycée Technique", "Lycée Technique"
        COL = "Collège", "Collège"

    nom = models.CharField(verbose_name="Nom", max_length=50)
    name = models.CharField(verbose_name="Name", max_length=50)
    type_ets = models.CharField(choices=Type.choices, verbose_name="Type", default=Type.GSS, max_length=20)
    region = models.CharField(verbose_name="Délégation régionale", max_length=50, default="DÉLÉGATION RÉGIONALE")
    departement = models.CharField(verbose_name="Délégation départementale", max_length=50, default="DÉLÉGATION DÉPARTEMENTALE")
    rgn = models.CharField(verbose_name="Regional delegation", max_length=50, default="REGIONAL DELEGATION")
    dptm = models.CharField(verbose_name="Divisional delegation", max_length=50, default="DIVISIONAL DELEGATION")
    localite = models.CharField(verbose_name="Localité", max_length=50)
    contact = models.CharField(max_length=9, verbose_name="Contact")
    contact1 = models.CharField(max_length=9, verbose_name="Contact1", blank=True, null=True)
    email = models.EmailField(verbose_name="Email", blank=True, null=True)
    pobox = models.CharField(max_length=50, verbose_name="Boîte Postale", blank=True)
    immatriculation = models.CharField(max_length=30, verbose_name="N° Immatriculation", blank=True)
    logo = models.ImageField(upload_to="image/school/", verbose_name="Logo", blank=True, null=True)
    code = models.CharField(max_length=10, verbose_name="Code")
    motto = models.CharField(blank=True, null=True, verbose_name="Devise", max_length=40)
    licence = models.DateField(verbose_name="Autorisé Jusqu'au", blank=True)
    with_competences = models.BooleanField(default=True, verbose_name="Inclure les compétences")
    day_start = models.TimeField(default=time(hour=7, minute=30))
    first_break_after = models.IntegerField(choices=((2, 2), (3, 3)), default=3)
    second_break_after = models.IntegerField(choices=((4, 4), (5, 5), (6, 6)), default=5)
    nb_plages = models.IntegerField(choices=((6, 6), (7, 7), (8, 8), (9, 9)), default=8)
    plage_duration = models.IntegerField(choices=((50, 50), (55, 55), (60, 60)), default=55)
    first_break_duration = models.IntegerField(choices=((10, 10), (15, 15), (20, 20), (25, 25), (30, 30)), default=15)
    second_break_duration = models.IntegerField(choices=((10, 10), (15, 15), (20, 20), (25, 25), (30, 30)), default=30)
    mergedprogrammations = models.BooleanField(default=False, verbose_name="Programmations Combinées")

    auto_create_schema = True

    class Meta:
        db_table = '"School"'
        verbose_name = "Etablissement"
        verbose_name_plural = "Etablissements"

    def __str__(self):
        return self.nom

    @property
    def chef(self):
        if self.type_ets in ["Lycée", "Lycée Bilingue", "Lycée Technique"]:
            return "Proviseur"
        elif self.type_ets in ["CES", "CETIC", "CES Bilingue"]:
            return "Directeur"
        return "Principal"

    def school_to_dict(self):
        return {
            'nom': self.nom,
            'name': self.name,
            'logo': self.logo if self.logo else "https://res.cloudinary.com/dulmalku0/image/upload/v1763529491/no_image_ejy2dl.jpg",
            'motto': self.motto if self.motto else "",
            'immatriculation': self.immatriculation,
            'region': self.region,
            'rgn': self.rgn,
            'departement': self.departement,
            'localite': self.localite,
            'dptm': self.dptm,
            'contact': self.contact,
            'po_box': self.pobox if self.pobox else "/",
            'type': self.type_ets,
            'chef': self.chef
        }

    @property
    def kind_numbers(self):
        from student.models import Student
        g = Student.objects.filter(sexe="Garçon").count()
        f = Student.objects.filter(sexe="Fille").count()
        kind = ""
        if f > 0:
            kind += "Une Fille" if f == 1 else f"{f} Filles"
            if g > 0:
                kind += ", "
        if g > 0:
            kind += "Un Garçon" if g == 1 else f"{g} Garçons"
        return kind

    @property
    def effectif(self):
        from student.models import Student
        return Student.objects.count()


class User(AbstractUser):
    school = models.ForeignKey(School, null=True, on_delete=models.CASCADE, verbose_name="Etablissement")
    is_admin = models.BooleanField(default=False, verbose_name="Administrateur")
    civilite = models.CharField(verbose_name="Civilité", default=Civilite.MR, choices=Civilite.choices)
    contact = models.CharField(verbose_name="Contact", max_length=9)
    poste = models.CharField(choices=Poste.choices, default=Poste.AU)
    droits = models.CharField(blank=True, null=True)
    theme = models.CharField(default="blue")

    @property
    def post(self):
        if self.poste == "Chef d'Établissement":
            return self.school.chef
        return self.poste

    def __str__(self):
        return self.username


class Domain(DomainMixin):
    pass


class TrancheHoraire(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="tranches_horaires")
    number = models.IntegerField()
    start = models.TimeField()
    end = models.TimeField()
    is_cours = models.BooleanField(default=True)

    class Meta:
        ordering = ["number"]
        db_table = '"TrancheHoraire"'
        constraints = [
            models.UniqueConstraint(fields=('school', 'number'), name='unique_school_number'),
        ]

    @property
    def debut(self):
        minutes_start = self.start.minute if self.start.minute >= 10 else f"0{self.start.minute}"
        return f"{self.start.hour}h{minutes_start}"

    @property
    def fin(self):
        minutes_end = self.end.minute if self.end.minute >= 10 else f"0{self.end.minute}"
        return f"{self.end.hour}h{minutes_end}"

    @property
    def start_end(self):
        return f"{self.debut} - {self.fin}"
