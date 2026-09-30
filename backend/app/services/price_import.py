"""Import d'une édition de l'e-répertoire (Répertoire des Prix de Référence).

BIE construit son propre référentiel de prix à partir des fichiers publiés, sans
connexion à SYCOREF. Formats pris en charge : Excel et CSV (colonnes détectées par
mots-clés). Le PDF officiel sera traité par extraction de tableaux, puis la même
normalisation.
"""

from __future__ import annotations

import csv
import io
import re
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
    nature: str | None = None  # déduite d'un code au format e-répertoire


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
        code = str(get("code")).strip() if get("code") else None
        rpr = RPR_CODE.match(code) if code else None
        parsed.append(
            PriceRow(
                code=code,
                nature=rpr.group(1) if rpr else None,
                label=label,
                unit=str(get("unit") or "unité").strip(),
                unit_price=int(price),
                zone=str(get("zone")).strip() if get("zone") else None,
                category=str(get("category")).strip() if get("category") else category,
            )
        )
    return PriceImport(parsed, rejected)


# --- e-répertoire officiel (PDF) ----------------------------------------------------

RPR_CODE = re.compile(r"^(\d{4}) (\d{4}) (\d{3}) (\d{4})\b\s*(.*)$")
TYPICAL_BS_BI_RATIO = 1.25


def _valid_number(tokens: list[str]) -> bool:
    if not tokens:
        return False
    lead, groups = tokens[0], tokens[1:]
    if not (1 <= len(lead) <= 3) or (len(lead) > 1 and lead.startswith("0")):
        return False
    return all(len(g) == 3 for g in groups)


def split_price_pair(tokens: list[str]) -> tuple[int, int] | None:
    """Découpe « 17 640 22 050 » en (17 640, 22 050).

    Les montants sont imprimés avec des espaces entre groupes de trois chiffres : on
    teste chaque point de coupure donnant deux nombres bien formés et BI ≤ BS ; en cas
    d'ambiguïté, on retient le rapport BS/BI le plus proche de celui du répertoire.
    """
    candidates = []
    for i in range(1, len(tokens)):
        left, right = tokens[:i], tokens[i:]
        if _valid_number(left) and _valid_number(right):
            bi, bs = int("".join(left)), int("".join(right))
            if 0 < bi <= bs:
                candidates.append((abs(bs / bi - TYPICAL_BS_BI_RATIO), bi, bs))
    if not candidates:
        return None
    _, bi, bs = min(candidates)
    return bi, bs


@dataclass
class RprArticle:
    code: str
    nature: str  # premier segment du code : nature économique
    label: str
    unit: str
    price_min: int  # BI : borne inférieure
    price_max: int  # BS : borne supérieure
    page: int


def parse_rpr_line(line: str, page: int) -> RprArticle | None:
    match = RPR_CODE.match(line.strip())
    if not match:
        return None
    rest = match.group(5).split()
    numeric_tail = []
    while rest and rest[-1].isdigit():
        numeric_tail.insert(0, rest.pop())
    prices = split_price_pair(numeric_tail)
    if prices is None or not rest:
        return None
    unit = rest.pop()
    label = " ".join(rest).strip()
    if not label:
        return None
    code = " ".join(match.group(i) for i in range(1, 5))
    return RprArticle(code, match.group(1), label, unit, prices[0], prices[1], page)


RPR_COLUMNS = ("CODE", "FAMILLE", "DESIGNATIONS", "SPECIFICATIONS", "UNITE", "BI", "BS")


@dataclass
class RprArticleFull(RprArticle):
    family: str = ""
    specs: str = ""


def _page_articles(page, page_number: int) -> tuple[list[RprArticleFull], list[str]]:
    """Articles d'une page, par position des mots.

    Les colonnes sont bornées par les en-têtes ; chaque article s'étend à mi-distance
    entre son code et les codes voisins (les cellules sont centrées verticalement).
    """
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    header = {w["text"]: w for w in words if w["text"] in RPR_COLUMNS}
    if not {"CODE", "DESIGNATIONS", "BI", "BS"} <= header.keys():
        return [], []
    starts = sorted((header[c]["x0"], c) for c in RPR_COLUMNS if c in header)
    header_bottom = max(header[c]["bottom"] for c in header) + 2

    def column(word) -> str:
        center = (word["x0"] + word["x1"]) / 2
        current = starts[0][1]
        for x0, name in starts:
            if center >= x0 - 4:
                current = name
        return current

    body = [w for w in words if w["top"] > header_bottom]
    lines: dict[int, list] = {}
    for w in body:
        lines.setdefault(round(w["top"]), []).append(w)
    code_rows = []
    for top, ws in sorted(lines.items()):
        code_words = sorted((w for w in ws if column(w) == "CODE"), key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in code_words)
        match = RPR_CODE.match(text)
        if match and len(text.split()) >= 4:
            code_rows.append((top, " ".join(text.split()[:4])))

    articles, unread = [], []
    for k, (top, code) in enumerate(code_rows):
        lo = (code_rows[k - 1][0] + top) / 2 if k else header_bottom
        hi = (top + code_rows[k + 1][0]) / 2 if k + 1 < len(code_rows) else page.height
        cells: dict[str, list] = {c: [] for c in RPR_COLUMNS}
        for w in body:
            if lo <= w["top"] < hi:
                cells[column(w)].append(w)

        def text_of(name: str, cells=cells) -> str:
            ws = sorted(cells[name], key=lambda w: (round(w["top"]), w["x0"]))
            return " ".join(w["text"] for w in ws).strip()

        bi_tokens = [t for t in text_of("BI").split() if t.isdigit()]
        bs_tokens = [t for t in text_of("BS").split() if t.isdigit()]
        label = text_of("DESIGNATIONS")
        unit = text_of("UNITE") or "U"
        if not (bi_tokens and bs_tokens and label):
            unread.append(f"p.{page_number}: {code} {label[:60]}")
            continue
        bi, bs = int("".join(bi_tokens)), int("".join(bs_tokens))
        articles.append(
            RprArticleFull(
                code=code,
                nature=code[:4],
                label=label,
                unit=unit,
                price_min=bi,
                price_max=bs,
                page=page_number,
                family=text_of("FAMILLE"),
                specs=text_of("SPECIFICATIONS"),
            )
        )
    return articles, unread


def parse_rpr_pdf(path: str, pages: range | None = None) -> tuple[list[RprArticleFull], list[str]]:
    """Extrait les articles d'un e-répertoire PDF ; renvoie aussi les codes non lus."""
    import pdfplumber

    articles: list[RprArticleFull] = []
    unread: list[str] = []
    with pdfplumber.open(path) as pdf:
        indices = pages if pages is not None else range(len(pdf.pages))
        for i in indices:
            found, missed = _page_articles(pdf.pages[i], i + 1)
            articles.extend(found)
            unread.extend(missed)
    return articles, unread
