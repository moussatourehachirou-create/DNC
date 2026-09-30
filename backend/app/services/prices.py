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

# Prix retenu pour le chiffrage : la borne supérieure (BS) sert de plafond prudent pour
# programmer ; tout prix saisi au-delà est signalé. Paramètre à valider avec la DNCF.
PROGRAMMING_PRICE = "bs"


def programming_price(price_min: int, price_max: int) -> int:
    return price_max if PROGRAMMING_PRICE == "bs" else price_min


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
                unit_price=programming_price(bi, bs),
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
