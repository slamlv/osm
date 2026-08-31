from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from authentification.models import SchoolYear
from osm.utils import school_year
from .models import ArchivedDocument, YearClosure, DocType, TERMS, PER_CLASSROOM, PER_TERM, TERM_LABELS, ALSO_GLOBAL,\
    PARAM_SENSITIVE, NOTE_DEPENDENT, EFFECTIF_DEPENDENT, build_unit_key
from classroom.models import ClassRoom
from student.models import StudentEnrollment, Student, EnrollmentStatus

"""
=============================================================================
 APP `archives` — Services
=============================================================================
 A. ANNÉE & NOTES     : année de l'établissement, hook d'obsolescence
 B. ARCHIVAGE         : cache au téléchargement + état de fraîcheur
 C. CLÔTURE           : préconditions, consolidation, nettoyage, promotion
=============================================================================
"""
# ===========================================================================
#  A. ANNÉE DE L'ÉTABLISSEMENT & OBSOLESCENCE DES NOTES
# ===========================================================================
def year_coherence(school):
    """Compare l'année de l'établissement à l'année courante globale."""
    from osm.utils import school_year as global_year
    local, glob = school.establishment_year, global_year()
    return {"local": local, "global": glob, "aligned": local == glob, "closure_done": YearClosure.objects.filter(
                school_year=local, status=YearClosure.Status.CLOSED).exists()}


def touch_notes_bulk(classrooms, term_index=None, sequence=None):
    """Marque les notes comme modifiées pour PLUSIEURS classes (saisie par
    niveau). À appeler depuis level-marks-edit / tlevel-marks-edit."""
    if term_index is None and sequence:
        term_index = (int(sequence) + 1) // 2
    if term_index not in (1, 2, 3):
        return 0
    field = f"notes_updated_t{term_index}"
    ids = [c.id if hasattr(c, "id") else c for c in classrooms]
    return ClassRoom.objects.filter(id__in=ids).update(**{field: timezone.now()})


# ===========================================================================
#  ▸ AJOUT — EMPREINTE DES PARAMÈTRES DE GÉNÉRATION
# ===========================================================================
def current_params(doc_type, classroom=None, term_index=None, year=None):
    """Paramètres qui déterminent aujourd'hui le contenu d'un document.

    Comparés à ceux enregistrés sur l'archive (champ `params`) pour décider
    d'une régénération. On compare des VALEURS et non des dates : ré-enregistrer
    le même seuil ne périme donc rien.

    ATTENTION : cette fonction est la SEULE source de vérité — elle sert à
    l'écriture de l'archive comme à la vérification. Toute divergence de format
    entre les deux ferait apparaître les archives comme perpétuellement
    périmées. D'où les conversions explicites en float et l'arrondi.
    ▸ Paramètre term_index, nécessaire pour distinguer le PV annuel (qui dépend
    des décisions) des PV trimestriels.
    """
    if doc_type not in PARAM_SENSITIVE:
        return {}

    # --- document rattaché à une classe : son seuil ---
    if classroom is not None:
        params =  {"seuil": round(float(classroom.moyenne_min_admission or 10), 2)}
        # --- Le PV ANNUEL dépend aussi des décisions du conseil ---
        if doc_type == DocType.PV and term_index == 0:
            from note.deliberation import decisions_fingerprint  # ADAPTE
            params["decisions"] = decisions_fingerprint(classroom, year or school_year())
        return params

    # --- document d'établissement : signature de tous les seuils en vigueur.
    #     Si UNE classe change de seuil, le taux d'ensemble change aussi,
    #     donc le document global doit se périmer.
    vals = sorted(round(float(v or 10), 2) for v in ClassRoom.objects.values_list("moyenne_min_admission", flat=True))
    return {"seuils": vals}


# ===========================================================================
#  B. ARCHIVAGE INCRÉMENTAL — le cache au téléchargement
# ===========================================================================
def find_archive(year, doc_type, classroom=None, term_index=None):
    """▸ Recherche par unit_key (une seule colonne indexée et
    unique) plutôt que par un filtre multi-colonnes avec des NULL."""
    key = build_unit_key(year, doc_type, classroom.id if classroom else None, term_index)
    return ArchivedDocument.objects.filter(unit_key=key).first()


def cached_or_generate(school, doc_type, classroom=None, term_index=None, *, year=None, generate=None, filename=None,
                       user=None, force=False):
    """LE POINT D'ENTRÉE DES VUES DE TÉLÉCHARGEMENT.

    Renvoie (pdf_bytes, doc, from_cache).

    - Archive existante et non périmée -> son contenu est renvoyé SANS
      RÉGÉNÉRATION (retéléchargement instantané).
    - Sinon `generate()` est appelée, l'archive est (ré)écrite.

    `generate()` doit renvoyer (pdf_bytes, page_map|None, page_count).
    """
    year = year or school.establishment_year
    doc = find_archive(year, doc_type, classroom, term_index)

    if doc and not force and not doc.is_stale:
        try:
            doc.file.open("rb")
            data = doc.file.read()
            doc.file.close()
            if data:
                return data, doc, True
        except Exception:
            pass                      # fichier illisible -> on régénère

    if generate is None:
        return None, doc, False

    result = generate()
    if not result:
        return None, doc, False
    data, page_map, page_count = result

    if doc is None:
        doc = ArchivedDocument(
            school_year=year, doc_type=doc_type, classroom=classroom, classroom_label=classroom.code if classroom else "",
            term_index=term_index, title=unit_title(doc_type, classroom, term_index))
    doc.title = unit_title(doc_type, classroom, term_index)
    doc.classroom_label = classroom.code if classroom else doc.classroom_label
    doc.store(filename or default_filename(doc_type, term_index), data, page_map=page_map, page_count=page_count,
              user=user, params=current_params(doc_type, classroom, term_index, year))
    return data, doc, False


def unit_title(doc_type, classroom, term_index):
    bits = [DocType(doc_type).label]
    # ▸ Un document sans classe d'un type "par classe" est global
    if classroom:
        bits.append(classroom.code)
    elif doc_type in PER_CLASSROOM:
        bits.append("Établissement")
    if term_index is not None and term_index in TERM_LABELS:
        bits.append(TERM_LABELS[term_index])
    return " - ".join(bits)


def default_filename(doc_type, term_index=None):
    base = slugify(DocType(doc_type).label)
    if term_index is not None and term_index in TERM_LABELS:
        base += "-" + slugify(TERM_LABELS[term_index])
    return f"{base}.pdf"


# ---------------------------------------------------------------------------
#  ÉTAT DE FRAÎCHEUR — ce que la clôture doit (re)faire
# ---------------------------------------------------------------------------
def planned_units(school, selected_types):
    """Unités attendues. Une unité = (doc_type, classroom|None, term_index|None).

    ▸ Un type peut produire les DEUX familles — une unité par classe ET une
    unité d'établissement (cas des statistiques de réussite).
    Le second bloc est donc un `if` indépendant, et non un `else`.
    """
    units = []
    types = sorted(selected_types or [], key=lambda t: 0 if t == DocType.BULLETIN else 1)
    if school.with_competences and DocType.BULLETIN_WITH_COMPETENCES not in types:
        types.insert(1, DocType.BULLETIN_WITH_COMPETENCES)
    classrooms = list(ClassRoom.objects.all().order_by_niveau())

    for dtype in types:
        # --- déclinaison par classe ---
        if dtype in PER_CLASSROOM:
            for c in classrooms:
                if dtype in PER_TERM:
                    for idx, _ in TERMS:
                        if dtype == DocType.BULLETIN_WITH_COMPETENCES and idx == 0:
                            continue
                        units.append((dtype, c, idx))
                else:
                    units.append((dtype, c, None))
        # --- déclinaison établissement (globale) ---
        if dtype in ALSO_GLOBAL or dtype not in PER_CLASSROOM:
            if dtype in PER_TERM:
                for idx, _ in TERMS:
                    units.append((dtype, None, idx))
            else:
                units.append((dtype, None, None))
    return units


def units_state(school, selected_types, year=None):
    """Classe chaque unité prévue en 'fresh' / 'stale' / 'missing'.

    ▸ Indexation des archives existantes par unit_key (cohérent avec
    find_archive, et insensible au problème des NULL).
    """
    year = year or school.establishment_year()
    existing = {d.unit_key: d for d in ArchivedDocument.objects.filter(school_year=year).select_related("classroom")}

    fresh, stale, missing = [], [], []
    for dtype, classroom, term in planned_units(school, selected_types):
        key = build_unit_key(year, dtype, classroom.id if classroom else None, term)
        doc = existing.get(key)
        entry = {"doc_type": dtype, "classroom": classroom, "term_index": term, "doc": doc,
                 "label": unit_title(dtype, classroom, term),
                 # ▸ Motif affiché dans l'assistant
                 "reason": (doc.stale_reason if doc else "Jamais archivé")}
        if doc is None:
            missing.append(entry)
        elif doc.is_stale:
            stale.append(entry)
        else:
            fresh.append(entry)
    return {"fresh": fresh, "stale": stale, "missing": missing, "todo": missing + stale,
            "total": len(fresh) + len(stale) + len(missing)}


def refresh_progress(school, closure):
    st = units_state(school, closure.selected_types, closure.school_year)
    done = len(st["fresh"])
    return {"done": done, "total": st["total"], "todo": len(st["todo"]),
            "percent": int(done * 100 / st["total"]) if st["total"] else 100}


@transaction.atomic
def refresh_one(school, closure, user=None):
    """Traite LA PROCHAINE unité manquante ou périmée. Renvoie (label, fini)."""
    st = units_state(school, closure.selected_types, closure.school_year)
    if not st["todo"]:
        return None, True

    entry = st["todo"][0]
    dtype, classroom, term = entry["doc_type"], entry["classroom"], entry["term_index"]
    generator = GENERATORS.get(dtype)

    if generator is None:
        _placeholder(closure.school_year, dtype, classroom, term, unit_title(dtype, classroom, term))
        return f"{entry['label']} (générateur absent)", False

    data, doc, cached = cached_or_generate(
        school, dtype, classroom, term, year=closure.school_year,
        generate=lambda: generator(school, closure.school_year, classroom, term),
        user=user, force=True)

    if data is None:                          # rien à produire (classe vide…)
        _placeholder(closure.school_year, dtype, classroom, term, "Sans objet")
        return f"{entry['label']} (sans objet)", False

    remaining = units_state(school, closure.selected_types, closure.school_year)["todo"]
    return entry["label"], not remaining


def _placeholder(year, dtype, classroom, term, title):
    """Entrée vide, pour qu'une unité impossible à produire ne boucle pas.
    ▸ Passe par unit_key et enregistre les params du moment."""
    key = build_unit_key(year, dtype, classroom.id if classroom else None, term)
    if ArchivedDocument.objects.filter(unit_key=key).exists():
        return
    ArchivedDocument.objects.create(
        school_year=year, doc_type=dtype, classroom=classroom, classroom_label=classroom.code if classroom else "",
        term_index=term, title=title, size_bytes=0, params=current_params(dtype, classroom, term, year))


def verify_archives(school, closure):
    """Feu vert avant toute destruction."""
    st = units_state(school, closure.selected_types, closure.school_year)
    docs = ArchivedDocument.objects.filter(school_year=closure.school_year)
    empties = list(docs.filter(size_bytes=0).exclude(title="Sans objet").values_list("title", flat=True))
    return {"ok": not st["todo"] and not empties, "missing": len(st["missing"]), "stale": len(st["stale"]),
            "empties": empties, "count": docs.count(),
            "total_size": sum(docs.values_list("size_bytes", flat=True))}


# ===========================================================================
#  C. CLÔTURE
# ===========================================================================
def missing_marks():
    """Trous de saisie. Vide = clôture possible."""
    from note.models import Note
    holes = []
    if not ClassRoom.objects.exists() or not Student.objects.exists():
        return True
    for classroom in ClassRoom.objects.all().order_by_niveau():
        if not classroom.students.exists():
            continue
        enseignements = list(classroom.enseignement.select_related("matiere__sujet", "enseignant").all())
        enseignements_ids = [ens.id for ens in enseignements]
        existing = set(
            Note.objects.filter(enseignement_id__in=enseignements_ids, eval__in=range(1, 7), note__gte=0)
            .values_list("enseignement_id", "eval")
        )
        for ens in enseignements:
            for seq in range(1, 7):
                if (ens.id, seq) not in existing:
                    holes.append({"classe": classroom.code, "matiere": ens.matiere.sujet.label, "sequence": seq,
                                  'enseignant': ens.enseignant})
    return holes
    """for classroom in ClassRoom.objects.all().order_by_niveau():
        if not classroom.students.exists():
            continue
        for ens in classroom.enseignement.select_related("matiere__sujet", "enseignant").all():
            for seq in range(1, 7):
                filed = Note.objects.filter(enseignement=ens, eval=seq, note__gte=0).exists()
                if not filed:
                    holes.append({"classe": classroom.code, "matiere": ens.matiere.sujet.label, "sequence": seq,
                                  'enseignant': ens.enseignant})
    return holes"""


#  Version CIBLÉE de missing_marks() : une seule classe, un seul trimestre
#  (2 séquences), donc appelable à chaque sauvegarde sans lourdeur. Réutilisée
#  par la tâche de préchauffage
# -----------------------------------------------------------------------------
_TERM_SEQUENCES = {1: (1, 2), 2: (3, 4), 3: (5, 6), 0: (1, 2, 3, 4, 5, 6)}


def missing_marks_for_classroom(classroom, term_index):
    """True s'il manque des notes du trimestre ou de l'année pour cette classe"""
    from note.models import Note

    sequences = _TERM_SEQUENCES.get(term_index)
    if sequences is None:
        return True

    effectif = classroom.students.count()
    if not effectif:
        return True

    enseignements = classroom.enseignement.all()
    nb_enseignements = enseignements.count()
    nb_sequences = len(sequences)
    nb_existants = (
        Note.objects.filter(enseignement__in=enseignements, eval__in=sequences, note__gte=0).
        values("enseignement", "eval").distinct().count()
    )
    return nb_existants != nb_enseignements * nb_sequences
    """
    for ens in classroom.enseignements.all():
        for seq in sequences:
            if Note.objects.filter(enseignement=ens, sequence=seq, note__gte=0).exists():
                return True
    return False"""


def missing_decisions(school, year=None):
    """Signalement NON bloquant."""
    year = year or school.establishment_year
    qs = StudentEnrollment.objects.filter(school_year__libelle=year)
    no_decision = qs.filter(decision__in=["", "En cours", "Non statué"]).count()
    stays = qs.filter(decision__in=["Promu", "Redoublant"])
    no_class = stays.filter(next_classroom__isnull=True).count()
    return {"total": qs.count(), "no_decision": no_decision, "no_next_class": no_class,
            "ok": no_decision == 0 and no_class == 0}


#: nombre de trous détaillés remontés à l'interface (le reste est compté)
CONSOLIDATION_PREVIEW = 50


def verify_consolidation(school, year=None):
    """Repère les inscriptions dont les résultats n'ont pas été figés.

    Ne recalcule RIEN : les moyennes ne sont produites qu'à un seul endroit,
    la construction des bulletins. Cette étape signale les trous et indique
    quels bulletins régénérer pour les combler.

    Causes possibles :
      • élève transféré en cours d'année, absent de l'effectif à l'édition
      • génération d'un trimestre restée en échec

    Une seule requête, colonnes limitées.
    """
    year = year or school.establishment_year

    fields = ("moyenne_t1", "moyenne_t2", "moyenne_t3", "moyenne_annuelle")
    labels = ("Trimestre 1", "Trimestre 2", "Trimestre 3", "Annuel")
    terms = (1, 2, 3, 0)

    holes, units, count = [], set(), 0
    qs = (StudentEnrollment.objects
          .filter(school_year__libelle=year, classroom__isnull=False)
          .select_related("student", "classroom")
          .only("id", "student__nom", "student__prenom", "classroom__id", "classroom__code", *fields))

    for enr in qs:
        missing = [(lbl, idx) for lbl, idx, f in zip(labels, terms, fields) if getattr(enr, f) is None]
        if not missing:
            continue
        count += 1
        if len(holes) < CONSOLIDATION_PREVIEW:
            holes.append({"student": enr.student, "classroom": enr.classroom, "manquants": [m[0] for m in missing]})
        # unités de bulletins à régénérer pour combler ces trous
        if enr.classroom_id:
            for _lbl, idx in missing:
                units.add((enr.classroom_id, idx))

    return {"ok": count == 0, "count": count, "holes": holes, "units": sorted(units)}


def fill_consolidation_gaps(school, closure, user=None, limit=None):
    """Comble les trous en RÉGÉNÉRANT les bulletins concernés.

    Le gel se fait alors par le chemin normal (classroom.reportcard_data),
    donc un seul code de calcul reste en jeu.

    À n'appeler QUE tant que les notes existent, c'est-à-dire AVANT le
    nettoyage — l'ordre des étapes de clôture le garantit.
    """
    report = verify_consolidation(school, closure.school_year)
    done = 0
    for classroom_id, term_index in report["units"]:
        if limit and done >= limit:
            break
        classroom = ClassRoom.objects.filter(pk=classroom_id).first()
        if classroom is None:
            continue
        generator_with_competences = GENERATORS.get(DocType.BULLETIN_WITH_COMPETENCES) if school.with_competences else None
        generator = GENERATORS.get(DocType.BULLETIN)
        if generator is None:
            continue
        cached_or_generate(school, DocType.BULLETIN, classroom, term_index, year=closure.school_year,
            generate=lambda c=classroom, t=term_index: generator(school, closure.school_year, c, t),
            user=user, force=True)
        if generator_with_competences is None:
            continue
        cached_or_generate(school, DocType.BULLETIN, classroom, term_index, year=closure.school_year,
            generate=lambda c=classroom, t=term_index: generator_with_competences(school, closure.school_year, c, t,
                                                                                  freeze=False), user=user, force=True)
        done += 1
    return {"regenerated": done, "remaining": verify_consolidation(school, closure.school_year)["count"]}


CLEANUP_TARGETS = [
    ("notes", "Notes des évaluations", ("note", "Note")),
    ("discipline", "Données de discipline", ("student", "StudentDiscipline")),
    #("enseignements", "Attributions enseignant / matière / classe", ("classroom", "Enseignements")),
]


def _model(app_label, model_name):
    from django.apps import apps
    return apps.get_model(app_label, model_name)


def cleanup_preview():
    rows = []
    for key, label, (app, model) in CLEANUP_TARGETS:
        try:
            rows.append({"key": key, "label": label, "count": _model(app, model).objects.count()})
        except Exception as exc:
            rows.append({"key": key, "label": label, "count": None, "error": str(exc)})
    return rows


@transaction.atomic
def cleanup_year(school, closure, keys=None):
    """Suppression, uniquement si les archives sont au vert."""
    if not verify_archives(school, closure)["ok"]:
        raise RuntimeError("Archives incomplètes ou périmées : nettoyage refusé.")
    deleted = {}
    for key, label, (app, model) in CLEANUP_TARGETS:
        if keys is not None and key not in keys:
            continue
        try:
            n, _ = _model(app, model).objects.all().delete()
            deleted[label] = n
        except Exception as exc:
            deleted[label] = f"erreur : {exc}"
    try:
        ClassRoom.objects.update(titulaire=None)
        deleted["Professeurs titulaires (détachés)"] = "OK"
    except Exception:
        pass
    try:
        from note.models import Period
        Period.objects.update(start=None, end=None)
        deleted["Périodes de remplissage des notes nettoyées"] = "OK"
    except Exception:
        pass
    try:
        ClassRoom.objects.update(notes_updated_t1=None, notes_updated_t2=None, notes_updated_t3=None, decisions_updated=None)
    except Exception:
        pass
    try:
        from classroom.models import Enseignements
        Enseignements.objects.update(nlpt1=None, nlpt2=None, nlpt3=None, nlpp1=None, nlpp2=None, nlpp3=None,
                                     nlft1=None, nlft2=None, nlft3=None, nlfp1=None, nlfp2=None, nlfp3=None)
        deleted["Progressions nettoyées"] = "OK"
    except Exception:
        pass
    try:
        from classroom.models import Programmation
        Programmation.objects.all().delete()
        deleted["Programmations des cours nettoyées"] = "OK"
    except Exception:
        pass
    # Mise à jour de l'ancienneté du personnel
    try:
        from staff.models import Personnel
        from django.db.models import F
        Personnel.objects.filter(since__isnull=False).update(since=F('since') + 1)
    except Exception:
        pass
    return deleted


def next_year_label(year):
    try:
        a, b = year.split("/")
        return f"{int(a)+1}/{int(b)+1}"
    except Exception:
        return ""


@transaction.atomic
def promote_year(school, closure):
    """Crée l'année suivante, bascule les élèves, avance le pointeur d'année de l'établissement."""
    from authentification.models import SchoolYear
    old = closure.school_year
    new = next_year_label(old)
    new_year = SchoolYear.objects.get(libelle=new)

    moved = left = pending = 0
    for enr in (StudentEnrollment.objects.filter(school_year__libelle=old)
            .select_related("student", "next_classroom")):
        student = enr.student
        if enr.decision in ("Promu", "Redoublant") and enr.next_classroom_id:
            student.classe = enr.next_classroom
            student.save(update_fields=["classe"])
            StudentEnrollment.objects.update_or_create(
                student=student, school_year=new_year, defaults={"classroom": enr.next_classroom})
            moved += 1
        elif enr.decision in ("Transféré", "Sorti", "Exclu"):
            student.classe = None
            student.is_active = False
            student.save(update_fields=["classe", "is_active"])
            left += 1
        else:
            enr.decision = EnrollmentStatus.NON_STATUE
            enr.save(update_fields=["decision"])
            student.classe = None
            StudentEnrollment.objects.get_or_create(
                student=student, school_year=new_year, defaults={"classroom": None})
            student.save(update_fields=["classe"])
            pending += 1

    school.school_year = school.last_schoolyear_closed = SchoolYear.objects.get(libelle=old)
    school.save(update_fields=["school_year", "last_schoolyear_closed"])
    ArchivedDocument.objects.filter(size_bytes=0).delete()

    return {"new_year": new, "moved": moved, "left": left, "pending": pending}


# ===========================================================================
#  GÉNÉRATEURS
# ===========================================================================
#  Signature : f(year, classroom, term_index) -> (pdf_bytes, page_map, pages)
#              ou None s'il n'y a rien à produire.
#  term_index : 1, 2, 3 = trimestre ; 0 = annuel ; None = non périodique.
#  classroom  : None = document d'ÉTABLISSEMENT (toutes classes confondues).
#
#  Ces mêmes fonctions servent AU TÉLÉCHARGEMENT et à la clôture.
# ---------------------------------------------------------------------------
"""
=============================================================================
 PRINCIPE : on ne réécrit AUCUNE logique de production. Chaque vue expose déjà
 un `build_pdf_or_reason(classroom, …)` qui renvoie soit un objet FPDF, soit
 une chaîne expliquant pourquoi la classe est sautée (notes incomplètes).
 Les générateurs se contentent de traduire les arguments et de déléguer.

 Conséquence : un correctif apporté à une vue profite automatiquement à
 l'archivage, et inversement. Il n'existe qu'un seul code de production.

 CONVENTION DE TRADUCTION
 ---------------------------------------------------------------------------
   term_index (archives)  ->  evl (tes vues)  ->  evl_in            trimestre
        1                        1              (1, 2)     DU PREMIER TRIMESTRE
        2                        2              (3, 4)     DU DEUXIÈME TRIMESTRE
        3                        3              (5, 6)     DU TROISIÈME TRIMESTRE
        0 (annuel)               4     (1,2,3,4,5,6)       ANNUEL

 Le libellé annuel varie selon le document (ANNUEL, ANNUELLE, ANNUELLES) :
 d'où le paramètre `annual` de term_labels().
=============================================================================
"""

# ---------------------------------------------------------------------------
#  TRADUCTION DES PÉRIODES
# ---------------------------------------------------------------------------
#: term_index -> évaluations concernées
_EVL_IN = {
    1: (1, 2),
    2: (3, 4),
    3: (5, 6),
    0: (1, 2, 3, 4, 5, 6),
}

_TRIM = {
    1: "DU PREMIER TRIMESTRE",
    2: "DU DEUXIÈME TRIMESTRE",
    3: "DU TROISIÈME TRIMESTRE",
}


def term_labels(term_index, annual="ANNUEL"):
    """(evl_in, trimestre) pour un term_index. `annual` : libellé de l'annuel,
    qui diffère d'un document à l'autre (ANNUEL / ANNUELLE / ANNUELLES)."""
    evl_in = _EVL_IN.get(term_index)
    if evl_in is None:
        return None, None
    return evl_in, (annual if term_index == 0 else _TRIM[term_index])


def _emit(pdf):
    """(bytes, page_map, pages) à partir d'un objet FPDF, ou None si la
    construction a renvoyé une raison de saut (notes incomplètes)."""
    if pdf is None or isinstance(pdf, str):
        return None                     # rien à produire : archive « sans objet »
    try:
        pages = pdf.page_no()
    except Exception:
        pages = 0
    return bytes(pdf.output()), None, pages


# ===========================================================================
#  BULLETINS (sans compétences, construit une carte des pages)
# ===========================================================================
def _bulletins(school, year, classroom, term_index, freeze=True):
    """Bulletins d'une classe pour un trimestre (0 = annuel).

    Reprend le corps de Bulletin.post, sans la requête HTTP : mêmes appels,
    mêmes données. Le seuil vient de la classe, pas du formulaire.
    """
    from classroom.models import ClassRoom
    from note.views import ReportCard
    from osm.utils import check_notes

    evl_in, trimestre = term_labels(term_index, annual="ANNUEL")
    if evl_in is None:
        return None

    classroom = (ClassRoom.objects.select_related('classe')
                 .prefetch_related('students__pere', 'students__mere',
                                   'students__discipline', 'matieres__sujet')
                 .get(pk=classroom.pk))

    if not classroom.students.exists():
        return None

    # notes incomplètes -> pas de bulletin, l'unité restera « sans objet »
    if missing_marks_for_classroom(classroom, term_index):
        return None
    
    #if check_notes(classroom, evl_in) is not None:
    #    return None

    filename = f"Bulletin Scolaire {trimestre.title()} {classroom.code}.pdf"

    data = classroom.reportcard_data(evl_in, year=school.establishment_year, with_competences=False, freeze=freeze)
    data['school_data'] = school.school_to_dict()
    data['trimestre'], data['annee'] = trimestre, year
    data['filename'] = filename

    pdf = ReportCard(data=data)

    # --- carte des pages : permet de ressortir le bulletin d'UN élève -------
    #  ReportCard.nb_pages = nombre de pages PAR élève (constant).
    #  L'ordre doit être CELUI DU PDF, donc celui de data['students_data'].
    page_map = None
    try:
        nb = int(getattr(pdf, "nb_pages", 0) or 0)
        students = list(classroom.students.all().order_by("nom", "prenom"))
        if nb and students:
            page_map = {}
            for i, student in enumerate(students):
                sid = student.id
                if sid:
                    page_map[sid] = [i * nb + 1, (i + 1) * nb]
    except Exception:
        page_map = None          # sans carte, l'archive reste parfaitement valide

    try:
        pages = pdf.page_no()
    except Exception:
        pages = 0
    return bytes(pdf.output()), page_map, pages


# ===========================================================================
#  BULLETINS  (avec compétences, construit une carte des pages)
# ===========================================================================
def _bulletins_with_competences(school, year, classroom, term_index, freeze=True):
    """Bulletins d'une classe pour un trimestre (0 = annuel).

    Reprend le corps de Bulletin.post, sans la requête HTTP : mêmes appels,
    mêmes données. Le seuil vient de la classe, pas du formulaire.
    """
    from classroom.models import ClassRoom
    from note.views import ReportCard
    from osm.utils import check_notes

    evl_in, trimestre = term_labels(term_index, annual="ANNUEL")
    if evl_in is None:
        return None

    classroom = (ClassRoom.objects.select_related('classe')
                 .prefetch_related('students__pere', 'students__mere',
                                   'students__discipline', 'matieres__sujet')
                 .get(pk=classroom.pk))

    if not classroom.students.exists():
        return None

    # notes incomplètes -> pas de bulletin, l'unité restera « sans objet »
    if missing_marks_for_classroom(classroom, term_index):
        return None
    
    #if check_notes(classroom, evl_in) is not None:
    #    return None

    filename = f"Bulletin Scolaire {trimestre.title()} {classroom.code}.pdf"

    data = classroom.reportcard_data(evl_in, year=school.establishment_year, with_competences=True, freeze=freeze)
    data['school_data'] = school.school_to_dict()
    data['trimestre'], data['annee'] = trimestre, year
    data['filename'] = filename

    pdf = ReportCard(data=data)

    # --- carte des pages : permet de ressortir le bulletin d'UN élève -------
    #  ReportCard.nb_pages = nombre de pages PAR élève (constant).
    #  L'ordre doit être CELUI DU PDF, donc celui de data['students_data'].
    page_map = None
    try:
        nb = int(getattr(pdf, "nb_pages", 0) or 0)
        students = list(classroom.students.all().order_by("nom", "prenom"))
        if nb and students:
            page_map = {}
            for i, student in enumerate(students):
                sid = student.id
                if sid:
                    page_map[sid] = [i * nb + 1, (i + 1) * nb]
    except Exception:
        page_map = None          # sans carte, l'archive reste parfaitement valide

    try:
        pages = pdf.page_no()
    except Exception:
        pages = 0
    return bytes(pdf.output()), page_map, pages


# ===========================================================================
#  PROCÈS-VERBAL DE DÉLIBÉRATION
# ===========================================================================
def _pv(school, year, classroom, term_index):
    """Délègue à ExamReport.build_pdf_or_reason — aucune logique dupliquée."""
    from classroom.models import ClassRoom
    from note.views import ExamReport

    evl_in, trimestre = term_labels(term_index, annual="ANNUEL")
    if evl_in is None:
        return None
    classroom = ClassRoom.objects.prefetch_related('matieres').get(pk=classroom.pk)
    return _emit(ExamReport.build_pdf_or_reason(
        classroom, evl_in, pv_ordered=True, annee=year, school=school, trimestre=trimestre))


"""
# ===========================================================================
#  TABLEAU D'HONNEUR
# ===========================================================================
def _tableau_honneur(year, classroom, term_index):
    from classroom.models import ClassRoom
    from notes.views import TableauHonneur                # ADAPTE le chemin

    evl_in, trimestre = term_labels(term_index, annual="ANNUELLE")
    if evl_in is None:
        return None
    classroom = (ClassRoom.objects.prefetch_related('students', 'matieres')
                 .get(pk=classroom.pk))
    return _emit(TableauHonneur.build_pdf_or_reason(
        classroom, evl_in, annee=year, school=_school(), trimestre=trimestre))


# ===========================================================================
#  RELEVÉ DE NOTES
# ===========================================================================
def _marks_report(year, classroom, term_index):
    from classroom.models import ClassRoom
    from notes.views import MarksReport                   # ADAPTE le chemin

    #: le relevé n'existe pas en version annuelle
    if term_index not in (1, 2, 3):
        return None
    evl_in, trimestre = term_labels(term_index)
    classroom = (ClassRoom.objects.select_related('classe')
                 .prefetch_related('students', 'matieres__sujet')
                 .get(pk=classroom.pk))
    return _emit(MarksReport.build_pdf_or_reason(
        classroom, evl_in, annee=year, school=_school(), trimestre=trimestre))


# ===========================================================================
#  FICHE DE NOTES  (document de classe, non périodique)
# ===========================================================================
def _marks_sheet(year, classroom, term_index):
    from classroom.models import ClassRoom
    from classroom.views import MarksSheet                # ADAPTE le chemin

    classroom = ClassRoom.objects.prefetch_related('students').get(pk=classroom.pk)
    return _emit(MarksSheet.build_pdf_or_reason(classroom, annee=year,
                                                school=_school()))"""


# ===========================================================================
#  STATISTIQUES DE RÉUSSITE  (par classe ET établissement)
# ===========================================================================
def _stats_reussite(school, year, classroom, term_index):
    """La vue Stats gère déjà les deux cas : classroom=None produit les
    statistiques de TOUT l'établissement. C'est exactement la sémantique
    d'ALSO_GLOBAL.

    NB: build_pdf_or_reason est ici une méthode d'INSTANCE : on
    instancie la vue sans requête, elle ne s'en sert pas dans cette méthode.
    """
    from classroom.models import ClassRoom
    from classroom.views import Stats

    evl_in, trimestre = term_labels(term_index, annual="ANNUELLES")
    if evl_in is None:
        return None

    if classroom is not None:
        classroom = (ClassRoom.objects.select_related('classe')
                     .prefetch_related('students', 'matieres__sujet')
                     .get(pk=classroom.pk))

    return _emit(Stats().build_pdf_or_reason(
        classroom, evl_in, annee=year, school=school,  trimestre=trimestre))


# ===========================================================================
#  LISTE DES ÉLÈVES (document de classe, non périodique)
# ===========================================================================
def _class_list(school, year, classroom, term_index=None):
    from classroom.models import ClassRoom
    from classroom.views import ClassroomList

    classroom = ClassRoom.objects.prefetch_related('students').get(pk=classroom.pk)
    if not classroom.students.exists():
        return None
    return _emit(ClassroomList(annee=year, classroom=classroom, school=school))


# ===========================================================================
#  ALBUM PHOTO DE CLASSE
# ===========================================================================
def _album(school, year, classroom, term_index=None):
    from classroom.views import ClassAlbum
    from django.db.models import Prefetch
    from staff.models import Personnel
    from note.models import Enseignements

    classrooms = (
        ClassRoom.objects.prefetch_related(
            Prefetch(
                'enseignement',
                queryset=Enseignements.objects.select_related('matiere__sujet', 'enseignant')
            ),
            'students')
        .select_related('titulaire')
    )
    principal = Personnel.objects.filter(poste="Chef d'Établissement").first()
    school_data = {
        'nom': school.nom,
        'name': school.name,
        'logo': school.logo,
        'principal': principal
    }
    classroom = classrooms.get(pk=classroom.pk)
    return _emit(ClassAlbum.build_pdf_or_reason(classroom, year, school_data))


# ===========================================================================
#  RÉPARTITION ÂGE / SEXE  (document d'établissement)
# ===========================================================================
def _stats_age_sexe(school, year, classroom, term_index):
    from student.views import build_age_sex_table, AgeSexTablePDF
    from student.models import Student
    from classroom.models import ClassRoom

    data = build_age_sex_table(year)
    if not Student.objects.exists() or not ClassRoom.objects.exists():
        return None
    return _emit(AgeSexTablePDF(data, school))


# ===========================================================================
#  REGISTRE
# ===========================================================================
GENERATORS = {
    DocType.BULLETIN:                        _bulletins,
    DocType.BULLETIN_WITH_COMPETENCES:       _bulletins_with_competences,
    DocType.PV:                              _pv,
    DocType.CLASS_LIST:                      _class_list,
    DocType.ALBUM:                           _album,
    DocType.STATS_AGE_SEXE:                  _stats_age_sexe,
    DocType.STATS_REUSSITE:                  _stats_reussite,
    # types à déclarer dans DocType si tu veux les archiver aussi :
    # DocType.TABLEAU_HONNEUR:               _tableau_honneur,
    # DocType.MARKS_REPORT:                  _marks_report,
    # DocType.MARKS_SHEET:                   _marks_sheet,
}
