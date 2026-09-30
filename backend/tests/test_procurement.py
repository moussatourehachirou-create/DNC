from datetime import date

from app.engines.budget_rules import Severity
from app.engines.procurement import (
    BENIN_2020_599_PROVISOIRE as RULES,
)
from app.engines.procurement import (
    ManualLot,
    build_lots,
    check_lots,
    detect_fractionnement,
    market_needs,
)


def test_direct_lines_are_not_market_needs(mission_snapshot):
    needs = {n.line_id: n.amount for n in market_needs(mission_snapshot)}
    assert set(needs) == {"l4", "l5", "l6"}
    assert needs["l6"] == 6_000_000  # 75 % de 8 000 000 en mode mixte


def test_lots_group_across_activities(mission_snapshot):
    lots = {lot.category: lot for lot in build_lots(mission_snapshot, RULES)}
    impression = lots["impression"]
    assert impression.amount == 3_600_000  # 100 000 + 3 500 000, deux activités
    assert impression.activity_ids == ("a1", "a2")
    assert impression.procedure.code == "dispense"
    assert lots["restauration"].procedure.code == "demande_cotation"


def test_backward_schedule_ends_on_need_date(mission_snapshot):
    lot = next(lot for lot in build_lots(mission_snapshot, RULES) if lot.category == "restauration")
    assert lot.need_date == date(2027, 9, 1)
    assert lot.steps[-1].end == lot.need_date
    assert lot.steps[0].start == lot.launch_date
    assert lot.launch_date == date(2027, 7, 28)  # 35 jours de cotation


def test_threshold_edges():
    assert RULES.procedure_for(4_000_000).code == "dispense"
    assert RULES.procedure_for(4_000_001).code == "demande_cotation"
    assert RULES.procedure_for(10_000_000).code == "demande_cotation"
    assert RULES.procedure_for(10_000_001).code == "appel_offres"


def test_launch_date_already_passed(mission_snapshot):
    lots = build_lots(mission_snapshot, RULES)
    violations = check_lots(lots, 2027, today=date(2027, 8, 15))
    late = [v for v in violations if v.code == "lancement_depasse"]
    assert {v.message.split(" :")[0] for v in late} == {"Lot impression", "Lot restauration"}
    assert all(v.severity == Severity.APPROVAL for v in late)
    assert check_lots(lots, 2027, today=date(2027, 5, 1)) == []


def test_fractionnement_detected():
    lots = [
        ManualLot("lot1", "DPP", "fournitures", 3_900_000),
        ManualLot("lot2", "DPP", "fournitures", 3_800_000),
        ManualLot("lot3", "DPP", "vehicules", 50_000_000),
    ]
    violations = detect_fractionnement(lots, RULES)
    assert len(violations) == 1
    assert "Demande de cotation" in violations[0].message
    assert violations[0].severity == Severity.BLOCKING


def test_no_fractionnement_when_same_procedure():
    lots = [
        ManualLot("lot1", "DPP", "fournitures", 1_000_000),
        ManualLot("lot2", "DPP", "fournitures", 2_000_000),
    ]
    assert detect_fractionnement(lots, RULES) == []
