"""Import générique d'un PTA/PTAB Excel.

Les formats varient d'un ministère à l'autre (docs/analyse-modeles-reels.md). L'import
procède par heuristiques explicables, sans rien écrire en base :
1. repérer la ligne d'en-tête (cellule commençant par « Code ») et les 2 lignes suivantes ;
2. reconnaître les colonnes par mots-clés (code, libellé, imputation, AE/CP × sources,
   période, poids, responsable, mode d'exécution…) ;
3. déduire l'unité (FCFA, milliers, millions) des en-têtes ;
4. déterminer le niveau de chaque ligne par le préfixe du libellé ou, à défaut, par la
   profondeur du code ;
5. rattacher chaque ligne à son parent par le code ;
6. produire un aperçu (nœuds, lignes de ressource forfaitaires, anomalies) à valider.

Un profil (`ImportProfile`) permet de surcharger chaque déduction.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import IO, Any

import openpyxl

from app.models.entities import NodeLevel

MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5, "juin": 6, "juil": 7, "jt": 7,
    "aou": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip

LEVEL_PREFIXES: list[tuple[str, NodeLevel]] = [
    ("programme", NodeLevel.PROGRAMME),
    ("objectif", NodeLevel.OBJECTIF),
    ("resultat", NodeLevel.RESULTAT),
    ("action", NodeLevel.ACTION),
    ("activite budgetaire", NodeLevel.ACTIVITE_BUDGETAIRE),
    ("activite operationnelle", NodeLevel.ACTIVITE),
    ("activite", NodeLevel.ACTIVITE),
    ("tache", NodeLevel.TACHE),
]

# Schéma le plus fréquent (MESRS, MESTFP) : profondeur du code → niveau.
DEFAULT_DEPTH_LEVELS = [
    NodeLevel.PROGRAMME,
    NodeLevel.OBJECTIF,
    NodeLevel.RESULTAT,
    NodeLevel.ACTION,
    NodeLevel.ACTIVITE_BUDGETAIRE,
    NodeLevel.ACTIVITE,
    NodeLevel.TACHE,
]

# Au-delà de 5 000 milliards FCFA pour une seule ligne, une cellule relève d'une formule
# cassée ou d'une erreur d'unité : elle est signalée et ignorée (seuil paramétrable).
MAX_PLAUSIBLE_AMOUNT = Decimal(5_000_000_000_000)

SOURCE_KEYS = {
    "BN": ("bn", "budget national", "contributions budgetaires", "contribution budgetaire"),
    "DON": ("don",),
    "EMP": ("emp", "emprunt"),
    "RP": ("ressources propres", "fonds propres"),
    "PTF": ("ptf",),
}


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if text in ("", "-"):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_code(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip('"').strip()
    text = re.sub(r"\.+$", "", text)
    if not re.fullmatch(r"\d+(\.\d+)*", text):
        return None
    return text


def parse_period(value: Any) -> tuple[int | None, int | None]:
    """« Janv-Déc », « Mai-Mai », « Trimestre 1,2 », « Fév- Mars » → (début, fin)."""
    if value is None:
        return None, None
    if hasattr(value, "month"):
        return value.month, value.month
    text = norm(value)
    found = []
    for token in re.findall(r"[a-z]+", text):
        for key, month in MONTHS.items():
            if token.startswith(key):
                found.append(month)
                break
    if found:
        return found[0], found[-1]
    quarters = [int(q) for q in re.findall(r"[1-4]", text)] if "trim" in text else []
    if quarters:
        return (min(quarters) - 1) * 3 + 1, max(quarters) * 3
    return None, None


def level_from_label(label: str) -> NodeLevel | None:
    text = norm(label)
    text = text.replace("opereationnelle", "operationnelle").replace(
        "operattionnelle", "operationnelle"
    )
    text = re.sub(r"\bact?v?ite\b", "activite", text)
    head = text.split(":")[0] if ":" in text[:40] else text[:30]
    for prefix, level in LEVEL_PREFIXES:
        if head.startswith(prefix):
            return level
    return None


def strip_prefix(label: str) -> str:
    """« Activité opérationnelle : Gestion des… » → « Gestion des… »."""
    if ":" in label[:45] and level_from_label(label):
        return label.split(":", 1)[1].strip()
    return label.strip()


@dataclass
class ColumnMap:
    code: int | None = None
    label: int | None = None
    rubric: int | None = None
    imputation: int | None = None
    amounts: dict[str, dict[str, int]] = field(default_factory=dict)  # AE/CP → source → col
    period: int | None = None
    start: int | None = None
    end: int | None = None
    weight: int | None = None
    responsible: int | None = None
    associated: int | None = None
    mode: int | None = None
    observations: int | None = None
    extra: dict[str, int] = field(default_factory=dict)  # indicateurs, ODD, genre…


@dataclass
class ImportProfile:
    sheet: str | None = None
    header_row: int | None = None  # 1-indexé
    unit_multiplier: int | None = None
    depth_levels: list[NodeLevel] = field(default_factory=lambda: list(DEFAULT_DEPTH_LEVELS))
    columns: ColumnMap | None = None


@dataclass
class ParsedNode:
    row: int
    code: str
    parent_code: str | None
    level: NodeLevel
    label: str
    imputation: str | None = None
    amounts: dict[str, dict[str, int]] = field(default_factory=dict)
    start_month: int | None = None
    end_month: int | None = None
    weight: Decimal | None = None
    responsible: str | None = None
    associated: str | None = None
    execution_mode: str | None = None
    observations: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)

    def total(self, kind: str = "CP") -> int:
        return sum(self.amounts.get(kind, {}).values())


@dataclass
class Anomaly:
    row: int | None
    code: str
    message: str


@dataclass
class ImportPreview:
    sheet: str
    header_row: int
    unit_multiplier: int
    columns: ColumnMap
    nodes: list[ParsedNode]
    anomalies: list[Anomaly]

    def totals_by_level(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for node in self.nodes:
            out[node.level.value] = out.get(node.level.value, 0) + node.total()
        return out


def _find_header(ws_rows: list[tuple]) -> int:
    for i, row in enumerate(ws_rows[:120]):
        for value in row[:3]:
            text = norm(value)
            if text.startswith("code") or text == "codes":
                return i
    raise ValueError("ligne d'en-tête introuvable (aucune cellule « Code »)")


def _detect_columns(header_rows: list[tuple], above: tuple | None = None) -> tuple[ColumnMap, int]:
    width = max(len(r) for r in header_rows)
    labels = [" | ".join(norm(r[j]) for r in header_rows if j < len(r) and r[j] is not None)
              for j in range(width)]  # fmt: skip
    cols = ColumnMap()
    unit = 1
    joined = " ".join(labels)
    if "million" in joined and "milliers" not in joined:
        unit = 1_000_000
    elif "millier" in joined:
        unit = 1000

    # Blocs AE / CP : repérés dans les lignes d'en-tête (et la ligne au-dessus),
    # chacun prolongé à droite jusqu'au bloc suivant.
    starts: dict[int, str] = {}
    for row in ([above] if above else []) + header_rows:
        for j, value in enumerate(row[:width]):
            text = norm(value)
            if not text or j in starts:
                continue
            if "autorisation d'engagement" in text or re.search(r"\bae\b", text):
                starts[j] = "AE"
            elif re.search(r"\bcp\b", text) or text == "budget" or "montant" in text:
                starts[j] = "CP"
    block_starts = sorted(starts.items())
    for j, text in enumerate(labels):
        if cols.code is None and text.startswith("code"):
            cols.code = j
        elif cols.rubric is None and text.startswith("rubrique"):
            cols.rubric = j
        elif (
            cols.label is None
            and any(
                k in text
                for k in ("programme", "objectif", "designation", "activite", "action", "os/")
            )
            and "imputation" not in text
        ):
            cols.label = j
        elif cols.imputation is None and "imputation" in text:
            cols.imputation = j
        elif "periode" in text and cols.period is None:
            cols.period = j
        elif ("debut" in text) and cols.start is None:
            cols.start = j
        elif text.endswith("fin") or "| fin" in text or text == "fin":
            cols.end = j
        elif "poids" in text and cols.weight is None:
            cols.weight = j
        elif cols.responsible is None and (
            "responsable" in text or ("resp" in text and "structure" in text)
        ):
            cols.responsible = j
        elif "associ" in text and cols.associated is None:
            cols.associated = j
        elif "mode" in text and "passation" not in text and cols.mode is None:
            cols.mode = j
        elif "observ" in text or text.startswith("obs") or "obertion" in text:
            cols.observations = j
        elif "indicateur" in text:
            cols.extra["indicateurs"] = j
        elif "cible" in text:
            cols.extra["valeurs_cibles"] = j
        elif "odd" in text:
            cols.extra["odd"] = j
        elif "pag" in text:
            cols.extra["pag"] = j
        elif "genre" in text:
            cols.extra["genre"] = j
        elif "climat" in text:
            cols.extra["climat"] = j

    # Sources dans chaque bloc AE/CP. Un en-tête fusionné peut être décalé d'une colonne :
    # une source déjà vue dans le bloc courant appartient alors au bloc suivant.
    kinds = [kind for _, kind in block_starts]
    for idx, (start, kind) in enumerate(block_starts):
        stop = block_starts[idx + 1][0] if idx + 1 < len(block_starts) else width
        for j in range(start, stop):
            sub = labels[j]
            if "total" in sub:
                continue
            for source, keys in SOURCE_KEYS.items():
                if any(re.search(rf"(^|[|/ ]){re.escape(k)}($|[| s])", sub) for k in keys):
                    target = kind
                    if source in cols.amounts.get(kind, {}) and idx + 1 < len(kinds):
                        target = kinds[idx + 1]
                    cols.amounts.setdefault(target, {}).setdefault(source, j)
                    break
    return cols, unit


def _cell(row: tuple, idx: int | None) -> Any:
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def parse_workbook(file: str | IO[bytes], profile: ImportProfile | None = None) -> ImportPreview:
    profile = profile or ImportProfile()
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    ws = wb[profile.sheet] if profile.sheet else wb.worksheets[0]
    rows = [tuple(r) for r in ws.iter_rows(max_col=60, values_only=True)]

    h = profile.header_row - 1 if profile.header_row else _find_header(rows)
    detected, unit = _detect_columns(rows[h : h + 3], rows[h - 1] if h > 0 else None)
    cols = profile.columns or detected
    unit = profile.unit_multiplier or unit
    if cols.code is None or cols.label is None:
        raise ValueError("colonnes « Code » ou « Libellé » introuvables")

    anomalies: list[Anomaly] = []
    nodes: list[ParsedNode] = []
    seen: dict[str, ParsedNode] = {}
    votes: dict[int, Counter[NodeLevel]] = {}
    for offset, row in enumerate(rows[h + 1 :], start=h + 2):
        raw_code = _cell(row, cols.code)
        label = str(_cell(row, cols.label) or "").strip()
        code = parse_code(raw_code)
        if code is None:
            if raw_code not in (None, "") and label:
                anomalies.append(
                    Anomaly(offset, "code_illisible", f"Code non reconnu : {raw_code!r}")
                )
            continue
        if not label:
            anomalies.append(Anomaly(offset, "libelle_vide", f"Ligne {code} sans libellé"))
            continue

        rubric = str(_cell(row, cols.rubric) or "")
        level = level_from_label(rubric) or level_from_label(label)
        depth = code.count(".")
        if level is not None:
            votes.setdefault(depth, Counter())[level] += 1

        amounts: dict[str, dict[str, int]] = {}
        for kind, sources in cols.amounts.items():
            for source, j in sources.items():
                value = parse_amount(_cell(row, j))
                if value is None:
                    continue
                if value < 0:
                    anomalies.append(
                        Anomaly(offset, "montant_negatif", f"{code} : montant négatif")
                    )
                    continue
                if value * unit > MAX_PLAUSIBLE_AMOUNT:
                    message = f"{code} : {value * unit:,.0f} FCFA ({kind} {source}) ignoré"
                    anomalies.append(Anomaly(offset, "montant_aberrant", message.replace(",", " ")))
                    continue
                amounts.setdefault(kind, {})[source] = int((value * unit).to_integral_value())

        start, end = parse_period(_cell(row, cols.period))
        if cols.start is not None:
            start = parse_period(_cell(row, cols.start))[0] or start
        if cols.end is not None:
            end = parse_period(_cell(row, cols.end))[1] or end

        parent_code = code.rsplit(".", 1)[0] if "." in code else None
        while parent_code and parent_code not in seen:
            parent_code = parent_code.rsplit(".", 1)[0] if "." in parent_code else None

        weight = parse_amount(_cell(row, cols.weight))
        imputation = _cell(row, cols.imputation)
        node = ParsedNode(
            row=offset,
            code=code,
            parent_code=parent_code,
            level=level or NodeLevel.TACHE,  # provisoire, fixé par `_assign_levels`
            label=strip_prefix(label),
            imputation=re.sub(r"\s+", " ", str(imputation).strip().strip('"'))
            if imputation
            else None,
            amounts=amounts,
            start_month=start,
            end_month=end,
            weight=weight,
            responsible=_str(_cell(row, cols.responsible)),
            associated=_str(_cell(row, cols.associated)),
            execution_mode=_str(_cell(row, cols.mode)),
            observations=_str(_cell(row, cols.observations)),
            attributes={k: s for k, j in cols.extra.items() if (s := _str(_cell(row, j)))},
        )
        if code in seen:
            anomalies.append(Anomaly(offset, "code_duplique", f"Code {code} en double"))
            continue
        seen[code] = node
        nodes.append(node)

    anomalies.extend(_assign_levels(nodes, votes, profile))
    anomalies.extend(_check_totals(nodes))
    return ImportPreview(ws.title, h + 1, unit, cols, nodes, anomalies)


FIVE_LEVELS = [
    NodeLevel.PROGRAMME,
    NodeLevel.ACTION,
    NodeLevel.ACTIVITE_BUDGETAIRE,
    NodeLevel.ACTIVITE,
    NodeLevel.TACHE,
]


def depth_mapping(
    depths: list[int], votes: dict[int, Counter[NodeLevel]], default: list[NodeLevel]
) -> dict[int, NodeLevel]:
    """Niveau de chaque profondeur de code.

    Les préfixes de libellés (« Action : », « Tâche : ») votent ; le vote majoritaire
    l'emporte s'il est net (au moins 60 % des libellés préfixés de cette profondeur).
    Sans vote, on retient le schéma à 7 niveaux (MESRS, MESTFP) ou à 5 niveaux
    (programme, action, activité budgétaire, activité, tâche) selon le nombre de profondeurs,
    aligné par le bas : la profondeur la plus grande correspond aux tâches.
    """
    scheme = default if len(depths) > len(FIVE_LEVELS) else FIVE_LEVELS
    ordered = sorted(depths)
    mapping = {}
    for i, depth in enumerate(ordered):
        from_bottom = len(ordered) - 1 - i
        mapping[depth] = scheme[max(len(scheme) - 1 - from_bottom, 0)]
    for depth, counter in votes.items():
        level, count = counter.most_common(1)[0]
        if count >= 0.6 * sum(counter.values()):
            mapping[depth] = level
    return mapping


def _assign_levels(
    nodes: list[ParsedNode], votes: dict[int, Counter[NodeLevel]], profile: ImportProfile
) -> list[Anomaly]:
    depths = sorted({n.code.count(".") for n in nodes})
    mapping = depth_mapping(depths, votes, profile.depth_levels)
    anomalies = []
    for node in nodes:
        expected = mapping[node.code.count(".")]
        prefixed = level_from_label(node.label)
        node.level = expected
        if prefixed is not None and prefixed != expected:
            anomalies.append(
                Anomaly(
                    node.row,
                    "niveau_ambigu",
                    f"{node.code} : libellé de type « {prefixed.value} » à un niveau "
                    f"« {expected.value} »",
                )
            )
    return anomalies


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _check_totals(nodes: list[ParsedNode], tolerance: int = 1000) -> list[Anomaly]:
    """Vérifie que chaque parent égale la somme de ses enfants (CP), à l'arrondi près."""
    children: dict[str, list[ParsedNode]] = {}
    for n in nodes:
        if n.parent_code:
            children.setdefault(n.parent_code, []).append(n)
    anomalies = []
    for n in nodes:
        kids = children.get(n.code)
        if not kids or not n.amounts.get("CP"):
            continue
        total_kids = sum(k.total() for k in kids)
        if total_kids and abs(total_kids - n.total()) > tolerance * len(kids):
            anomalies.append(
                Anomaly(
                    n.row,
                    "total_incoherent",
                    f"{n.code} : {n.total():,} FCFA contre {total_kids:,} pour la somme des "
                    f"sous-éléments".replace(",", " "),
                )
            )
    return anomalies


NATURE_RE = re.compile(r"\b(\d{4})\b")


def natures_of(imputation: str | None) -> list[str]:
    """Natures économiques à 4 chiffres présentes dans une imputation (« 6114 6012 »)."""
    if not imputation:
        return []
    parts = imputation.split()
    return [p for p in parts if NATURE_RE.fullmatch(p)]


@dataclass
class FlatLine:
    """Ligne de ressource forfaitaire déduite d'un montant importé."""

    node_code: str
    label: str
    amount: int
    funding_source: str
    budget_line: str | None
    execution_mode: str | None
    need_month: int


def forfait_lines(preview: ImportPreview) -> list[FlatLine]:
    """Convertit les montants des nœuds « feuilles budgétaires » en lignes forfaitaires.

    Une feuille budgétaire est un nœud portant un montant CP dont aucun enfant ne porte
    de montant. Les modes d'exécution et imputations manquants sont hérités du parent.
    """
    by_code = {n.code: n for n in preview.nodes}
    has_amount_child = {n.parent_code for n in preview.nodes if n.total() > 0 and n.parent_code}

    def inherited(node: ParsedNode, attr: str) -> Any:
        current: ParsedNode | None = node
        while current is not None:
            value = getattr(current, attr)
            if value:
                return value
            current = by_code.get(current.parent_code) if current.parent_code else None
        return None

    lines = []
    for node in preview.nodes:
        if node.total() <= 0 or node.code in has_amount_child:
            continue
        natures = natures_of(node.imputation) or natures_of(inherited(node, "imputation"))
        start = node.start_month or inherited(node, "start_month") or 1
        for source, amount in node.amounts.get("CP", {}).items():
            if amount <= 0:
                continue
            lines.append(
                FlatLine(
                    node_code=node.code,
                    label=node.label[:200],
                    amount=amount,
                    funding_source=source,
                    budget_line=natures[-1] if natures else None,
                    execution_mode=inherited(node, "execution_mode"),
                    need_month=start,
                )
            )
    return lines
