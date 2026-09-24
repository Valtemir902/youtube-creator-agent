from creator_service.mcp_errors import classify_exception, error_response, tool_error


def test_legacy_verified_partial_write_runtime_error_is_structured():
    error = RuntimeError(
        "O YouTube não confirmou todos os campos solicitados (title, categoryId). "
        "A alteração foi revertida automaticamente e a restauração foi verificada."
    )
    assert classify_exception(error).code == "partial_write_detected"


def test_legacy_unverified_restore_runtime_error_is_uncertain():
    error = RuntimeError(
        "O YouTube persistiu um estado parcial e a restauração automática não pôde ser confirmada. "
        "Novas alterações devem permanecer bloqueadas até uma releitura segura."
    )
    assert classify_exception(error).code == "write_state_uncertain"


def test_rollback_incomplete_preserves_field_level_evidence_in_error_response():
    details = {
        "restored_and_verified": False,
        "expected_snapshot": {"title": "old", "description": "old", "tags": ["old"], "categoryId": "22", "defaultLanguage": "pt-BR"},
        "observed_snapshot": {"title": "old", "description": "old", "tags": ["new"], "categoryId": "22", "defaultLanguage": "pt-BR"},
        "mismatched_fields": ["tags"],
        "field_matches": {
            "title_matches": True,
            "description_matches": True,
            "tags_match": False,
            "category_matches": True,
            "default_language_matches": True,
        },
    }
    response = error_response(tool_error("rollback_incomplete", details=details))
    assert response["success"] is False
    assert response["error"]["code"] == "rollback_incomplete"
    assert response["error"]["details"] == details
