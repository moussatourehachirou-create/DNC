import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.main import app
from tests.test_pta_import import HEADER, ROWS, workbook


@pytest.fixture
def client(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'bie.db'}")
    with TestClient(app) as c:
        yield c


def create_org(client) -> str:
    r = client.post("/api/organisations", json={"code": "MESTFP", "name": "MESTFP"})
    assert r.status_code == 201
    return r.json()["id"]


def test_import_then_analysis_then_ppm(client):
    org = create_org(client)
    xlsx = workbook(HEADER + ROWS).getvalue()

    preview = client.post("/api/imports/pta/preview", files={"file": ("pta.xlsx", xlsx)})
    assert preview.status_code == 200
    assert preview.json()["total_cp"] == 16_500_000

    imported = client.post(
        "/api/imports/pta",
        files={"file": ("pta.xlsx", xlsx)},
        data={"organisation_id": org, "year": "2025", "label": "PTA 2025"},
    )
    assert imported.status_code == 201, imported.text
    version_id = imported.json()["version_id"]

    tree = client.get(f"/api/versions/{version_id}/tree").json()
    assert len(tree) == 1 and tree[0]["level"] == "programme"
    assert tree[0]["cost"] == 16_500_000

    client.put(
        f"/api/versions/{version_id}/envelopes",
        json=[{"budget_line": "6012", "authorized": 10_000_000},
              {"budget_line": "6299", "authorized": 3_000_000}],
    )  # fmt: skip
    report = client.get(f"/api/versions/{version_id}/analysis").json()
    assert report["totals"]["total"] == 16_500_000
    overrun = [v for v in report["violations"] if v["code"] == "depassement_enveloppe"]
    assert overrun and overrun[0]["budget_line"] == "6012"
    # La restauration (mode indirect) devient un lot de marché.
    [lot] = report["lots"]
    assert lot["category"] == "restauration" and lot["procedure_code"] == "dispense"

    for kind in ("pta", "pcc", "ppm"):
        r = client.get(f"/api/versions/{version_id}/exports/{kind}.xlsx")
        assert r.status_code == 200 and r.content[:2] == b"PK"


def test_manual_planning_with_lines(client):
    org = create_org(client)
    version = client.post(
        f"/api/organisations/{org}/versions", data={"year": "2027", "label": "PTA 2027"}
    ).json()
    vid = version["id"]
    activity = client.post(
        f"/api/versions/{vid}/nodes",
        json={"level": "activite", "label": "Missions trimestrielles de suivi"},
    ).json()
    task = client.post(
        f"/api/versions/{vid}/nodes",
        json={"level": "tache", "label": "Assurer le déplacement", "parent_id": activity["id"]},
    ).json()
    line = client.post(
        f"/api/nodes/{task['id']}/lines",
        json={"label": "Per diem", "quantity": "20", "unit": "jour", "unit_price": 30000,
              "budget_line": "6371"},
    )  # fmt: skip
    assert line.status_code == 201 and line.json()["cost"] == 600_000

    tree = client.get(f"/api/versions/{vid}/tree").json()
    assert tree[0]["cost"] == 600_000
    assert tree[0]["children"][0]["lines"][0]["label"] == "Per diem"

    report = client.get(f"/api/versions/{vid}/analysis").json()
    assert [v["code"] for v in report["violations"]] == ["enveloppe_absente"]


def test_price_import_and_search(client):
    csv = "Code;Désignation;Unité;Prix unitaire\n01.02.003;Per diem cadre supérieur;jour;30000\n"
    csv += "01.02.004;Carburant super;litre;700\n;Article sans prix;unité;abc\n"
    r = client.post(
        "/api/prices/editions",
        files={"file": ("rpr.csv", csv.encode())},
        data={"label": "Test"},
    )
    assert r.status_code == 201
    assert r.json()["items"] == 2 and len(r.json()["rejected"]) == 1
    hits = client.get("/api/prices/search", params={"q": "carburant"}).json()
    assert hits[0]["unit_price"] == 700 and hits[0]["unit"] == "litre"
