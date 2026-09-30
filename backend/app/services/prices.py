"""Chargement et consultation du référentiel de prix de BIE (issu de l'e-répertoire)."""

from __future__ import annotations

import csv
import gzip
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import PriceEdition, PriceItem
from app.services.price_import import RprArticle

REFERENTIALS = Path(__file__).resolve().parent.parent / "referentials"
BUNDLED_EDITION = ("e-Répertoire des prix de référence v26.3 (19e édition, juin 2026)",
                   "e_repertoire_v26_3.csv.gz")  # fmt: skip


def price_for_basis(item: PriceItem, basis: str | None) -> int | None:
    """Prix d'un article selon la borne choisie par l'utilisateur (BI ou BS).

    Un article sans fourchette (import Excel/CSV à prix unique) garde son prix. Sans
    choix de borne, aucun prix n'est imposé : la décision revient à l'utilisateur.
    """
    if item.price_min is None or item.price_max is None:
        return item.unit_price
    if basis == "bi":
        return item.price_min
    if basis == "bs":
        return item.price_max
    return None


def bundled_rows() -> list[dict]:
    with gzip.open(REFERENTIALS / BUNDLED_EDITION[1], "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def load_edition(
    session: Session, label: str, articles: list[RprArticle] | list[dict]
) -> PriceEdition:
    """Crée une édition active à partir d'articles extraits (PDF) ou de lignes CSV."""
    edition = PriceEdition(label=label, status="active")
    session.add(edition)
    session.flush()
    items = []
    for a in articles:
        if isinstance(a, dict):
            bi, bs = int(a["prix_bi"]), int(a["prix_bs"])
            code, nature, label_, unit = a["code"], a["nature"], a["designation"], a["unite"]
            family, specs = a.get("famille"), a.get("specifications")
        else:
            bi, bs = a.price_min, a.price_max
            code, nature, label_, unit = a.code, a.nature, a.label, a.unit
            family, specs = getattr(a, "family", None), getattr(a, "specs", None)
        items.append(
            PriceItem(
                edition_id=edition.id,
                source="repertoire",
                code=code,
                nature=nature,
                label=label_,
                unit=unit,
                unit_price=None,
                price_min=bi,
                price_max=bs,
                category=family or None,
                specifications=specs or None,
            )
        )
    session.add_all(items)
    # Une seule édition active : les précédentes passent en archive.
    for previous in session.scalars(
        select(PriceEdition).where(PriceEdition.id != edition.id, PriceEdition.status == "active")
    ):
        previous.status = "archivee"
    session.flush()
    return edition


def load_bundled_edition(session: Session) -> PriceEdition:
    existing = session.scalar(select(PriceEdition).where(PriceEdition.label == BUNDLED_EDITION[0]))
    if existing:
        session.execute(delete(PriceItem).where(PriceItem.edition_id == existing.id))
        session.delete(existing)
        session.flush()
    return load_edition(session, BUNDLED_EDITION[0], bundled_rows())


def check_price_ranges(session: Session, version_id: str) -> list:
    """Lignes dont le prix unitaire sort de la fourchette [BI, BS] de leur article."""
    from app.engines.budget_rules import Severity, Violation
    from app.engines.costing import PriceRange, check_against_range
    from app.models.entities import PlanNode, ResourceLineRow

    rows = session.execute(
        select(ResourceLineRow, PriceItem)
        .join(PlanNode, PlanNode.id == ResourceLineRow.node_id)
        .join(PriceItem, PriceItem.code == ResourceLineRow.price_reference)
        .where(PlanNode.version_id == version_id, PriceItem.price_min.is_not(None))
    ).all()
    violations = []
    seen: set[str] = set()
    for line, item in rows:
        if line.id in seen:
            continue
        seen.add(line.id)
        anomaly = check_against_range(
            line.unit_price, PriceRange(item.code, item.price_min, item.price_max)
        )
        if anomaly:
            violations.append(
                Violation(
                    code="prix_hors_fourchette",
                    severity=Severity.APPROVAL,
                    message=f"« {line.label[:60]} » : {anomaly.explanation}",
                    structure_id=line.organisation_id,
                    budget_line=line.budget_line,
                    line_ids=(line.id,),
                )
            )
    return violations
