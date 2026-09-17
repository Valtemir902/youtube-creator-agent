from creator_service.mcp_errors import classify_exception


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
