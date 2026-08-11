from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from io import BytesIO
from urllib.parse import quote
from django.http import FileResponse

"""
=============================================================================
 APP `archives` — Modèles (TENANT_APPS)
=============================================================================
 Archivage INCRÉMENTAL : un document est archivé au moment où on le
 télécharge, et l'archive sert de CACHE tant qu'elle n'est pas périmée.

 DEUX CRITÈRES DE PÉREMPTION :
   1. les NOTES ont changé      -> ClassRoom.notes_updated_t{i} > archived_at
   2. les PARAMÈTRES ont changé -> params stockés ≠ paramètres actuels
      (aujourd'hui : la moyenne minimale d'admission)
=============================================================================
"""
# ---------------------------------------------------------------------------
#  TYPES DE DOCUMENTS
# ---------------------------------------------------------------------------
class DocType(models.TextChoices):
    BULLETIN                        = "BULLETIN", "Bulletins scolaires"
    BULLETIN_WITH_COMPETENCES       = "BULLETIN_WITH_COMPETENCES", "Bulletins avec compétences"
    PV                              = "PV", "Procès verbaux"
    CLASS_LIST                      = "CLASS_LIST", "Listes de classe"
    ALBUM                           = "ALBUM", "Albums photos de classe"
    STATS_AGE_SEXE                  = "STATS_AGE_SEXE", "Statistiques (âge / sexe)"
    STATS_REUSSITE                  = "STATS_REUSSITE", "Statistiques de réussite"
    CLOSURE_REPORT                  = "CLOSURE_REPORT", "Rapport de clôture"


#: Seul document imposé : jamais décochable, jamais supprimable.
MANDATORY_TYPES = {DocType.BULLETIN, DocType.BULLETIN_WITH_COMPETENCES}

# ▸ Les stats de réussite existent aussi en version par classe
PER_CLASSROOM = {DocType.BULLETIN, DocType.PV, DocType.CLASS_LIST, DocType.BULLETIN_WITH_COMPETENCES,
                 DocType.ALBUM, DocType.STATS_REUSSITE}

# ▸ Les stats de réussite sont également trimestrielles (et annuelles)
PER_TERM = {DocType.BULLETIN, DocType.PV, DocType.STATS_REUSSITE, DocType.BULLETIN_WITH_COMPETENCES}

# ▸ Types produits EN PLUS en version établissement (classroom = None).
#   Un type peut donc appartenir à la fois à PER_CLASSROOM et à ALSO_GLOBAL :
#   il produit alors une unité par classe ET une unité globale.
ALSO_GLOBAL = {DocType.STATS_REUSSITE}

# ▸ Les stats de réussite dépendent des notes, donc elles se périment
NOTE_DEPENDENT = {DocType.BULLETIN, DocType.PV, DocType.STATS_REUSSITE, DocType.BULLETIN_WITH_COMPETENCES}

# ▸ Si l'effectif change, elles se périment
EFFECTIF_DEPENDENT = {DocType.BULLETIN, DocType.PV, DocType.STATS_REUSSITE, DocType.BULLETIN_WITH_COMPETENCES,
                      DocType.ALBUM, DocType.CLASS_LIST, DocType.STATS_AGE_SEXE}

# ▸ Types dont le contenu dépend AUSSI de paramètres (seuil d'admission)
PARAM_SENSITIVE = {DocType.BULLETIN, DocType.PV, DocType.STATS_REUSSITE, DocType.BULLETIN_WITH_COMPETENCES}

#: Trimestres archivés. term_index : 1, 2, 3 et 0 = annuel.
TERMS = [(1, "Trimestre 1"), (2, "Trimestre 2"), (3, "Trimestre 3"),
         (0, "Annuel")]
TERM_LABELS = dict(TERMS)

#: AUCUN document financier n'est archivé : les données financières ne sont
#: jamais supprimées, et les états se régénèrent à la demande avec filtres.


def archive_upload_path(instance, filename):
    """archives/2025-2026/BULLETIN/6eme-a/bulletins-trimestre-1.pdf"""
    parts = ["archives", slugify(instance.school_year), instance.doc_type]
    if instance.classroom_label:
        parts.append(slugify(instance.classroom_label))
    return "/".join(parts + [filename])


def build_unit_key(school_year, doc_type, classroom_id=None, term_index=None):
    """Identité textuelle d'une unité d'archive.

    Pourquoi ce champ plutôt que `nulls_distinct=False` : en SQL, deux NULL
    ne sont jamais égaux, donc une contrainte portant sur `classroom` et
    `term_index` (tous deux nullables pour un document global non périodique)
    serait totalement inopérante et laisserait passer des doublons.
    La clé remplace les NULL par un tiret, ce qui rend l'unicité vérifiable
    par une simple égalité de chaîne — y compris à la main, en base.

        2025-2026|BULLETIN|12|1        bulletins de la classe 12, trimestre 1
        2025-2026|STATS_REUSSITE|-|0   stats de réussite, établissement, annuel
        2025-2026|STATS_AGE_SEXE|-|-   stats âge/sexe, établissement
    """
    cls = classroom_id if classroom_id else "-"
    trm = "-" if term_index is None else term_index
    return f"{school_year}|{doc_type}|{cls}|{trm}"
# -----------------------------------------------------------------------------


# ---------------------------------------------------------------------------
#  DOCUMENT ARCHIVÉ  (coffre + cache + marqueur de progression)
# ---------------------------------------------------------------------------
class ArchivedDocument(models.Model):
    school_year = models.CharField(max_length=9, db_index=True)
    doc_type    = models.CharField(max_length=30, choices=DocType.choices, db_index=True)
    classroom   = models.ForeignKey("classroom.ClassRoom", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="archived_documents")
    #: libellé figé : la classe peut être renommée ou supprimée plus tard
    classroom_label = models.CharField(max_length=30, blank=True, default="")
    #: effectif figé : l'effectif peut changer plus tard
    effectif = models.PositiveSmallIntegerField(default=0)
    #: 1,2,3 = trimestre ; 0 = annuel ; NULL = document non périodique
    term_index  = models.SmallIntegerField(null=True, blank=True)
    # ▸ clé d'unicité calculée (voir build_unit_key ci-dessus)
    unit_key    = models.CharField(max_length=120, unique=True, editable=False, default="")
    title       = models.CharField(max_length=160)
    file        = models.FileField(upload_to=archive_upload_path, null=True, blank=True)
    size_bytes  = models.PositiveIntegerField(default=0)
    page_count  = models.PositiveSmallIntegerField(default=0)

    #: Bulletins : {student_id: [page_debut, page_fin]}
    page_map    = models.JSONField(null=True, blank=True)

    # ▸ Empreinte des paramètres ayant déterminé le contenu.
    #   Ex. {"seuil": 10.0} pour un document de classe,
    #       {"seuils": [10.0, 10.0, 12.0]} pour un document d'établissement.
    #   Une valeur différente aujourd'hui = archive périmée. On compare la
    #   VALEUR et non une date : ré-enregistrer le même seuil ne périme rien.
    params      = models.JSONField(null=True, blank=True)

    #: date de (RÉ)ÉCRITURE du fichier — comparée aux notes
    archived_at = models.DateTimeField(default=timezone.now)
    created_at  = models.DateTimeField(auto_now_add=True)
    created_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    #: nombre de régénérations (indicateur d'activité, utile au diagnostic)
    versions    = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "ArchivedDocument"
        ordering = ["school_year", "doc_type", "classroom_label", "term_index"]
        # ▸ L'unicité repose sur unit_key (champ unique=True)
        indexes = [
            models.Index(fields=["school_year", "doc_type"]),
            models.Index(fields=["school_year", "doc_type", "classroom", "term_index"]),
        ]

    def __str__(self):
        bits = [self.get_doc_type_display(), self.classroom_label or "Établissement", self.term_label]
        return " • ".join(b for b in bits if b)

    def update_effectif(self):
        if self.doc_type != DocType.CLOSURE_REPORT:
            if self.classroom_id:
                effectif = self.classroom.effectif
            else:
                from student.models import Student
                effectif = Student.objects.count()
            if effectif != self.effectif:
                self.effectif = effectif

    # ▸ La clé est recalculée à chaque enregistrement
    def save(self, *args, **kwargs):
        self.unit_key = build_unit_key(self.school_year, self.doc_type, self.classroom_id, self.term_index)
        self.update_effectif()
        super().save(*args, **kwargs)

    # ---- libellés -----------------------------------------------------
    @property
    def term_label(self):
        if self.term_index is None:
            return ""
        return TERM_LABELS.get(self.term_index, "")

    @property
    def is_global(self):
        """Document d'établissement (aucune classe rattachée)."""
        return self.classroom_id is None and self.doc_type in PER_CLASSROOM

    @property
    def size_display(self):
        kb = (self.size_bytes or 0) / 1024
        return f"{kb/1024:.1f} Mo" if kb >= 1024 else f"{kb:.0f} Ko"

    # ---- fraîcheur ----------------------------------------------------
    @property
    def notes_reference_date(self):
        """Dernière modification des notes qui concernent ce document.

        ▸ Un document d'établissement dépend de TOUTES les classes : on
        prend la modification la plus récente, toutes classes confondues.
        """
        if self.doc_type not in NOTE_DEPENDENT:
            return None

        # --- document rattaché à une classe ---
        if self.classroom_id:
            return self.classroom.notes_updated_at(self.term_index or 0)

        # --- document d'établissement : le maximum sur toutes les classes ---
        from django.db.models import Max
        from classroom.models import ClassRoom          # import local : anti-cycle
        idx = self.term_index
        fields = ([f"notes_updated_t{idx}"] if idx in (1, 2, 3)
                  else ["notes_updated_t1", "notes_updated_t2", "notes_updated_t3"])
        agg = ClassRoom.objects.aggregate(**{f: Max(f) for f in fields})
        dates = [v for v in agg.values() if v]
        return max(dates) if dates else None

    @property
    def is_year_closed(self):
        closure = YearClosure.objects.filter(school_year=self.school_year).first()
        if closure and closure.status == YearClosure.Status.CLOSED:
            return True
        return False

    @property
    def is_stale(self):
        """True si le document doit être régénéré.
        ▸ Trois causes possibles — effectif différent, les notes ont bougé,
        ou les paramètres de génération ont changé (seuil d'admission).
        """
        if not self.is_year_closed:
            if not self.file and self.title != "Sans objet":
                return True
            # 1) l'effectif a-t-il changé après l'archivage ?
            if self.doc_type in EFFECTIF_DEPENDENT and not self.is_year_closed:
                if self.classroom_id:
                    effectif = self.classroom.effectif
                else:
                    from student.models import Student
                    effectif = Student.objects.count()
                if effectif != self.effectif:
                    return True
            # 2) les notes ont-elles bougé après l'archivage ?

            if self.doc_type in NOTE_DEPENDENT:
                ref = self.notes_reference_date
                if ref and self.archived_at and ref > self.archived_at:
                    return True
            # 3) les paramètres de génération ont-ils changé ?
            if self.doc_type in PARAM_SENSITIVE:
                from .services import current_params        # import local : anti-cycle
                return (self.params or {}) != current_params(self.doc_type, self.classroom, self.term_index, self.school_year)
        return False

    @property
    def stale_reason(self):
        """Motif lisible, affiché dans l'assistant de clôture."""
        if not self.is_year_closed:
            if not self.file and self.title != "Sans objet":
                return "Jamais généré"
            if self.doc_type in EFFECTIF_DEPENDENT:
                if self.classroom_id:
                    effectif = self.classroom.effectif
                else:
                    from student.models import Student
                    effectif = Student.objects.count()
                if effectif != self.effectif:
                    return "L'effectif d'élèves a changé"
            if self.doc_type in NOTE_DEPENDENT:
                ref = self.notes_reference_date
                if ref and self.archived_at and ref > self.archived_at:
                    return "Données disciplinaires, d'élèves ou Notes modifiées"
            if self.doc_type in PARAM_SENSITIVE:
                from .services import current_params
                currents = current_params(self.doc_type, self.classroom, self.term_index, self.school_year)
                if (self.params or {}) != currents:
                    if self.doc_type == DocType.PV and self.term_index == 0:
                        if self.params['decisions'] != currents['decisions']:
                            return "Décisions de fin d'année modifiées"
                    return "Moyenne minimale d'admission modifiée"
        return ""

    @property
    def is_deletable(self):
        """Les bulletins sont les seuls documents non supprimables."""
        return self.doc_type not in MANDATORY_TYPES

    # ---- (ré)écriture du fichier --------------------------------------
    def store(self, filename, data, page_map=None, page_count=0, user=None, params=None):
        """Écrit ou RÉÉCRIT le fichier de l'archive.

        ORDRE VOLONTAIRE : écrire le nouveau fichier, enregistrer la ligne,
        et SEULEMENT ENSUITE supprimer l'ancien.

        L'ordre inverse exposerait à une perte sèche : si l'écriture échoue
        après la suppression, l'archive précédente serait détruite sans
        remplaçant. Le pire cas devient ici un fichier orphelin de quelques
        centaines de kilo-octets, au lieu d'un document définitivement perdu.
        """
        from django.core.files.base import ContentFile

        # nom de l'ancien fichier, mémorisé AVANT que le champ soit réaffecté
        old_name = self.file.name if self.file else None

        self.size_bytes = len(data)
        self.page_count = page_count or 0
        if page_map is not None:
            self.page_map = page_map
        if params is not None:
            self.params = params
        self.archived_at = timezone.now()
        if user is not None:
            self.created_by = user

        # 1) écriture du nouveau fichier — si elle échoue, l'ancien est intact
        self.file.save(filename, ContentFile(data), save=False)
        if old_name:
            self.versions = (self.versions or 1) + 1

        # 2) enregistrement de la ligne — si elle échoue, la base pointe
        #    toujours l'ancien fichier, qui existe encore
        self.save()

        # 3) suppression de l'ancien, devenu orphelin.
        #    Le test des noms est indispensable : certains stockages écrasent
        #    au lieu de renommer, on supprimerait alors ce qu'on vient d'écrire.
        if old_name and old_name != self.file.name:
            try:
                self.file.storage.delete(old_name)
            except Exception:
                pass  # orphelin toléré : jamais au prix de l'archive
        print("Done")
        return self


# ---------------------------------------------------------------------------
#  CLÔTURE D'UNE ANNÉE
# ---------------------------------------------------------------------------
class YearClosure(models.Model):

    class Status(models.TextChoices):
        PREPARING  = "PREPARING", "Préparation"
        REFRESHING = "REFRESHING", "Mise à jour des archives"
        ARCHIVED   = "ARCHIVED", "Archives à jour"
        CLEANED    = "CLEANED", "Nettoyé"
        CLOSED     = "CLOSED", "Clôturé"

    STEPS = [
        ("checks",      "Vérification des notes"),
        ("decisions",   "Décisions de fin d'année"),
        ("select",      "Choix des documents"),
        ("refresh",     "Mise à jour des archives"),
        ("verify",      "Vérification d'intégrité"),
        ("consolidate", "Consolidation des moyennes et rangs"),
        ("cleanup",     "Nettoyage des données"),
        ("promote",     "Ouverture de l'année suivante"),
    ]

    school_year    = models.CharField(max_length=9, unique=True)
    status         = models.CharField(max_length=12, choices=Status.choices, default=Status.PREPARING)
    selected_types = models.JSONField(default=list, blank=True)
    steps          = models.JSONField(default=dict, blank=True)

    started_by  = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="closures_started")
    started_at  = models.DateTimeField(auto_now_add=True)
    closed_by   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="closures_finished")
    closed_at   = models.DateTimeField(null=True, blank=True)

    classrooms = models.PositiveSmallIntegerField(default=0)
    students   = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "YearClosure"
        ordering = ["-school_year"]

    def __str__(self):
        return f"Clôture {self.school_year} ({self.get_status_display()})"

    def is_done(self, key):
        return bool(self.steps.get(key, {}).get("done"))

    def mark(self, key, detail=None, done=True, save=True):
        self.steps[key] = {"done": done, "at": timezone.now().isoformat(), "detail": detail or {}}
        if save:
            self.save(update_fields=["steps"])

    def detail(self, key):
        return self.steps.get(key, {}).get("detail", {})

    @property
    def current_step(self):
        for key, _ in self.STEPS:
            if not self.is_done(key):
                return key
        return None

    @property
    def progress_percent(self):
        done = sum(1 for k, _ in self.STEPS if self.is_done(k))
        return int(done * 100 / len(self.STEPS))


# ---------------------------------------------------------------------------
#  VERROU — pour les vues de saisie de notes
# ---------------------------------------------------------------------------
def year_is_locked(school):
    """True dès que la mise à jour des archives de clôture a commencé."""
    return YearClosure.objects.filter(
        school_year=school.establishment_year,
        status__in=[YearClosure.Status.REFRESHING, YearClosure.Status.ARCHIVED,
                    YearClosure.Status.CLEANED, YearClosure.Status.CLOSED]
    ).exists()


"""
=============================================================================
 POINT D'ATTACHE UNIQUE DE L'ARCHIVAGE
=============================================================================
 Une seule classe, ArchiveRef, qui décrit « quelle unité d'archive ce
 document représente ». Elle se passe en argument facultatif à pdf_response,
 et sert aussi de garde anti-régénération pour les documents lourds.

 DEUX NIVEAUX D'USAGE
 ---------------------------------------------------------------------------
 1) STOCKAGE SEUL — une ligne, pour tous les documents (y compris ceux
    empaquetés dans un ZIP) :

        return pdf_response(pdf, "Liste_6emeA",
                            archive=ArchiveRef(DocType.CLASS_LIST, classroom))

    Le document est archivé au passage. Il sera régénéré à chaque
    téléchargement, ce qui est sans conséquence pour un document léger.

 2) STOCKAGE + CACHE — deux lignes, pour les documents COÛTEUX (bulletins,
    albums). La garde est placée AVANT toute génération :

        ref = ArchiveRef(DocType.BULLETIN, classroom, term_index=term)
        hit = ref.response(f"Bulletins_{classroom.code}")
        if hit:                       # archive à jour : rien à régénérer
            return hit
        pdf = ReportCard(data=...)    # génération seulement si nécessaire
        return pdf_response(pdf, f"Bulletins_{classroom.code}", archive=ref)

    C'est le seul endroit où l'on peut économiser la génération : une fois
    dans pdf_response, le PDF est déjà fabriqué.
=============================================================================
"""
class ArchiveRef:
    """Descripteur d'une unité d'archive, passé à pdf_response.

    doc_type    : valeur de DocType
    classroom   : ClassRoom ou None (None = document d'établissement)
    term_index  : 1, 2, 3 = trimestre ; 0 = annuel ; None = non périodique
    year        : année scolaire ; par défaut celle de l'établissement
    page_map    : {student_id: [page_debut, page_fin]} pour les bulletins
    user        : auteur, pour la traçabilité
    enabled     : mettre à False pour désactiver ponctuellement l'archivage
                  (aperçu, brouillon, test) sans changer l'appel
    """

    __slots__ = ("doc_type", "classroom", "term_index", "year",
                 "page_map", "user", "enabled", "_doc")

    def __init__(self, school, doc_type, classroom=None, term_index=None, *, year=None, page_map=None, user=None,
                 enabled=True):
        self.doc_type = doc_type
        self.classroom = classroom
        self.term_index = term_index
        self.year = year or school.establishment_year
        self.page_map = page_map
        self.user = user
        self.enabled = enabled
        self._doc = None

    # ------------------------------------------------------------------
    #  LECTURE — utilisée comme garde avant génération
    # ------------------------------------------------------------------
    def cached_bytes(self):
        """Contenu de l'archive si elle existe ET n'est pas périmée, sinon None."""
        if not self.enabled:
            return None
        from .services import find_archive
        doc = find_archive(self.year, self.doc_type, self.classroom, self.term_index)
        self._doc = doc
        if doc is None or doc.is_stale or not doc.file:
            return None
        try:
            doc.file.open("rb")
            data = doc.file.read()
            doc.file.close()
            return data or None
        except Exception:
            return None          # fichier illisible : on régénérera

    def response(self, filename):
        """Réponse HTTP servie depuis l'archive, ou None s'il faut générer.
        À appeler EN TÊTE de vue pour les documents coûteux."""
        data = self.cached_bytes()
        if data is None:
            return None
        return _pdf_http(data, filename, cache_hit=True)

    # ------------------------------------------------------------------
    #  ÉCRITURE — appelée par pdf_response
    # ------------------------------------------------------------------
    def store(self, data, page_count=0):
        """Crée ou met à jour l'archive avec le contenu fourni.
        Ne lève jamais : un incident d'archivage ne doit pas priver
        l'utilisateur de son document."""
        if not self.enabled or not data:
            return None
        try:
            from .services import find_archive, unit_title, default_filename, current_params
            doc = self._doc or find_archive(self.year, self.doc_type, self.classroom, self.term_index)
            if doc is None:
                doc = ArchivedDocument(
                    school_year=self.year, doc_type=self.doc_type, classroom=self.classroom, term_index=self.term_index)
            if doc.is_stale:
                doc.title = unit_title(self.doc_type, self.classroom, self.term_index)
                doc.classroom_label = self.classroom.code if self.classroom else doc.classroom_label
                doc.store(default_filename(self.doc_type, self.term_index), data, page_map=self.page_map,
                          page_count=page_count, user=self.user, params=current_params(self.doc_type, self.classroom,
                                                                                       self.term_index, self.year))
            self._doc = doc
            return doc
        except Exception:
            return None


# ---------------------------------------------------------------------------
#  Fabrique de réponse — partagée par ArchiveRef.response et pdf_response
# ---------------------------------------------------------------------------
def _pdf_http(data, filename, cache_hit=False):
    """Réponse identique à celle de osm.utils.pdf_response : même type,
    mêmes en-têtes, même gestion des noms accentués."""
    name = filename if str(filename).lower().endswith(".pdf") else f"{filename}.pdf"
    filename_ascii = name.encode('ascii', 'ignore').decode('ascii')
    quoted = quote(name)
    resp = FileResponse(BytesIO(data), as_attachment=True, filename=filename_ascii)
    resp['Content-Disposition'] = (
        f"attachment; filename='{filename_ascii}'; filename*=UTF-8''{quoted}"
    )
    #: repère de diagnostic : le document venait-il de l'archive ?
    resp['X-Archive'] = 'HIT' if cache_hit else 'MISS'
    return resp
