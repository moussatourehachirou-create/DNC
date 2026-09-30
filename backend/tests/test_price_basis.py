"""La borne de prix (BI ou BS) est un choix de l'utilisateur, jamais imposé par BIE."""

from app.services.ai import planning_agent
from app.services.ai.planning_agent import ActivityProposal, ProposedResource, ProposedTask
from tests.test_api import create_org

BLOC_NOTE = "6013 3321 128 1114"  # e-répertoire v26.3 : BI 600, BS 969


def setup_activity(client):
    org = create_org(client)
    assert client.post("/api/prices/editions/bundled").json()["items"] > 9000
    vid = client.post(
        f"/api/organisations/{org}/versions", data={"year": "2027", "label": "PTA"}
    ).json()["id"]
    activity = client.post(
        f"/api/versions/{vid}/nodes", json={"level": "activite", "label": "Fournitures du service"}
    ).json()
    return org, vid, activity["id"]


def fake_agent(session, activity, context, similar):
    return ActivityProposal(
        tasks=[
            ProposedTask(
                label="Acheter les fournitures",
                start_month=2,
                end_month=2,
                weight=100,
                resources=[
                    ProposedResource(
                        label="Bloc-notes",
                        quantity=100,
                        unit="U",
                        rpr_code=BLOC_NOTE,
                        execution_mode="indirect",
                        justification="Dotation annuelle",
                    )
                ],
            )
        ]
    )


def test_bundled_edition_keeps_both_bounds(client):
    setup_activity(client)
    [hit] = [h for h in client.get("/api/prices/search", params={"q": "bloc note grand format"}).json()
             if h["code"] == BLOC_NOTE]  # fmt: skip
    assert (hit["price_min"], hit["price_max"], hit["nature"]) == (600, 969, "6013")
    assert hit["unit_price"] is None  # aucune borne imposée


def test_agent_waits_for_user_choice_then_applies_it(client, monkeypatch):
    org, _, activity_id = setup_activity(client)
    monkeypatch.setattr(planning_agent, "_agent_proposal", fake_agent)
    monkeypatch.setattr(planning_agent, "get_settings",
                        lambda: type("S", (), {"anthropic_api_key": "test"})())  # fmt: skip

    [res] = client.post(f"/api/nodes/{activity_id}/propose").json()["tasks"][0]["resources"]
    assert res["unit_price"] is None and (res["price_min"], res["price_max"]) == (600, 969)
    assert "borne de prix à choisir (BI ou BS)" in res["needs_review"]

    assert client.patch(f"/api/organisations/{org}", json={"price_basis": "bi"}).status_code == 200
    [res] = client.post(f"/api/nodes/{activity_id}/propose").json()["tasks"][0]["resources"]
    assert (res["unit_price"], res["price_basis"], res["cost"]) == (600, "bi", 60_000)

    client.patch(f"/api/organisations/{org}", json={"price_basis": "bs"})
    [res] = client.post(f"/api/nodes/{activity_id}/propose").json()["tasks"][0]["resources"]
    assert (res["unit_price"], res["price_basis"]) == (969, "bs")


def test_price_outside_range_is_flagged(client):
    _, vid, activity_id = setup_activity(client)
    for price, basis in ((969, "bs"), (1_200, "libre")):
        client.post(
            f"/api/nodes/{activity_id}/lines",
            json={"label": f"Bloc-notes {price}", "quantity": "10", "unit": "U", "unit_price": price,
                  "price_reference": BLOC_NOTE, "price_basis": basis, "budget_line": "6013"},
        )  # fmt: skip
    violations = client.get(f"/api/versions/{vid}/analysis").json()["violations"]
    flagged = [v for v in violations if v["code"] == "prix_hors_fourchette"]
    assert len(flagged) == 1 and "Bloc-notes 1200" in flagged[0]["message"]
    assert "borne supérieure" in flagged[0]["message"]
