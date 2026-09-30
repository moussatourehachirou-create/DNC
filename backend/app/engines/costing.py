"""Moteur de chiffrage (Costing Engine).

Fonctions pures : aucune dépendance à la base de données. Le même code sert à la
programmation réelle et aux scénarios de simulation.

Règles (cahier des charges, section 7.5) :
- coût = quantité × prix unitaire × fréquence, arrondi au franc CFA ;
- choix du prix selon une priorité explicite : prix de structure validé, puis
  e-répertoire, puis historique des dépenses, puis estimation IA signalée ;
- chaque prix retenu porte sa source et une explication ;
- un prix saisi qui s'écarte trop de la référence est signalé comme anormal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class PriceSource(StrEnum):
    STRUCTURE = "structure"
    REPERTOIRE = "repertoire"
    HISTORIQUE = "historique"
    ESTIMATION_IA = "estimation_ia"
    SAISIE = "saisie"


# Ordre de priorité : le premier disponible l'emporte.
PRICE_PRIORITY: tuple[PriceSource, ...] = (
    PriceSource.STRUCTURE,
    PriceSource.REPERTOIRE,
    PriceSource.HISTORIQUE,
    PriceSource.ESTIMATION_IA,
)

DEFAULT_ANOMALY_THRESHOLD = Decimal("0.20")


@dataclass(frozen=True)
class PriceCandidate:
    source: PriceSource
    unit_price: int
    unit: str
    reference: str | None = None  # code article, édition, identifiant de la dépense
    label: str | None = None


@dataclass(frozen=True)
class PriceResolution:
    unit_price: int
    source: PriceSource
    reference: str | None
    explanation: str
    needs_review: bool


@dataclass(frozen=True)
class PriceAnomaly:
    entered_price: int
    reference_price: int
    deviation: Decimal  # écart relatif signé : +0,35 = 35 % au-dessus
    explanation: str


def to_fcfa(value: Decimal) -> int:
    """Arrondit un montant au franc CFA le plus proche (demi vers le haut)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_cost(quantity: Decimal, unit_price: int, frequency: Decimal = Decimal(1)) -> int:
    """Coût d'une ligne de ressource en FCFA."""
    if quantity < 0 or unit_price < 0 or frequency < 0:
        raise ValueError("quantité, prix unitaire et fréquence doivent être positifs")
    return to_fcfa(quantity * Decimal(unit_price) * frequency)


def resolve_price(candidates: list[PriceCandidate], unit: str) -> PriceResolution | None:
    """Retient le prix de référence selon l'ordre de priorité, pour l'unité demandée."""
    usable = [c for c in candidates if c.unit == unit]
    for source in PRICE_PRIORITY:
        for candidate in usable:
            if candidate.source == source:
                return PriceResolution(
                    unit_price=candidate.unit_price,
                    source=source,
                    reference=candidate.reference,
                    explanation=_explain(candidate),
                    needs_review=source == PriceSource.ESTIMATION_IA,
                )
    return None


def _explain(candidate: PriceCandidate) -> str:
    ref = f" ({candidate.reference})" if candidate.reference else ""
    match candidate.source:
        case PriceSource.STRUCTURE:
            return f"Prix validé propre à la structure{ref}."
        case PriceSource.REPERTOIRE:
            return f"Prix de référence de l'e-répertoire{ref}."
        case PriceSource.HISTORIQUE:
            return f"Médiane des dépenses réalisées lors des exercices antérieurs{ref}."
        case PriceSource.ESTIMATION_IA:
            return f"Estimation proposée par l'IA, à vérifier{ref}."
        case _:
            return f"Prix saisi par l'utilisateur{ref}."


def detect_anomaly(
    entered_price: int,
    reference_price: int,
    threshold: Decimal = DEFAULT_ANOMALY_THRESHOLD,
) -> PriceAnomaly | None:
    """Signale un prix saisi dont l'écart à la référence dépasse le seuil (en valeur absolue)."""
    if reference_price <= 0:
        return None
    deviation = (Decimal(entered_price) - Decimal(reference_price)) / Decimal(reference_price)
    if abs(deviation) <= threshold:
        return None
    direction = "au-dessus" if deviation > 0 else "en dessous"
    pct = to_fcfa(abs(deviation) * 100)
    return PriceAnomaly(
        entered_price=entered_price,
        reference_price=reference_price,
        deviation=deviation,
        explanation=(
            f"Prix saisi {entered_price:,} FCFA, {pct} % {direction} "
            f"de la référence {reference_price:,} FCFA."
        ).replace(",", " "),
    )


def median_price(observed: list[int]) -> int | None:
    """Médiane des prix observés, utilisée comme prix historique."""
    if not observed:
        return None
    values = sorted(observed)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return to_fcfa((Decimal(values[mid - 1]) + Decimal(values[mid])) / 2)
