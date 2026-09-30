"""Moteur de gouvernance : directives des autorités et contrôle de leur respect.

Chaque autorité (national, ministère, programme, structure) émet des directives sur son
périmètre (section 7.14). Une directive est une règle vérifiable : un sélecteur de lignes,
une condition, une sévérité. Elle s'applique aux niveaux inférieurs, qui peuvent la
durcir mais jamais l'assouplir.

Les agents de veille appellent `evaluate` à chaque événement et périodiquement.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum, StrEnum

from app.engines.budget_rules import Severity, Violation
from app.engines.snapshot import PlanningSnapshot, ResourceLine


class Level(IntEnum):
    NATIONAL = 0
    MINISTERE = 1
    PROGRAMME = 2
    STRUCTURE = 3


class DirectiveKind(StrEnum):
    PLAFOND = "plafond"  # montant maximal des lignes sélectionnées
    INTERDICTION = "interdiction"  # aucune ligne sélectionnée autorisée
    PART_MINIMALE = "part_minimale"  # part minimale du total portant un marqueur
    PERIODE_INTERDITE = "periode_interdite"  # mois où les lignes sélectionnées sont exclues


class Autonomy(StrEnum):
    INFORMER = "informer"
    JUSTIFIER = "justifier"
    BLOQUER = "bloquer"


AUTONOMY_SEVERITY = {
    Autonomy.INFORMER: Severity.WARNING,
    Autonomy.JUSTIFIER: Severity.APPROVAL,
    Autonomy.BLOQUER: Severity.BLOCKING,
}

AUTONOMY_RANK = {Autonomy.INFORMER: 0, Autonomy.JUSTIFIER: 1, Autonomy.BLOQUER: 2}


@dataclass(frozen=True)
class Selector:
    """Désigne les lignes concernées ; les critères renseignés se cumulent (ET)."""

    market_category: str | None = None
    budget_line_prefix: str | None = None
    keyword: str | None = None
    tag: str | None = None

    def matches(self, line: ResourceLine) -> bool:
        if self.market_category and line.market_category != self.market_category:
            return False
        if self.budget_line_prefix and not (line.budget_line or "").startswith(
            self.budget_line_prefix
        ):
            return False
        if self.keyword and self.keyword.lower() not in line.label.lower():
            return False
        return not (self.tag and self.tag not in line.tags)


@dataclass(frozen=True)
class Directive:
    id: str
    authority: str
    level: Level
    title: str
    kind: DirectiveKind
    selector: Selector = field(default_factory=Selector)
    structure_ids: frozenset[str] | None = None  # None = tout le périmètre de l'autorité
    amount: int | None = None  # pour PLAFOND
    share: Decimal | None = None  # pour PART_MINIMALE (0..1)
    months: frozenset[int] = frozenset()  # pour PERIODE_INTERDITE
    autonomy: Autonomy = Autonomy.JUSTIFIER
    parent_id: str | None = None

    def in_scope(self, line: ResourceLine) -> bool:
        return self.structure_ids is None or line.structure_id in self.structure_ids


def _violation(d: Directive, structure_id: str, message: str, ids: list[str]) -> Violation:
    return Violation(
        code=f"directive:{d.id}",
        severity=AUTONOMY_SEVERITY[d.autonomy],
        message=f"{d.title} — {message}",
        structure_id=structure_id,
        line_ids=tuple(ids),
    )


def evaluate(directives: list[Directive], snapshot: PlanningSnapshot) -> list[Violation]:
    """Contrôle toutes les directives actives sur la photo ; une violation par structure."""
    violations: list[Violation] = []
    for d in directives:
        scoped = [line for line in snapshot.lines if d.in_scope(line)]
        selected = [line for line in scoped if d.selector.matches(line)]
        by_structure: dict[str, list[ResourceLine]] = defaultdict(list)
        for line in selected:
            by_structure[line.structure_id].append(line)

        match d.kind:
            case DirectiveKind.INTERDICTION:
                for sid, lines in by_structure.items():
                    violations.append(
                        _violation(
                            d, sid, f"{len(lines)} ligne(s) concernée(s).", [ln.id for ln in lines]
                        )
                    )
            case DirectiveKind.PLAFOND:
                assert d.amount is not None
                total = sum(line.cost for line in selected)
                if total > d.amount:
                    for sid, lines in by_structure.items():
                        violations.append(
                            _violation(
                                d,
                                sid,
                                f"{total:,} FCFA programmés pour un plafond de {d.amount:,} FCFA.".replace(
                                    ",", " "
                                ),
                                [ln.id for ln in lines],
                            )
                        )
            case DirectiveKind.PERIODE_INTERDITE:
                for sid, lines in by_structure.items():
                    hits = [ln for ln in lines if ln.need_month in d.months]
                    if hits:
                        violations.append(
                            _violation(
                                d,
                                sid,
                                f"{len(hits)} ligne(s) prévue(s) sur une période exclue.",
                                [ln.id for ln in hits],
                            )
                        )
            case DirectiveKind.PART_MINIMALE:
                assert d.share is not None
                structures = {line.structure_id for line in scoped}
                for sid in sorted(structures):
                    total = sum(ln.cost for ln in scoped if ln.structure_id == sid)
                    tagged = sum(ln.cost for ln in by_structure.get(sid, []))
                    if total and Decimal(tagged) / Decimal(total) < d.share:
                        pct = Decimal(tagged) * 100 / Decimal(total)
                        violations.append(
                            _violation(
                                d,
                                sid,
                                f"part actuelle {pct:.1f} % pour un minimum de {d.share * 100:.0f} %.",
                                [],
                            )
                        )
    return violations


@dataclass(frozen=True)
class ConsistencyIssue:
    directive_id: str
    parent_id: str
    message: str


def check_inheritance(directives: list[Directive]) -> list[ConsistencyIssue]:
    """Une directive d'un niveau inférieur peut durcir sa directive mère, jamais l'assouplir."""
    by_id = {d.id: d for d in directives}
    issues = []
    for child in directives:
        parent = by_id.get(child.parent_id) if child.parent_id else None
        if parent is None:
            continue
        if child.level <= parent.level:
            issues.append(
                ConsistencyIssue(
                    child.id, parent.id, "une directive fille doit relever d'un niveau inférieur"
                )
            )
        if child.kind != parent.kind:
            issues.append(
                ConsistencyIssue(child.id, parent.id, "type différent de la directive mère")
            )
            continue
        if child.kind == DirectiveKind.PLAFOND and (child.amount or 0) > (parent.amount or 0):
            issues.append(
                ConsistencyIssue(child.id, parent.id, "plafond supérieur à celui du niveau parent")
            )
        if child.kind == DirectiveKind.PART_MINIMALE and (child.share or 0) < (parent.share or 0):
            issues.append(
                ConsistencyIssue(
                    child.id, parent.id, "part minimale inférieure à celle du niveau parent"
                )
            )
        if child.kind == DirectiveKind.PERIODE_INTERDITE and not parent.months <= child.months:
            issues.append(
                ConsistencyIssue(
                    child.id, parent.id, "période exclue plus courte que celle du niveau parent"
                )
            )
        if AUTONOMY_RANK[child.autonomy] < AUTONOMY_RANK[parent.autonomy]:
            issues.append(
                ConsistencyIssue(child.id, parent.id, "réaction moins stricte que le niveau parent")
            )
    return issues
