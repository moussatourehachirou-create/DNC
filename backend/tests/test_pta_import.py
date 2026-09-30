from io import BytesIO

import openpyxl
import pytest

from app.models.entities import NodeLevel
from app.services.pta_import import (
    forfait_lines,
    level_from_label,
    natures_of,
    parse_amount,
    parse_code,
    parse_period,
    parse_workbook,
)


def workbook(rows: list[list]) -> BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PTA"
    for row in rows:
        ws.append(row)
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


HEADER = [
    ["MINISTÈRE X — PTA 2025"],
    [],
    ["Code", "Programmes/Objectifs/Résultats/Actions/Activités/Tâches", "Imputation budgétaire",
     "Montant budgétisé en CP (en milliers de FCFA)", None, None, "Total", "Période d'exécution",
     "Poids (%)", "Structure responsable", "Mode d'exécution"],
    [None, None, None, "Sources", None, None, "Total"],
    [None, None, None, "BN", "Don", "EMP"],
]  # fmt: skip

ROWS = [
    [" 058", "PROGRAMME 1 : PILOTAGE", None, 16_500, 0, 0, 16_500],
    [" 058.1.", "Objectif spécifique : Renforcer", None, 16_500, 0, 0, 16_500],
    [" 058.1.1", "Résultat : Capacités renforcées", None, 16_500, 0, 0, 16_500],
    [" 058.1.1.1.", "Action : Pilotage", None, 16_500, 0, 0, 16_500],
    [" 058.1.1.1.1", "Activité budgétaire : Administration", "021058001029 210012001000000 1 0160",
     16_500, 0, 0, 16_500],
    [" 058.1.1.1.1.1.", "Activité opérationnelle : Gestion des carrières",
     "021058001029 210012001000000 1 0160", 16_500, 0, 0, 16_500, "Jan - Déc", 2, "SGM",
     "Mode mixte"],
    [" 058.1.1.1.1.1.1", "Tâche : Elaborer les TDR", None, "-", None, None, 0, "Jan-Fév", 5, "SGM",
     "Mode direct"],
    [" 058.1.1.1.1.1.2", "Tâche : Sensibiliser les agents", "6114 6012", 14_000, None, None, 14_000,
     "Mai-Août", 35, "SGM", "Mode direct"],
    [" 058.1.1.1.1.1.3", "Tâche: Assurer la restauration", "6299", 2_500, None, None, 2_500,
     "Jan-Fév", 25, "SGM", "Mode indirect"],
    ["XX", "Ligne parasite", None, 1, None, None, 1],
]  # fmt: skip


def test_parse_mestfp_like_workbook():
    preview = parse_workbook(workbook(HEADER + ROWS))
    assert preview.header_row == 3
    assert preview.unit_multiplier == 1000
    assert preview.columns.amounts == {"CP": {"BN": 3, "DON": 4, "EMP": 5}}

    by_code = {n.code: n for n in preview.nodes}
    assert by_code["058"].level == NodeLevel.PROGRAMME
    assert by_code["058.1.1.1.1.1"].level == NodeLevel.ACTIVITE
    assert by_code["058.1.1.1.1.1"].label == "Gestion des carrières"
    task = by_code["058.1.1.1.1.1.2"]
    assert task.level == NodeLevel.TACHE
    assert task.parent_code == "058.1.1.1.1.1"
    assert task.amounts["CP"]["BN"] == 14_000_000  # milliers → FCFA
    assert (task.start_month, task.end_month) == (5, 8)
    assert task.execution_mode == "Mode direct"

    assert [a.code for a in preview.anomalies] == ["code_illisible"]


def test_forfait_lines_from_leaves():
    preview = parse_workbook(workbook(HEADER + ROWS))
    lines = {line.node_code: line for line in forfait_lines(preview)}
    assert set(lines) == {"058.1.1.1.1.1.2", "058.1.1.1.1.1.3"}
    assert lines["058.1.1.1.1.1.2"].budget_line == "6012"
    assert lines["058.1.1.1.1.1.3"].execution_mode == "Mode indirect"
    assert lines["058.1.1.1.1.1.3"].need_month == 1
    assert sum(line.amount for line in lines.values()) == 16_500_000


def test_incoherent_parent_total_is_flagged():
    rows = [r[:] for r in ROWS]
    rows[5][3] = 99_999  # l'activité ne correspond plus à la somme de ses tâches
    preview = parse_workbook(workbook(HEADER + rows))
    assert any(a.code == "total_incoherent" and "058.1.1.1.1.1" in a.message
               for a in preview.anomalies)  # fmt: skip


def test_missing_header_raises():
    with pytest.raises(ValueError):
        parse_workbook(workbook([["rien"], ["du tout"]]))


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Janv-Déc", (1, 12)), ("Mai-Mai", (5, 5)), ("Fév- Mars", (2, 3)),
     ("Trimestre 1,2,3,4", (1, 12)), ("Juil- Sept", (7, 9)), (None, (None, None))],
)  # fmt: skip
def test_parse_period(value, expected):
    assert parse_period(value) == expected


def test_small_parsers():
    assert parse_code(" 058.1.1.1.1.1.") == "058.1.1.1.1.1"
    assert parse_code('"021058001037') == "021058001037"
    assert parse_code("OG") is None
    assert parse_amount("29 661 017") == 29_661_017
    assert parse_amount("51\xa0420\xa0339") == 51_420_339
    assert parse_amount("-") is None
    assert natures_of("6114 6012") == ["6114", "6012"]
    assert natures_of("021058001029 210012001000000 1 0160") == ["0160"]
    assert level_from_label("Activité opérattionnelle : X") == NodeLevel.ACTIVITE
    assert level_from_label("Actvité opérationnelles : X") == NodeLevel.ACTIVITE
    assert level_from_label("Tâche: Y") == NodeLevel.TACHE
