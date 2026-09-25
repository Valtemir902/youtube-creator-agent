from __future__ import annotations

import pytest

from creator_service.advanced_service import AdvancedSafeCreatorService
from creator_service.mcp_errors import CreatorToolError


class _Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _VideoCategories:
    def __init__(self, *, exists=True, assignable=True):
        self.exists = exists
        self.assignable = assignable

    def list(self, *, part: str, id: str):
        assert part == "snippet"
        items = []
        if self.exists:
            items.append({"id": id, "snippet": {"assignable": self.assignable, "title": "Category"}})
        return _Request({"items": items})


class _YouTube:
    def __init__(self, *, exists=True, assignable=True):
        self._categories = _VideoCategories(exists=exists, assignable=assignable)

    def videoCategories(self):
        return self._categories


def _service(*, exists=True, assignable=True):
    service = AdvancedSafeCreatorService.__new__(AdvancedSafeCreatorService)
    service._youtube = lambda: _YouTube(exists=exists, assignable=assignable)
    return service


def _metadata(**overrides):
    value = {
        "title": "Title",
        "description": "Description",
        "tags": ["simple"],
        "categoryId": "22",
        "defaultLanguage": "pt-BR",
    }
    value.update(overrides)
    return value


def test_title_inside_official_limit():
    report = _service().validate_youtube_metadata_limits(_metadata(title="x" * 100))
    assert report["title_length"] == 100
    assert report["title_within_limit"] is True


def test_title_above_official_limit_is_blocked():
    with pytest.raises(CreatorToolError) as caught:
        _service().validate_youtube_metadata_limits(_metadata(title="x" * 101))
    assert caught.value.code == "metadata_limit_exceeded"
    assert caught.value.details["field"] == "title"


def test_description_ascii_uses_utf8_bytes():
    report = _service().validate_youtube_metadata_limits(_metadata(description="abc"))
    assert report["description_char_length"] == 3
    assert report["description_utf8_bytes"] == 3


def test_description_accents_use_more_utf8_bytes_than_characters():
    report = _service().validate_youtube_metadata_limits(_metadata(description="café"))
    assert report["description_char_length"] == 4
    assert report["description_utf8_bytes"] == 5


def test_description_emoji_uses_utf8_byte_limit():
    report = _service().validate_youtube_metadata_limits(_metadata(description="😀"))
    assert report["description_char_length"] == 1
    assert report["description_utf8_bytes"] == 4


def test_description_above_5000_utf8_bytes_is_blocked_before_write():
    with pytest.raises(CreatorToolError) as caught:
        _service().validate_youtube_metadata_limits(_metadata(description="é" * 2501))
    assert caught.value.code == "metadata_limit_exceeded"
    assert caught.value.details["field"] == "description"
    assert caught.value.details["actual"] == 5002


def test_tags_simple_count_commas_between_items():
    report = _service().validate_youtube_metadata_limits(_metadata(tags=["abc", "def"]))
    assert report["tags_raw_characters"] == 6
    assert report["tags_separator_characters"] == 1
    assert report["tags_effective_youtube_length"] == 7


def test_tags_with_spaces_count_virtual_quotes():
    report = _service().validate_youtube_metadata_limits(_metadata(tags=["Foo Baz"]))
    assert report["items"][0]["raw_length"] == 7
    assert report["items"][0]["effective_length"] == 9
    assert report["tags_effective_youtube_length"] == 9


def test_tags_with_accents_count_characters_not_utf8_bytes():
    report = _service().validate_youtube_metadata_limits(_metadata(tags=["café"]))
    assert report["items"][0]["raw_length"] == 4
    assert report["items"][0]["effective_length"] == 4


def test_tags_exact_500_effective_characters_are_allowed():
    report = _service().validate_youtube_metadata_limits(_metadata(tags=["x" * 500]))
    assert report["tags_effective_youtube_length"] == 500
    assert report["tags_within_limit"] is True


def test_tags_above_500_effective_characters_are_blocked():
    with pytest.raises(CreatorToolError) as caught:
        _service().validate_youtube_metadata_limits(_metadata(tags=["x" * 501]))
    assert caught.value.code == "metadata_limit_exceeded"
    assert caught.value.details["field"] == "tags"


def test_duplicate_and_empty_tag_diagnostics_are_explicit():
    report = _service().validate_youtube_metadata_limits(_metadata(tags=["dup", "dup", ""]))
    assert report["duplicate_tags"] == ["dup"]
    assert report["empty_tag_indexes"] == [2]


def test_invalid_category_is_rejected_before_video_update():
    with pytest.raises(CreatorToolError) as caught:
        _service(exists=False).validate_youtube_metadata_limits(_metadata(categoryId="999"))
    assert caught.value.code == "invalid_request"
    assert caught.value.details["category_valid"] is False


def test_non_assignable_category_is_rejected():
    with pytest.raises(CreatorToolError) as caught:
        _service(assignable=False).validate_youtube_metadata_limits(_metadata(categoryId="22"))
    assert caught.value.code == "invalid_request"
    assert caught.value.details["category_assignable"] is False


def test_default_language_format_is_validated_without_rewrite():
    report = _service().validate_youtube_metadata_limits(_metadata(defaultLanguage="pt-BR"))
    assert report["defaultLanguage"] == "pt-BR"
    assert report["default_language_valid"] is True


def test_invalid_default_language_is_rejected():
    with pytest.raises(CreatorToolError) as caught:
        _service().validate_youtube_metadata_limits(_metadata(defaultLanguage="pt_BR!"))
    assert caught.value.code == "invalid_request"
    assert caught.value.details["default_language_valid"] is False


def test_known_failing_production_payload_is_well_inside_official_limits():
    title = "Café Sem Irrigação na Seca: Como Conservo Umidade e Protejo a Lavoura"
    description = """Como cuidar de uma lavoura de café sem irrigação durante a seca? Neste vídeo mostro o manejo que faço para conservar umidade no solo e reduzir o estresse hídrico do cafezal.

Você vai ver:
• por que faço a poda do café;
• como aproveito restos vegetais no pé das plantas;
• cobertura do solo para ajudar a reter umidade;
• por que mantenho o mato entre as linhas por um período;
• como a roçada devolve material vegetal ao solo;
• manejo simples para enfrentar períodos de calor e pouca chuva.

O objetivo é manter o solo mais protegido e ajudar o café a sofrer menos nos períodos secos, aproveitando materiais que já existem na própria lavoura.

Este conteúdo mostra uma experiência prática da roça. O manejo ideal pode variar conforme solo, clima, variedade e sistema de produção da sua região.

#Cafeicultura #LavouraDeCafe #CafeNaSeca"""
    tags = [
        "café sem irrigação",
        "como proteger café da seca",
        "lavoura de café",
        "cafeicultura",
        "seca no café",
        "manejo do café",
        "estresse hídrico no café",
        "cobertura do solo café",
        "cobertura morta no café",
        "umidade no solo",
        "manejo na seca",
        "poda do café",
        "roçada no café",
        "vida na roça",
        "Made in Roça",
    ]
    report = _service().validate_youtube_metadata_limits(
        _metadata(title=title, description=description, tags=tags)
    )
    assert report["title_length"] == 69
    assert report["description_char_length"] == 838
    assert report["description_utf8_bytes"] == 875
    assert report["tags_count"] == 15
    assert report["tags_raw_characters"] == 245
    assert report["tags_effective_youtube_length"] == 287
    assert report["title_within_limit"] is True
    assert report["description_within_limit"] is True
    assert report["tags_within_limit"] is True
    assert report["category_valid"] is True
    assert report["default_language_valid"] is True
