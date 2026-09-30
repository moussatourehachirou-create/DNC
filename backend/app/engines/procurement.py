"""Moteur de passation des marchés (Procurement Engine).

Chaîne (section 7.7) :
1. les lignes en mode indirect, et la part marché des lignes mixtes, deviennent des
   besoins de marché ;
2. les besoins homogènes sont regroupés en lots à l'échelle de la structure et de
   l'exercice (jamais activité par activité) : c'est ce qui prévient le fractionnement ;
3. la procédure est déterminée par le montant cumulé du lot et les seuils en vigueur ;
4. le calendrier est calculé à rebours depuis la date de besoin la plus précoce.

Seuils et délais sont des référentiels versionnés, jamais codés en dur dans la logique.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from app.engines.budget_rules import Severity, Violation
from app.engines.costing import to_fcfa
from app.engines.snapshot import PlanningSnapshot, ResourceLine

UNCATEGORIZED = "non_categorise"


class MarketType(StrEnum):
    """Types de marché tels qu'ils figurent dans les PPM (colonne « Type de marché »)."""

    TRAVAUX = "T"
    FOURNITURES = "F"
    SERVICES = "S"
    PRESTATIONS_INTELLECTUELLES = "PI"  # confiées à des cabinets, bureaux ou firmes
    CONSULTANT_INDIVIDUEL = "PI_IND"  # prestations intellectuelles, consultants individuels


class AuthorityScope(StrEnum):
    """Catégorie d'autorité contractante au sens du décret n° 2020-599."""

    ETAT = "etat"  # toutes autorités sauf communes sans statut particulier
    COMMUNE_SANS_STATUT = "commune_sans_statut_particulier"


@dataclass(frozen=True)
class ProcedureThreshold:
    """Procédure applicable jusqu'à `max_amount_ht` inclus (None = sans plafond)."""

    code: str
    label: str
    max_amount_ht: int | None


@dataclass(frozen=True)
class ProcedureStep:
    code: str
    label: str
    duration_days: int


@dataclass(frozen=True)
class ProcurementRules:
    """Référentiel de passation d'un exercice et d'une catégorie d'autorité.

    - `thresholds` : barème croissant de procédures par type de marché ;
    - `steps` : étapes et délais par code de procédure ;
    - `control_thresholds` : montant HT à partir duquel l'organe national (DNCMP)
      exerce le contrôle a priori ; en dessous, la cellule de contrôle (CCMP) ;
    - `community_thresholds` : seuils UEMOA imposant la publication communautaire ;
    - `category_types` : type de marché de chaque catégorie de besoin ;
    - les seuils s'appliquent aux montants HT : si les coûts programmés sont TTC,
      ils sont convertis avec `vat_rate`.
    """

    version: str
    thresholds: dict[MarketType, tuple[ProcedureThreshold, ...]]
    steps: dict[str, tuple[ProcedureStep, ...]]
    control_thresholds: dict[MarketType, int] = field(default_factory=dict)
    community_thresholds: dict[MarketType, int] = field(default_factory=dict)
    national_control_body: str = "DNCMP"
    local_control_body: str = "CCMP"
    category_types: dict[str, MarketType] = field(default_factory=dict)
    default_type: MarketType = MarketType.FOURNITURES
    costs_include_vat: bool = True
    vat_rate: Decimal = Decimal("0.18")

    def market_type_of(self, category: str) -> MarketType:
        return self.category_types.get(category, self.default_type)

    def to_ht(self, amount: int) -> int:
        if not self.costs_include_vat:
            return amount
        return to_fcfa(Decimal(amount) / (1 + self.vat_rate))

    def procedure_for(
        self, amount_ht: int, market_type: MarketType = MarketType.FOURNITURES
    ) -> ProcedureThreshold:
        for threshold in self.thresholds[market_type]:
            if threshold.max_amount_ht is None or amount_ht <= threshold.max_amount_ht:
                return threshold
        raise ValueError("aucune procédure ne couvre ce montant : référentiel incomplet")

    def control_body_for(self, amount_ht: int, market_type: MarketType) -> str:
        """Organe de contrôle a priori (art. 9 à 11 du décret n° 2020-599)."""
        ceiling = self.control_thresholds.get(market_type)
        if ceiling is not None and amount_ht >= ceiling:
            return self.national_control_body
        return self.local_control_body

    def requires_community_publication(self, amount_ht: int, market_type: MarketType) -> bool:
        """Publication de l'avis sur le site de l'UEMOA (art. 7 et 8)."""
        ceiling = self.community_thresholds.get(market_type)
        return ceiling is not None and amount_ht >= ceiling


_DISPENSE = ("dispense", "Dispense de procédure (3 devis)", 4_000_000)
_DC = ("DC", "Demande de cotation", 10_000_000)
_DRP = "Demande de renseignements et de prix"

# Étapes calquées sur les colonnes des PPM officiels (MESTFP, MIC 2025) pour que
# l'export remplisse directement le format attendu. Délais indicatifs, paramétrables.
_STEPS_DRP_AO = lambda publication: (  # noqa: E731
    ProcedureStep("reception_dossier", "Réception du dossier par l'organe de contrôle", 5),
    ProcedureStep("avis_dossier", "Avis de non-objection sur le dossier", 5),
    ProcedureStep("autorisation_lancement", "Autorisation de lancement", 3),
    ProcedureStep("publication", "Publication de l'avis", 2),
    ProcedureStep("ouverture_plis", "Ouverture des plis", publication),
    ProcedureStep("evaluation", "Évaluation des offres", 10),
    ProcedureStep("avis_evaluation", "Avis de non-objection sur l'évaluation", 5),
    ProcedureStep("examen_juridique", "Examen juridique du contrat", 5),
    ProcedureStep("approbation", "Approbation du contrat", 7),
    ProcedureStep("notification", "Notification du contrat", 3),
)

_STEPS = {
    "dispense": (
        ProcedureStep("devis", "Consultation de trois fournisseurs", 5),
        ProcedureStep("bon_commande", "Bon de commande et facture", 5),
    ),
    "DC": (
        ProcedureStep("dossier", "Préparation du dossier de cotation", 7),
        ProcedureStep("consultation", "Consultation des fournisseurs", 10),
        ProcedureStep("evaluation", "Ouverture et évaluation", 7),
        ProcedureStep("attribution", "Attribution et notification", 6),
    ),
    "DRP": _STEPS_DRP_AO(10),
    "AOO": _STEPS_DRP_AO(30),
    "AMI_DP": (
        ProcedureStep("ami", "Appel à manifestation d'intérêt", 30),
        ProcedureStep("evaluation_ami", "Évaluation des manifestations", 15),
        ProcedureStep("demande_propositions", "Demande de propositions", 30),
        ProcedureStep("evaluation_technique", "Évaluation technique", 15),
        ProcedureStep("evaluation_financiere", "Évaluation financière", 10),
        ProcedureStep("contrat", "Négociation, approbation, notification", 15),
    ),
    "SCI": (
        ProcedureStep("avis", "Avis de sélection de consultants individuels", 20),
        ProcedureStep("evaluation", "Comparaison des CV et évaluation", 15),
        ProcedureStep("contrat", "Négociation, approbation, notification", 15),
    ),
}

_CATEGORY_TYPES = {
    "impression": MarketType.SERVICES,
    "restauration": MarketType.SERVICES,
    "location_salle": MarketType.SERVICES,
    "entretien_locaux": MarketType.SERVICES,
    "maintenance": MarketType.SERVICES,
    "fournitures_bureau": MarketType.FOURNITURES,
    "materiel_informatique": MarketType.FOURNITURES,
    "mobilier": MarketType.FOURNITURES,
    "vehicules": MarketType.FOURNITURES,
    "carburant": MarketType.FOURNITURES,
    "construction": MarketType.TRAVAUX,
    "rehabilitation": MarketType.TRAVAUX,
    "etudes": MarketType.PRESTATIONS_INTELLECTUELLES,
    "consultants": MarketType.PRESTATIONS_INTELLECTUELLES,
    "consultant_individuel": MarketType.CONSULTANT_INDIVIDUEL,
}


def _decree_2020_599(
    scope: AuthorityScope,
    passation: dict[MarketType, int],
    control: dict[MarketType, int],
    community: dict[MarketType, int],
) -> ProcurementRules:
    """Barème du décret : dispense ≤ 4 M ; DC ≤ 10 M ; DRP jusqu'au seuil de passation
    (exclu) ; procédure du code des marchés à partir du seuil de passation (art. 1, 3 à 6)."""

    def scale(market_type: MarketType, above_code: str, above_label: str):
        return (
            ProcedureThreshold(*_DISPENSE),
            ProcedureThreshold(*_DC),
            ProcedureThreshold("DRP", _DRP, passation[market_type] - 1),
            ProcedureThreshold(above_code, above_label, None),
        )

    ao = ("AOO", "Appel d'offres ouvert")
    return ProcurementRules(
        version=f"decret-2020-599/{scope.value}",
        thresholds={
            MarketType.TRAVAUX: scale(MarketType.TRAVAUX, *ao),
            MarketType.FOURNITURES: scale(MarketType.FOURNITURES, *ao),
            MarketType.SERVICES: scale(MarketType.SERVICES, *ao),
            MarketType.PRESTATIONS_INTELLECTUELLES: scale(
                MarketType.PRESTATIONS_INTELLECTUELLES,
                "AMI_DP",
                "Appel à manifestation d'intérêt puis demande de propositions",
            ),
            MarketType.CONSULTANT_INDIVIDUEL: scale(
                MarketType.CONSULTANT_INDIVIDUEL, "SCI", "Sélection de consultants individuels"
            ),
        },
        steps=_STEPS,
        control_thresholds=control,
        community_thresholds=community,
        category_types=_CATEGORY_TYPES,
    )


T, F, S = MarketType.TRAVAUX, MarketType.FOURNITURES, MarketType.SERVICES
PI, PI_IND = MarketType.PRESTATIONS_INTELLECTUELLES, MarketType.CONSULTANT_INDIVIDUEL

# Décret n° 2020-599 du 23 décembre 2020 (Bénin), montants en FCFA HT.
# État et autorités contractantes autres que les communes sans statut particulier.
# Contrôle DNCMP : art. 9.1 (le cas des établissements publics dont le chef de cellule
# n'est pas délégué de contrôle relève de l'art. 9.2, à paramétrer par structure).
BENIN_2020_599_ETAT = _decree_2020_599(
    AuthorityScope.ETAT,
    passation={T: 100_000_000, F: 70_000_000, S: 70_000_000, PI: 50_000_000, PI_IND: 20_000_000},
    control={T: 500_000_000, F: 300_000_000, S: 300_000_000, PI: 200_000_000, PI_IND: 100_000_000},
    community={T: 1_000_000_000, F: 500_000_000, S: 500_000_000, PI: 150_000_000,
               PI_IND: 150_000_000},
)  # fmt: skip

# Communes sans statut particulier (art. 3 al. 2 et art. 9.2).
BENIN_2020_599_COMMUNE = _decree_2020_599(
    AuthorityScope.COMMUNE_SANS_STATUT,
    passation={T: 35_000_000, F: 25_000_000, S: 25_000_000, PI: 20_000_000, PI_IND: 15_000_000},
    control={T: 300_000_000, F: 150_000_000, S: 150_000_000, PI: 120_000_000, PI_IND: 80_000_000},
    community={T: 1_000_000_000, F: 500_000_000, S: 500_000_000, PI: 150_000_000,
               PI_IND: 150_000_000},
)  # fmt: skip

# Référentiel par défaut.
BENIN_2020_599 = BENIN_2020_599_ETAT


@dataclass(frozen=True)
class MarketNeed:
    line_id: str
    activity_id: str
    structure_id: str
    category: str
    amount: int  # montant programmé (TTC si les coûts incluent la TVA)
    need_date: date


@dataclass(frozen=True)
class ScheduledStep:
    code: str
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class ProcurementLot:
    id: str
    structure_id: str
    category: str
    market_type: MarketType
    amount: int
    amount_ht: int
    procedure: ProcedureThreshold
    control_body: str
    community_publication: bool
    need_date: date
    launch_date: date
    steps: tuple[ScheduledStep, ...]
    needs: tuple[MarketNeed, ...]

    @property
    def activity_ids(self) -> tuple[str, ...]:
        return tuple(sorted({n.activity_id for n in self.needs}))


def need_date_of(line: ResourceLine, fiscal_year: int) -> date:
    return date(fiscal_year, line.need_month, 1)


def market_needs(snapshot: PlanningSnapshot) -> list[MarketNeed]:
    needs = []
    for line in snapshot.lines:
        amount = line.market_amount
        if amount <= 0:
            continue
        needs.append(
            MarketNeed(
                line_id=line.id,
                activity_id=line.activity_id,
                structure_id=line.structure_id,
                category=line.market_category or UNCATEGORIZED,
                amount=amount,
                need_date=need_date_of(line, snapshot.fiscal_year),
            )
        )
    return needs


def schedule_backwards(
    need_date: date, steps: tuple[ProcedureStep, ...]
) -> tuple[date, tuple[ScheduledStep, ...]]:
    """Place les étapes à rebours pour que la dernière se termine à la date de besoin."""
    scheduled: list[ScheduledStep] = []
    end = need_date
    for step in reversed(steps):
        start = end - timedelta(days=step.duration_days)
        scheduled.append(ScheduledStep(step.code, step.label, start, end))
        end = start
    scheduled.reverse()
    return end, tuple(scheduled)


def build_lots(snapshot: PlanningSnapshot, rules: ProcurementRules) -> list[ProcurementLot]:
    """Regroupe les besoins par structure et catégorie sur tout l'exercice."""
    groups: dict[tuple[str, str], list[MarketNeed]] = defaultdict(list)
    for need in market_needs(snapshot):
        groups[(need.structure_id, need.category)].append(need)

    lots = []
    for (structure_id, category), needs in sorted(groups.items()):
        amount = sum(n.amount for n in needs)
        market_type = rules.market_type_of(category)
        amount_ht = rules.to_ht(amount)
        procedure = rules.procedure_for(amount_ht, market_type)
        need_date = min(n.need_date for n in needs)
        launch, steps = schedule_backwards(need_date, rules.steps.get(procedure.code, ()))
        lots.append(
            ProcurementLot(
                id=f"{structure_id}:{category}",
                structure_id=structure_id,
                category=category,
                market_type=market_type,
                amount=amount,
                amount_ht=amount_ht,
                procedure=procedure,
                control_body=rules.control_body_for(amount_ht, market_type),
                community_publication=rules.requires_community_publication(amount_ht, market_type),
                need_date=need_date,
                launch_date=launch,
                steps=steps,
                needs=tuple(sorted(needs, key=lambda n: (n.need_date, n.line_id))),
            )
        )
    return lots


def check_lots(
    lots: list[ProcurementLot], fiscal_year: int, today: date | None = None
) -> list[Violation]:
    """Alertes de calendrier et besoins non catégorisés."""
    violations: list[Violation] = []
    year_start = date(fiscal_year, 1, 1)
    for lot in lots:
        line_ids = tuple(n.line_id for n in lot.needs)
        if lot.category == UNCATEGORIZED:
            violations.append(
                Violation(
                    code="besoin_non_categorise",
                    severity=Severity.BLOCKING,
                    message="Besoins de marché sans catégorie : regroupement impossible.",
                    structure_id=lot.structure_id,
                    line_ids=line_ids,
                )
            )
        if today is not None and lot.launch_date < today:
            violations.append(
                Violation(
                    code="lancement_depasse",
                    severity=Severity.APPROVAL,
                    message=(
                        f"Lot {lot.category} : lancement requis le {lot.launch_date:%d/%m/%Y}, "
                        "date déjà dépassée."
                    ),
                    structure_id=lot.structure_id,
                    line_ids=line_ids,
                )
            )
        elif lot.launch_date < year_start:
            violations.append(
                Violation(
                    code="lancement_avant_exercice",
                    severity=Severity.WARNING,
                    message=(
                        f"Lot {lot.category} : lancement requis le {lot.launch_date:%d/%m/%Y}, "
                        "avant l'ouverture de l'exercice ; décaler le besoin ou anticiper."
                    ),
                    structure_id=lot.structure_id,
                    line_ids=line_ids,
                )
            )
    return violations


@dataclass(frozen=True)
class ManualLot:
    """Lot tel que découpé manuellement par la PRMP, pour contrôle du fractionnement."""

    id: str
    structure_id: str
    category: str
    amount_ht: int
    market_type: MarketType = MarketType.FOURNITURES


def detect_fractionnement(lots: list[ManualLot], rules: ProcurementRules) -> list[Violation]:
    """Signale des lots homogènes qui passent chacun sous un seuil que leur cumul franchit."""
    groups: dict[tuple[str, str], list[ManualLot]] = defaultdict(list)
    for lot in lots:
        groups[(lot.structure_id, lot.category)].append(lot)

    violations = []
    for (structure_id, category), group in groups.items():
        if len(group) < 2:
            continue
        market_type = group[0].market_type
        total = sum(lot.amount_ht for lot in group)
        cumulative = rules.procedure_for(total, market_type)
        individual = {rules.procedure_for(lot.amount_ht, market_type).code for lot in group}
        if individual != {cumulative.code}:
            violations.append(
                Violation(
                    code="fractionnement",
                    severity=Severity.BLOCKING,
                    message=(
                        f"Catégorie {category} découpée en {len(group)} lots pour "
                        f"{total:,} FCFA HT au total : le cumul relève de la procédure "
                        f"« {cumulative.label} »."
                    ).replace(",", " "),
                    structure_id=structure_id,
                )
            )
    return violations
