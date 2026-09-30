from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.engines.snapshot import (
    Activity,
    Envelope,
    ExecutionMode,
    PlanningSnapshot,
    ResourceLine,
    Task,
)


@pytest.fixture
def client(tmp_path):
    """Client HTTP sur une base SQLite jetable."""
    from app.core import db
    from app.main import app

    db.configure(f"sqlite:///{tmp_path / 'bie.db'}")
    with TestClient(app) as c:
        yield c


def line(id, activity, task, label, qty, unit, price, **kw) -> ResourceLine:
    return ResourceLine(
        id=id,
        activity_id=activity,
        task_id=task,
        structure_id=kw.pop("structure_id", "DPP"),
        label=label,
        quantity=Decimal(qty),
        unit=unit,
        unit_price=price,
        **kw,
    )


@pytest.fixture
def mission_snapshot() -> PlanningSnapshot:
    """Activité « missions trimestrielles de suivi » du cahier des charges + une formation."""
    lines = (
        line("l1", "a1", "t1", "Per diem", 20, "jour", 30_000, budget_line="6114", need_month=3),
        line("l2", "a1", "t1", "Carburant", 300, "litre", 700, budget_line="6012", need_month=3),
        line(
            "l3", "a1", "t1", "Hébergement", 10, "nuitée", 35_000, budget_line="6114", need_month=3
        ),
        line(
            "l4",
            "a1",
            "t2",
            "Impression des rapports",
            50,
            "unité",
            2_000,
            budget_line="6229",
            execution_mode=ExecutionMode.INDIRECT,
            market_category="impression",
            need_month=6,
        ),
        line(
            "l5",
            "a2",
            "t3",
            "Impression des supports de formation",
            1_000,
            "unité",
            3_500,
            budget_line="6229",
            execution_mode=ExecutionMode.INDIRECT,
            market_category="impression",
            need_month=9,
        ),
        line(
            "l6",
            "a2",
            "t3",
            "Location de salle et restauration",
            1,
            "forfait",
            8_000_000,
            budget_line="6299",
            execution_mode=ExecutionMode.MIXTE,
            market_share=Decimal("0.75"),
            market_category="restauration",
            need_month=9,
            tags=frozenset({"genre"}),
        ),
    )
    return PlanningSnapshot(
        fiscal_year=2027,
        activities=(
            Activity(
                "a1",
                "DPP",
                "Organiser les missions trimestrielles de suivi des projets",
                action_code="P1.A2",
            ),
            Activity("a2", "DPP", "Former les points focaux régionaux", action_code="P1.A3"),
        ),
        tasks=(
            Task("t1", "a1", "Assurer le déplacement des équipes", 1),
            Task("t2", "a1", "Produire les rapports", 2),
            Task("t3", "a2", "Organiser la formation", 1),
        ),
        lines=lines,
        envelopes=(
            Envelope("DPP", "6114", "BN", 1_000_000),
            Envelope("DPP", "6012", "BN", 5_000_000),
            Envelope("DPP", "6229", "BN", 3_700_000),
            Envelope("DPP", "6299", "BN", 10_000_000),
        ),
    )
