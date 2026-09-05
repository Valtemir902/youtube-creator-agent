from src.intelligence.youtube_research import _competition_label, _demand_label


def test_competition_labels():
    assert _competition_label(80) == "baixa"
    assert _competition_label(55) == "média"
    assert _competition_label(20) == "alta"


def test_demand_labels():
    assert _demand_label(80) == "alta"
    assert _demand_label(55) == "média"
    assert _demand_label(20) == "baixa"
