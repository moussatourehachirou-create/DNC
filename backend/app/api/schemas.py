from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OrganisationIn(BaseModel):
    code: str
    name: str
    kind: str = "ministere"
    parent_id: str | None = None
    financial_autonomy: bool = False
    price_basis: Literal["bi", "bs"] | None = None


class OrganisationPatch(BaseModel):
    name: str | None = None
    price_basis: Literal["bi", "bs"] | None = None


class OrganisationOut(OrganisationIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organisation_id: str
    fiscal_year_id: str
    label: str
    kind: str
    status: str
    control_mode: str


class LineIn(BaseModel):
    label: str
    quantity: Decimal = Decimal(1)
    unit: str = "unité"
    unit_price: int = Field(ge=0)
    frequency: Decimal = Decimal(1)
    price_source: str = "saisie"
    price_reference: str | None = None
    price_basis: Literal["bi", "bs", "libre"] | None = None
    budget_line: str | None = None
    funding_source: str = "BN"
    execution_mode: str = "direct"
    market_share: Decimal = Decimal(0)
    market_category: str | None = None
    need_month: int = Field(default=1, ge=1, le=12)
    tags: list[str] | None = None


class LineOut(LineIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    node_id: str
    cost: int


class NodeIn(BaseModel):
    parent_id: str | None = None
    level: str
    code: str | None = None
    label: str
    imputation: str | None = None
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    weight: Decimal | None = None
    responsible: str | None = None
    execution_mode: str | None = None
    # {"AE": {"BN": 0}, "CP": {"BN": 0}} en FCFA
    amounts: dict[str, dict[str, int]] | None = None
    # Fusionnés dans les attributs existants : indicateur, validateur…
    attributes: dict | None = None


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    parent_id: str | None
    level: str
    position: int
    code: str | None
    label: str
    imputation: str | None
    start_month: int | None
    end_month: int | None
    weight: Decimal | None
    responsible: str | None
    execution_mode: str | None
    amounts: dict | None
    attributes: dict | None
    origin: str
    cost: int = 0
    children: list[NodeOut] = []
    lines: list[LineOut] = []


class EnvelopeIn(BaseModel):
    budget_line: str
    funding_source: str = "BN"
    authorized: int = Field(ge=0)


class AnomalyOut(BaseModel):
    row: int | None
    code: str
    message: str


class ImportSummary(BaseModel):
    sheet: str
    header_row: int
    unit_multiplier: int
    nodes: int
    lines: int
    total_cp: int
    levels: dict[str, int]
    anomalies: list[AnomalyOut]
    version_id: str | None = None
