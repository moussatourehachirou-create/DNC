from dataclasses import replace

from app.services import nomenclature


def test_natures_loaded_from_decree():
    assert nomenclature.label_of("6013") == "Fournitures de bureau"
    assert nomenclature.label_of("6012") == "Carburants et lubrifiants"
    assert nomenclature.label_of("6114") == "Indemnités de mission à l’intérieur"
    assert nomenclature.natures()["6013"].parent == "601"
    assert len(nomenclature.natures()) > 350


def test_search():
    codes = [n.code for n in nomenclature.search("carburant")]
    assert "6012" in codes
    assert nomenclature.search("6013")[0].code == "6013"


def test_unknown_nature_is_flagged(mission_snapshot):
    assert nomenclature.check_imputations(mission_snapshot) == []
    lines = (
        *mission_snapshot.lines,
        replace(mission_snapshot.lines[0], id="x", budget_line="6371"),
    )
    [violation] = nomenclature.check_imputations(replace(mission_snapshot, lines=lines))
    assert violation.budget_line == "6371" and violation.line_ids == ("x",)
