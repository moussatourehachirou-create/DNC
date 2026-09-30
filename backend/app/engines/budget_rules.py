"""Moteur des règles budgétaires : contrôle des enveloppes.

Pour chaque enveloppe (structure × ligne budgétaire × source de financement) :
autorisé, programmé, reliquat, taux de consommation, dépassement (section 7.2).
Le niveau de réaction à un dépassement est paramétrable : bloquer, soumettre à
validation (dérogation motivée) ou simplement avertir.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.engines.snapshot import PlanningSnapshot, ResourceLine


class Severity(StrEnum):
    WARNING = "avertissement"
    APPROVAL = "soumis_a_validation"
    BLOCKING = "bloquant"


EnvelopeKey = tuple[str, str, str]  # (structure, ligne budgétaire, source)


@dataclass(frozen=True)
class EnvelopeStatus:
    structure_id: str
    budget_line: str
    funding_source: str
    authorized: int
    programmed: int

    @property
    def remaining(self) -> int:
        return self.authorized - self.programmed

    @property
    def consumption_rate(self) -> Decimal:
        if self.authorized == 0:
            return Decimal(0) if self.programmed == 0 else Decimal(1)
        return (Decimal(self.programmed) / Decimal(self.authorized)).quantize(Decimal("0.0001"))

    @property
    def overrun(self) -> int:
        return max(0, self.programmed - self.authorized)


@dataclass(frozen=True)
class Violation:
    code: str
    severity: Severity
    message: str
    structure_id: str
    budget_line: str | None = None
    line_ids: tuple[str, ...] = ()


def _key(line: ResourceLine) -> EnvelopeKey | None:
    if line.budget_line is None:
        return None
    return (line.structure_id, line.budget_line, line.funding_source)


def envelope_statuses(snapshot: PlanningSnapshot) -> list[EnvelopeStatus]:
    """Situation de chaque enveloppe, y compris les lignes programmées sans enveloppe."""
    programmed: dict[EnvelopeKey, int] = defaultdict(int)
    for line in snapshot.lines:
        key = _key(line)
        if key is not None:
            programmed[key] += line.cost

    authorized = {
        (e.structure_id, e.budget_line, e.funding_source): e.authorized for e in snapshot.envelopes
    }
    keys = sorted(set(authorized) | set(programmed))
    return [
        EnvelopeStatus(
            structure_id=k[0],
            budget_line=k[1],
            funding_source=k[2],
            authorized=authorized.get(k, 0),
            programmed=programmed.get(k, 0),
        )
        for k in keys
    ]


def check_envelopes(
    snapshot: PlanningSnapshot,
    overrun_severity: Severity = Severity.BLOCKING,
    alert_rate: Decimal = Decimal("0.95"),
) -> list[Violation]:
    """Contrôles d'enveloppe : lignes non imputées, dépassements, seuil d'alerte."""
    violations: list[Violation] = []

    unimputed = [line for line in snapshot.lines if line.budget_line is None]
    by_structure: dict[str, list[str]] = defaultdict(list)
    for line in unimputed:
        by_structure[line.structure_id].append(line.id)
    for structure_id, ids in by_structure.items():
        violations.append(
            Violation(
                code="ligne_non_imputee",
                severity=Severity.BLOCKING,
                message=f"{len(ids)} ligne(s) de ressource sans imputation budgétaire.",
                structure_id=structure_id,
                line_ids=tuple(ids),
            )
        )

    line_ids_by_key: dict[EnvelopeKey, list[str]] = defaultdict(list)
    for line in snapshot.lines:
        key = _key(line)
        if key is not None:
            line_ids_by_key[key].append(line.id)

    for status in envelope_statuses(snapshot):
        key = (status.structure_id, status.budget_line, status.funding_source)
        ids = tuple(line_ids_by_key.get(key, ()))
        if status.authorized == 0 and status.programmed > 0:
            violations.append(
                Violation(
                    code="enveloppe_absente",
                    severity=overrun_severity,
                    message=(
                        f"Aucune enveloppe pour la ligne {status.budget_line} "
                        f"(source {status.funding_source}) ; {status.programmed:,} FCFA programmés."
                    ).replace(",", " "),
                    structure_id=status.structure_id,
                    budget_line=status.budget_line,
                    line_ids=ids,
                )
            )
        elif status.overrun > 0:
            violations.append(
                Violation(
                    code="depassement_enveloppe",
                    severity=overrun_severity,
                    message=(
                        f"Ligne {status.budget_line} : dépassement de {status.overrun:,} FCFA "
                        f"({status.programmed:,} programmés pour {status.authorized:,} autorisés)."
                    ).replace(",", " "),
                    structure_id=status.structure_id,
                    budget_line=status.budget_line,
                    line_ids=ids,
                )
            )
        elif status.authorized > 0 and status.consumption_rate >= alert_rate:
            violations.append(
                Violation(
                    code="enveloppe_presque_epuisee",
                    severity=Severity.WARNING,
                    message=(
                        f"Ligne {status.budget_line} : {status.consumption_rate * 100:.0f} % "
                        f"de l'enveloppe programmée, reliquat {status.remaining:,} FCFA."
                    ).replace(",", " "),
                    structure_id=status.structure_id,
                    budget_line=status.budget_line,
                    line_ids=ids,
                )
            )
    return violations


def can_submit(violations: list[Violation]) -> bool:
    """Une programmation ne peut être soumise que sans violation bloquante."""
    return not any(v.severity == Severity.BLOCKING for v in violations)
