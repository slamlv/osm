from django.db import migrations


# Taille des lots pour le bulk_create (équilibre mémoire / nb de requêtes).
BATCH_SIZE = 500


def seed_current_enrollments(apps, schema_editor):
    SchoolYear = apps.get_model('authentification', 'SchoolYear')
    Student = apps.get_model('student', 'Student')
    StudentEnrollment = apps.get_model('student', 'StudentEnrollment')

    # 1) Récupère l'année courante. Si elle n'existe pas, on s'arrête proprement
    #    (la migration ne plante pas, mais ne crée rien).
    current_year = SchoolYear.objects.filter(is_current=True).first()
    if current_year is None:
        print("\n[seed_current_enrollments] Aucune année courante trouvée — "
              "rien à faire. Crée l'année courante puis relance cette migration.")
        return

    # 2) Évite les doublons : on récupère les IDs des élèves déjà inscrits
    #    pour cette année (au cas où la migration est relancée).
    already_enrolled = set(
        StudentEnrollment.objects
        .filter(school_year_id=current_year.id)
        .values_list('student_id', flat=True)
    )

    # 3) Ne traite que les élèves AYANT une classe et PAS encore inscrits.
    students = (
        Student.objects
        .filter(classe__isnull=False)
        .exclude(id__in=already_enrolled)
        .values_list('id', 'classe_id')  # léger : on ne charge que ce qu'il faut
    )

    # 4) Construit les objets et insère par lots.
    to_create = [
        StudentEnrollment(
            student_id=student_id,
            school_year_id=current_year.id,
            classroom_id=classe_id,
            decision="En cours",   # = EnrollmentStatus.EN_COURS
        )
        for student_id, classe_id in students
    ]

    if not to_create:
        print("\n[seed_current_enrollments] Aucun nouvel enrollment à créer.")
        return

    StudentEnrollment.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
    print(f"\n[seed_current_enrollments] {len(to_create)} enrollment(s) créé(s) "
          f"pour l'année {current_year.libelle}.")


def reverse_seed(apps, schema_editor):
    """
    Annulation : supprime les enrollments "En cours" de l'année courante.
    On reste prudent en ne touchant qu'aux décisions encore "En cours"
    (on ne détruit pas des décisions de fin d'année déjà saisies).
    """
    SchoolYear = apps.get_model('school_year', 'SchoolYear')
    StudentEnrollment = apps.get_model('student', 'StudentEnrollment')

    current_year = SchoolYear.objects.filter(is_current=True).first()
    if current_year is None:
        return

    StudentEnrollment.objects.filter(
        school_year_id=current_year.id,
        decision="En cours",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('student', '0007_studentenrollment'),
        ('authentification', '0027_schoolyear'),
    ]

    operations = [
        migrations.RunPython(seed_current_enrollments, reverse_seed),
    ]
