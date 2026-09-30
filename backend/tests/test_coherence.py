from decimal import Decimal

from app.engines.budget_rules import Severity
from app.engines.coherence import CoherenceNode, check, raise_amount


def cp(bn: int, ae: int | None = None) -> dict:
    out = {"CP": {"BN": bn}}
    if ae is not None:
        out["AE"] = {"BN": ae}
    return out


def tree() -> list[CoherenceNode]:
    """Action 100 M → activité 60 M → deux tâches (lignes 40 M + 30 M)."""
    return [
        CoherenceNode(
            "act", None, "action", "Action", amounts=cp(100_000_000), start_month=1, end_month=12
        ),
        CoherenceNode(
            "a1", "act", "activite", "Activité", amounts=cp(60_000_000), responsible="DPAF"
        ),
        CoherenceNode(
            "t1",
            "a1",
            "tache",
            "Tâche 1",
            lines_cost={"BN": 40_000_000},
            responsible="SSE",
            indicator={"type": "valeur", "objectif": 12},
            start_month=3,
            end_month=6,
        ),
        CoherenceNode(
            "t2",
            "a1",
            "tache",
            "Tâche 2",
            lines_cost={"BN": 30_000_000},
            responsible="SSE",
            indicator={"type": "fait"},
            start_month=2,
            end_month=5,
        ),
    ]


def codes(report, severity=None):
    return sorted(f.code for f in report.findings if severity is None or f.severity == severity)


def test_sous_elements_depassent_et_correction_proposee():
    report = check(tree())
    blocking = report.blocking
    assert [f.code for f in blocking] == ["sous_elements_depassent"]
    assert blocking[0].node_id == "a1"
    assert blocking[0].fix.amount == 10_000_000
    # L'action garde 100 M déclarés pour 70 M retenus en dessous : 30 M à répartir
    assert "reste_a_repartir" in codes(report, Severity.WARNING)


def test_hausse_repercutee_sur_les_niveaux_superieurs():
    nodes = tree()
    nodes[0] = CoherenceNode("act", None, "action", "Action", amounts=cp(65_000_000))
    changed = raise_amount(nodes, "a1", "BN", 10_000_000)
    assert changed["a1"]["CP"]["BN"] == 70_000_000
    assert changed["act"]["CP"]["BN"] == 70_000_000  # le surplus remonte jusqu'à l'action


def test_hausse_non_repercutee_si_le_parent_suffit():
    changed = raise_amount(tree(), "a1", "BN", 10_000_000)
    assert set(changed) == {"a1"}


def test_ae_inferieure_au_cp():
    nodes = [CoherenceNode("act", None, "action", "Action", amounts=cp(100, ae=80))]
    finding = check(nodes).blocking[0]
    assert finding.code == "ae_inferieure_cp"
    assert finding.fix.kind == "raise_ae" and finding.fix.amount == 100


def test_periode_hors_parent_et_alignement():
    nodes = tree()
    nodes[1] = CoherenceNode("a1", "act", "activite", "Activité", start_month=4, end_month=9)
    report = check(nodes)
    period = [f for f in report.findings if f.code == "hors_periode_parent"]
    assert {f.node_id for f in period} == {"t1", "t2"}
    fix = next(f.fix for f in period if f.node_id == "t1")
    assert (fix.start_month, fix.end_month) == (4, 6)


def test_periode_inversee():
    report = check([CoherenceNode("x", None, "tache", "X", start_month=8, end_month=3)])
    assert "periode_inversee" in codes(report, Severity.BLOCKING)


def test_responsable_indicateur_et_separation_des_roles():
    nodes = [
        CoherenceNode(
            "t", None, "tache", "T", lines_cost={"BN": 5}, responsible="A", validator="A"
        ),
    ]
    assert codes(check(nodes)) == ["executant_validateur", "indicateur_manquant"]
    nodes = [
        CoherenceNode("t", None, "tache", "T", lines_cost={"BN": 5}, indicator={"type": "taux"})
    ]
    assert codes(check(nodes)) == ["responsable_manquant"]


def test_taux_de_poids_et_poids_incomplets():
    nodes = [
        CoherenceNode("p", None, "action", "P"),
        CoherenceNode("a", "p", "activite", "A", weight=Decimal(30)),
        CoherenceNode("b", "p", "activite", "B", weight=Decimal(10)),
        CoherenceNode("c", "p", "activite", "C"),
    ]
    report = check(nodes)
    assert report.weight_rates == {"a": 0.75, "b": 0.25}
    assert "poids_incomplet" in codes(report)


def test_api_mode_programmation(client):
    org = client.post(
        "/api/organisations", json={"code": "MX", "name": "Min X", "kind": "ministere"}
    ).json()
    version = client.post(
        f"/api/organisations/{org['id']}/versions", data={"year": 2027, "label": "PTA"}
    ).json()
    assert version["control_mode"] == "brouillon"
    vid = version["id"]
    action = client.post(
        f"/api/versions/{vid}/nodes",
        json={"level": "action", "label": "Action", "amounts": {"CP": {"BN": 1_000_000}}},
    ).json()
    task = client.post(
        f"/api/versions/{vid}/nodes",
        json={"level": "tache", "label": "T", "parent_id": action["id"]},
    ).json()
    client.post(
        f"/api/nodes/{task['id']}/lines",
        json={"label": "Achat", "quantity": 3, "unit_price": 500_000},
    )

    # Brouillon : l'anomalie est signalée, pas bloquée ; le passage en programmation est refusé
    report = client.get(f"/api/versions/{vid}/coherence").json()
    finding = next(f for f in report["findings"] if f["code"] == "sous_elements_depassent")
    assert (
        client.put(f"/api/versions/{vid}/mode", json={"mode": "programmation"}).status_code == 409
    )

    # Correction assistée : « Augmenter de 500 000 »
    fixed = client.post(f"/api/versions/{vid}/coherence/fix", json=finding["fix"]).json()
    assert fixed["counts"]["bloquant"] == 0
    assert (
        client.put(f"/api/versions/{vid}/mode", json={"mode": "programmation"}).json()[
            "control_mode"
        ]
        == "programmation"
    )

    # Contrôles actifs : une ligne qui dépasse est refusée, une ligne qui tient est acceptée
    over = client.post(
        f"/api/nodes/{task['id']}/lines", json={"label": "Plus", "quantity": 1, "unit_price": 1}
    )
    assert over.status_code == 409
    tree = client.get(f"/api/versions/{vid}/tree").json()
    assert tree[0]["cost"] == 1_500_000

    # Les attributs se fusionnent (indicateur puis validateur)
    client.patch(
        f"/api/nodes/{task['id']}",
        json={"level": "tache", "label": "T", "attributes": {"indicateur": {"type": "fait"}}},
    )
    node = client.patch(
        f"/api/nodes/{task['id']}",
        json={"level": "tache", "label": "T", "attributes": {"validateur": "DPP"}},
    ).json()
    assert node["attributes"] == {"indicateur": {"type": "fait"}, "validateur": "DPP"}


def test_rapport_limite_par_type():
    from app.engines.coherence import check as run_check
    from app.services.coherence import PER_CODE_LIMIT, report_json

    nodes = [CoherenceNode(f"t{i}", None, "tache", f"T{i}") for i in range(PER_CODE_LIMIT + 10)]
    out = report_json(run_check(nodes))
    assert out["by_code"]["indicateur_manquant"]["count"] == PER_CODE_LIMIT + 10
    assert len(out["findings"]) == PER_CODE_LIMIT
