from app.services.ai import planning_agent
from app.services.ai.planning_agent import (
    ActivityProposal,
    ProposedResource,
    ProposedTask,
    similarity,
)
from tests.test_api import create_org


def seed(client):
    org = create_org(client)
    vid = client.post(
        f"/api/organisations/{org}/versions", data={"year": "2026", "label": "PTA 2026"}
    ).json()["id"]
    old = client.post(
        f"/api/versions/{vid}/nodes",
        json={
            "level": "activite",
            "label": "Organiser les missions trimestrielles de suivi des projets",
        },
    ).json()
    task = client.post(
        f"/api/versions/{vid}/nodes",
        json={"level": "tache", "label": "Réaliser les missions", "parent_id": old["id"]},
    ).json()
    client.post(
        f"/api/nodes/{task['id']}/lines",
        json={
            "label": "Per diem",
            "quantity": "20",
            "unit": "jour",
            "unit_price": 30000,
            "budget_line": "6114",
        },
    )
    new = client.post(
        f"/api/versions/{vid}/nodes",
        json={
            "level": "activite",
            "label": "Organiser les missions semestrielles de suivi des projets",
        },
    ).json()
    csv = "Code;Désignation;Unité;Prix unitaire\n6012 3321 111 1111;Carburant super sans plomb;litre;700\n"
    client.post(
        "/api/prices/editions", files={"file": ("rpr.csv", csv.encode())}, data={"label": "Test"}
    )
    return vid, new["id"]


def test_similarity():
    assert similarity("Missions trimestrielles de suivi", "Missions semestrielles de suivi") > 0.4
    assert similarity("Missions de suivi", "Achat de véhicules") == 0


def test_historical_fallback_without_api_key(client):
    _, activity_id = seed(client)
    r = client.post(f"/api/nodes/{activity_id}/propose")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "historique"
    [task] = body["tasks"]
    assert task["label"] == "Réaliser les missions"
    [res] = task["resources"]
    assert res["budget_line"] == "6114" and "prix à saisir" in res["needs_review"][0]


def test_agent_output_is_checked_against_references(client, monkeypatch):
    _, activity_id = seed(client)

    def fake_agent(session, activity, context, similar):
        assert similar and similar[0].label.startswith("Organiser les missions trimestrielles")
        return ActivityProposal(
            tasks=[
                ProposedTask(label="Actualiser les TDR", start_month=1, end_month=1, weight=5),
                ProposedTask(
                    label="Réaliser les missions",
                    start_month=3,
                    end_month=9,
                    weight=80,
                    resources=[
                        ProposedResource(
                            label="Carburant",
                            quantity=300,
                            unit="litre",
                            rpr_code="6012 3321 111 1111",
                            justification="2 véhicules × 150 L",
                        ),
                        ProposedResource(
                            label="Per diem",
                            quantity=20,
                            unit="jour",
                            rpr_code="0000 0000 000 0000",
                            nature="6371",
                            justification="5 agents × 4 jours",
                        ),
                    ],
                ),
            ],
            sources=["historique"],
        )

    monkeypatch.setattr(planning_agent, "_agent_proposal", fake_agent)
    monkeypatch.setattr(
        planning_agent, "get_settings", lambda: type("S", (), {"anthropic_api_key": "test"})()
    )
    body = client.post(f"/api/nodes/{activity_id}/propose").json()
    assert body["mode"] == "ia"
    carburant, per_diem = body["tasks"][1]["resources"]
    # Le prix vient de l'e-répertoire, pas du modèle ; la nature est déduite de l'article.
    assert carburant["unit_price"] == 700 and carburant["cost"] == 210_000
    assert carburant["budget_line"] == "6012" and carburant["needs_review"] == []
    # Code inventé et nature inexistante : signalés.
    assert per_diem["unit_price"] is None
    assert any("introuvable" in m for m in per_diem["needs_review"])
    assert any("6371" in m for m in per_diem["needs_review"])

    accepted = [
        {
            "label": "Réaliser les missions",
            "resources": [
                {
                    "label": "Carburant",
                    "quantity": "300",
                    "unit": "litre",
                    "unit_price": 700,
                    "budget_line": "6012",
                    "price_source": "repertoire",
                    "price_reference": "6012 3321 111 1111",
                }
            ],
        }
    ]
    created = client.post(f"/api/nodes/{activity_id}/apply-proposal", json=accepted)
    assert created.status_code == 201 and created.json()[0]["origin"] == "ia"
