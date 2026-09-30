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
from dataclasses import dataclass
from datetime import date, timedelta

from app.engines.budget_rules import Severity, Violation
from app.engines.snapshot import PlanningSnapshot, ResourceLine

UNCATEGORIZED = "non_categorise"


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
    """Référentiel de passation pour un exercice : seuils triés et étapes par procédure."""

    version: str
    thresholds: tuple[ProcedureThreshold, ...]
    steps: dict[str, tuple[ProcedureStep, ...]]

    def procedure_for(self, amount_ht: int) -> ProcedureThreshold:
        for threshold in self.thresholds:
            if threshold.max_amount_ht is None or amount_ht <= threshold.max_amount_ht:
                return threshold
        raise ValueError("aucune procédure ne couvre ce montant : référentiel incomplet")

    def lower_threshold_crossed(self, amount_ht: int) -> ProcedureThreshold | None:
        """Premier seuil franchi par le montant (utile pour détecter un fractionnement)."""
        for threshold in self.thresholds:
            if threshold.max_amount_ht is not None and amount_ht > threshold.max_amount_ht:
                return threshold
        return None


# Référentiel initial — Décret n° 2020-599 du 23 décembre 2020 (Bénin).
# Seuls les seuils de dispense (4 000 000 FCFA HT) et de demande de cotation
# (10 000 000 FCFA HT) ont été vérifiés. Les seuils supérieurs et les délais des étapes
# sont des valeurs provisoires À VALIDER avec le texte officiel et l'ARMP.
BENIN_2020_599_PROVISOIRE = ProcurementRules(
    version="decret-2020-599-provisoire",
    thresholds=(
        ProcedureThreshold("dispense", "Dispense de procédure", 4_000_000),
        ProcedureThreshold("demande_cotation", "Demande de cotation", 10_000_000),
        ProcedureThreshold("appel_offres", "Appel d'offres (à préciser)", None),
    ),
    steps={
        "dispense": (
            ProcedureStep("expression_besoin", "Expression du besoin", 5),
            ProcedureStep("bon_commande", "Bon de commande", 5),
        ),
        "demande_cotation": (
            ProcedureStep("dossier", "Préparation du dossier de cotation", 10),
            ProcedureStep("consultation", "Consultation des fournisseurs", 10),
            ProcedureStep("evaluation", "Ouverture et évaluation", 7),
            ProcedureStep("attribution", "Attribution et contrat", 8),
        ),
        "appel_offres": (
            ProcedureStep("dao", "Élaboration du DAO", 20),
            ProcedureStep("avis_dao", "Avis sur le DAO", 10),
            ProcedureStep("publication", "Publication et remise des offres", 30),
            ProcedureStep("evaluation", "Ouverture et évaluation des offres", 15),
            ProcedureStep("attribution", "Attribution, avis, approbation", 20),
            ProcedureStep("notification", "Signature et notification", 10),
        ),
    },
)


@dataclass(frozen=True)
class MarketNeed:
    line_id: str
    activity_id: str
    structure_id: str
    category: str
    amount: int
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
    amount: int
    procedure: ProcedureThreshold
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
        procedure = rules.procedure_for(amount)
        need_date = min(n.need_date for n in needs)
        launch, steps = schedule_backwards(need_date, rules.steps.get(procedure.code, ()))
        lots.append(
            ProcurementLot(
                id=f"{structure_id}:{category}",
                structure_id=structure_id,
                category=category,
                amount=amount,
                procedure=procedure,
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
    amount: int


def detect_fractionnement(lots: list[ManualLot], rules: ProcurementRules) -> list[Violation]:
    """Signale des lots homogènes qui passent chacun sous un seuil que leur cumul franchit."""
    groups: dict[tuple[str, str], list[ManualLot]] = defaultdict(list)
    for lot in lots:
        groups[(lot.structure_id, lot.category)].append(lot)

    violations = []
    for (structure_id, category), group in groups.items():
        if len(group) < 2:
            continue
        total = sum(lot.amount for lot in group)
        cumulative = rules.procedure_for(total)
        individual = {rules.procedure_for(lot.amount).code for lot in group}
        if individual != {cumulative.code}:
            violations.append(
                Violation(
                    code="fractionnement",
                    severity=Severity.BLOCKING,
                    message=(
                        f"Catégorie {category} découpée en {len(group)} lots pour "
                        f"{total:,} FCFA au total : le cumul relève de la procédure "
                        f"« {cumulative.label} »."
                    ).replace(",", " "),
                    structure_id=structure_id,
                )
            )
    return violations
