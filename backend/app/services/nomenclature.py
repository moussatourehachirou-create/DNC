"""Référentiel de nomenclature budgétaire (décret n° 2014-794, annexe II).

Sert à l'imputation assistée : validation des natures économiques, libellés, recherche
par mots-clés. Le fichier JSON est versionné avec le code ; une nouvelle nomenclature
devient un nouveau fichier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.engines.budget_rules import Severity, Violation
from app.engines.snapshot import PlanningSnapshot
from app.services.pta_import import norm

REFERENTIALS = Path(__file__).resolve().parent.parent / "referentials"


@dataclass(frozen=True)
class Nature:
    code: str
    label: str
    parent: str | None


@lru_cache
def natures() -> dict[str, Nature]:
    data = json.loads((REFERENTIALS / "classification_economique_depenses.json").read_text())
    out: dict[str, Nature] = {}
    for item in data["items"]:
        out.setdefault(item["code"], Nature(item["code"], item["label"], item["parent"]))
    return out


def label_of(code: str) -> str | None:
    nature = natures().get(code)
    return nature.label if nature else None


def search(query: str, limit: int = 20) -> list[Nature]:
    terms = [norm(t) for t in query.split() if len(t) > 2]
    scored = []
    for nature in natures().values():
        text = norm(nature.label)
        score = sum(1 for t in terms if t in text) + (5 if nature.code.startswith(query) else 0)
        if score:
            scored.append((score, len(nature.code) == 4, nature.code, nature))
    scored.sort(key=lambda s: (-s[0], not s[1], s[2]))
    return [s[3] for s in scored[:limit]]


def check_imputations(snapshot: PlanningSnapshot) -> list[Violation]:
    """Signale les natures économiques absentes de la nomenclature en vigueur."""
    unknown: dict[tuple[str, str], list[str]] = {}
    known = natures()
    for line in snapshot.lines:
        if line.budget_line and line.budget_line not in known:
            unknown.setdefault((line.structure_id, line.budget_line), []).append(line.id)
    return [
        Violation(
            code="nature_inconnue",
            severity=Severity.APPROVAL,
            message=f"Nature économique {code} absente de la nomenclature (décret n° 2014-794).",
            structure_id=structure_id,
            budget_line=code,
            line_ids=tuple(ids),
        )
        for (structure_id, code), ids in sorted(unknown.items())
    ]
