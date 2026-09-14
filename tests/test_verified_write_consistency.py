from __future__ import annotations

import pytest

from creator_service.verified_advanced_service import VerifiedAdvancedSafeCreatorService


def _snippet(*, title="Title", description="Description", tags=None):
    return {
        "title": title,
        "description": description,
        "tags": list(tags or []),
        "categoryId": "22",
        "defaultLanguage": None,
    }


def test_metadata_normalizer_preserves_more_than_twelve_tags():
    tags = [f"tag {index}" for index in range(25)]
    normalized = VerifiedAdvancedSafeCreatorService._normalize_metadata_payload(
        video_id="video-1",
        title="Title",
        description="Description",
        tags=tags,
        current=_snippet(tags=tags),
    )
    assert normalized["tags"] == tags
    assert len(normalized["tags"]) == 25


def test_metadata_normalizer_rejects_aggregate_tag_budget():
    tags = ["x" * 260, "y" * 260]
    with pytest.raises(ValueError, match="500 caracteres"):
        VerifiedAdvancedSafeCreatorService._normalize_metadata_payload(
            video_id="video-1",
            title="Title",
            description="Description",
            tags=tags,
            current=_snippet(),
        )


def test_semantic_comparison_tolerates_only_harmless_text_normalization():
    expected = _snippet(
        title="Meu   vídeo",
        description="linha 1\r\nlinha 2\n\n",
        tags=["tag um", "tag dois"],
    )
    actual = _snippet(
        title="Meu vídeo",
        description="linha 1\nlinha 2",
        tags=["tag um", "tag dois"],
    )
    assert VerifiedAdvancedSafeCreatorService._mismatches(actual, expected) == []
    assert set(VerifiedAdvancedSafeCreatorService._exact_differences(actual, expected)) == {"title", "description"}


def test_wait_for_snippet_retries_until_eventual_consistency(monkeypatch):
    service = object.__new__(VerifiedAdvancedSafeCreatorService)
    expected = _snippet(tags=["a", "b"])
    observations = [
        _snippet(title="old", tags=["a", "b"]),
        _snippet(tags=["a", "b"]),
    ]
    sleeps = []

    monkeypatch.setattr(service, "_current_video_snippet", lambda _video_id: observations.pop(0))
    monkeypatch.setattr("creator_service.verified_advanced_service.time.sleep", lambda seconds: sleeps.append(seconds))

    observed, mismatches, exact, attempts = service._wait_for_snippet(
        "video-1",
        expected,
        (0.0, 1.0, 2.0),
    )
    assert observed == expected
    assert mismatches == []
    assert exact == []
    assert attempts == 2
    assert sleeps == [1.0]
