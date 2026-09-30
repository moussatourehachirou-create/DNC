"""Moteur des instruments : projections du graphe de planification.

Le PTA, le PPM et le plan de consommation des crédits (PCC) ne sont pas des données
saisies : ce sont des vues calculées à partir de la même photo. Ils ne peuvent donc
pas diverger (principe « une donnée saisie une fois »).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.engines.procurement import ProcurementLot, ProcurementRules, build_lots
from app.engines.snapshot import PlanningSnapshot


@dataclass(frozen=True)
class PtaRow:
    structure_id: str
    action_code: str | None
    result_label: str | None
    activity_id: str
    activity_label: str
    task_label: str
    resource_label: str
    quantity: str
    unit: str
    unit_price: int
    cost: int
    budget_line: str | None
    funding_source: str
    execution_mode: str
    quarter: int


@dataclass(frozen=True)
class PpmRow:
    lot_id: str
    structure_id: str
    category: str
    amount: int
    procedure: str
    launch_date: str
    need_date: str
    steps: tuple[tuple[str, str, str], ...]  # (libellé, début, fin)
    activity_ids: tuple[str, ...]


def build_pta(snapshot: PlanningSnapshot) -> list[PtaRow]:
    activities = {a.id: a for a in snapshot.activities}
    tasks = {t.id: t for t in snapshot.tasks}
    rows = []
    for line in snapshot.lines:
        activity = activities.get(line.activity_id)
        task = tasks.get(line.task_id)
        rows.append(
            PtaRow(
                structure_id=line.structure_id,
                action_code=activity.action_code if activity else None,
                result_label=activity.result_label if activity else None,
                activity_id=line.activity_id,
                activity_label=activity.label if activity else "",
                task_label=task.label if task else "",
                resource_label=line.label,
                quantity=str(line.quantity),
                unit=line.unit,
                unit_price=line.unit_price,
                cost=line.cost,
                budget_line=line.budget_line,
                funding_source=line.funding_source,
                execution_mode=line.execution_mode.value,
                quarter=line.quarter,
            )
        )
    task_order = {
        line.id: tasks[line.task_id].order if line.task_id in tasks else 0
        for line in snapshot.lines
    }
    ordered = sorted(
        zip(snapshot.lines, rows, strict=True),
        key=lambda pair: (
            pair[1].structure_id,
            pair[1].action_code or "",
            pair[1].activity_label,
            task_order[pair[0].id],
        ),
    )
    return [row for _, row in ordered]


def ppm_rows(lots: list[ProcurementLot]) -> list[PpmRow]:
    return [
        PpmRow(
            lot_id=lot.id,
            structure_id=lot.structure_id,
            category=lot.category,
            amount=lot.amount,
            procedure=lot.procedure.label,
            launch_date=lot.launch_date.isoformat(),
            need_date=lot.need_date.isoformat(),
            steps=tuple((s.label, s.start.isoformat(), s.end.isoformat()) for s in lot.steps),
            activity_ids=lot.activity_ids,
        )
        for lot in sorted(lots, key=lambda lot: (lot.launch_date, lot.id))
    ]


def build_ppm(snapshot: PlanningSnapshot, rules: ProcurementRules) -> list[PpmRow]:
    return ppm_rows(build_lots(snapshot, rules))


def consumption_plan(snapshot: PlanningSnapshot) -> dict[str, list[int]]:
    """Plan de consommation des crédits : montants par ligne budgétaire et par mois (12)."""
    plan: dict[str, list[int]] = defaultdict(lambda: [0] * 12)
    for line in snapshot.lines:
        key = line.budget_line or "non_impute"
        plan[key][line.need_month - 1] += line.cost
    return dict(sorted(plan.items()))


def totals(snapshot: PlanningSnapshot) -> dict[str, int]:
    """Totaux utiles aux tableaux de bord."""
    total = sum(line.cost for line in snapshot.lines)
    market = sum(line.market_amount for line in snapshot.lines)
    return {"total": total, "passe_en_marche": market, "execution_directe": total - market}
