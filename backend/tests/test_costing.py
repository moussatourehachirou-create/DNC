from decimal import Decimal

import pytest

from app.engines.costing import (
    PriceCandidate,
    PriceSource,
    detect_anomaly,
    line_cost,
    median_price,
    resolve_price,
)


def test_line_cost_matches_cahier_des_charges_example():
    assert line_cost(Decimal(20), 30_000) == 600_000
    assert line_cost(Decimal(300), 700) == 210_000
    assert line_cost(Decimal(10), 35_000) == 350_000
    assert line_cost(Decimal(50), 2_000) == 100_000


def test_line_cost_frequency_and_rounding():
    assert line_cost(Decimal("2.5"), 1_001, Decimal(4)) == 10_010
    assert line_cost(Decimal("0.5"), 3) == 2  # 1,5 arrondi au franc supérieur


def test_line_cost_rejects_negative():
    with pytest.raises(ValueError):
        line_cost(Decimal(-1), 100)


def test_resolve_price_follows_priority_and_unit():
    candidates = [
        PriceCandidate(PriceSource.HISTORIQUE, 32_000, "jour", "médiane 2024-2026"),
        PriceCandidate(PriceSource.REPERTOIRE, 30_000, "jour", "RPR 26.2 / 01.02.003"),
        PriceCandidate(PriceSource.STRUCTURE, 28_000, "mois", "grille interne"),
    ]
    resolution = resolve_price(candidates, unit="jour")
    assert resolution is not None
    assert resolution.source == PriceSource.REPERTOIRE
    assert resolution.unit_price == 30_000
    assert "e-répertoire" in resolution.explanation
    assert not resolution.needs_review


def test_resolve_price_flags_ai_estimate():
    resolution = resolve_price([PriceCandidate(PriceSource.ESTIMATION_IA, 5_000, "unité")], "unité")
    assert resolution is not None and resolution.needs_review


def test_resolve_price_none_when_no_candidate():
    assert resolve_price([], "jour") is None


def test_detect_anomaly():
    anomaly = detect_anomaly(45_000, 30_000)
    assert anomaly is not None
    assert anomaly.deviation == Decimal("0.5")
    assert "50 % au-dessus" in anomaly.explanation
    assert detect_anomaly(33_000, 30_000) is None
    assert detect_anomaly(20_000, 30_000) is not None


def test_median_price():
    assert median_price([]) is None
    assert median_price([3, 1, 2]) == 2
    assert median_price([1, 2, 3, 4]) == 3  # 2,5 arrondi


def test_price_range_from_e_repertoire():
    from app.engines.costing import PriceRange, check_against_range

    bloc_note = PriceRange("6013 3321 128 1114", 600, 969)
    assert check_against_range(800, bloc_note) is None
    above = check_against_range(1_200, bloc_note)
    assert above is not None and "borne supérieure" in above.explanation
    assert above.reference_price == 969
    below = check_against_range(500, bloc_note)
    assert below is not None and "borne inférieure" in below.explanation
