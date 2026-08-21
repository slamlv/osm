"""Règles de délibération : décisions de passage et mentions."""

# ---------------------------------------------------------------------------
#  DÉCISIONS (PV ANNUEL)
# ---------------------------------------------------------------------------
#: abréviations portées sur le document
DECISION_CODES = {
    "Promu":      "ADM",
    "Redoublant": "RED",
    "Exclu":      "EXC",
    "Transféré":  "TRF",
    "Sorti":      "SOR",
}


def proposed_decision(moyenne, seuil):
    """Proposition CALCULÉE, telle que le conseil la reçoit avant délibération."""
    if moyenne is None:
        return ""
    return "ADM" if float(moyenne) >= float(seuil) else "RED"


def student_decision(student, year, moyenne=None, seuil=10):
    """Décision PORTÉE AU PV. Renvoie (code, divergente).

    Priorité à la décision réelle du conseil ; à défaut, la proposition
    calculée. `divergente` vaut True quand le conseil s'est écarté du calcul
    """

    proposal = proposed_decision(moyenne, seuil)
    enr = student.enrollments.filter(student=student, school_year__libelle=year).only("decision").first()
    decision = getattr(enr, "decision", "") if enr else ""

    if not decision or decision in ("En cours", "Non statué"):
        return proposal, False

    code = DECISION_CODES.get(decision, decision[:3].upper())
    #: divergence : seuls ADM et RED sont comparables à la proposition.
    #: Un transfert ou une exclusion ne « diverge » pas, il relève d'autre chose.
    divergente = bool(proposal) and code in ("ADM", "RED") and code != proposal
    decision = decision if decision in DECISION_CODES else ""
    if decision in ("Promu", "Sorti", "Transféré", "Exclu") and student.sexe == "Fille":
        decision += "e"
    elif decision == "Redoublant":
        decision = "Redouble"
    return decision, divergente


def decisions_fingerprint(classroom, year):
    """Empreinte des décisions d'une classe, pour la péremption des archives.

    Comparée par current_params : une décision modifiée change l'empreinte,
    donc périme le PV annuel archivé, donc déclenche sa régénération.
    Triée pour être stable quel que soit l'ordre de lecture.
    """
    from student.models import StudentEnrollment

    rows = (StudentEnrollment.objects.filter(school_year__libelle=year, student__classe=classroom)
            .values_list("student_id", "decision", "next_classroom_id"))
    return "|".join(f"{sid}:{dec or ''}:{nxt or ''}" for sid, dec, nxt in sorted(rows))


# ---------------------------------------------------------------------------
#  MENTIONS (PV TRIMESTRIELS)
# ---------------------------------------------------------------------------
#: seuils de mérite, du plus élevé au plus bas. Paramétrables : remplace par
#: une lecture de configuration si un établissement veut ses propres valeurs.
MERIT_THRESHOLDS = (
    (16, "Félicitations"),
    (14, "Encouragements"),
    (12, "Tableau d'honneur"),
)
#: en dessous de cette moyenne : avertissement pour le travail
WORK_WARNING_BELOW = 8


def merit_mention(moyenne):
    """Mention de TRAVAIL, déduite de la moyenne."""
    if moyenne is None:
        return ""
    m = float(moyenne)
    for seuil, label in MERIT_THRESHOLDS:
        if m >= seuil:
            return label
    return "Avertissement travail" if 0 < m < WORK_WARNING_BELOW else ""


def conduct_mention(discipline):
    """Sanction de CONDUITE, LUE depuis StudentDiscipline — jamais calculée.

    `discipline` : le dictionnaire déjà construit pour le bulletin, qui porte
    les clés 'avert', 'blame' et 'excl_def'.
    """
    if not discipline:
        return ""
    if discipline.get("excl_def"):
        return "Exclusion définitive"
    if discipline.get("blame"):
        return "Blâme de conduite"
    if discipline.get("avert"):
        return "Avertissement conduite"
    return ""


def full_mention(moyenne, discipline=None):
    """Mention complète : mérite et sanction se CUMULENT.

    Un élève peut très bien mériter des encouragements pour son travail et
    un avertissement pour sa conduite — la situation est fréquente, et un PV
    qui n'en retiendrait qu'une seule serait faux.
    """
    parts = [p for p in (merit_mention(moyenne), conduct_mention(discipline)) if p]
    return " • ".join(parts)
