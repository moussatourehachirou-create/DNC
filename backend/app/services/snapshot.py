"""Construit la photo (`PlanningSnapshot`) d'une version à partir de la base."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.snapshot import (
    Activity,
    Envelope,
    ExecutionMode,
    PlanningSnapshot,
    ResourceLine,
    Task,
)
from app.models.entities import (
    EnvelopeRow,
    NodeLevel,
    PlanNode,
    PlanVersion,
    ResourceLineRow,
)

MODE_ALIASES = {
    "direct": ExecutionMode.DIRECT,
    "indirect": ExecutionMode.INDIRECT,
    "mixte": ExecutionMode.MIXTE,
}


def parse_mode(value: str | None) -> ExecutionMode:
    text = (value or "direct").lower()
    for key, mode in MODE_ALIASES.items():
        if key in text and not (key == "direct" and "indirect" in text):
            return mode
    return ExecutionMode.DIRECT


def build_snapshot(session: Session, version_id: str) -> PlanningSnapshot:
    version = session.get(PlanVersion, version_id)
    if version is None:
        raise LookupError(f"version {version_id} introuvable")

    nodes = {
        n.id: n for n in session.scalars(select(PlanNode).where(PlanNode.version_id == version_id))
    }

    def ancestor(node: PlanNode, level: NodeLevel) -> PlanNode | None:
        current: PlanNode | None = node
        while current is not None:
            if current.level == level:
                return current
            current = nodes.get(current.parent_id) if current.parent_id else None
        return None

    def activity_of(node: PlanNode) -> PlanNode:
        return ancestor(node, NodeLevel.ACTIVITE) or node

    activities: dict[str, Activity] = {}
    tasks: dict[str, Task] = {}
    for node in nodes.values():
        if node.level == NodeLevel.ACTIVITE:
            action = ancestor(node, NodeLevel.ACTION)
            result = ancestor(node, NodeLevel.RESULTAT)
            activities[node.id] = Activity(
                id=node.id,
                structure_id=node.organisation_id,
                label=node.label,
                action_code=action.code if action else None,
                result_label=result.label if result else None,
            )
        elif node.level == NodeLevel.TACHE:
            tasks[node.id] = Task(
                id=node.id,
                activity_id=activity_of(node).id,
                label=node.label,
                order=node.position,
            )

    rows = session.scalars(
        select(ResourceLineRow).join(PlanNode).where(PlanNode.version_id == version_id)
    )
    lines = []
    for row in rows:
        node = nodes[row.node_id]
        activity = activity_of(node)
        if activity.id not in activities:
            activities[activity.id] = Activity(
                activity.id, activity.organisation_id, activity.label
            )
        lines.append(
            ResourceLine(
                id=row.id,
                activity_id=activity.id,
                task_id=node.id,
                structure_id=row.organisation_id,
                label=row.label,
                quantity=row.quantity,
                unit=row.unit,
                unit_price=row.unit_price,
                frequency=row.frequency,
                budget_line=row.budget_line,
                funding_source=row.funding_source,
                execution_mode=parse_mode(row.execution_mode),
                market_share=row.market_share,
                market_category=row.market_category,
                need_month=row.need_month,
                tags=frozenset(row.tags or ()),
            )
        )

    envelopes = tuple(
        Envelope(e.organisation_id, e.budget_line, e.funding_source, e.authorized)
        for e in session.scalars(
            select(EnvelopeRow).where(EnvelopeRow.fiscal_year_id == version.fiscal_year_id)
        )
    )
    return PlanningSnapshot(
        fiscal_year=version.fiscal_year.year,
        activities=tuple(activities.values()),
        tasks=tuple(tasks.values()),
        lines=tuple(lines),
        envelopes=envelopes,
    )
