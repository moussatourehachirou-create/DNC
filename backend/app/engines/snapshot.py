"""Photo du graphe de planification, consommée par les moteurs.

Les moteurs travaillent sur ces structures immuables plutôt que sur les objets de la
base : `résultat = f(photo, référentiels)`. On peut ainsi calculer la version réelle
ou un scénario de simulation avec exactement le même code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.engines.costing import line_cost


class ExecutionMode(StrEnum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    MIXTE = "mixte"


@dataclass(frozen=True)
class ResourceLine:
    id: str
    activity_id: str
    task_id: str
    structure_id: str
    label: str
    quantity: Decimal
    unit: str
    unit_price: int
    frequency: Decimal = Decimal(1)
    budget_line: str | None = None  # imputation (ligne budgétaire / nature économique)
    funding_source: str = "BN"  # BN = budget national
    execution_mode: ExecutionMode = ExecutionMode.DIRECT
    market_share: Decimal = Decimal(0)  # part passée en marché pour le mode mixte (0..1)
    market_category: str | None = None  # catégorie de marché pour le regroupement en lots
    need_month: int = 1  # mois où la ressource est nécessaire (1..12)
    tags: frozenset[str] = field(default_factory=frozenset)  # marqueurs : genre, climat…

    @property
    def cost(self) -> int:
        return line_cost(self.quantity, self.unit_price, self.frequency)

    @property
    def market_amount(self) -> int:
        """Part du coût à passer en marché selon le mode d'exécution."""
        match self.execution_mode:
            case ExecutionMode.DIRECT:
                return 0
            case ExecutionMode.INDIRECT:
                return self.cost
            case ExecutionMode.MIXTE:
                share = min(max(self.market_share, Decimal(0)), Decimal(1))
                return int((Decimal(self.cost) * share).to_integral_value())

    @property
    def quarter(self) -> int:
        return (self.need_month - 1) // 3 + 1


@dataclass(frozen=True)
class Task:
    id: str
    activity_id: str
    label: str
    order: int = 0


@dataclass(frozen=True)
class Activity:
    id: str
    structure_id: str
    label: str
    action_code: str | None = None
    result_label: str | None = None


@dataclass(frozen=True)
class Envelope:
    structure_id: str
    budget_line: str
    funding_source: str
    authorized: int


@dataclass(frozen=True)
class PlanningSnapshot:
    fiscal_year: int
    activities: tuple[Activity, ...] = ()
    tasks: tuple[Task, ...] = ()
    lines: tuple[ResourceLine, ...] = ()
    envelopes: tuple[Envelope, ...] = ()

    def lines_of_activity(self, activity_id: str) -> list[ResourceLine]:
        return [line for line in self.lines if line.activity_id == activity_id]

    def activity_cost(self, activity_id: str) -> int:
        return sum(line.cost for line in self.lines_of_activity(activity_id))
