from dataclasses import replace
from decimal import Decimal

from app.engines.budget_rules import Severity, can_submit, check_envelopes, envelope_statuses


def status_of(snapshot, budget_line):
    return next(s for s in envelope_statuses(snapshot) if s.budget_line == budget_line)


def test_envelope_status(mission_snapshot):
    s = status_of(mission_snapshot, "6371")
    assert s.authorized == 1_000_000
    assert s.programmed == 950_000  # per diem 600 000 + hébergement 350 000
    assert s.remaining == 50_000
    assert s.consumption_rate == Decimal("0.95")
    assert s.overrun == 0


def test_alert_when_envelope_almost_consumed(mission_snapshot):
    violations = check_envelopes(mission_snapshot)
    codes = {(v.code, v.budget_line) for v in violations}
    assert ("enveloppe_presque_epuisee", "6371") in codes
    assert can_submit(violations)


def test_overrun_blocks_submission(mission_snapshot):
    lines = tuple(
        replace(ln, quantity=Decimal(15)) if ln.id == "l3" else ln for ln in mission_snapshot.lines
    )
    snapshot = replace(mission_snapshot, lines=lines)
    violations = check_envelopes(snapshot)
    overrun = next(v for v in violations if v.code == "depassement_enveloppe")
    assert overrun.budget_line == "6371"
    assert overrun.severity == Severity.BLOCKING
    assert "125 000" in overrun.message
    assert set(overrun.line_ids) == {"l1", "l3"}
    assert not can_submit(violations)


def test_overrun_can_be_soft(mission_snapshot):
    lines = tuple(
        replace(ln, quantity=Decimal(15)) if ln.id == "l3" else ln for ln in mission_snapshot.lines
    )
    violations = check_envelopes(
        replace(mission_snapshot, lines=lines), overrun_severity=Severity.APPROVAL
    )
    assert can_submit(violations)


def test_unimputed_line_and_missing_envelope(mission_snapshot):
    lines = mission_snapshot.lines + (
        replace(mission_snapshot.lines[0], id="l7", budget_line=None),
        replace(mission_snapshot.lines[0], id="l8", budget_line="9999"),
    )
    violations = check_envelopes(replace(mission_snapshot, lines=lines))
    codes = {v.code for v in violations}
    assert {"ligne_non_imputee", "enveloppe_absente"} <= codes
    assert not can_submit(violations)
