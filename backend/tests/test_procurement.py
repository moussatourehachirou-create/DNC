from datetime import date

from app.engines.budget_rules import Severity
from app.engines.procurement import (
    BENIN_2020_599 as RULES,
)
from app.engines.procurement import (
    BENIN_2020_599_COMMUNE as COMMUNE,
)
from app.engines.procurement import (
    ManualLot,
    MarketType,
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
    assert impression.amount_ht == 3_050_847  # 3,6 M TTC / 1,18
    assert impression.procedure.code == "dispense"
    assert lots["restauration"].procedure.code == "DC"


def test_regulatory_schedule_for_demande_de_cotation(mission_snapshot):
    lot = next(lot for lot in build_lots(mission_snapshot, RULES) if lot.category == "restauration")
    assert lot.procedure.code == "DC" and lot.control_body == "CCMP"
    assert lot.need_date == date(2027, 9, 1)
    assert lot.steps[-1].end == lot.need_date
    # Décret n° 2020-605 : 5 j. ouvrables de remise, 3 d'analyse, 2 de publication, 5 avant
    # signature ; calcul à rebours en jours ouvrables (le 1er août 2027 est férié).
    assert lot.launch_date == date(2027, 7, 28)
    assert lot.preparation_start == date(2027, 7, 21)
    remise = next(s for s in lot.steps if s.code == "remise_offres")
    assert (remise.start, remise.end, remise.unit) == (
        date(2027, 7, 28),
        date(2027, 8, 4),
        "ouvrables",
    )
    assert "2020-605, art. 15" in remise.basis
    assert next(s for s in lot.steps if s.code == "preparation").indicative


def test_open_tender_follows_decree_2020_600_and_law_2020_26():
    from app.engines.procedures import schedule, template_for

    national = template_for("AOO", "DNCMP", community=True)
    remise = next(s for s in national.after_launch if s.code == "remise_offres")
    assert (remise.duration, remise.unit) == (30, "calendaires")  # seuil communautaire
    assert next(s for s in national.before_launch if s.code == "avis_dossier").duration == 4
    cell = template_for("AOO", "CCMP", community=False)
    assert next(s for s in cell.after_launch if s.code == "remise_offres").duration == 21
    assert next(s for s in cell.before_launch if s.code == "avis_dossier").duration == 3
    assert next(s for s in cell.after_launch if s.code == "avis_evaluation").duration == 3
    assert template_for("AOO", "CCMP", False, urgent=True).after_launch[0].duration == 15

    plan = schedule(cell, date(2027, 9, 1))
    by_code = {s.code: s for s in plan.steps}
    # Le DAO est transmis au plus tard 10 jours ouvrables et élaboré au plus tard 30 jours
    # calendaires avant le lancement (décret n° 2020-600, art. 3.1 et 3.2).
    assert (plan.launch_date - by_code["preparation"].start).days == 30
    assert by_code["publication"].end == plan.launch_date
    assert by_code["delai_attente"].unit == "calendaires"
    assert all(s.basis for s in plan.steps)
    assert plan.steps[-1].end == date(2027, 9, 1)


def test_work_calendar():
    from app.engines.calendar import DEFAULT_CALENDAR, DayUnit, easter, legal_holidays

    assert easter(2027) == date(2027, 3, 28)
    assert date(2027, 3, 29) in legal_holidays(2027)  # lundi de Pâques
    assert date(2027, 8, 1) in legal_holidays(2027)  # fête nationale
    # Vendredi 30 juillet + 1 jour ouvrable = lundi 2 août.
    assert DEFAULT_CALENDAR.shift(date(2027, 7, 30), 1, DayUnit.OUVRABLES) == date(2027, 8, 2)
    assert DEFAULT_CALENDAR.shift(date(2027, 8, 2), -1, DayUnit.OUVRABLES) == date(2027, 7, 30)
    assert DEFAULT_CALENDAR.shift(date(2027, 7, 30), 3, DayUnit.CALENDAIRES) == date(2027, 8, 2)


def test_threshold_edges_decree_2020_599():
    assert RULES.procedure_for(4_000_000).code == "dispense"
    assert RULES.procedure_for(4_000_001).code == "DC"
    assert RULES.procedure_for(10_000_000).code == "DC"
    assert RULES.procedure_for(10_000_001).code == "DRP"
    # Seuil de passation : la procédure du code s'applique à partir du seuil (art. 1 et 3).
    assert RULES.procedure_for(69_999_999).code == "DRP"
    assert RULES.procedure_for(70_000_000).code == "AOO"
    assert RULES.procedure_for(99_999_999, MarketType.TRAVAUX).code == "DRP"
    assert RULES.procedure_for(100_000_000, MarketType.TRAVAUX).code == "AOO"
    assert RULES.procedure_for(50_000_000, MarketType.PRESTATIONS_INTELLECTUELLES).code == "AMI_DP"
    assert RULES.procedure_for(20_000_000, MarketType.CONSULTANT_INDIVIDUEL).code == "SCI"


def test_communes_have_lower_thresholds():
    assert COMMUNE.procedure_for(25_000_000).code == "AOO"
    assert COMMUNE.procedure_for(34_999_999, MarketType.TRAVAUX).code == "DRP"
    assert COMMUNE.procedure_for(35_000_000, MarketType.TRAVAUX).code == "AOO"


def test_control_body_and_community_publication():
    assert RULES.control_body_for(299_999_999, MarketType.FOURNITURES) == "CCMP"
    assert RULES.control_body_for(300_000_000, MarketType.FOURNITURES) == "DNCMP"
    assert RULES.control_body_for(500_000_000, MarketType.TRAVAUX) == "DNCMP"
    assert COMMUNE.control_body_for(150_000_000, MarketType.SERVICES) == "DNCMP"
    assert not RULES.requires_community_publication(499_999_999, MarketType.FOURNITURES)
    assert RULES.requires_community_publication(1_000_000_000, MarketType.TRAVAUX)


def test_vat_conversion():
    assert RULES.to_ht(11_800_000) == 10_000_000
    assert RULES.market_type_of("construction") == MarketType.TRAVAUX
    assert RULES.market_type_of("inconnue") == MarketType.FOURNITURES


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
