"""Modèle de données de BIE (section 10 du cahier des charges).

Choix structurants, issus de l'analyse des PTA réels (docs/analyse-modeles-reels.md) :
- l'arbre de planification est générique : un nœud par niveau (programme, objectif
  spécifique, résultat, action, activité budgétaire, activité, tâche), le niveau étant
  une donnée et non une table par niveau, car chaque ministère a sa propre profondeur ;
- les montants sont stockés en FCFA entiers ; l'unité des fichiers (FCFA ou milliers)
  est gérée à l'import ;
- les lignes de ressource (quantité × prix unitaire) sont rattachées à une tâche ou,
  à défaut, à une activité ;
- chaque table métier porte `organisation_id` : c'est la clé d'isolation entre
  structures (renforcée par la sécurité au niveau des lignes de PostgreSQL).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


class OrganisationType(StrEnum):
    MINISTERE = "ministere"
    INSTITUTION = "institution"
    AGENCE = "agence"
    ETABLISSEMENT_PUBLIC = "etablissement_public"
    COMMUNE = "commune"
    SOCIETE_ETAT = "societe_etat"
    PROJET = "projet"


class NodeLevel(StrEnum):
    PROGRAMME = "programme"
    OBJECTIF = "objectif_specifique"
    RESULTAT = "resultat"
    ACTION = "action"
    ACTIVITE_BUDGETAIRE = "activite_budgetaire"
    ACTIVITE = "activite"  # activité opérationnelle
    TACHE = "tache"


class VersionKind(StrEnum):
    INITIALE = "initiale"
    REVISEE = "revisee"
    SCENARIO = "scenario"


class VersionStatus(StrEnum):
    BROUILLON = "brouillon"
    SOUMIS = "soumis"
    VALIDE = "valide"
    EN_EXECUTION = "en_execution"
    CLOTURE = "cloture"


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Organisation(Timestamped, Base):
    """Structure utilisatrice (espace isolé) : ministère, agence, commune, projet…"""

    __tablename__ = "organisation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[OrganisationType] = mapped_column(String(32))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("organisation.id"))  # tutelle
    financial_autonomy: Mapped[bool] = mapped_column(default=False)


class FiscalYear(Timestamped, Base):
    __tablename__ = "fiscal_year"
    __table_args__ = (UniqueConstraint("organisation_id", "year"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organisation_id: Mapped[str] = mapped_column(ForeignKey("organisation.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="preparation")


class PlanVersion(Timestamped, Base):
    """Version d'un PTA : initiale, révisée n, ou scénario de simulation."""

    __tablename__ = "plan_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organisation_id: Mapped[str] = mapped_column(ForeignKey("organisation.id"), index=True)
    fiscal_year_id: Mapped[str] = mapped_column(ForeignKey("fiscal_year.id"), index=True)
    label: Mapped[str] = mapped_column(String(255))
    kind: Mapped[VersionKind] = mapped_column(String(16), default=VersionKind.INITIALE)
    status: Mapped[VersionStatus] = mapped_column(String(16), default=VersionStatus.BROUILLON)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("plan_version.id"))

    fiscal_year: Mapped[FiscalYear] = relationship()
    nodes: Mapped[list[PlanNode]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class PlanNode(Timestamped, Base):
    """Nœud de l'arbre de planification, du programme à la tâche."""

    __tablename__ = "plan_node"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organisation_id: Mapped[str] = mapped_column(ForeignKey("organisation.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("plan_version.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("plan_node.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[NodeLevel] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str | None] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(Text)
    imputation: Mapped[str | None] = mapped_column(String(128))  # code complet ou nature
    start_month: Mapped[int | None] = mapped_column(Integer)
    end_month: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))  # poids (%)
    responsible: Mapped[str | None] = mapped_column(String(255))
    associated: Mapped[str | None] = mapped_column(String(512))
    execution_mode: Mapped[str | None] = mapped_column(String(16))
    # Montants repris d'un PTA importé, par nature de crédit et source :
    # {"AE": {"BN": 0, "DON": 0, "EMP": 0}, "CP": {...}} — en FCFA.
    amounts: Mapped[dict | None] = mapped_column(JSON)
    # Attributs de suivi et d'alignement : indicateurs, cibles, ODD, PAG, genre, climat…
    attributes: Mapped[dict | None] = mapped_column(JSON)
    observations: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), default="saisie")  # saisie, import, ia

    version: Mapped[PlanVersion] = relationship(back_populates="nodes")
    lines: Mapped[list[ResourceLineRow]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )


class ResourceLineRow(Timestamped, Base):
    """Ligne de ressource : quantité × prix unitaire × fréquence."""

    __tablename__ = "resource_line"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organisation_id: Mapped[str] = mapped_column(ForeignKey("organisation.id"), index=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("plan_node.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[int] = mapped_column(Integer)
    frequency: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal(1))
    price_source: Mapped[str] = mapped_column(String(16), default="saisie")
    price_reference: Mapped[str | None] = mapped_column(String(128))
    budget_line: Mapped[str | None] = mapped_column(String(32))  # nature économique
    funding_source: Mapped[str] = mapped_column(String(16), default="BN")
    execution_mode: Mapped[str] = mapped_column(String(16), default="direct")
    market_share: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal(0))
    market_category: Mapped[str | None] = mapped_column(String(64))
    need_month: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list | None] = mapped_column(JSON)

    node: Mapped[PlanNode] = relationship(back_populates="lines")


class EnvelopeRow(Timestamped, Base):
    """Enveloppe autorisée : structure × ligne budgétaire × source, pour un exercice."""

    __tablename__ = "envelope"
    __table_args__ = (UniqueConstraint("fiscal_year_id", "budget_line", "funding_source"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    organisation_id: Mapped[str] = mapped_column(ForeignKey("organisation.id"), index=True)
    fiscal_year_id: Mapped[str] = mapped_column(ForeignKey("fiscal_year.id"), index=True)
    budget_line: Mapped[str] = mapped_column(String(32))
    funding_source: Mapped[str] = mapped_column(String(16), default="BN")
    authorized: Mapped[int] = mapped_column(Integer)


class PriceEdition(Timestamped, Base):
    """Édition importée de l'e-répertoire (Répertoire des Prix de Référence)."""

    __tablename__ = "price_edition"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(128))  # ex. « 19e édition v26.2 »
    source_file: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="brouillon")  # brouillon, active


class PriceItem(Base):
    """Article de prix de référence (national) ou propre à une structure."""

    __tablename__ = "price_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    edition_id: Mapped[str | None] = mapped_column(ForeignKey("price_edition.id"), index=True)
    organisation_id: Mapped[str | None] = mapped_column(ForeignKey("organisation.id"), index=True)
    source: Mapped[str] = mapped_column(String(16))  # repertoire, structure, historique
    code: Mapped[str | None] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[int] = mapped_column(Integer)
    zone: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(128))
