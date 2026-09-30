"""Import d'une édition de l'e-répertoire (Répertoire des Prix de Référence).

BIE construit son propre référentiel de prix à partir des fichiers publiés, sans
connexion à SYCOREF. Formats pris en charge : Excel et CSV (colonnes détectées par
mots-clés). Le PDF officiel sera traité par extraction de tableaux, puis la même
normalisation.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import IO

import openpyxl

from app.services.pta_import import norm, parse_amount

COLUMN_KEYS = {
    "code": ("code", "reference", "ref"),
    "label": ("designation", "libelle", "article", "description"),
    "unit": ("unite", "u.m", "conditionnement"),
    "price": ("prix", "montant", "pu", "cout"),
    "zone": ("zone", "region", "departement", "localite"),
    "category": ("famille", "categorie", "chapitre", "rubrique"),
}


@dataclass
class PriceRow:
    code: str | None
    label: str
    unit: str
    unit_price: int
    zone: str | None
    category: str | None


@dataclass
class PriceImport:
    rows: list[PriceRow]
    rejected: list[tuple[int, str]]


def _map_columns(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for j, raw in enumerate(header):
        text = norm(raw)
        for field, keys in COLUMN_KEYS.items():
            if field not in mapping and any(text.startswith(k) or f" {k}" in text for k in keys):
                mapping[field] = j
                break
    return mapping


def _rows_from_file(file: IO[bytes], filename: str) -> list[list]:
    if filename.lower().endswith(".csv"):
        text = file.read().decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t")
        return [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


def parse_price_file(file: IO[bytes], filename: str) -> PriceImport:
    rows = _rows_from_file(file, filename)
    header_index, mapping = None, {}
    for i, row in enumerate(rows[:50]):
        candidate = _map_columns([str(v or "") for v in row])
        if {"label", "price"} <= candidate.keys():
            header_index, mapping = i, candidate
            break
    if header_index is None:
        raise ValueError("colonnes « désignation » et « prix » introuvables")

    category = None
    parsed: list[PriceRow] = []
    rejected: list[tuple[int, str]] = []
    for i, row in enumerate(rows[header_index + 1 :], start=header_index + 2):

        def get(field: str, row=row):
            j = mapping.get(field)
            return row[j] if j is not None and j < len(row) else None

        label = str(get("label") or "").strip()
        price = parse_amount(get("price"))
        if not label:
            continue
        if price is None:
            # Ligne de titre de chapitre ou de famille : elle sert de catégorie.
            if not any(get(f) for f in ("code", "unit")):
                category = label
            else:
                rejected.append((i, f"prix illisible pour « {label[:60]} »"))
            continue
        if price <= 0:
            rejected.append((i, f"prix nul ou négatif pour « {label[:60]} »"))
            continue
        parsed.append(
            PriceRow(
                code=str(get("code")).strip() if get("code") else None,
                label=label,
                unit=str(get("unit") or "unité").strip(),
                unit_price=int(price),
                zone=str(get("zone")).strip() if get("zone") else None,
                category=str(get("category")).strip() if get("category") else category,
            )
        )
    return PriceImport(parsed, rejected)
