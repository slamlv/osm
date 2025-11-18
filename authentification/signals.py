"""
    Signal pour l'insertion automatique des données par défaut dans certaines tables à la création d'un nouvel
    établissement
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import connection, transaction
from django_tenants.utils import schema_context
from .models import School
from django.core.management import call_command


@receiver(post_save, sender=School)
def insert_default_data(sender, instance, created, **kwargs):
    if created:
        if instance.schema_name != 'public':
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT schema_name FROM information_schema.schemata WHERE schema_name='{instance.schema_name}'")
                schema_exists = cursor.fetchone()
            if not  schema_exists:
                with connection.cursor() as cursor:
                    cursor.execute(f"CREATE SCHEMA {instance.schema_name};")
            call_command('migrate_schemas', schema_name=instance.schema_name)
            with schema_context(instance.schema_name):
                try:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            # Disciplines par défaut
                            cursor.execute("""SELECT COUNT(*) FROM "Discipline";""")
                            (count_discipline,) = cursor.fetchone()
                            if count_discipline == 0:
                                cursor.execute("""
                                    INSERT INTO "Discipline"(id, label, matiere, groupe) VALUES
                                    (1, 'Mathématiques', NULL, 'Sciences et Technologies'),
                                    (2, 'Physique', 'Physique/Chimie', 'Sciences et Technologies'),
                                    (3, 'Chimie', 'Physique/Chimie', 'Sciences et Technologies'),
                                    (4, 'Fabrication des Éléments Mécaniques', 'Physique/Chimie', 'Sciences et Technologies'),
                                    (5, 'PCT', 'Physique/Chimie', 'Sciences et Technologies'),
                                    (6, 'SVTEEHB', 'Sciences', 'Sciences et Technologies'),
                                    (7, 'Informatique', NULL, 'Sciences et Technologies'),
                                    (8, 'Maintenance Informatique', 'Informatique', 'Sciences et Technologies'),
                                    (9, 'Programmation Web', 'Informatique', 'Sciences et Technologies'),
                                    (10, 'Systèmes d''Information', 'Informatique', 'Sciences et Technologies'),
                                    (11, 'Philosophie', NULL, 'Sciences Humaines'),
                                    (12, 'Littérature', 'Français', 'Langues et Littératures'),
                                    (13, 'Langue Française', 'Français', 'Langues et Littératures'),
                                    (14, 'Étude de texte', 'Français', 'Langues et Littératures'),
                                    (15, 'Expression Écrite', 'Français', 'Langues et Littératures'),
                                    (16, 'Orthographe', 'Français', 'Langues et Littératures'),
                                    (17, 'LVII', NULL, 'Langues et Littératures'), (18, 'LVIII', NULL, 'Langues et Littératures'),
                                    (19, 'Latin', NULL, 'Langues et Littératures'), (20, 'Grec', NULL, 'Langues et Littératures'),
                                    (21, 'Anglais', NULL, 'Langues et Littératures'),
                                    (22, 'Anglais Renforcé', 'Anglais', 'Langues et Littératures'),
                                    (23, 'Anglais Oral', 'Anglais', 'Langues et Littératures'),
                                    (24, 'Histoire', 'Histoire/Géographie', 'Sciences Humaines'),
                                    (25, 'Géographie', 'Histoire/Géographie', 'Sciences Humaines'),
                                    (26, 'ECM', 'Histoire/Géographie', 'Sciences Humaines'),
                                    (27, 'Langues Nationales', NULL, 'Arts et Cultures Nationales'),
                                    (28, 'EPS', NULL, 'Développement Personnel'), (29, 'Travail Manuel', NULL, 'Développement Personnel'),
                                    (30, 'Religion', NULL, 'Développement Personnel'),
                                    (31, 'Expression Orale', 'Français', 'Langues et Littératures'),
                                    (32, 'Algorithmique et Programmation', 'Informatique', 'Sciences et Technologies'),
                                    (33, 'Programmation', 'Informatique', 'Sciences et Technologies'),
                                    (34, 'Maintenance et Multimédia', 'Informatique', 'Sciences et Technologies'),
                                    (35, 'Education à l''Intégrité', NULL, 'Développement personnel'),
                                    (36, 'Informatique Professionnelle', 'Informatique', 'Sciences et Technologies'),
                                    (37, 'Projet Professionnel', 'Informatique', 'Sciences et Technologies'),
                                    (38, 'Cultures Nationales', NULL, 'Arts et Cultures Nationales'),
                                    (39, 'Education Artistique', NULL, 'Arts et Cultures Nationales'),
                                    (40, 'Dessin et Technologie des Systèmes Mécaniques', 'Physique/Chimie', 'Sciences et Technologies'),
                                    (41, 'Réseau, Internet et Sécurité Informatique', 'Informatique', 'Sciences et Technologies'),
                                    (42, 'Histoire du Cinéma', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (43, 'Éléments de Langage et de Grammaire Cinématographiques', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (44, 'Outils et Métiers du Cinéma', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (45, 'Genres Cinématographiques', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (46, 'Analyse Filmique', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (47, 'Économie du Cinéma', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (48, 'Processus de Réalisation d''un Film', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (49, 'Projet de fin de Formation', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (50, 'Sociologie du Cinéma', 'Art Cinématographique', 'Arts du Cinéma'),
                                    (51, 'Français', NULL, 'Langues et Littératures'), (52, 'Dessin', NULL, 'Développement Personnel'),
                                    (53, 'Sciences', NULL, 'Sciences et Technologies');""")
                            # Classes par défaut
                            cursor.execute("""SELECT COUNT(*) FROM "Class";""")
                            (count_classes,) = cursor.fetchone()
                            if count_classes == 0:
                                cursor.execute("""INSERT INTO "Class"(id, niveau, serie, dfn) VALUES
                                    (1, 'Sixième', NULL, NULL), (2, 'Sixième', 'Bilingue', NULL), (3, 'Cinquième', NULL, NULL),
                                    (4, 'Cinquième', 'Bilingue', NULL), (5, 'Quatrième', NULL, NULL), (6, 'Quatrième', 'Bilingue', NULL),
                                    (7, 'Troisième', NULL, NULL), (8, 'Troisième', 'Bilingue', NULL),
                                    (9, 'Seconde', 'A1', 'Lettres - Philosophie (Latin et Grec)'),
                                    (10, 'Seconde', 'A2', 'Lettres - Philosophe (Latin et LVII)'),
                                    (11, 'Seconde', 'A3', 'Lettres - Philosophe (Latin)'),
                                    (12, 'Seconde', 'A4', 'Lettres - Philosophe (LVII)'),
                                    (13, 'Seconde', 'A5', 'Lettres - Philosophe (LVII et LVIII)'),
                                    (14, 'Seconde', 'ABI', 'Lettres - Philosophe (LVII et Anglais renforcé)'),
                                    (15, 'Seconde', 'AC', 'Arts Cinématographiques'),
                                    (16, 'Seconde', 'B', 'Sciences Économiques et Sociales'), (17, 'Seconde', 'SH', 'Sciences Humaines'),
                                    (18, 'Seconde', 'C', 'Mathématiques et Sciences Physiques'),
                                    (19, 'Première', 'A1', 'Lettres - Philosophie (Latin et Grec)'),
                                    (20, 'Première', 'A2', 'Lettres - Philosophe (Latin et LVII)'),
                                    (21, 'Première', 'A3', 'Lettres - Philosophe (Latin)'),
                                    (22, 'Première', 'A4', 'Lettres - Philosophe (LVII)'),
                                    (23, 'Première', 'A5', 'Lettres - Philosophe (LVII et LVIII)'),
                                    (24, 'Première', 'ABI', 'Lettres - Philosophe (LVII et Anglais renforcé)'),
                                    (25, 'Première', 'AC', 'Arts Cinématographiques'), (26, 'Première', 'SH', 'Sciences Humaines'),
                                    (27, 'Première', 'B', 'Sciences Économiques et Sociales'),
                                    (28, 'Première', 'C', 'Mathématiques et Sciences Physiques'),
                                    (29, 'Première', 'D', 'Mathématiques et SVT'), (30, 'Première', 'E', 'Mathématiques et Techniques'),
                                    (31, 'Première', 'TI', 'Technologies de l''Information'),
                                    (32, 'Terminale', 'A1', 'Lettres - Philosophie (Latin et Grec)'),
                                    (33, 'Terminale', 'A2', 'Lettres - Philosophe (Latin et LVII)'),
                                    (34, 'Terminale', 'A3', 'Lettres - Philosophe (Latin)'),
                                    (35, 'Terminale', 'A4', 'Lettres - Philosophe (LVII)'),
                                    (36, 'Terminale', 'A5', 'Lettres - Philosophe (LVII et LVIII)'),
                                    (37, 'Terminale', 'ABI', 'Lettres - Philosophe (LVII et Anglais renforcé)'),
                                    (38, 'Terminale', 'AC', 'Arts Cinématographiques'), (39, 'Terminale', 'SH', 'Sciences Humaines'),
                                    (40, 'Terminale', 'B', 'Sciences Économiques et Sociales'),
                                    (41, 'Terminale', 'C', 'Mathématiques et Sciences Physiques'),
                                    (42, 'Terminale', 'D', 'Mathématiques et SVT'), (43, 'Terminale', 'E', 'Mathématiques et Techniques'),
                                    (44, 'Terminale', 'TI', 'Technologies de l''Information'),
                                    (45, 'Seconde', 'E', 'Mathématiques et Techniques');""")
                            # Matières par défaut
                            cursor.execute("""SELECT COUNT(*) FROM "Matieres";""")
                            (count_matieres,) = cursor.fetchone()
                            if count_matieres == 0:
                                cursor.execute("""INSERT INTO "Matieres"(classe_id, sujet_id, coeff) VALUES
                                    (1, 1, 4), (1, 53, 2), (1, 7, 2), (1, 15, 2), (1, 14, 1), (1, 16, 1), (1, 21, 3), (1, 31, 2), (1, 24, 2),
                                    (1, 25, 2), (1, 28, 2), (1, 29, 1), (1, 26, 2), (2, 1, 4), (2, 53, 2), (2, 7, 2), (2, 15, 2), (2, 14, 1),
                                    (2, 16, 1), (2, 22, 3), (2, 31, 2), (2, 24, 2), (2, 25, 2), (2, 28, 2), (2, 29, 1), (2, 26, 2),
                                    (3, 1, 4), (3, 53, 2), (3, 7, 2), (3, 15, 2), (3, 14, 1), (3, 16, 1), (3, 21, 3), (3, 31, 2), (3, 24, 2),
                                    (3, 25, 2), (3, 28, 2), (3, 29, 1), (3, 26, 2), (4, 1, 4), (4, 53, 2), (4, 7, 2), (4, 15, 2), (4, 14, 1),
                                    (4, 16, 1), (4, 22, 3), (4, 31, 2), (4, 24, 2), (4, 25, 2), (4, 28, 2), (4, 29, 1), (4, 26, 2),
                                    (5, 1, 4), (5, 6, 2), (5, 7, 2), (5, 15, 1), (5, 14, 1), (5, 16, 1), (5, 21, 3), (5, 31, 1), (5, 24, 2),
                                    (5, 25, 2), (5, 28, 2), (5, 29, 1), (5, 26, 2), (5, 5, 2), (5, 17, 2), (6, 1, 4), (6, 6, 2), (6, 7, 2),
                                    (6, 15, 1), (6, 14, 1), (6, 16, 1), (6, 22, 3), (6, 31, 1), (6, 24, 2), (6, 25, 2), (6, 28, 2), (6, 29, 1),
                                    (6, 26, 2), (6, 35, 1), (6, 5, 2), (6, 17, 2), (7, 1, 4), (7, 6, 2), (7, 7, 2), (7, 15, 1), (7, 14, 1),
                                    (7, 16, 1), (7, 21, 3), (7, 31, 1), (7, 24, 2), (7, 25, 2), (7, 28, 2), (7, 29, 1), (7, 26, 2), (7, 5, 2),
                                    (7, 17, 2), (8, 1, 4), (8, 6, 2), (8, 7, 2), (8, 15, 1), (8, 14, 1), (8, 16, 1), (8, 22, 3), (8, 31, 1),
                                    (8, 24, 2), (8, 25, 2), (8, 28, 2), (8, 29, 1), (8, 26, 2), (8, 5, 2), (8, 17, 2), (18, 1, 5), (18, 2, 3),
                                    (18, 3, 3), (18, 6, 2), (18, 12, 2), (18, 13, 1), (18, 21, 3), (18, 24, 2), (18, 25, 2), (18, 26, 1),
                                    (18, 28, 2), (18, 29, 1), (18, 7, 3), (28, 1, 6), (28, 2, 4), (28, 3, 2), (28, 6, 2), (28, 12, 2),
                                    (28, 13, 1), (28, 21, 3), (28, 24, 2), (28, 25, 2), (28, 26, 1), (28, 28, 2), (28, 29, 1), (28, 7, 2),
                                    (28, 11, 1), (41, 1, 7), (41, 2, 4), (41, 3, 2), (41, 6, 2), (41, 12, 2), (41, 13, 1), (41, 21, 3),
                                    (41, 25, 2), (41, 26, 1), (41, 28, 2), (41, 29, 1), (41, 7, 4), (41, 11, 2), (29, 6, 6), (29, 1, 4),
                                    (29, 3, 2), (29, 7, 2), (29, 12, 2), (29, 13, 1), (29, 21, 3), (29, 2, 2), (29, 11, 2), (29, 24, 2),
                                    (29, 26, 1), (29, 28, 2), (29, 29, 1), (42, 6, 6), (42, 1, 4), (42, 3, 2), (42, 7, 2), (42, 12, 2),
                                    (42, 13, 1), (42, 21, 3), (42, 2, 3), (42, 11, 2), (42, 25, 2), (42, 26, 1), (42, 28, 2), (42, 29, 1),
                                    (9, 19, 3), (9, 20, 3), (9, 12, 3), (9, 13, 2), (9, 11, 2), (9, 21, 4), (9, 7, 2), (9, 26, 2), (9, 24, 2),
                                    (9, 25, 2), (9, 6, 1), (9, 27, 1), (9, 38, 1), (9, 39, 1), (9, 29, 1), (10, 19, 3), (10, 17, 3), (10, 12, 3),
                                    (10, 13, 2), (10, 11, 2), (10, 21, 4), (10, 7, 2), (10, 26, 2), (10, 24, 2), (10, 25, 2), (10, 6, 1),
                                    (10, 27, 1), (10, 38, 1), (10, 39, 1), (10, 29, 1), (11, 19, 4), (11, 12, 3), (11, 13, 2), (11, 11, 2),
                                    (11, 21, 4), (11, 7, 2), (11, 26, 2), (11, 1, 2), (11, 24, 2), (11, 25, 2), (11, 6, 1), (11, 27, 1),
                                    (11, 38, 1), (11, 39, 1), (11, 29, 1), (12, 17, 3), (12, 12, 3), (12, 13, 2), (12, 11, 2), (12, 21, 4),
                                    (12, 7, 2), (12, 26, 2), (12, 1, 2), (12, 24, 2), (12, 25, 2), (12, 6, 1), (12, 27, 1), (12, 38, 1),
                                    (12, 39, 1), (12, 29, 1), (13, 17, 3), (13, 18, 3), (13, 12, 3), (13, 13, 2), (13, 11, 2), (13, 21, 4),
                                    (13, 7, 2), (13, 26, 2), (13, 24, 2), (13, 25, 2), (13, 6, 1), (13, 27, 1), (13, 38, 1), (13, 39, 1),
                                    (13, 29, 1), (14, 17, 3), (14, 12, 3), (14, 13, 2), (14, 11, 2), (14, 22, 5), (14, 7, 2), (14, 26, 2),
                                    (14, 1, 2), (14, 24, 2), (14, 25, 2), (14, 6, 1), (14, 27, 1), (14, 38, 1), (14, 39, 1), (14, 29, 1),
                                    (19, 19, 3), (19, 20, 3), (19, 12, 3), (19, 13, 2), (19, 11, 2), (19, 21, 4), (19, 7, 2), (19, 26, 2),
                                    (19, 24, 2), (19, 25, 2), (19, 6, 1), (19, 27, 1), (19, 38, 1), (19, 39, 1), (19, 29, 1), (20, 19, 3),
                                    (20, 17, 3), (20, 12, 3), (20, 13, 2), (20, 11, 2), (20, 21, 4), (20, 7, 2), (20, 26, 2), (20, 24, 2),
                                    (20, 25, 2), (20, 6, 1), (20, 27, 1), (20, 38, 1), (20, 39, 1), (20, 29, 1), (21, 19, 4), (21, 12, 3),
                                    (21, 13, 2), (21, 11, 2), (21, 21, 4), (21, 7, 2), (21, 26, 2), (21, 1, 2), (21, 24, 2), (21, 25, 2),
                                    (21, 6, 1), (21, 27, 1), (21, 38, 1), (21, 39, 1), (21, 29, 1), (22, 17, 3), (22, 12, 3), (22, 13, 2),
                                    (22, 11, 2), (22, 21, 4), (22, 7, 2), (22, 26, 2), (22, 1, 2), (22, 24, 2), (22, 25, 2), (22, 6, 1),
                                    (22, 27, 1), (22, 38, 1), (22, 39, 1), (22, 29, 1), (23, 17, 3), (23, 18, 3), (23, 12, 3), (23, 13, 2),
                                    (23, 11, 2), (23, 21, 4), (23, 7, 2), (23, 26, 2), (23, 24, 2), (23, 25, 2), (23, 6, 1), (23, 27, 1),
                                    (23, 38, 1), (23, 39, 1), (23, 29, 1), (24, 17, 3), (24, 12, 3), (24, 13, 2), (24, 11, 2), (24, 22, 5),
                                    (24, 7, 2), (24, 26, 2), (24, 1, 2), (24, 24, 2), (24, 25, 2), (24, 6, 1), (24, 27, 1), (24, 38, 1),
                                    (24, 39, 1), (24, 29, 1), (32, 19, 3), (32, 20, 3), (32, 12, 3), (32, 13, 2), (32, 11, 4), (32, 21, 4),
                                    (32, 7, 1), (32, 26, 2), (32, 24, 2), (32, 25, 2), (32, 6, 1), (32, 27, 1), (32, 38, 1), (32, 39, 1),
                                    (32, 29, 1), (33, 19, 3), (33, 17, 3), (33, 12, 3), (33, 13, 2), (33, 11, 4), (33, 21, 4), (33, 7, 1),
                                    (33, 26, 2), (33, 24, 2), (33, 25, 2), (33, 6, 1), (33, 27, 1), (33, 38, 1), (33, 39, 1), (33, 29, 1),
                                    (34, 19, 4), (34, 12, 3), (34, 13, 2), (34, 11, 4), (34, 21, 4), (34, 7, 2), (34, 26, 2), (34, 1, 2),
                                    (34, 24, 2), (34, 25, 2), (34, 6, 1), (34, 27, 1), (34, 38, 1), (34, 39, 1), (34, 29, 1), (35, 17, 3),
                                    (35, 12, 3), (35, 13, 2), (35, 11, 4), (35, 21, 4), (35, 7, 2), (35, 26, 2), (35, 1, 2), (35, 24, 2),
                                    (35, 25, 2), (35, 6, 1), (35, 27, 1), (35, 38, 1), (35, 39, 1), (35, 29, 1), (36, 17, 3), (36, 18, 3),
                                    (36, 12, 3), (36, 13, 2), (36, 11, 2), (36, 21, 4), (36, 7, 2), (36, 26, 2), (36, 24, 2), (36, 25, 2),
                                    (36, 6, 1), (36, 27, 1), (36, 38, 1), (36, 39, 1), (36, 29, 1), (37, 17, 3), (37, 12, 3), (37, 13, 2),
                                    (37, 11, 4), (37, 22, 5), (37, 7, 1), (37, 26, 2), (37, 1, 2), (37, 24, 2), (37, 25, 2), (37, 6, 1),
                                    (37, 27, 1), (37, 38, 1), (37, 39, 1), (37, 29, 1), (31, 32, 3), (31, 10, 3), (31, 34, 2), (31, 1, 4),
                                    (31, 2, 2), (31, 3, 1), (31, 51, 3), (31, 21, 3), (31, 6, 2), (31, 24, 2), (31, 26, 2), (31, 11, 1),
                                    (31, 28, 2), (31, 29, 1), (44, 33, 3), (44, 10, 3), (44, 41, 2), (44, 1, 4), (44, 2, 2), (44, 3, 2),
                                    (44, 51, 3), (44, 21, 3), (44, 6, 2), (44, 25, 2), (44, 26, 2), (44, 11, 1), (44, 28, 2), (44, 29, 1),
                                    (45, 1, 5), (45, 2, 3), (45, 3, 2), (45, 40, 6), (45, 4, 4), (45, 51, 3), (45, 21, 3), (45, 7, 2),
                                    (45, 26, 2), (45, 28, 2), (45, 29, 1), (30, 1, 6), (30, 2, 3), (30, 3, 2), (30, 40, 6), (30, 4, 4),
                                    (30, 51, 3), (30, 21, 3), (30, 7, 2), (30, 26, 1), (30, 28, 2), (30, 29, 1), (43, 1, 6), (43, 2, 3),
                                    (43, 3, 2), (43, 40, 6), (43, 4, 4), (43, 51, 3), (43, 21, 3), (43, 7, 2), (43, 26, 1), (43, 28, 2),
                                    (43, 29, 1), (17, 25, 3), (17, 24, 3), (17, 12, 3), (17, 13, 2), (17, 11, 2), (17, 21, 4), (17, 26, 2),
                                    (17, 7, 2), (17, 28, 2), (17, 1, 2), (17, 6, 2), (17, 27, 1), (17, 38, 1), (17, 39, 1), (17, 29, 1),
                                    (26, 25, 3), (26, 24, 3), (26, 12, 3), (26, 13, 2), (26, 11, 2), (26, 21, 4), (26, 26, 2), (26, 7, 2),
                                    (26, 28, 2), (26, 1, 2), (26, 6, 2), (26, 27, 1), (26, 38, 1), (26, 39, 1), (26, 29, 1), (39, 25, 3),
                                    (39, 24, 3), (39, 12, 3), (39, 13, 2), (39, 11, 4), (39, 21, 4), (39, 26, 2), (39, 7, 2), (39, 28, 2),
                                    (39, 1, 2), (39, 6, 2), (39, 27, 1), (39, 38, 1), (39, 39, 1), (39, 29, 1), (15, 42, 4), (15, 43, 4),
                                    (15, 44, 3), (15, 51, 3), (15, 21, 3), (15, 7, 3), (15, 1, 1), (15, 2, 2), (15, 27, 1), (15, 38, 1),
                                    (15, 26, 2), (15, 11, 1), (15, 28, 2), (15, 29, 1), (25, 45, 4), (25, 46, 3), (25, 47, 3), (25, 51, 3),
                                    (25, 21, 3), (25, 7, 2), (25, 1, 1), (25, 2, 2), (25, 27, 1), (25, 38, 1), (25, 26, 2), (25, 11, 1),
                                    (25, 28, 2), (25, 29, 1), (25, 24, 2), (38, 48, 3), (38, 49, 4), (38, 50, 3), (38, 51, 3), (38, 21, 3),
                                    (38, 7, 2), (38, 27, 1), (38, 38, 1), (38, 26, 2), (38, 11, 1), (38, 28, 2), (38, 29, 1), (38, 25, 2);""")
                                # Périodes par défaut
                                cursor.execute("""SELECT COUNT(*) FROM "Period";""")
                                (count_periods,) = cursor.fetchone()
                                if count_periods == 0:
                                    cursor.execute("""INSERT INTO "Period"(id, evalx) VALUES
                                        (1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6);""")
                except Exception as e:
                    print(f"Erreur lors de l'insertion des données par défaut : {e}")
