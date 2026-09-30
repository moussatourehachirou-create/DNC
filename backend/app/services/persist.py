"""Enregistre un aperçu d'import validé dans l'arbre de planification."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    FiscalYear,
    PlanNode,
    PlanVersion,
    ResourceLineRow,
    VersionKind,
)
from app.services.classify import market_category, normalize_mode
from app.services.pta_import import ImportPreview, forfait_lines


def get_or_create_year(session: Session, organisation_id: str, year: int) -> FiscalYear:
    existing = session.scalar(
        select(FiscalYear).where(
            FiscalYear.organisation_id == organisation_id, FiscalYear.year == year
        )
    )
    if existing:
        return existing
    fiscal_year = FiscalYear(organisation_id=organisation_id, year=year)
    session.add(fiscal_year)
    session.flush()
    return fiscal_year


def save_import(
    session: Session,
    preview: ImportPreview,
    organisation_id: str,
    year: int,
    label: str,
) -> PlanVersion:
    """Crée une version et y recopie les nœuds et les lignes forfaitaires de l'aperçu."""
    fiscal_year = get_or_create_year(session, organisation_id, year)
    version = PlanVersion(
        organisation_id=organisation_id,
        fiscal_year_id=fiscal_year.id,
        label=label,
        kind=VersionKind.INITIALE,
    )
    session.add(version)
    session.flush()

    ids: dict[str, str] = {}
    positions: dict[str | None, int] = {}
    for parsed in preview.nodes:
        position = positions.get(parsed.parent_code, 0) + 1
        positions[parsed.parent_code] = position
        node = PlanNode(
            organisation_id=organisation_id,
            version_id=version.id,
            parent_id=ids.get(parsed.parent_code) if parsed.parent_code else None,
            level=parsed.level,
            position=position,
            code=parsed.code,
            label=parsed.label,
            imputation=parsed.imputation,
            start_month=parsed.start_month,
            end_month=parsed.end_month,
            weight=parsed.weight,
            responsible=parsed.responsible,
            associated=parsed.associated,
            execution_mode=normalize_mode(parsed.execution_mode) if parsed.execution_mode else None,
            amounts=parsed.amounts or None,
            attributes=parsed.attributes or None,
            observations=parsed.observations,
            origin="import",
        )
        session.add(node)
        session.flush()
        ids[parsed.code] = node.id

    for line in forfait_lines(preview):
        mode = normalize_mode(line.execution_mode)
        session.add(
            ResourceLineRow(
                organisation_id=organisation_id,
                node_id=ids[line.node_code],
                label=line.label,
                quantity=Decimal(1),
                unit="forfait",
                unit_price=line.amount,
                price_source="import",
                budget_line=line.budget_line,
                funding_source=line.funding_source,
                execution_mode=mode,
                market_share=Decimal("0.5") if mode == "mixte" else Decimal(0),
                market_category=market_category(line.label) if mode != "direct" else None,
                need_month=line.need_month,
            )
        )
    session.flush()
    return version
