# Create your models here.

from django.db import models
from django.db.models import Q
from authentification.models import User, TrancheHoraire
from staff.models import Personnel, Discipline
from django.db.models import When, Case, Value, IntegerField, F


class LVII(models.TextChoices):
    ALL = "Allemand", "Allemand"
    ESP = "Espagnol", "Espagnol"
    CHI = "Chinois", "Russe"
    ARA = "Arabe", "Arabe"


class LVIII(models.TextChoices):
    RUS = "Russe", "Russe"
    ITA = "Italien", "Italien"


class Class(models.Model):
    id = models.IntegerField(primary_key=True)
    niveau = models.CharField(max_length=15)
    serie = models.CharField(max_length=10, blank=True, null=True)
    dfn = models.CharField(max_length=50, blank=True, null=True)
    disciplines = models.ManyToManyField(Discipline, blank=True, through="Matieres")

    class Meta:
        db_table = '"Class"'

    def __str__(self):
        name = self.niveau
        if self.serie:
            name += f" {self.serie}"
        return name


    @classmethod
    def add_matiere(cls, classe, discipline: Discipline, coeff: int):
        matiere = Matieres(sujet=discipline, classe=classe, coeff=coeff)
        from django.db.models import Max
        matiere.id = Matieres.objects.aggregate(max_id=Max('id'))['max_id'] + 1 or 1
        matiere.save()
        classrooms = ClassRoom.objects.prefetch_related('matieres').filter(classe=classe)
        for classroom in classrooms:
            ens = Enseignements(matiere=matiere, classroom=classroom, rapporteur=get_staff_member())
            ens.save()

    @classmethod
    def remove_matiere(cls, classe, discipline: Discipline):
        return classe.disciplines.remove(discipline)


class MatieresQuerySet(models.QuerySet):
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
                *[When(sujet__groupe=key, then=Value(value)) for key, value in order.items()],
                default=Value(999),
                output_field=IntegerField()
            ),
            '-coeff'
        )


class Matieres(models.Model):
    sujet = models.ForeignKey(Discipline, on_delete=models.CASCADE)
    classe = models.ForeignKey(Class, on_delete=models.CASCADE)
    coeff = models.IntegerField()

    objects = MatieresQuerySet.as_manager()

    class Meta:
        db_table = '"Matieres"'

    def __str__(self):
        return f"{self.sujet.label} en {self.classe}"

    @property
    def label_and_coeff(self):
        return f"{self.sujet.label}, coeff: {self.coeff}"

    @property
    def delete_message(self):
        return f"{self.sujet.label} retiré avec succès en classe de {self.classe}"


class ClassRoomQuerySet(models.QuerySet):
    def order_by_niveau(self):
        order = {
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
                *[When(classe__niveau=key, then=Value(value)) for key, value in order.items()],
                default=Value(999),
                output_field=IntegerField()
            ), 'classe__serie', 'code'
        )


class ClassRoom(models.Model):
    classe = models.ForeignKey(Class, on_delete=models.CASCADE)
    code = models.CharField(max_length=15)
    lv2 = models.CharField(choices=LVII.choices, null=True, max_length=15)
    lv3 = models.CharField(choices=LVIII.choices, null=True, max_length=15)
    matieres = models.ManyToManyField(Matieres, through="Enseignements")
    titulaire = models.ForeignKey(Personnel, on_delete=models.SET_NULL, null=True)

    objects = ClassRoomQuerySet.as_manager()

    class Meta:
        db_table = '"ClassRoom"'

    @property
    def subjects(self):
        matieres = list()
        french, info = False, False
        for matiere in self.matieres.select_related('sujet').order_by_domain_and_coef(self.classe.serie):
            if (matiere.sujet.matiere != "Français" and matiere.sujet.matiere != "Informatique") or (
                    matiere.sujet.matiere == "Français" and not french) or (
                    matiere.sujet.matiere == "Informatique" and not info):
                matieres.append(matiere)
                if matiere.sujet.matiere == "Français":
                    french = True
                elif matiere.sujet.matiere == "Informatique":
                    info = True
        return matieres

    def timetable_recap(self, mp):
        recap = list()
        total_heures = 0
        for matiere in self.subjects:
            if not mp:
                programmations = matiere.programmations.filter(classroom_id=self.id)
            else:
                programmations = Programmation.objects.filter(classrooms=self, matiere__sujet=matiere.sujet)
            if programmations.exists():
                label = matiere.sujet.label
                if matiere.sujet.matiere in ["Français", "Informatique"]:
                    label = matiere.sujet.matiere
                if label == "LVII":
                    label = self.lv2
                elif label == "LVIII":
                    label = self.lv3
                nb_heures = programmations.count()
                total_heures += nb_heures
                recap.append({
                    'matiere': label,
                    'color': self.subject_color(matiere),
                    'nb_heures': nb_heures
                })
        if total_heures:
            recap.append({
                'matiere': "Total",
                'color': "text-bg-dark",
                'nb_heures': total_heures
            })
        return recap if recap else None

    def subject_color(self, subject):
        subjects = [matiere.sujet for matiere in self.subjects]
        index = subjects.index(subject.sujet)
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

    def __str__(self):
        langues = ""
        if self.lv2:
            langues += f", LVII: {self.lv2}"
        if self.lv3:
            langues += f", LVIII: {self.lv3}"
        return f"{self.code}: {self.classe.__str__()}{langues}"

    def classroom_to_dict(self):
        return {
            'label': self.code,
            'effectif': self.effectif,
            'titulaire': self.titulaire if self.titulaire else "",
            'total_coef': self.total_coef
        }

    @classmethod
    def save_classroom(cls, classroom):
        classroom.save()
        classroom = (
            ClassRoom.objects.select_related('classe').prefetch_related('classe__disciplines').get(pk=classroom.pk)
        )
        classe = classroom.classe
        disciplines = classe.disciplines.all()
        sujet_ids = [discipline.id for discipline in disciplines]
        matieres = Matieres.objects.filter(sujet_id__in=sujet_ids, classe_id=classe.id)
        for matiere in matieres:
            Enseignements.objects.create(matiere=matiere, classroom=classroom, rapporteur=get_staff_member())

    @property
    def kind_numbers(self):
        g = self.students.filter(sexe="Garçon").count()
        f = self.students.filter(sexe="Fille").count()
        kind = ""
        if f > 0:
            kind += "Une Fille" if f == 1 else f"{f} Filles"
            if g > 0:
                kind += ", "
        if g > 0:
            kind += "Un Garçon" if g == 1 else f"{g} Garçons"
        return kind

    @property
    def level(self):
        langues = ""
        if self.lv2:
            langues += f", LVII: {self.lv2}"
        if self.lv3:
            langues += f", LVIII: {self.lv3}"
        return f"{self.classe.__str__()}{langues}"

    @property
    def total_coef(self):
        from django.db.models.aggregates import Sum
        return self.matieres.aggregate(Sum("coeff"))["coeff__sum"]

    @property
    def effectif(self):
        return self.students.count()

    def marks_report_data(self, evals, for_stats=False, pv=False, pv_ordered=False):
        from note.models import Note
        from osm.utils import formated_float

        notes = (
            Note.objects.select_related('enseignement__matiere__sujet', 'enseignement__enseignant').
            filter(eleve__classe_id=self.pk, eval__in=evals)
            .order_by_domain_and_coef(serie=self.classe.serie)
        )
        students = list(self.students.all().order_by('nom', 'prenom'))
        students_data = [
            student.student_marks_report_data(evals=evals, notes=notes.filter(eleve_id=student.id),
                                              total_coef=self.total_coef, for_stats=for_stats,
                                              pv=pv) for student in students
        ]
        if not pv:
            classroom_matieres = self.matieres.all().order_by_domain_and_coef(serie=self.classe.serie)
            if not for_stats:
                if classroom_matieres.count() > 15:
                    classroom_matieres = classroom_matieres[:15]
            matieres = list(classroom_matieres)
            matieres_data = list()
            max_words = 1
            for matiere in matieres:
                matiere_label = matiere.sujet.label
                if matiere_label == "LVII":
                    matiere_label = self.lv2
                elif matiere_label == "LVIII":
                    matiere_label = self.lv3
                data_matiere = {
                    'id': matiere.id,
                    'label': matiere_label
                }
                if for_stats:
                    nbfe, nbfr, nbge, nbgr, nbtr = 0, 0, 0, 0, 0
                    notes_moyennes = list()
                    for student_data in students_data:
                        matiere_data = student_data['matieres_data'].get(matiere.id)
                        if matiere_data:
                            note_moyenne = matiere_data['moy']
                            if note_moyenne != "/":
                                notes_moyennes.append(note_moyenne)
                                if student_data['sexe'] == 'F':
                                    nbfe += 1
                                    if note_moyenne >= 10:
                                        nbfr += 1
                                        nbtr += 1
                                else:
                                    nbge += 1
                                    if note_moyenne >= 10:
                                        nbgr += 1
                                        nbtr += 1
                    enseignant = notes.filter(enseignement__matiere_id=matiere.id, eval=evals[0])\
                        .first().enseignement.enseignant
                    data_matiere['enseignant'] = enseignant.short_name if enseignant else "/"
                    data_matiere['nbfe'], data_matiere['nbfr'], data_matiere['pcf'] = nbfe, nbfr,\
                        formated_float((nbfr / nbfe) * 100) if nbfe else 0
                    data_matiere['nbge'], data_matiere['nbgr'], data_matiere['pcg'] = nbge, nbgr,\
                        formated_float((nbgr / nbge) * 100) if nbge else 0
                    data_matiere['nbte'], data_matiere['nbtr'], data_matiere['pct'] = len(notes_moyennes), nbtr,\
                        formated_float((nbtr / len(notes_moyennes)) * 100)
                    data_matiere['min_max'] = f"[{min(notes_moyennes)} - {max(notes_moyennes)}]"
                    data_matiere['moyenne'] = formated_float(sum(notes_moyennes) / len(notes_moyennes))
                else:
                    nb_words = len(matiere_label.split())
                    for word in matiere_label.split():
                        if word in ('de', 'du', 'et', 'la', 'le'):
                            nb_words -= 1
                    if nb_words > max_words:
                        max_words = nb_words
                matieres_data.append(data_matiere)
        result = {
            'label': self.code,
            'effectif': self.effectif,
            'garcons': self.students.filter(sexe="Garçon").count(),
            'filles': self.students.filter(sexe="Fille").count(),
            'redoublants': self.students.filter(statut="Redoublant").count()
        }
        if for_stats or pv:
            if for_stats:
                moyenne_generale, taux, min_max, nb, nb_admis, result['nbfe'], result['nbfr'], result['nbge'],\
                    result['nbgr'], result['pcf'], result['pcg'] = self.set_rang(students_data, for_stats=True)
            elif pv:
                if pv_ordered:
                    students_data, moyenne_generale, taux, min_max, nb, nb_admis = self.set_rang(students_data,
                                                                                                 pv_orderd=True)
                else:
                    moyenne_generale, taux, min_max, nb, nb_admis = self.set_rang(students_data)
            result['moyenne_generale'], result['taux'], result['min_max'] = moyenne_generale, taux, min_max
            result['nbe'], result['nbr'] = nb, nb_admis
        if not for_stats:
            result['students_data'] = students_data
        if not pv:
            result['matieres_data'] = matieres_data
            if not for_stats:
                result['max_words'] = max_words
        return result

    def set_rang(self, datas, cle_moyenne="moyenne", cle_rang="rang", for_stats=False, pv_orderd=False):
        from osm.utils import formated_float

        ordered_data = sorted(datas, key=lambda x: x[cle_moyenne], reverse=True)
        if cle_moyenne == "moyenne":
            minim = maxim = ordered_data[0]['moyenne']
            total_moyennes = 0
            nb = 0
            nb_admis = 0
        derniere_moyenne = None
        nb_ex_aequo = 0
        if for_stats:
            nbfe, nbfr, nbge, nbgr = 0, 0, 0, 0
        for i, data in enumerate(ordered_data):
            moy = data[cle_moyenne]
            if moy == 0:
                data[cle_rang] = "/"
                continue
            if moy != derniere_moyenne:
                rang = i + 1
                nb_ex_aequo = 1
                rang_str = f"{rang}ᵉ"
                derniere_moyenne = moy
            else:
                nb_ex_aequo += 1
                if nb_ex_aequo == 2:
                    ordered_data[i - 1][cle_rang] = f"{rang}ᵉ ex."
                rang_str = f"{rang}ᵉ ex."
            data[cle_rang] = rang_str
            if cle_moyenne == "moyenne":
                total_moyennes += moy
                nb += 1
                if moy >= 10:
                    nb_admis += 1
                if moy > maxim:
                    maxim = moy
                if moy < minim:
                    minim = moy
            if for_stats:
                if data['sexe'] == 'F':
                    nbfe += 1
                    if moy >= 10:
                        nbfr += 1
                else:
                    nbge += 1
                    if moy >= 10:
                        nbgr += 1
        if cle_moyenne == "moyenne":
            moyenne_generale = formated_float(total_moyennes / nb)
            taux = f"{formated_float((nb_admis / nb) * 100)}%"
            min_max = f"[{minim} - {maxim}]"
            if for_stats:
                return moyenne_generale, formated_float((nb_admis / nb) * 100), min_max, nb, nb_admis, nbfe, nbfr,\
                    nbge, nbgr, formated_float((nbfr / nbfe) * 100) if nbfe else 0, formated_float((nbgr / nbge) * 100) if nbge else 0
            if pv_orderd:
                return ordered_data, moyenne_generale, taux, min_max, nb, nb_admis
            return moyenne_generale, taux, min_max, nb, nb_admis

    def reportcard_data(self, evals, with_competences=True):
        from note.models import Note
        from osm.utils import formated_float

        notes = (
            Note.objects.select_related('enseignement__matiere__sujet', 'enseignement__enseignant').
            filter(eleve__classe_id=self.pk, eval__in=evals)
            .order_by_domain_and_coef(serie=self.classe.serie)
        )
        students = list(self.students.all().order_by('nom', 'prenom'))
        lv2, lv3 = self.lv2, self.lv3
        students_data = [
            student.student_reportcard_data(evals=evals, total_coef=self.total_coef, lv2=lv2, lv3=lv3,
                                            notes=notes.filter(eleve_id=student.id)) for student in students
        ]
        matieres = list(self.matieres.all().order_by_domain_and_coef(serie=self.classe.serie))
        matieres_data = list()
        groupes = []

        for matiere in matieres:
            notes_moyennes = list()
            for student_data in students_data:
                matiere_data = student_data['matieres_data'].get(matiere.id)
                if matiere_data:
                    note_moyenne = matiere_data['moy']
                    if note_moyenne != "/":
                        notes_moyennes.append(note_moyenne)
            note = notes.filter(enseignement__matiere_id=matiere.id, eval=evals[0]).first()
            matiere_label = matiere.sujet.label
            if matiere_label == "LVII":
                matiere_label = lv2
            elif matiere_label == "LVIII":
                matiere_label = lv3
            data_matiere = {
                'id': matiere.id,
                'label': matiere_label,
                'enseignant': note.enseignement.enseignant.short_name if note.enseignement.enseignant else "/",
                'min-max': f"[{min(notes_moyennes)} - {max(notes_moyennes)}]",
                'coef': matiere.coeff,
            }
            if len(evals) == 2 and with_competences:
                note1 = notes.filter(enseignement__matiere_id=matiere.id, eval=evals[1]).first()
                data_matiere['compt1'] = note.competences
                data_matiere['compt2'] = note1.competences if note1.competences != note.competences else ""
            else:
                data_matiere['groupe'] = matiere.sujet.groupe
                if matiere.sujet.groupe not in groupes:
                    groupes.append(matiere.sujet.groupe)
            matieres_data.append(data_matiere)

        if len(evals) == 6:
            self.set_rang(students_data, "moyenne1", "rang1")
            self.set_rang(students_data, "moyenne2", "rang2")
            self.set_rang(students_data, "moyenne3", "rang3")
        moyenne_generale, taux, min_max, nb, nb_admis = self.set_rang(students_data)

        return {
            'classroom_data': self.classroom_to_dict(),
            'matieres_data': matieres_data,
            'students_data': students_data,
            'moyenne_generale': moyenne_generale,
            'taux_reussite': taux,
            'nb': nb,
            'nb_admis': nb_admis,
            'min-max': min_max,
            'with_competences': with_competences,
            'groupes': groupes
        }


class Enseignements(models.Model):
    matiere = models.ForeignKey(Matieres, on_delete=models.CASCADE)
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE)
    enseignant = models.ForeignKey(Personnel, on_delete=models.SET_NULL, null=True, related_name="enseignant")
    rapporteur = models.ForeignKey(Personnel, on_delete=models.SET_NULL, null=True, related_name="rapporteur")

    def __str__(self):
        return self.matiere.__str__()

    class Meta:
        db_table = '"Enseignements"'

    @property
    def subject(self):
        return self.matiere.sujet.label


def get_staff_member():
    staff_members = Personnel.objects.select_related('user').all()
    for member_of_staff in staff_members:
        if member_of_staff.is_admin:
            return member_of_staff
    return None


class Programmation(models.Model):
    days = (
        (1, "Lundi"),
        (2, "Mardi"),
        (3, "Mercredi"),
        (4, "Jeudi"),
        (5, "Vendredi")
    )

    jour = models.IntegerField(choices=days)
    tranche_horaire = models.ForeignKey(TrancheHoraire, on_delete=models.CASCADE)
    matiere = models.ForeignKey(Matieres, on_delete=models.CASCADE, related_name="programmations")
    enseignant = models.ForeignKey(Personnel, null=True, on_delete=models.CASCADE, related_name="programmations")
    classroom = models.ForeignKey(ClassRoom, on_delete=models.CASCADE, related_name="programmations", null=True)
    classrooms = models.ManyToManyField(ClassRoom, related_name="mergedprogrammations")

    class Meta:
        db_table = '"Programmation"'
        constraints = [
            models.UniqueConstraint(fields=('jour', 'tranche_horaire', 'matiere', 'classroom'),
                                    name="unique_matiere_classroom_jour_tranche"),
            models.UniqueConstraint(fields=('jour', 'tranche_horaire', 'enseignant'),
                                    name="unique_enseignant_jour_tranche")
        ]

    @property
    def classes(self):
        if self.classroom:
            return self.classroom.code
        classrooms = ""
        classrooms_set = self.classrooms.order_by_niveau()
        for classroom in classrooms_set:
            classrooms += f"{classroom.code}"
            if classroom != classrooms_set.last():
                classrooms += ", "
        return classrooms

    @classmethod
    def create_mergedprogrammation(cls, jour, tranche_id, matiere_id, enseignant_id, classroom):
        programmation = Programmation.objects.filter(jour=jour, tranche_horaire_id=tranche_id,
                                                     enseignant_id=enseignant_id,
                                                     matiere__sujet=Matieres.objects.get(id=matiere_id).sujet)
        if programmation.exists():
            programmation.first().classrooms.add(classroom)
        else:
            programmation = Programmation.objects.create(jour=jour, tranche_horaire_id=tranche_id,
                                                         enseignant_id=enseignant_id, matiere_id=matiere_id)
            programmation.classrooms.add(classroom)

    @classmethod
    def update_mergedprogrammation(cls, programmation, jour, tranche_id, matiere_id, ex_id, enseignant_id, classroom):
        if (Matieres.objects.get(id=matiere_id).sujet !=
            Matieres.objects.get(id=programmation.matiere_id).sujet) or (ex_id != enseignant_id):
            programmation.classrooms.remove(classroom)
            if not programmation.classrooms.exists():
                programmation.delete()
            Programmation.create_mergedprogrammation(jour, tranche_id, matiere_id, enseignant_id, classroom)

    def short(self, classroom, recap=False):
        label = self.matiere.sujet.label
        if self.matiere.sujet.matiere in ["Français", "Informatique"]:
            label = self.matiere.sujet.matiere
        if label == "LVII":
            return classroom.lv2
        elif label == "LVII":
            return classroom.lv3
        if recap:
            return label
        if len(label) > 15:
            label = f"{label[:12]}..."
        return label

    def __str__(self):
        return f"{self.short}"
