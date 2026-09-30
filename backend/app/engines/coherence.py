"""Contrôle de cohérence de l'arbre de planification (idée reprise de la plateforme PTAB).

Deux modes de travail sur une version :
- **brouillon** : la saisie est libre, les anomalies sont seulement signalées ;
- **programmation** (« contrôles actifs ») : on n'y entre qu'avec zéro anomalie bloquante,
  et toute modification qui en créerait une est refusée.

Les contrôles portent, source de financement par source :
- AE ≥ CP : pas de crédit de paiement sans autorisation d'engagement ;
- somme des sous-éléments (enfants et lignes de ressource) ≤ montant déclaré du nœud ;
- période d'un nœud comprise dans celle de son parent, début ≤ fin ;
- tâches et activités sans responsable, tâches sans indicateur de suivi ;
- un même agent ne peut être responsable (exécutant) et validateur ;
- poids renseignés sur une partie seulement des éléments d'un même niveau.

Chaque anomalie corrigeable porte une proposition de correction (« Augmenter de X »),
appliquée seulement sur action de l'utilisateur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.engines.budget_rules import Severity


class ControlMode(StrEnum):
    BROUILLON = "brouillon"
    PROGRAMMATION = "programmation"


@dataclass(frozen=True)
class CoherenceNode:
    id: str
    parent_id: str | None
    level: str
    label: str
    code: str | None = None
    # Montants déclarés : {"AE": {"BN": 0}, "CP": {"BN": 0}} ; None si non déclarés
    amounts: dict[str, dict[str, int]] | None = None
    # Coût des lignes de ressource rattachées directement au nœud, par source
    lines_cost: dict[str, int] = field(default_factory=dict)
    start_month: int | None = None
    end_month: int | None = None
    weight: Decimal | None = None
    responsible: str | None = None
    validator: str | None = None
    indicator: dict | None = None


@dataclass(frozen=True)
class Fix:
    """Correction proposée ; `kind` : raise_amount, raise_ae ou align_period."""

    kind: str
    node_id: str
    label: str
    source: str | None = None
    amount: int | None = None
    start_month: int | None = None
    end_month: int | None = None


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    node_id: str
    message: str
    fix: Fix | None = None


@dataclass
class CoherenceReport:
    findings: list[Finding]
    # Montant retenu par nœud et par source (déclaré, sinon calculé depuis le dessous)
    amounts: dict[str, dict[str, int]]
    # Taux de poids par nœud (poids / somme des poids du même niveau)
    weight_rates: dict[str, float]

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCKING]

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out


LEVELS_WITH_RESPONSIBLE = {"activite", "tache"}


def _fmt(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " FCFA"


def _name(node: CoherenceNode) -> str:
    return f"{node.code} {node.label}".strip() if node.code else node.label


def check(nodes: list[CoherenceNode]) -> CoherenceReport:
    by_id = {n.id: n for n in nodes}
    children: dict[str | None, list[CoherenceNode]] = {}
    for n in nodes:
        parent = n.parent_id if n.parent_id in by_id else None
        children.setdefault(parent, []).append(n)

    findings: list[Finding] = []
    retained: dict[str, dict[str, int]] = {}

    def below(node: CoherenceNode) -> dict[str, int]:
        """Montant retenu du nœud par source, après contrôle de son sous-arbre."""
        total = dict(node.lines_cost)
        for child in children.get(node.id, []):
            for source, amount in below(child).items():
                total[source] = total.get(source, 0) + amount
        cp = (node.amounts or {}).get("CP")
        if cp is None:
            retained[node.id] = total
            return total
        for source in sorted(set(total) | set(cp)):
            declared, needed = cp.get(source, 0), total.get(source, 0)
            if needed > declared:
                findings.append(
                    Finding(
                        "sous_elements_depassent",
                        Severity.BLOCKING,
                        node.id,
                        f"{_name(node)} : les sous-éléments totalisent {_fmt(needed)} en "
                        f"{source} pour {_fmt(declared)} déclarés.",
                        Fix(
                            "raise_amount",
                            node.id,
                            f"Augmenter de {_fmt(needed - declared)} ({source}) et répercuter "
                            "sur les niveaux supérieurs",
                            source=source,
                            amount=needed - declared,
                        ),
                    )
                )
            elif declared > needed and (node.id in children or node.lines_cost):
                findings.append(
                    Finding(
                        "reste_a_repartir",
                        Severity.WARNING,
                        node.id,
                        f"{_name(node)} : {_fmt(declared - needed)} en {source} restent à "
                        "répartir sur les sous-éléments.",
                    )
                )
        ae = (node.amounts or {}).get("AE")
        if ae is not None:
            for source, cp_amount in cp.items():
                if ae.get(source, 0) < cp_amount:
                    findings.append(
                        Finding(
                            "ae_inferieure_cp",
                            Severity.BLOCKING,
                            node.id,
                            f"{_name(node)} : autorisation d'engagement {_fmt(ae.get(source, 0))} "
                            f"inférieure au crédit de paiement {_fmt(cp_amount)} en {source}.",
                            Fix(
                                "raise_ae",
                                node.id,
                                f"Porter l'AE {source} à {_fmt(cp_amount)}",
                                source=source,
                                amount=cp_amount,
                            ),
                        )
                    )
        result = {s: max(cp.get(s, 0), total.get(s, 0)) for s in set(cp) | set(total)}
        retained[node.id] = result
        return result

    for root in children.get(None, []):
        below(root)

    for node in nodes:
        findings.extend(_period_findings(node, by_id.get(node.parent_id or "")))
        has_amount = sum(retained.get(node.id, {}).values()) > 0
        if node.level in LEVELS_WITH_RESPONSIBLE and has_amount and not node.responsible:
            findings.append(
                Finding(
                    "responsable_manquant",
                    Severity.WARNING,
                    node.id,
                    f"{_name(node)} : aucun responsable désigné.",
                )
            )
        if node.level == "tache" and not node.indicator:
            findings.append(
                Finding(
                    "indicateur_manquant",
                    Severity.WARNING,
                    node.id,
                    f"{_name(node)} : pas d'indicateur de suivi (valeur, taux ou fait / pas fait).",
                )
            )
        if node.responsible and node.validator and node.responsible == node.validator:
            findings.append(
                Finding(
                    "executant_validateur",
                    Severity.BLOCKING,
                    node.id,
                    f"{_name(node)} : {node.responsible} ne peut être à la fois responsable "
                    "et validateur.",
                )
            )

    weight_rates: dict[str, float] = {}
    for parent_id, siblings in children.items():
        weighted = [s for s in siblings if s.weight is not None]
        total_weight = sum((s.weight for s in weighted), Decimal(0))
        if total_weight > 0:
            for s in weighted:
                weight_rates[s.id] = float(s.weight / total_weight)
        if weighted and len(weighted) < len(siblings):
            first = next(s for s in siblings if s.weight is None)
            findings.append(
                Finding(
                    "poids_incomplet",
                    Severity.WARNING,
                    parent_id or first.id,
                    f"{len(siblings) - len(weighted)} élément(s) sans poids parmi "
                    f"{len(siblings)} au même niveau (ex. {_name(first)}).",
                )
            )

    return CoherenceReport(findings, retained, weight_rates)


def _period_findings(node: CoherenceNode, parent: CoherenceNode | None) -> list[Finding]:
    start, end = node.start_month, node.end_month
    if start and end and start > end:
        return [
            Finding(
                "periode_inversee",
                Severity.BLOCKING,
                node.id,
                f"{_name(node)} : le mois de début ({start}) est après le mois de fin ({end}).",
                Fix(
                    "align_period",
                    node.id,
                    f"Ramener à {end}–{start}",
                    start_month=end,
                    end_month=start,
                ),
            )
        ]
    if parent is None or not (start or end):
        return []
    p_start, p_end = parent.start_month, parent.end_month
    outside = (p_start and start and start < p_start) or (p_end and end and end > p_end)
    if not outside:
        return []
    new_start = max(start or 1, p_start or 1)
    new_end = min(end or 12, p_end or 12)
    if new_start > new_end:
        new_start, new_end = p_start or 1, p_end or 12
    return [
        Finding(
            "hors_periode_parent",
            Severity.BLOCKING,
            node.id,
            f"{_name(node)} : période {start or '?'}–{end or '?'} hors de celle de "
            f"{_name(parent)} ({p_start or 1}–{p_end or 12}).",
            Fix(
                "align_period",
                node.id,
                f"Aligner sur la période du niveau supérieur ({new_start}–{new_end})",
                start_month=new_start,
                end_month=new_end,
            ),
        )
    ]


def raise_amount(
    nodes: list[CoherenceNode], node_id: str, source: str, amount: int
) -> dict[str, dict[str, dict[str, int]]]:
    """Nouveaux montants déclarés après une hausse de `amount` en `source` sur `node_id`.

    La hausse est répercutée sur chaque ancêtre déclaré dont les sous-éléments dépasseraient
    alors le montant (« remonter le surplus jusqu'à l'action »). L'AE suit le CP si besoin.
    Retourne {node_id: amounts} pour les seuls nœuds modifiés.
    """
    by_id = {n.id: n for n in nodes}
    report = check(nodes)
    changed: dict[str, dict[str, dict[str, int]]] = {}
    current: CoherenceNode | None = by_id[node_id]
    increase = amount
    while current is not None and increase > 0:
        if current.amounts and "CP" in current.amounts:
            new = {k: dict(v) for k, v in current.amounts.items()}
            new["CP"][source] = new["CP"].get(source, 0) + increase
            if "AE" in new and new["AE"].get(source, 0) < new["CP"][source]:
                new["AE"][source] = new["CP"][source]
            changed[current.id] = new
            parent = by_id.get(current.parent_id or "")
            if parent is None or not (parent.amounts and "CP" in parent.amounts):
                break

            # Surplus que le parent doit absorber : besoin de ses enfants après la hausse
            def need(child: CoherenceNode) -> int:
                if child.id in changed:
                    return changed[child.id]["CP"].get(source, 0)
                return report.amounts.get(child.id, {}).get(source, 0)

            siblings_need = sum(
                need(c) for c in nodes if c.parent_id == parent.id
            ) + parent.lines_cost.get(source, 0)
            increase = siblings_need - parent.amounts["CP"].get(source, 0)
            current = parent
        else:
            current = by_id.get(current.parent_id or "")
    return changed
