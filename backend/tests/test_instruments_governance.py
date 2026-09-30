from decimal import Decimal

from app.engines.budget_rules import Severity
from app.engines.governance import (
    Autonomy,
    Directive,
    DirectiveKind,
    Level,
    Selector,
    check_inheritance,
    evaluate,
)
from app.engines.instruments import build_ppm, build_pta, consumption_plan, totals
from app.engines.procurement import BENIN_2020_599 as RULES


def test_pta_and_ppm_derive_from_same_snapshot(mission_snapshot):
    pta = build_pta(mission_snapshot)
    ppm = build_ppm(mission_snapshot, RULES)
    assert len(pta) == 6
    assert pta[0].activity_label.startswith("Former") or pta[0].action_code == "P1.A2"
    market_total = sum(row.amount for row in ppm)
    assert market_total == totals(mission_snapshot)["passe_en_marche"] == 9_600_000
    assert sum(r.cost for r in pta) == totals(mission_snapshot)["total"]


def test_consumption_plan(mission_snapshot):
    plan = consumption_plan(mission_snapshot)
    assert plan["6371"][2] == 950_000
    assert plan["6053"][5] == 100_000 and plan["6053"][8] == 3_500_000
    assert sum(sum(months) for months in plan.values()) == totals(mission_snapshot)["total"]


def test_interdiction_directive(mission_snapshot):
    d = Directive(
        "d1",
        "Ministre",
        Level.MINISTERE,
        "Pas de restauration en 2027",
        DirectiveKind.INTERDICTION,
        Selector(market_category="restauration"),
        autonomy=Autonomy.BLOQUER,
    )
    [violation] = evaluate([d], mission_snapshot)
    assert violation.line_ids == ("l6",)
    assert violation.severity == Severity.BLOCKING


def test_plafond_and_period_directives(mission_snapshot):
    plafond = Directive(
        "d2",
        "DGB",
        Level.NATIONAL,
        "Plafond impression",
        DirectiveKind.PLAFOND,
        Selector(budget_line_prefix="605"),
        amount=3_000_000,
    )
    periode = Directive(
        "d3",
        "DPPD",
        Level.PROGRAMME,
        "Pas de missions au T1",
        DirectiveKind.PERIODE_INTERDITE,
        Selector(keyword="per diem"),
        months=frozenset({1, 2, 3}),
        autonomy=Autonomy.INFORMER,
    )
    codes = {v.code: v for v in evaluate([plafond, periode], mission_snapshot)}
    assert "3 600 000" in codes["directive:d2"].message
    assert codes["directive:d3"].severity == Severity.WARNING


def test_part_minimale_directive(mission_snapshot):
    d = Directive(
        "d4",
        "DGB",
        Level.NATIONAL,
        "10 % sensible au genre",
        DirectiveKind.PART_MINIMALE,
        Selector(tag="genre"),
        share=Decimal("0.10"),
    )
    assert evaluate([d], mission_snapshot) == []  # 8 M sur 12,76 M
    strict = Directive(
        "d5",
        "DGB",
        Level.NATIONAL,
        "70 % sensible au genre",
        DirectiveKind.PART_MINIMALE,
        Selector(tag="genre"),
        share=Decimal("0.70"),
    )
    [violation] = evaluate([strict], mission_snapshot)
    assert "62.7 %" in violation.message


def test_child_directive_cannot_loosen_parent():
    parent = Directive(
        "p",
        "DGB",
        Level.NATIONAL,
        "Plafond",
        DirectiveKind.PLAFOND,
        amount=1_000_000,
        autonomy=Autonomy.BLOQUER,
    )
    looser = Directive(
        "c",
        "Ministre",
        Level.MINISTERE,
        "Plafond",
        DirectiveKind.PLAFOND,
        amount=2_000_000,
        autonomy=Autonomy.INFORMER,
        parent_id="p",
    )
    stricter = Directive(
        "s",
        "Ministre",
        Level.MINISTERE,
        "Plafond",
        DirectiveKind.PLAFOND,
        amount=500_000,
        autonomy=Autonomy.BLOQUER,
        parent_id="p",
    )
    issues = check_inheritance([parent, looser, stricter])
    assert {i.directive_id for i in issues} == {"c"}
    assert len(issues) == 2
