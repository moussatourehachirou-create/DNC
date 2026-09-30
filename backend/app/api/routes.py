"""Routes REST de BIE.

Les écritures passent par ces routes, qu'elles viennent d'un humain ou d'un agent : la
même validation s'applique partout (principe « l'IA propose, l'humain valide »).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    EnvelopeIn,
    ImportSummary,
    LineIn,
    LineOut,
    NodeIn,
    NodeOut,
    OrganisationIn,
    OrganisationOut,
    OrganisationPatch,
    VersionOut,
)
from app.core.db import get_session
from app.engines.budget_rules import check_envelopes, envelope_statuses
from app.engines.coherence import ControlMode, Fix
from app.engines.costing import line_cost
from app.engines.instruments import totals
from app.engines.procurement import BENIN_2020_599, build_lots, check_lots
from app.models.entities import (
    EnvelopeRow,
    NodeLevel,
    Organisation,
    PlanNode,
    PlanVersion,
    PriceEdition,
    PriceItem,
    ResourceLineRow,
)
from app.services import coherence, exports, nomenclature, prices
from app.services.ai import planning_agent
from app.services.persist import get_or_create_year, save_import
from app.services.price_import import parse_price_file, parse_rpr_pdf
from app.services.pta_import import ImportProfile, forfait_lines, parse_workbook
from app.services.snapshot import build_snapshot

router = APIRouter()
RULES = BENIN_2020_599
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _get(session: Session, model, id_: str):
    obj = session.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} introuvable")
    return obj


# --- Structures -------------------------------------------------------------------


def _commit_checked(session: Session, version_id: str) -> None:
    """Valide la transaction ; en mode programmation, refuse toute anomalie bloquante."""
    version = session.get(PlanVersion, version_id)
    if version is not None and version.control_mode == ControlMode.PROGRAMMATION:
        session.flush()
        blocking = coherence.run(session, version_id).blocking
        if blocking:
            session.rollback()
            raise HTTPException(
                409,
                {
                    "message": "Modification refusée en mode programmation (contrôles actifs).",
                    "findings": [{"code": f.code, "message": f.message} for f in blocking],
                },
            )
    session.commit()


@router.post("/organisations", response_model=OrganisationOut, status_code=201)
def create_organisation(body: OrganisationIn, session: Session = Depends(get_session)):
    org = Organisation(**body.model_dump())
    session.add(org)
    session.commit()
    return org


@router.patch("/organisations/{org_id}", response_model=OrganisationOut)
def update_organisation(
    org_id: str, body: OrganisationPatch, session: Session = Depends(get_session)
):
    """Met à jour une structure, notamment la borne de prix retenue par défaut (BI ou BS)."""
    org = _get(session, Organisation, org_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(org, key, value)
    session.commit()
    return org


@router.get("/organisations", response_model=list[OrganisationOut])
def list_organisations(session: Session = Depends(get_session)):
    return session.scalars(select(Organisation).order_by(Organisation.name)).all()


@router.get("/organisations/{org_id}/versions", response_model=list[VersionOut])
def list_versions(org_id: str, session: Session = Depends(get_session)):
    return session.scalars(
        select(PlanVersion)
        .where(PlanVersion.organisation_id == org_id)
        .order_by(PlanVersion.created_at.desc())
    ).all()


@router.post("/organisations/{org_id}/versions", response_model=VersionOut, status_code=201)
def create_version(
    org_id: str,
    year: int = Form(...),
    label: str = Form(...),
    session: Session = Depends(get_session),
):
    _get(session, Organisation, org_id)
    fy = get_or_create_year(session, org_id, year)
    version = PlanVersion(organisation_id=org_id, fiscal_year_id=fy.id, label=label)
    session.add(version)
    session.commit()
    return version


# --- Import de PTA ----------------------------------------------------------------


def _summary(preview, version_id: str | None = None) -> ImportSummary:
    lines = forfait_lines(preview)
    return ImportSummary(
        sheet=preview.sheet,
        header_row=preview.header_row,
        unit_multiplier=preview.unit_multiplier,
        nodes=len(preview.nodes),
        lines=len(lines),
        total_cp=sum(line.amount for line in lines),
        levels=dict(Counter(n.level.value for n in preview.nodes)),
        anomalies=[asdict(a) for a in preview.anomalies[:500]],
        version_id=version_id,
    )


@router.post("/imports/pta/preview", response_model=ImportSummary)
def preview_pta(file: UploadFile = File(...), sheet: str | None = Form(None)):
    try:
        preview = parse_workbook(file.file, ImportProfile(sheet=sheet))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return _summary(preview)


@router.post("/imports/pta", response_model=ImportSummary, status_code=201)
def import_pta(
    file: UploadFile = File(...),
    organisation_id: str = Form(...),
    year: int = Form(...),
    label: str = Form("PTA importé"),
    sheet: str | None = Form(None),
    session: Session = Depends(get_session),
):
    _get(session, Organisation, organisation_id)
    try:
        preview = parse_workbook(file.file, ImportProfile(sheet=sheet))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    version = save_import(session, preview, organisation_id, year, label)
    session.commit()
    return _summary(preview, version.id)


# --- Arbre de planification --------------------------------------------------------


def _line_out(row: ResourceLineRow) -> LineOut:
    data = {c: getattr(row, c) for c in LineOut.model_fields if c not in ("cost",)}
    return LineOut(**data, cost=line_cost(row.quantity, row.unit_price, row.frequency))


def _node_out(node: PlanNode) -> NodeOut:
    fields = {
        k: getattr(node, k) for k in NodeOut.model_fields if k not in ("cost", "children", "lines")
    }
    return NodeOut(**fields)


@router.get("/versions/{version_id}/tree", response_model=list[NodeOut])
def version_tree(version_id: str, session: Session = Depends(get_session)):
    _get(session, PlanVersion, version_id)
    nodes = session.scalars(
        select(PlanNode).where(PlanNode.version_id == version_id).order_by(PlanNode.position)
    ).all()
    lines = session.scalars(
        select(ResourceLineRow).join(PlanNode).where(PlanNode.version_id == version_id)
    ).all()
    out: dict[str, NodeOut] = {n.id: _node_out(n) for n in nodes}
    for row in lines:
        out[row.node_id].lines.append(_line_out(row))
    roots = []
    for node in nodes:
        (out[node.parent_id].children if node.parent_id in out else roots).append(out[node.id])

    def total(node: NodeOut) -> int:
        node.cost = sum(line.cost for line in node.lines) + sum(total(c) for c in node.children)
        return node.cost

    for root in roots:
        total(root)
    return roots


@router.post("/versions/{version_id}/nodes", response_model=NodeOut, status_code=201)
def create_node(version_id: str, body: NodeIn, session: Session = Depends(get_session)):
    version = _get(session, PlanVersion, version_id)
    siblings = session.scalars(
        select(PlanNode).where(
            PlanNode.version_id == version_id, PlanNode.parent_id == body.parent_id
        )
    ).all()
    node = PlanNode(
        organisation_id=version.organisation_id,
        version_id=version_id,
        position=len(siblings) + 1,
        **body.model_dump(),
    )
    session.add(node)
    _commit_checked(session, version_id)
    return _node_out(node)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
def update_node(node_id: str, body: NodeIn, session: Session = Depends(get_session)):
    node = _get(session, PlanNode, node_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "attributes":
            value = {**(node.attributes or {}), **(value or {})}
        setattr(node, key, value)
    _commit_checked(session, node.version_id)
    return _node_out(node)


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: str, session: Session = Depends(get_session)):
    node = _get(session, PlanNode, node_id)
    session.delete(node)
    session.commit()


@router.post("/nodes/{node_id}/lines", response_model=LineOut, status_code=201)
def create_line(node_id: str, body: LineIn, session: Session = Depends(get_session)):
    node = _get(session, PlanNode, node_id)
    row = ResourceLineRow(
        organisation_id=node.organisation_id, node_id=node_id, **body.model_dump()
    )
    session.add(row)
    _commit_checked(session, node.version_id)
    return _line_out(row)


@router.patch("/lines/{line_id}", response_model=LineOut)
def update_line(line_id: str, body: LineIn, session: Session = Depends(get_session)):
    row = _get(session, ResourceLineRow, line_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    _commit_checked(session, row.node.version_id)
    return _line_out(row)


@router.delete("/lines/{line_id}", status_code=204)
def delete_line(line_id: str, session: Session = Depends(get_session)):
    session.delete(_get(session, ResourceLineRow, line_id))
    session.commit()


# --- Enveloppes ---------------------------------------------------------------------


@router.put("/versions/{version_id}/envelopes", status_code=204)
def set_envelopes(version_id: str, body: list[EnvelopeIn], session: Session = Depends(get_session)):
    version = _get(session, PlanVersion, version_id)
    existing = {
        (e.budget_line, e.funding_source): e
        for e in session.scalars(
            select(EnvelopeRow).where(EnvelopeRow.fiscal_year_id == version.fiscal_year_id)
        )
    }
    for item in body:
        row = existing.get((item.budget_line, item.funding_source))
        if row:
            row.authorized = item.authorized
        else:
            session.add(
                EnvelopeRow(
                    organisation_id=version.organisation_id,
                    fiscal_year_id=version.fiscal_year_id,
                    **item.model_dump(),
                )
            )
    session.commit()


# --- Analyse : enveloppes, marchés, contrôles --------------------------------------


class ModeIn(BaseModel):
    mode: ControlMode


class FixIn(BaseModel):
    kind: str
    node_id: str
    source: str | None = None
    amount: int | None = None
    start_month: int | None = None
    end_month: int | None = None


@router.get("/versions/{version_id}/coherence")
def version_coherence(version_id: str, session: Session = Depends(get_session)):
    version = _get(session, PlanVersion, version_id)
    return {
        "mode": version.control_mode,
        **coherence.report_json(coherence.run(session, version_id)),
    }


@router.put("/versions/{version_id}/mode", response_model=VersionOut)
def set_mode(version_id: str, body: ModeIn, session: Session = Depends(get_session)):
    """Passe en mode programmation (seulement sans anomalie bloquante) ou revient au brouillon."""
    version = _get(session, PlanVersion, version_id)
    if body.mode == ControlMode.PROGRAMMATION:
        report = coherence.run(session, version_id)
        if report.blocking:
            raise HTTPException(
                409,
                {
                    "message": f"{len(report.blocking)} anomalie(s) bloquante(s) à corriger avant "
                    "d'activer les contrôles.",
                    **coherence.report_json(report),
                },
            )
    version.control_mode = body.mode
    session.commit()
    return version


@router.post("/versions/{version_id}/coherence/fix")
def apply_coherence_fix(version_id: str, body: FixIn, session: Session = Depends(get_session)):
    """Applique une correction proposée par le contrôle de cohérence."""
    _get(session, PlanVersion, version_id)
    try:
        changed = coherence.apply_fix(session, version_id, Fix(label="", **body.model_dump()))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _commit_checked(session, version_id)
    return {"changed": changed, **coherence.report_json(coherence.run(session, version_id))}


@router.get("/versions/{version_id}/analysis")
def analysis(version_id: str, today: date | None = None, session: Session = Depends(get_session)):
    try:
        snapshot = build_snapshot(session, version_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    lots = build_lots(snapshot, RULES)
    violations = (
        check_envelopes(snapshot)
        + nomenclature.check_imputations(snapshot)
        + prices.check_price_ranges(session, version_id)
        + check_lots(lots, snapshot.fiscal_year, today)
    )
    return {
        "fiscal_year": snapshot.fiscal_year,
        "totals": totals(snapshot),
        "envelopes": [
            {
                **asdict(s),
                "remaining": s.remaining,
                "consumption_rate": float(s.consumption_rate),
                "overrun": s.overrun,
            }
            for s in envelope_statuses(snapshot)
        ],  # fmt: skip
        "lots": [
            {
                "id": lot.id,
                "category": lot.category,
                "market_type": lot.market_type.value,
                "amount": lot.amount,
                "amount_ht": lot.amount_ht,
                "procedure": lot.procedure.label,
                "procedure_code": lot.procedure.code,
                "control_body": lot.control_body,
                "community_publication": lot.community_publication,
                "need_date": lot.need_date.isoformat(),
                "launch_date": lot.launch_date.isoformat(),
                "needs": len(lot.needs),
                "activity_ids": list(lot.activity_ids),
                "preparation_start": lot.preparation_start.isoformat(),
                "steps": [
                    {
                        "code": s.code,
                        "label": s.label,
                        "start": s.start.isoformat(),
                        "end": s.end.isoformat(),
                        "duration": s.duration,
                        "unit": s.unit.value,
                        "basis": s.basis,
                        "indicative": s.indicative,
                    }
                    for s in lot.steps
                ],
            }
            for lot in lots
        ],
        "violations": [asdict(v) for v in violations],
        "rules_version": RULES.version,
    }


@router.get("/versions/{version_id}/exports/{kind}.xlsx")
def export(version_id: str, kind: str, session: Session = Depends(get_session)):
    version = _get(session, PlanVersion, version_id)
    org = _get(session, Organisation, version.organisation_id)
    snapshot = build_snapshot(session, version_id)
    title = f"{org.name} — {version.label} — {snapshot.fiscal_year}"
    if kind == "pta":
        content = exports.export_pta(snapshot, title)
    elif kind == "pcc":
        content = exports.export_pcc(snapshot, title)
    elif kind == "ppm":
        content = exports.export_ppm(snapshot, build_lots(snapshot, RULES), org.name)
    else:
        raise HTTPException(404, "export inconnu (pta, pcc, ppm)")
    filename = f"{kind.upper()}_{org.code}_{snapshot.fiscal_year}.xlsx"
    return Response(content, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})  # fmt: skip


# --- Agent de planification (IA) ---------------------------------------------------


def _proposal_json(proposal) -> dict:
    return {
        "activity_id": proposal.activity_id,
        "mode": proposal.mode,
        "total": proposal.total,
        "sources": proposal.sources,
        "remarks": proposal.remarks,
        "tasks": [
            {
                "label": t.label,
                "start_month": t.start_month,
                "end_month": t.end_month,
                "weight": t.weight,
                "resources": [
                    {**asdict(r), "quantity": str(r.quantity), "cost": r.cost} for r in t.resources
                ],  # fmt: skip
            }
            for t in proposal.tasks
        ],
    }


@router.post("/nodes/{node_id}/propose")
def propose(node_id: str, session: Session = Depends(get_session)):
    """Propose tâches et ressources pour une activité ; rien n'est écrit en base."""
    node = _get(session, PlanNode, node_id)
    parent = session.get(PlanNode, node.parent_id) if node.parent_id else None
    context = f"Rattachement : {parent.label}" if parent else ""
    org = _get(session, Organisation, node.organisation_id)
    try:
        proposal = planning_agent.propose_tasks(session, node, context, org.price_basis)
    except RuntimeError as exc:
        raise HTTPException(502, f"agent indisponible : {exc}") from exc
    return _proposal_json(proposal)


class AcceptedResource(LineIn):
    pass


class AcceptedTask(BaseModel):
    label: str
    start_month: int | None = None
    end_month: int | None = None
    weight: Decimal | None = None
    resources: list[AcceptedResource] = []


@router.post("/nodes/{node_id}/apply-proposal", response_model=list[NodeOut], status_code=201)
def apply_proposal(
    node_id: str, tasks: list[AcceptedTask], session: Session = Depends(get_session)
):
    """Enregistre les tâches et ressources acceptées (éventuellement modifiées) par l'utilisateur."""
    activity = _get(session, PlanNode, node_id)
    existing = session.scalars(select(PlanNode).where(PlanNode.parent_id == node_id)).all()
    created = []
    for offset, task in enumerate(tasks, start=len(existing) + 1):
        node = PlanNode(
            organisation_id=activity.organisation_id,
            version_id=activity.version_id,
            parent_id=activity.id,
            level=NodeLevel.TACHE,
            position=offset,
            label=task.label,
            start_month=task.start_month,
            end_month=task.end_month,
            weight=task.weight,
            origin="ia",
        )
        session.add(node)
        session.flush()
        for res in task.resources:
            session.add(
                ResourceLineRow(
                    organisation_id=activity.organisation_id, node_id=node.id, **res.model_dump()
                )
            )
        created.append(node)
    _commit_checked(session, activity.version_id)
    return [_node_out(n) for n in created]


# --- Nomenclature budgétaire ----------------------------------------------------------


@router.get("/referentials/natures")
def search_natures(q: str = Query(min_length=2)):
    return [{"code": n.code, "label": n.label, "parent": n.parent} for n in nomenclature.search(q)]


# --- Référentiel de prix (e-répertoire) ---------------------------------------------


@router.post("/prices/editions", status_code=201)
def import_prices(
    file: UploadFile = File(...),
    label: str = Form(...),
    session: Session = Depends(get_session),
):
    """Importe une édition : PDF officiel de l'e-répertoire, ou Excel/CSV."""
    filename = file.filename or ""
    if filename.lower().endswith(".pdf"):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(file.file.read())
            tmp.flush()
            articles, unread = parse_rpr_pdf(tmp.name)
        if not articles:
            raise HTTPException(422, "aucun article reconnu dans ce PDF")
        edition = prices.load_edition(session, label, articles)
        session.commit()
        return {"edition_id": edition.id, "items": len(articles),
                "rejected": [{"row": None, "reason": u} for u in unread[:200]]}  # fmt: skip
    try:
        parsed = parse_price_file(file.file, filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    edition = PriceEdition(label=label, source_file=filename, status="active")
    session.add(edition)
    session.flush()
    for row in parsed.rows:
        session.add(PriceItem(edition_id=edition.id, source="repertoire", **asdict(row)))
    session.commit()
    return {"edition_id": edition.id, "items": len(parsed.rows),
            "rejected": [{"row": r, "reason": m} for r, m in parsed.rejected[:200]]}  # fmt: skip


@router.post("/prices/editions/bundled", status_code=201)
def load_bundled_prices(session: Session = Depends(get_session)):
    """Charge l'édition de l'e-répertoire livrée avec BIE (v26.3)."""
    edition = prices.load_bundled_edition(session)
    session.commit()
    count = session.scalar(select(func.count()).where(PriceItem.edition_id == edition.id))
    return {"edition_id": edition.id, "label": edition.label, "items": count}


@router.get("/prices/search")
def search_prices(
    q: str = Query(min_length=2), unit: str | None = None, session: Session = Depends(get_session)
):
    terms = [t for t in q.split() if len(t) > 1]
    stmt = select(PriceItem)
    for term in terms:
        stmt = stmt.where(or_(PriceItem.label.ilike(f"%{term}%"), PriceItem.code.ilike(f"{term}%")))
    if unit:
        stmt = stmt.where(PriceItem.unit == unit)
    active = select(PriceEdition.id).where(PriceEdition.status == "active")
    stmt = stmt.where(or_(PriceItem.edition_id.in_(active), PriceItem.edition_id.is_(None)))
    items = session.scalars(stmt.order_by(PriceItem.label).limit(30)).all()
    return [
        {"id": i.id, "code": i.code, "label": i.label, "unit": i.unit, "unit_price": i.unit_price,
         "price_min": i.price_min, "price_max": i.price_max, "nature": i.nature,
         "nature_label": nomenclature.label_of(i.nature) if i.nature else None,
         "zone": i.zone, "category": i.category, "source": i.source}
        for i in items
    ]  # fmt: skip
