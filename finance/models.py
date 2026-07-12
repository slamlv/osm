from django.db import models, transaction
from django.db.models import Sum
from authentification.models import User
from student.models import Student
from staff.models import Personnel
from django.utils import timezone

# -*- coding: utf-8 -*-
"""
=============================================================================
 MODULE FINANCIER OSM — Modélisation (v1)
=============================================================================
 Principes de conception validés ensemble :

 1. GRILLE UNIFIÉE : un même système exprime le public (APEE, montant unique)
    et le privé (scolarité par niveau) grâce au niveau OPTIONNEL sur la grille
    (level=None => tous les niveaux). Les frais annexes (inscription, tenue,
    examens blancs...) sont juste des types de frais supplémentaires.

 2. HORS CAISSE : FeeType.affects_cashbox=False pour les fonds collectés puis
    reversés à l'État (Frais exigibles, Frais d'examen). Suivis et pointés
    (solvables/insolvables) mais JAMAIS comptés dans le solde.

 3. TRANCHES = JALONS : les tranches (montant + date limite) sont définies sur
    la grille, mais un paiement n'est JAMAIS rattaché à une tranche. Paiements
    partiels libres ; le retard s'évalue en comparant le CUMUL payé au CUMUL
    des jalons échus. (APEE : aucune tranche définie = dû à l'année.)

 4. CAISSE UNIQUE : un solde de départ (fonds existants à l'adoption d'OSM)
    + les mouvements. Le solde est CALCULÉ, jamais stocké. Le mode de paiement
    (Espèces / OM / MoMo / ...) est un attribut de chaque mouvement -> états
    par canal sans multiplier les comptes.

 5. INTÉGRITÉ FINANCIÈRE : aucune suppression de paiement/transaction.
    Annulation tracée (motif, auteur, date). Reçus numérotés en séquence.

 6. S'APPUIE SUR L'EXISTANT : le dû d'un élève se déduit de son inscription
    de l'année (StudentEnrollment -> classe -> niveau -> ligne de grille).
    Rien n'est dupliqué.

 NB : `level` ci-dessous est un CharField avec les mêmes valeurs que le niveau
 de tes ClassRoom — À ALIGNER sur ta modélisation réelle du niveau (champ
 choices ? modèle ?). Point ouvert signalé.
=============================================================================
"""


# ---------------------------------------------------------------------------
#  MODES DE PAIEMENT (partagés paiements élèves & transactions)
# ---------------------------------------------------------------------------
class PaymentMethod(models.TextChoices):
    CASH     = "Espèces", "Espèces"
    OM       = "Orange Money", "Orange Money"
    MOMO     = "MTN MoMo", "MTN Mobile Money"
    VIREMENT = "Virement", "Virement bancaire"
    CHEQUE   = "Chèque", "Chèque"


# ---------------------------------------------------------------------------
#  1. TYPES DE FRAIS
# ---------------------------------------------------------------------------
class FeeType(models.Model):
    """Type de frais paramétrable par l'établissement.
    Exemples : APEE (public) ; Scolarité, Inscription (privé) ;
    Frais exigibles, Frais d'examen (affects_cashbox=False : reversés à l'État,
    suivis mais hors trésorerie)."""
    nom = models.CharField(max_length=60, unique=True)
    affects_cashbox = models.BooleanField(
        default=True,
        help_text="Décocher pour les fonds collectés puis reversés à l'État "
                  "(frais exigibles, frais d'examen) : suivis mais hors caisse.")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.nom

    class Meta:
        db_table = '"FeeType"'


# ---------------------------------------------------------------------------
#  2. GRILLE TARIFAIRE (le coeur du système unifié)
# ---------------------------------------------------------------------------
class SchoolFee(models.Model):
    """Montant d'un type de frais pour une année scolaire.
    level=None => s'applique à TOUS les niveaux (cas APEE).
    Une ligne par niveau => tarification par niveau (cas scolarité privée,
    frais d'examen limités aux classes d'examen : pas de ligne = pas concerné)."""
    fee_type = models.ForeignKey(FeeType, on_delete=models.PROTECT,
                                 related_name="fees")
    school_year = models.CharField(max_length=9, db_index=True)   # ex "2025-2026"
    # Niveau PUR, aligné sur Class.niveau ("Sixième", "Terminale"...).
    # - Vide = tous les niveaux (cas APEE).
    # - Une ligne "Terminale" couvre TOUTES les séries (A4, C, D...) d'un coup.
    # - PRIORITÉ : si une ligne "tous niveaux" ET une ligne spécifique existent
    #   pour le même frais, la ligne SPÉCIFIQUE prime (permet "APEE 25 000
    #   pour tous, sauf Terminale 20 000").
    # - Résolution pour un élève : student.classe.classe.niveau
    #   (ClassRoom -> Class -> .niveau)
    # - Le form proposera les niveaux existants dynamiquement :
    #   Class.objects.values_list('niveau', flat=True).distinct()
    level = models.CharField(max_length=15, null=True, blank=True,
                             help_text="Vide = tous les niveaux")
    # Série (spécialité), alignée sur Class.serie ("C", "D", "A4"...).
    # Permet les frais propres à certaines spécialités (ex. frais de
    # LABORATOIRE pour les séries scientifiques). CASCADE DE SPÉCIFICITÉ :
    #   1. level + serie   ("Terminale" + "C")   <- la plus spécifique, prime
    #   2. level seul      ("Terminale", toutes séries)
    #   3. rien            (tous les niveaux)
    # Résolution élève : niveau = student.classe.classe.niveau
    #                    serie  = student.classe.classe.serie
    serie = models.CharField(max_length=10, null=True, blank=True,
                             help_text="Vide = toutes les séries du niveau")
    amount = models.PositiveIntegerField(help_text="Montant total (FCFA)")

    class Meta:
        db_table = '"SchoolFee"'
        unique_together = ("fee_type", "school_year", "level", "serie")

    def __str__(self):
        lvl = self.level or "Tous niveaux"
        if self.serie:
            lvl += f" {self.serie}"
        return f"{self.fee_type} {self.school_year} [{lvl}] : {self.amount}"

    @property
    def specificity(self):
        """Score de spécificité d'une ligne de grille :
        2 = niveau + série ; 1 = niveau seul ; 0 = tous niveaux."""
        if self.level and self.serie:
            return 2
        if self.level:
            return 1
        return 0


class FeeInstallment(models.Model):
    """Jalon de paiement (tranche) d'une ligne de grille. PUREMENT INDICATIF
    pour l'évaluation des retards : les paiements ne s'y rattachent pas.
    La somme des jalons doit égaler SchoolFee.amount (validé au form)."""
    school_fee = models.ForeignKey(SchoolFee, on_delete=models.CASCADE,
                                   related_name="installments")
    label = models.CharField(max_length=40)          # "1ère tranche"
    amount = models.PositiveIntegerField()
    due_date = models.DateField()

    class Meta:
        db_table = '"FeeInstallment"'
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.label} • {self.amount} • {self.due_date:%d/%m/%Y}"


# ---------------------------------------------------------------------------
#  3. REMISES / EXONÉRATIONS
# ---------------------------------------------------------------------------
class FeeDiscount(models.Model):
    """Remise individuelle : enfants d'enseignants, bourses, cas sociaux...
    Le dû NET d'un élève = grille (son niveau) - ses remises."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE,
                                related_name="fee_discounts")
    fee_type = models.ForeignKey(FeeType, on_delete=models.PROTECT)
    school_year = models.CharField(max_length=9, db_index=True)
    amount = models.PositiveIntegerField(help_text="Remise en FCFA")
    reason = models.CharField(max_length=120)
    granted_by = models.ForeignKey(User,
                                   on_delete=models.SET_NULL, null=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = '"FeeDiscount"'
        unique_together = ("student", "fee_type", "school_year")


# ---------------------------------------------------------------------------
#  4. PAIEMENTS ÉLÈVES
# ---------------------------------------------------------------------------
class StudentPayment(models.Model):
    """Encaissement d'un élève : montant LIBRE (avances possibles), imputé au
    cumul de (élève, type de frais, année). Reçu numéroté. Jamais supprimé :
    annulation tracée."""
    student = models.ForeignKey(Student, on_delete=models.PROTECT,
                                related_name="payments")
    fee_type = models.ForeignKey(FeeType, on_delete=models.PROTECT)
    school_year = models.CharField(max_length=9, db_index=True)
    amount = models.PositiveIntegerField()
    method = models.CharField(max_length=20, choices=PaymentMethod.choices,
                              default=PaymentMethod.CASH)
    date = models.DateField(default=timezone.localdate)
    receipt_number = models.CharField(max_length=20, unique=True, editable=False)
    received_by = models.ForeignKey(User,
                                    on_delete=models.SET_NULL, null=True,
                                    related_name="payments_received")
    note = models.CharField(max_length=120, blank=True, default="")

    # --- annulation tracée (jamais de suppression) ---
    cancelled = models.BooleanField(default=False)
    cancel_reason = models.CharField(max_length=120, blank=True, default="")
    cancelled_by = models.ForeignKey(User,
                                     on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = '"StudentPayment"'
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["school_year", "fee_type"])]

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = self._next_receipt_number()
        super().save(*args, **kwargs)

    @classmethod
    def _next_receipt_number(cls):
        """Numérotation séquentielle par année civile : REC-2026-00042.
        select_for_update sous transaction pour éviter les doublons en
        cas d'encaissements simultanés."""
        year = timezone.localdate().year
        prefix = f"REC-{year}-"
        with transaction.atomic():
            last = (cls.objects.select_for_update()
                    .filter(receipt_number__startswith=prefix)
                    .order_by("-receipt_number").first())
            n = int(last.receipt_number.split("-")[-1]) + 1 if last else 1
            return f"{prefix}{n:05d}"


# ---------------------------------------------------------------------------
#  5. TRÉSORERIE (caisse unique)
# ---------------------------------------------------------------------------
class CashBox(models.Model):
    """Singleton par établissement (par tenant) : le point de départ de la
    trésorerie. Le SOLDE N'EST JAMAIS STOCKÉ : il se calcule
      solde(T) = opening_balance
               + Σ StudentPayment (fee_type.affects_cashbox, non annulés, date<=T)
               + Σ Transaction recettes (non annulées, date<=T)
               - Σ Transaction dépenses (non annulées, date<=T)
    -> toujours juste, infalsifiable, auditable."""
    opening_balance = models.IntegerField(
        default=0, help_text="Fonds existants à l'adoption de la plateforme")
    opening_date = models.DateField(default=timezone.localdate)

    def save(self, *args, **kwargs):
        self.pk = 1          # singleton
        super().save(*args, **kwargs)

    class Meta:
        db_table = '"CashBox"'

    @classmethod
    def cashbox_balance(cls, at=None):
        """Solde de la caisse à la date `at` (incluse). 3 agrégats SQL.
        Seuls comptent : paiements des frais qui AFFECTENT la caisse, non annulés ;
        transactions non annulées."""
        box = CashBox.objects.first()
        opening, opening_date = (box.opening_balance, box.opening_date) if box else (0, None)

        pay_qs = StudentPayment.objects.filter(cancelled=False,
                                               fee_type__affects_cashbox=True)
        inc_qs = Transaction.objects.filter(cancelled=False,
                                            kind=TransactionCategory.Kind.INCOME)
        exp_qs = Transaction.objects.filter(cancelled=False,
                                            kind=TransactionCategory.Kind.EXPENSE)
        if opening_date:
            pay_qs = pay_qs.filter(date__gte=opening_date)
            inc_qs = inc_qs.filter(date__gte=opening_date)
            exp_qs = exp_qs.filter(date__gte=opening_date)
        if at:
            pay_qs = pay_qs.filter(date__lte=at)
            inc_qs = inc_qs.filter(date__lte=at)
            exp_qs = exp_qs.filter(date__lte=at)

        s = lambda qs: qs.aggregate(t=Sum("amount"))["t"] or 0
        return opening + s(pay_qs) + s(inc_qs) - s(exp_qs)

    @classmethod
    def cash_journal(cls, date_from, date_to):
        """Chronologie unifiée des mouvements de caisse sur la période :
        paiements élèves (en caisse) + recettes + dépenses, avec solde courant.
        Renvoie (solde_initial, [entrées datées], solde_final)."""
        opening = CashBox.cashbox_balance(at=date_from) - CashBox._day_total(date_from)  # solde AVANT le 1er jour

        entries = []
        for p in (StudentPayment.objects
                .filter(cancelled=False, fee_type__affects_cashbox=True,
                        date__range=(date_from, date_to))
                .select_related("student", "fee_type")):
            entries.append({"date": p.date, "sens": +1, "montant": p.amount,
                            "libelle": f"{p.fee_type} — {p.student}",
                            "methode": p.method, "ref": p.receipt_number})
        for t in (Transaction.objects
                .filter(cancelled=False, date__range=(date_from, date_to))
                .select_related("category", "beneficiary")):
            sens = +1 if t.kind == TransactionCategory.Kind.INCOME else -1
            lib = t.description + (f" — {t.beneficiary}" if t.beneficiary else "")
            entries.append({"date": t.date, "sens": sens, "montant": t.amount,
                            "libelle": lib, "methode": t.method, "ref": t.reference})

        entries.sort(key=lambda e: e["date"])
        solde = opening
        for e in entries:
            solde += e["sens"] * e["montant"]
            e["solde"] = solde
        return opening, entries, solde

    @classmethod
    def _day_total(cls, day):
        """Total signé des mouvements du jour `day` (aide interne au journal)."""
        s = lambda qs: qs.aggregate(t=Sum("amount"))["t"] or 0
        pays = s(StudentPayment.objects.filter(cancelled=False, date=day,
                                               fee_type__affects_cashbox=True))
        inc = s(Transaction.objects.filter(cancelled=False, date=day,
                                           kind=TransactionCategory.Kind.INCOME))
        exp = s(Transaction.objects.filter(cancelled=False, date=day,
                                           kind=TransactionCategory.Kind.EXPENSE))
        return pays + inc - exp


class TransactionCategory(models.Model):
    """Catégories paramétrables de mouvements divers.
    Recettes : Subvention, Don, Location... Dépenses : Salaires vacataires,
    Fournitures, Entretien, Eau/Électricité, Transport..."""
    class Kind(models.TextChoices):
        INCOME  = "RECETTE", "Recette"
        EXPENSE = "DEPENSE", "Dépense"

    nom = models.CharField(max_length=60, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nom} ({self.get_kind_display()})"

    class Meta:
        db_table = '"TransactionCategory"'


class Transaction(models.Model):
    """Mouvement de caisse HORS paiements élèves : dépenses (salaires des
    vacataires via `beneficiary`, factures, fournitures...) et recettes
    diverses (subventions, dons...). Même règle : annulation tracée."""
    category = models.ForeignKey(TransactionCategory, on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=TransactionCategory.Kind.choices,
                            editable=False)   # dénormalisé depuis category (filtres rapides)
    amount = models.PositiveIntegerField()
    date = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=160)
    beneficiary = models.ForeignKey(Personnel, on_delete=models.SET_NULL,
                                    null=True, blank=True,
                                    help_text="Pour les salaires : l'enseignant payé")
    method = models.CharField(max_length=20, choices=PaymentMethod.choices,
                              default=PaymentMethod.CASH)
    reference = models.CharField(max_length=60, blank=True, default="",
                                 help_text="N° de pièce / facture")
    created_by = models.ForeignKey(User,
                                   on_delete=models.SET_NULL, null=True)

    cancelled = models.BooleanField(default=False)
    cancel_reason = models.CharField(max_length=120, blank=True, default="")
    cancelled_by = models.ForeignKey(User,
                                     on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = '"Transaction"'
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        self.kind = self.category.kind      # cohérence garantie
        super().save(*args, **kwargs)
