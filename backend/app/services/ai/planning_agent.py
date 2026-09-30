"""Agent de planification : propose les tâches et les ressources d'une activité.

Fonctionnement (cahier des charges, sections 9.1 et 9.6) :
1. recherche des activités similaires dans les PTA déjà importés (historique) ;
2. Claude, outillé pour chercher dans l'e-répertoire et la nomenclature, propose des
   tâches et des ressources en citant ses sources ;
3. la proposition est ensuite **reprise de façon déterministe** : chaque prix vient de
   l'e-répertoire (BI/BS), chaque imputation est vérifiée dans la nomenclature, et ce
   qui ne peut pas être vérifié est marqué « à revoir ».

L'agent ne modifie jamais la base : il renvoie une proposition que l'utilisateur
accepte, modifie ou rejette. Sans clé API, un mode de repli propose les tâches de
l'activité historique la plus proche.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import NodeLevel, PlanNode, PriceEdition, PriceItem, ResourceLineRow
from app.services import nomenclature
from app.services.classify import market_category
from app.services.pta_import import norm

# --- Schéma de sortie demandé au modèle ------------------------------------------


class ProposedResource(BaseModel):
    label: str = Field(description="Libellé de la ressource, par exemple « Per diem cadres »")
    quantity: float = Field(description="Quantité totale (personnes × jours, litres…)")
    unit: str = Field(description="Unité : jour, nuitée, litre, unité, forfait…")
    rpr_code: str | None = Field(
        default=None, description="Code de l'article de l'e-répertoire retenu, s'il existe"
    )
    nature: str | None = Field(default=None, description="Nature économique à 4 chiffres")
    execution_mode: str = Field(default="direct", description="direct, indirect ou mixte")
    need_month: int = Field(default=1, ge=1, le=12)
    justification: str = Field(description="Pourquoi cette ressource et cette quantité")


class ProposedTask(BaseModel):
    label: str
    start_month: int = Field(ge=1, le=12)
    end_month: int = Field(ge=1, le=12)
    weight: float = Field(description="Poids de la tâche dans l'activité, en %")
    resources: list[ProposedResource] = []


class ActivityProposal(BaseModel):
    tasks: list[ProposedTask]
    sources: list[str] = Field(
        default=[], description="Activités historiques et articles utilisés comme références"
    )
    remarks: str = Field(default="", description="Hypothèses et points à vérifier")


# --- Proposition vérifiée renvoyée à l'utilisateur ------------------------------------


@dataclass
class CheckedResource:
    label: str
    quantity: Decimal
    unit: str
    unit_price: int | None
    price_min: int | None
    price_max: int | None
    price_source: str
    price_reference: str | None
    budget_line: str | None
    budget_line_label: str | None
    execution_mode: str
    market_category: str | None
    need_month: int
    justification: str
    needs_review: list[str] = field(default_factory=list)

    @property
    def cost(self) -> int | None:
        if self.unit_price is None:
            return None
        return int((self.quantity * self.unit_price).to_integral_value())


@dataclass
class CheckedTask:
    label: str
    start_month: int
    end_month: int
    weight: float
    resources: list[CheckedResource]


@dataclass
class CheckedProposal:
    activity_id: str
    mode: str  # "ia" ou "historique"
    tasks: list[CheckedTask]
    sources: list[str]
    remarks: str

    @property
    def total(self) -> int:
        return sum(r.cost or 0 for t in self.tasks for r in t.resources)


# --- Recherche d'activités similaires --------------------------------------------------

STOPWORDS = {"de", "des", "du", "la", "le", "les", "et", "en", "a", "au", "aux", "l", "d", "un",
             "une", "pour", "sur", "dans", "par"}  # fmt: skip


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", norm(text)) if t not in STOPWORDS and len(t) > 2}


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class SimilarActivity:
    node_id: str
    label: str
    score: float
    tasks: list[str]
    lines: list[tuple[str, str, str, int, str | None]]  # libellé, qté, unité, PU, nature


def similar_activities(
    session: Session, activity: PlanNode, limit: int = 5
) -> list[SimilarActivity]:
    """Activités historiques de la même structure, classées par similarité de libellé."""
    candidates = session.scalars(
        select(PlanNode).where(
            PlanNode.organisation_id == activity.organisation_id,
            PlanNode.level == NodeLevel.ACTIVITE,
            PlanNode.id != activity.id,
        )
    ).all()
    scored = sorted(
        ((similarity(activity.label, c.label), c) for c in candidates), key=lambda x: -x[0]
    )
    out = []
    for score, node in scored[:limit]:
        if score <= 0:
            break
        children = session.scalars(
            select(PlanNode).where(PlanNode.parent_id == node.id).order_by(PlanNode.position)
        ).all()
        node_ids = [node.id, *(c.id for c in children)]
        rows = session.scalars(
            select(ResourceLineRow).where(ResourceLineRow.node_id.in_(node_ids))
        ).all()
        out.append(
            SimilarActivity(
                node_id=node.id,
                label=node.label,
                score=round(score, 3),
                tasks=[c.label for c in children],
                lines=[
                    (r.label, str(r.quantity), r.unit, r.unit_price, r.budget_line) for r in rows
                ],
            )
        )
    return out


# --- Outils exposés à l'agent ---------------------------------------------------------


def search_price_items(session: Session, query: str, limit: int = 8) -> list[dict]:
    terms = [t for t in tokens(query)][:5]
    if not terms:
        return []
    active = select(PriceEdition.id).where(PriceEdition.status == "active")
    stmt = select(PriceItem).where(PriceItem.edition_id.in_(active))
    for term in terms[:3]:
        stmt = stmt.where(PriceItem.label.ilike(f"%{term}%"))
    items = session.scalars(stmt.limit(limit)).all()
    return [
        {"code": i.code, "designation": i.label, "unite": i.unit, "prix_bi": i.price_min,
         "prix_bs": i.price_max, "nature": i.nature}
        for i in items
    ]  # fmt: skip


SYSTEM_PROMPT = """Tu es l'agent de planification de Budget Intelligence Engine, au service \
des ministères et institutions du Bénin. À partir d'une activité opérationnelle, tu proposes \
les tâches (étapes de réalisation) et les ressources nécessaires, pour un PTA budgétisé.

Méthode :
- appuie-toi d'abord sur les activités similaires des PTA antérieurs fournies ;
- pour chaque ressource payante, cherche l'article correspondant dans l'e-répertoire avec \
l'outil `rechercher_prix` et reporte son code ; n'invente jamais de code ni de prix ;
- choisis la nature économique à 4 chiffres (outil `rechercher_nature` au besoin) ;
- indique le mode d'exécution : « direct » (régie, per diem, carburant…), « indirect » \
(passé en marché : fournitures, prestations, travaux) ou « mixte » ;
- les tâches sans coût (TDR, rapports, validations) sont utiles : garde-les ;
- justifie chaque quantité (nombre de personnes × jours, etc.) et cite tes sources.
Réponds en français."""


def _agent_proposal(
    session: Session, activity: PlanNode, context: str, similar: list[SimilarActivity]
) -> ActivityProposal:
    """Appel à Claude avec outils (tool runner) et sortie structurée."""
    import anthropic
    from anthropic import beta_tool

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    @beta_tool
    def rechercher_prix(requete: str) -> str:
        """Recherche des articles dans l'e-répertoire des prix de référence (BI/BS en FCFA).

        Args:
            requete: Mots-clés de l'article, par exemple « per diem », « carburant super »,
                « location salle de conférence ».
        """
        return json.dumps(search_price_items(session, requete), ensure_ascii=False)

    @beta_tool
    def rechercher_nature(requete: str) -> str:
        """Recherche une nature économique de dépense dans la nomenclature budgétaire.

        Args:
            requete: Mots-clés ou début de code, par exemple « indemnités de mission ».
        """
        found = nomenclature.search(requete, limit=10)
        return json.dumps([{"code": n.code, "libelle": n.label} for n in found], ensure_ascii=False)

    history = (
        "\n\n".join(
            f"[{s.node_id}] {s.label} (similarité {s.score})\n"
            f"Tâches : {'; '.join(s.tasks) or '—'}\n"
            f"Ressources : {'; '.join(f'{lbl} ({q} {u} × {pu} FCFA, nature {n})' for lbl, q, u, pu, n in s.lines) or '—'}"
            for s in similar
        )
        or "Aucune activité similaire dans l'historique."
    )
    user = (
        f"Activité à planifier : « {activity.label} »\n"
        f"Contexte : {context}\n\n"
        f"Activités similaires des PTA antérieurs :\n{history}"
    )
    runner = client.beta.messages.tool_runner(
        model=settings.llm_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=[rechercher_prix, rechercher_nature],
        messages=[{"role": "user", "content": user}],
        output_format=ActivityProposal,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        max_iterations=12,
    )
    final = None
    for message in runner:
        final = message
    if final is None or final.stop_reason == "refusal":
        raise RuntimeError("proposition refusée ou vide")
    parsed = getattr(final, "parsed_output", None)
    if parsed is not None:
        return parsed
    text = "".join(b.text for b in final.content if b.type == "text")
    return ActivityProposal.model_validate_json(text)


def _historical_proposal(similar: list[SimilarActivity]) -> ActivityProposal:
    """Repli sans IA : reprend les tâches et ressources de l'activité la plus proche."""
    best = similar[0]
    resources = [
        ProposedResource(label=lbl, quantity=float(q), unit=u, nature=n,
                         justification=f"Repris de l'activité [{best.node_id}] {best.label}")
        for lbl, q, u, _pu, n in best.lines
    ]  # fmt: skip
    tasks = [ProposedTask(label=t, start_month=1, end_month=12, weight=0) for t in best.tasks]
    if not tasks:
        tasks = [ProposedTask(label=best.label, start_month=1, end_month=12, weight=100)]
    tasks[-1].resources = resources
    return ActivityProposal(
        tasks=tasks,
        sources=[best.node_id],
        remarks="Proposition reprise de l'historique, sans IA (clé API non configurée).",
    )


def check_proposal(
    session: Session, activity_id: str, proposal: ActivityProposal, mode: str
) -> CheckedProposal:
    """Reprise déterministe : prix de l'e-répertoire, natures vérifiées, points à revoir."""
    tasks = []
    for task in proposal.tasks:
        checked = []
        for res in task.resources:
            review: list[str] = []
            item = None
            if res.rpr_code:
                item = session.scalar(select(PriceItem).where(PriceItem.code == res.rpr_code))
                if item is None:
                    review.append(f"article {res.rpr_code} introuvable dans l'e-répertoire")
            else:
                review.append("aucun article de l'e-répertoire : prix à saisir")
            nature = res.nature or (item.nature if item else None)
            if nature and nomenclature.label_of(nature) is None:
                review.append(f"nature {nature} absente de la nomenclature")
            if item and nature and item.nature and nature != item.nature:
                review.append(f"nature {nature} différente de celle de l'article ({item.nature})")
            if not nature:
                review.append("imputation à préciser")
            mode_exec = (
                res.execution_mode
                if res.execution_mode in ("direct", "indirect", "mixte")
                else "direct"
            )
            checked.append(
                CheckedResource(
                    label=res.label,
                    quantity=Decimal(str(res.quantity)),
                    unit=item.unit if item else res.unit,
                    unit_price=item.unit_price if item else None,
                    price_min=item.price_min if item else None,
                    price_max=item.price_max if item else None,
                    price_source="repertoire" if item else "a_saisir",
                    price_reference=item.code if item else None,
                    budget_line=nature,
                    budget_line_label=nomenclature.label_of(nature) if nature else None,
                    execution_mode=mode_exec,
                    market_category=market_category(res.label) if mode_exec != "direct" else None,
                    need_month=res.need_month,
                    justification=res.justification,
                    needs_review=review,
                )
            )
        tasks.append(
            CheckedTask(task.label, task.start_month, task.end_month, task.weight, checked)
        )
    return CheckedProposal(activity_id, mode, tasks, proposal.sources, proposal.remarks)


def propose_tasks(session: Session, activity: PlanNode, context: str = "") -> CheckedProposal:
    similar = similar_activities(session, activity)
    if get_settings().anthropic_api_key:
        proposal = _agent_proposal(session, activity, context, similar)
        mode = "ia"
    elif similar:
        proposal = _historical_proposal(similar)
        mode = "historique"
    else:
        proposal = ActivityProposal(tasks=[], remarks="Ni clé API ni historique disponible.")
        mode = "vide"
    return check_proposal(session, activity.id, proposal, mode)
