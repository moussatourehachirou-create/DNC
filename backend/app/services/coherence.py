"""Contrôle de cohérence d'une version enregistrée et application des corrections."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.coherence import CoherenceNode, CoherenceReport, Fix, check, raise_amount
from app.engines.costing import line_cost
from app.models.entities import PlanNode, ResourceLineRow


def load_nodes(session: Session, version_id: str) -> list[CoherenceNode]:
    rows = session.scalars(select(PlanNode).where(PlanNode.version_id == version_id)).all()
    lines = session.scalars(
        select(ResourceLineRow).join(PlanNode).where(PlanNode.version_id == version_id)
    ).all()
    costs: dict[str, dict[str, int]] = {}
    for line in lines:
        by_source = costs.setdefault(line.node_id, {})
        cost = line_cost(line.quantity, line.unit_price, line.frequency)
        by_source[line.funding_source] = by_source.get(line.funding_source, 0) + cost
    return [
        CoherenceNode(
            id=n.id,
            parent_id=n.parent_id,
            level=n.level,
            label=n.label,
            code=n.code,
            amounts=n.amounts or None,
            lines_cost=costs.get(n.id, {}),
            start_month=n.start_month,
            end_month=n.end_month,
            weight=n.weight,
            responsible=n.responsible,
            validator=(n.attributes or {}).get("validateur"),
            indicator=(n.attributes or {}).get("indicateur"),
        )
        for n in rows
    ]


def run(session: Session, version_id: str) -> CoherenceReport:
    return check(load_nodes(session, version_id))


PER_CODE_LIMIT = 50


def report_json(report: CoherenceReport) -> dict:
    """Rapport sérialisé ; le détail est limité à `PER_CODE_LIMIT` anomalies par type."""
    by_code: dict[str, dict] = {}
    findings = []
    for f in report.findings:
        group = by_code.setdefault(f.code, {"severity": f.severity.value, "count": 0})
        group["count"] += 1
        if group["count"] <= PER_CODE_LIMIT:
            findings.append(
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "node_id": f.node_id,
                    "message": f.message,
                    "fix": asdict(f.fix) if f.fix else None,
                }
            )
    return {
        "counts": report.counts(),
        "by_code": by_code,
        "findings": findings,
        "weight_rates": report.weight_rates,
    }


def apply_fix(session: Session, version_id: str, fix: Fix) -> list[str]:
    """Applique une correction proposée ; retourne les identifiants des nœuds modifiés."""
    node = session.get(PlanNode, fix.node_id)
    if node is None or node.version_id != version_id:
        raise ValueError("nœud introuvable dans cette version")
    if fix.kind == "align_period":
        node.start_month, node.end_month = fix.start_month, fix.end_month
        return [node.id]
    if not fix.source or not fix.amount or fix.amount <= 0:
        raise ValueError("source et montant positifs requis")
    if fix.kind == "raise_ae":
        amounts = {k: dict(v) for k, v in (node.amounts or {}).items()}
        amounts.setdefault("AE", {})[fix.source] = fix.amount
        node.amounts = amounts
        return [node.id]
    if fix.kind == "raise_amount":
        changed = raise_amount(load_nodes(session, version_id), node.id, fix.source, fix.amount)
        for node_id, amounts in changed.items():
            session.get(PlanNode, node_id).amounts = amounts
        return list(changed)
    raise ValueError(f"correction inconnue : {fix.kind}")
