import pytest

from creator_service.native_mode import _dedupe_keywords, _recommended_format


def test_dedupe_keywords_normalizes_and_limits():
    values = ["  vida   na roça ", "VIDA NA ROÇA", "rotina no sítio"] + [f"tema {i}" for i in range(30)]
    result = _dedupe_keywords(values)
    assert result[0] == "vida na roça"
    assert result[1] == "rotina no sítio"
    assert len(result) == 20
    assert len({item.casefold() for item in result}) == len(result)


def test_dedupe_keywords_rejects_empty_input():
    with pytest.raises(ValueError):
        _dedupe_keywords([" ", "a"])


def test_recommended_format_uses_observed_channel_mix():
    assert _recommended_format(0.70, 0.30) == "short"
    assert _recommended_format(0.20, 0.80) == "long"
    assert _recommended_format(0.55, 0.45) == "mixed"
