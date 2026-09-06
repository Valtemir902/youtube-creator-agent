from pathlib import Path


def test_transcription_engine_is_server_side_and_portable():
    code = Path("src/creator_service/media_transcription.py").read_text(encoding="utf-8")
    assert "class WhisperCppTranscriber" in code
    assert "pywhispercpp.model" in code
    assert "imageio_ffmpeg" in code
    assert "pcm_s16le" in code
    assert '"-ar",\n                "16000"' in code
    assert "subprocess.run" in code
    docker = Path("Dockerfile.server").read_text(encoding="utf-8")
    assert "apt-get" not in docker
    assert "YCA_WHISPER_MODEL=base" in docker
    assert "Model('base'" in docker
    requirements = Path("requirements-server.txt").read_text(encoding="utf-8")
    assert "pywhispercpp==1.5.1" in requirements
    assert "imageio-ffmpeg==0.6.0" in requirements


def test_dashboard_smart_analysis_no_longer_uses_manual_prompt():
    html = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    assert "O motor local de transcrição ainda está sendo integrado" not in html
    assert "waitForUploadAnalysis" in html
    assert "/api/dashboard/upload/analyze/" in html
    assert "/api/dashboard/upload/metadata/" in html
    assert "uploadSessionFingerprint" in html
    assert "Nenhum upload duplicado" in html


def test_backend_has_async_analysis_and_polling_contract():
    code = Path("src/creator_service/dashboard_routes.py").read_text(encoding="utf-8")
    assert "BackgroundTasks" in code
    assert '@app.post("/api/dashboard/upload/analyze/{session_id}")' in code
    assert '@app.get("/api/dashboard/upload/analyze/{session_id}")' in code
    assert '@app.put("/api/dashboard/upload/metadata/{session_id}")' in code
    assert "run_upload_analysis" in code
    assert '"status": "completed"' in code
    assert '"status": "failed"' in code


def test_mcp_exposes_channel_context_tools_for_gpt():
    code = Path("src/creator_service/cloud_mcp_server.py").read_text(encoding="utf-8")
    assert "def list_connected_channels" in code
    assert "def activate_connected_channel" in code
    assert "user_confirmed is not True" in code
    assert "activate_channel(_resolver().db, _tenant_id(), channel_id)" in code
