from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    return text.replace(old, new, 1)


# 1) Server-side transcription engine. Uses whisper.cpp binary/model bundled in the image.
Path("src/creator_service/media_transcription.py").write_text(r'''from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class MediaTranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaTranscriptionResult:
    text: str
    engine: str
    language: str
    chars: int


class WhisperCppTranscriber:
    """Local, tenant-safe media transcription through ffmpeg + whisper.cpp.

    The browser only needs ordinary chunked upload support, so the same path works
    on desktop and mobile browsers without relying on experimental Web Speech APIs.
    """

    def __init__(self, *, binary: str | None = None, model: str | None = None, ffmpeg: str | None = None):
        self.binary = binary or os.environ.get("YCA_WHISPER_BIN", "/opt/whisper/bin/whisper-cli")
        self.model = model or os.environ.get("YCA_WHISPER_MODEL", "/opt/whisper/models/ggml-base.bin")
        self.ffmpeg = ffmpeg or os.environ.get("YCA_FFMPEG_BIN", "/usr/bin/ffmpeg")
        self.threads = max(1, min(8, int(os.environ.get("YCA_WHISPER_THREADS", "4"))))
        self.timeout = max(60, min(7200, int(os.environ.get("YCA_TRANSCRIPTION_TIMEOUT_SECONDS", "1800"))))

    def ready(self) -> bool:
        return Path(self.binary).is_file() and os.access(self.binary, os.X_OK) and Path(self.model).is_file() and bool(shutil.which(self.ffmpeg) or Path(self.ffmpeg).is_file())

    @staticmethod
    def _tail(value: str, limit: int = 1200) -> str:
        value = (value or "").strip()
        return value[-limit:] if len(value) > limit else value

    def transcribe(self, media_path: str | Path, *, language: str = "auto") -> MediaTranscriptionResult:
        source = Path(media_path).resolve()
        if not source.is_file():
            raise MediaTranscriptionError("Arquivo de mídia não encontrado para transcrição.")
        if not self.ready():
            raise MediaTranscriptionError("Motor local de transcrição indisponível no servidor.")
        lang = (language or "auto").strip().lower()
        if not lang or len(lang) > 12:
            lang = "auto"

        with tempfile.TemporaryDirectory(prefix="yca-transcribe-") as tmp_raw:
            tmp = Path(tmp_raw)
            wav = tmp / "audio.wav"
            out_prefix = tmp / "transcript"
            ffmpeg_cmd = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ]
            try:
                ffmpeg_result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise MediaTranscriptionError("Falha ao extrair o áudio do vídeo.") from exc
            if ffmpeg_result.returncode != 0 or not wav.is_file() or wav.stat().st_size < 128:
                detail = self._tail(ffmpeg_result.stderr)
                raise MediaTranscriptionError(f"Não foi possível extrair uma faixa de áudio válida. {detail}".strip())

            whisper_cmd = [
                self.binary,
                "-m",
                self.model,
                "-f",
                str(wav),
                "-l",
                lang,
                "-t",
                str(self.threads),
                "-otxt",
                "-of",
                str(out_prefix),
                "-np",
            ]
            try:
                whisper_result = subprocess.run(whisper_cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise MediaTranscriptionError("O motor de transcrição excedeu o tempo limite ou não pôde iniciar.") from exc
            transcript_file = out_prefix.with_suffix(".txt")
            if whisper_result.returncode != 0 or not transcript_file.is_file():
                detail = self._tail(whisper_result.stderr or whisper_result.stdout)
                raise MediaTranscriptionError(f"Falha no reconhecimento de fala. {detail}".strip())
            text = " ".join(transcript_file.read_text(encoding="utf-8", errors="replace").split()).strip()
            if not text:
                raise MediaTranscriptionError("Nenhuma fala compreensível foi encontrada no vídeo.")
            return MediaTranscriptionResult(text=text, engine="whisper.cpp/base", language=lang, chars=len(text))
''', encoding="utf-8")


# 2) Build a portable ARM64/x86_64 image with ffmpeg and whisper.cpp.
Path("Dockerfile.server").write_text(r'''FROM python:3.11-slim AS whisper-builder

ARG WHISPER_CPP_REF=v1.7.6
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git cmake build-essential && \
    rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${WHISPER_CPP_REF} https://github.com/ggerganov/whisper.cpp.git /src/whisper.cpp && \
    cmake -S /src/whisper.cpp -B /src/whisper.cpp/build \
      -DBUILD_SHARED_LIBS=OFF \
      -DWHISPER_BUILD_TESTS=OFF \
      -DWHISPER_BUILD_EXAMPLES=ON \
      -DGGML_NATIVE=OFF && \
    cmake --build /src/whisper.cpp/build --config Release -j2 && \
    mkdir -p /opt/whisper/bin /opt/whisper/models && \
    cp /src/whisper.cpp/build/bin/whisper-cli /opt/whisper/bin/whisper-cli && \
    /src/whisper.cpp/models/download-ggml-model.sh base && \
    cp /src/whisper.cpp/models/ggml-base.bin /opt/whisper/models/ggml-base.bin

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    YCA_WHISPER_BIN=/opt/whisper/bin/whisper-cli \
    YCA_WHISPER_MODEL=/opt/whisper/models/ggml-base.bin \
    YCA_FFMPEG_BIN=/usr/bin/ffmpeg \
    YCA_WHISPER_THREADS=4

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --create-home --uid 10001 appuser

COPY --from=whisper-builder /opt/whisper /opt/whisper
COPY requirements-server.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements-server.txt

COPY src ./src
COPY cloud_mcp_server.py onboarding_server.py ./

RUN mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket; s=socket.create_connection(('127.0.0.1',8000),3); s.close()" || exit 1

CMD ["python", "cloud_mcp_server.py"]
''', encoding="utf-8")


# 3) Dashboard backend: async transcription job, polling, manifest metadata refresh.
path = Path("src/creator_service/dashboard_routes.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from fastapi import Depends, FastAPI, Header, HTTPException, Request, status\n",
    "from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status\n",
    "fastapi imports",
)
text = replace_once(
    text,
    "from .dashboard_store import DashboardActionStore\n",
    "from .dashboard_store import DashboardActionStore\nfrom .media_transcription import MediaTranscriptionError, WhisperCppTranscriber\n",
    "transcription import",
)

request_anchor = '''class UploadAIPlanRequest(BaseModel):\n    video_name: str = Field(min_length=1, max_length=255)\n    transcript: str = Field(default="", max_length=30000)\n    user_context: str = Field(default="", max_length=4000)\n    max_age_days: int = Field(default=30, ge=1, le=180)\n\n\n'''
request_block = request_anchor + '''class UploadAnalysisRequest(BaseModel):\n    user_context: str = Field(default="", max_length=4000)\n    max_age_days: int = Field(default=30, ge=1, le=180)\n\n\nclass UploadMetadataRequest(BaseModel):\n    title: str = Field(min_length=1, max_length=100)\n    description: str = Field(default="", max_length=5000)\n    tags: list[str] = Field(default_factory=list, max_length=12)\n    format: str = Field(default="long", pattern="^(long|short)$")\n    visibility: str = Field(default="public", pattern="^(public|unlisted|private|scheduled)$")\n    publish_at: str | None = Field(default=None, max_length=80)\n    category_id: str = Field(default="27", max_length=10)\n    default_language: str = Field(default="pt-BR", max_length=20)\n\n\n'''
text = replace_once(text, request_anchor, request_block, "upload request models")

helper_anchor = '''    def save_manifest(tenant_id: str, session_id: str, data: dict[str, Any]) -> None:\n        path = manifest_path(tenant_id, session_id)\n        temp = path.with_suffix(".tmp")\n        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")\n        temp.replace(path)\n\n'''
helper_block = helper_anchor + '''    def apply_manifest_metadata(manifest: dict[str, Any], payload: UploadMetadataRequest) -> None:\n        try:\n            tags = _clean_tags(payload.tags)\n            publish_at = _validate_schedule(payload.publish_at) if payload.visibility == "scheduled" else None\n        except ValueError as exc:\n            raise HTTPException(status_code=400, detail=str(exc)) from exc\n        manifest["metadata"] = {\n            "title": payload.title.strip(),\n            "description": payload.description.strip(),\n            "tags": tags,\n            "format": payload.format,\n            "visibility": payload.visibility,\n            "publish_at": publish_at,\n            "category_id": payload.category_id,\n            "default_language": payload.default_language,\n        }\n\n    def run_upload_analysis(tenant_id: str, session_id: str, user_context: str, max_age_days: int) -> None:\n        try:\n            manifest = load_manifest(tenant_id, session_id)\n            video_item = manifest.get("video", {})\n            if int(video_item.get("received", 0)) != int(video_item.get("size", 0)):\n                raise RuntimeError("O vídeo precisa terminar de chegar ao servidor antes da transcrição.")\n            directory = session_dir(tenant_id, session_id)\n            video_path = directory / f"video{video_item.get('suffix', '')}"\n            transcriber = WhisperCppTranscriber()\n            result = transcriber.transcribe(video_path)\n            service = service_for(tenant_id)\n            service.context.validate_youtube()\n            plan = grounded_seo_plan(\n                service,\n                source_text=result.text[:30000],\n                original_title=str(video_item.get("name", "")),\n                user_context=user_context,\n                max_age_days=max_age_days,\n                playlists=list_playlists(service._youtube()),\n            )\n            manifest = load_manifest(tenant_id, session_id)\n            manifest["analysis"] = {\n                "status": "completed",\n                "plan": plan,\n                "transcription": {\n                    "engine": result.engine,\n                    "language": result.language,\n                    "chars": result.chars,\n                },\n                "completed_at": int(time.time()),\n            }\n            save_manifest(tenant_id, session_id, manifest)\n        except Exception as exc:\n            try:\n                manifest = load_manifest(tenant_id, session_id)\n                manifest["analysis"] = {\n                    "status": "failed",\n                    "error": str(exc)[:1200],\n                    "completed_at": int(time.time()),\n                }\n                save_manifest(tenant_id, session_id, manifest)\n            except Exception:\n                pass\n\n'''
text = replace_once(text, helper_anchor, helper_block, "manifest helpers")

route_anchor = '''    @app.post("/api/dashboard/upload/finish/{session_id}")\n    async def dashboard_upload_finish(\n'''
route_block = '''    @app.put("/api/dashboard/upload/metadata/{session_id}")\n    async def dashboard_upload_metadata(\n        session_id: str,\n        payload: UploadMetadataRequest,\n        request: Request,\n        tenant: DashboardTenant = Depends(writable),\n    ) -> dict[str, Any]:\n        manifest = load_manifest(tenant.tenant_id, session_id)\n        apply_manifest_metadata(manifest, payload)\n        save_manifest(tenant.tenant_id, session_id, manifest)\n        audit(request, "dashboard_upload_metadata_updated", "success", tenant.tenant_id, {"session_id": session_id})\n        return {"ok": True}\n\n    @app.post("/api/dashboard/upload/analyze/{session_id}")\n    async def dashboard_upload_analyze_start(\n        session_id: str,\n        payload: UploadAnalysisRequest,\n        background_tasks: BackgroundTasks,\n        request: Request,\n        tenant: DashboardTenant = Depends(writable),\n    ) -> dict[str, Any]:\n        manifest = load_manifest(tenant.tenant_id, session_id)\n        video_item = manifest.get("video", {})\n        if int(video_item.get("received", 0)) != int(video_item.get("size", 0)):\n            raise HTTPException(status_code=409, detail="O vídeo ainda não terminou de chegar ao servidor.")\n        current = dict(manifest.get("analysis", {}) or {})\n        if current.get("status") in {"queued", "processing"}:\n            return {"status": current.get("status")}\n        manifest["analysis"] = {"status": "queued", "started_at": int(time.time())}\n        save_manifest(tenant.tenant_id, session_id, manifest)\n        background_tasks.add_task(run_upload_analysis, tenant.tenant_id, session_id, payload.user_context, payload.max_age_days)\n        audit(request, "dashboard_upload_analysis_started", "success", tenant.tenant_id, {"session_id": session_id})\n        return {"status": "queued"}\n\n    @app.get("/api/dashboard/upload/analyze/{session_id}")\n    async def dashboard_upload_analyze_status(\n        session_id: str,\n        tenant: DashboardTenant = Depends(readable),\n    ) -> dict[str, Any]:\n        manifest = load_manifest(tenant.tenant_id, session_id)\n        analysis = dict(manifest.get("analysis", {}) or {})\n        if not analysis:\n            return {"status": "not_started"}\n        return analysis\n\n''' + route_anchor
text = replace_once(text, route_anchor, route_block, "analysis routes")
path.write_text(text, encoding="utf-8")


# 4) MCP gets channel awareness + channel activation so GPT context follows active channel.
path = Path("src/creator_service/cloud_mcp_server.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .cloud_auth import IntrospectionTokenVerifier\n",
    "from .cloud_auth import IntrospectionTokenVerifier\nfrom .channel_accounts import activate_channel, list_channel_accounts\n",
    "mcp channel imports",
)
mcp_anchor = '''    @server.tool(\n        title="Criar link seguro de conexão",\n'''
mcp_block = '''    @server.tool(\n        title="Listar canais conectados",\n        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),\n    )\n    def list_connected_channels() -> dict[str, Any]:\n        _require_scope(READ_SCOPE)\n        _limit("read", limit=180)\n        return list_channel_accounts(_resolver().db, _tenant_id())\n\n    @server.tool(\n        title="Ativar canal conectado",\n        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=True),\n    )\n    def activate_connected_channel(channel_id: str, user_confirmed: bool) -> dict[str, Any]:\n        _require_scope(WRITE_SCOPE)\n        _limit("channel_switch", limit=30)\n        if user_confirmed is not True:\n            raise ValueError("Confirmação explícita do usuário é obrigatória para trocar o canal ativo.")\n        channel = activate_channel(_resolver().db, _tenant_id(), channel_id)\n        _audit("mcp_channel_activated", "success", {"channel_id": channel_id})\n        return {"ok": True, "active_channel": channel}\n\n''' + mcp_anchor
text = replace_once(text, mcp_anchor, mcp_block, "mcp channel tools")
path.write_text(text, encoding="utf-8")


# 5) Front-end: remove prompt fallback and make Smart Analyze upload once, poll server ASR, then reuse session for publish.
path = Path("src/creator_service/web/dashboard.html")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "let currentAction=null,rollbackAction=null,uploadSession=null,publishAction=null,lastVideos=[],lastPlaylists=[],workspaceOrigin=null;",
    "let currentAction=null,rollbackAction=null,uploadSession=null,uploadSessionFingerprint=null,publishAction=null,lastVideos=[],lastPlaylists=[],workspaceOrigin=null;",
    "dashboard state",
)
old_smart = '''$('optimizeSelectedVideo').onclick=()=>runAiOptimization($('videoId').value.trim(),$('aiVideoContext').value,$('aiVideoPlan'));$('reloadLive').onclick=loadLive;$('optimizeLive').onclick=()=>{const id=$('liveSelect').value;if(!id)return toast('Selecione uma live.',true);runAiOptimization(id,$('liveContext').value,$('livePlan'))};$('smartAnalyzeUpload').onclick=async()=>{const video=$('uploadVideo').files[0];if(!video)return toast('Escolha o vídeo primeiro.',true);const context=prompt('O motor local de transcrição ainda está sendo integrado. Informe brevemente o conteúdo real do vídeo para esta análise sem enviar o arquivo à VPS.');if(!context)return;setBusy($('smartAnalyzeUpload'),true,'Pesquisando SEO');try{const d=await api('/api/dashboard/upload/ai-plan',{method:'POST',body:JSON.stringify({video_name:video.name,transcript:'',user_context:context,max_age_days:30})});const p=d.plan||{};$('uploadTitle').value=p.title||'';$('uploadDescription').value=p.description||'';$('uploadTags').value=(p.tags||[]).join(', ');$('smartUploadHint').className='notice good';$('smartUploadHint').textContent='Plano de SEO gerado com dados recentes. Revise os campos e use o modo manual de upload enquanto o envio direto ao YouTube pelo dispositivo é integrado.';toast('SEO inteligente preparado.')}catch(e){toast(e.message,true)}finally{setBusy($('smartAnalyzeUpload'),false)}};'''
new_smart = '''$('optimizeSelectedVideo').onclick=()=>runAiOptimization($('videoId').value.trim(),$('aiVideoContext').value,$('aiVideoPlan'));$('reloadLive').onclick=loadLive;$('optimizeLive').onclick=()=>{const id=$('liveSelect').value;if(!id)return toast('Selecione uma live.',true);runAiOptimization(id,$('liveContext').value,$('livePlan'))};
function uploadFingerprint(video,thumb){return [video?.name||'',video?.size||0,video?.lastModified||0,thumb?.name||'',thumb?.size||0,thumb?.lastModified||0].join('|')}
async function waitForUploadAnalysis(sessionId){const started=Date.now();while(Date.now()-started<35*60*1000){const d=await api('/api/dashboard/upload/analyze/'+encodeURIComponent(sessionId));if(d.status==='completed')return d;if(d.status==='failed')throw new Error(d.error||'Falha na transcrição do vídeo.');$('smartUploadHint').className='notice warn';$('smartUploadHint').textContent='Transcrevendo o áudio e cruzando o conteúdo com dados recentes…';await new Promise(r=>setTimeout(r,2200))}throw new Error('A análise excedeu o tempo limite de 35 minutos.')}
$('smartAnalyzeUpload').onclick=async()=>{const video=$('uploadVideo').files[0],thumb=$('uploadThumb').files[0];if(!video)return toast('Escolha o vídeo primeiro.',true);setBusy($('smartAnalyzeUpload'),true,'Preparando análise');try{if(uploadSession){try{await api('/api/dashboard/upload/'+encodeURIComponent(uploadSession),{method:'DELETE'})}catch{}uploadSession=null;uploadSessionFingerprint=null}const start=await api('/api/dashboard/upload/start',{method:'POST',body:JSON.stringify({video_name:video.name,video_size:video.size,thumbnail_name:thumb?.name||null,thumbnail_size:thumb?.size||0,title:(video.name.replace(/\.[^.]+$/,'').slice(0,100)||'Vídeo'),description:'',tags:[],format:$('uploadFormat').value,visibility:'private',publish_at:null})});uploadSession=start.session_id;uploadSessionFingerprint=uploadFingerprint(video,thumb);let videoPct=0,thumbPct=thumb?0:1;const render=()=>{const p=Math.round((videoPct*.9+thumbPct*.1)*100);$('uploadProgress').style.width=p+'%';$('uploadProgressText').textContent=`${p}% enviado com segurança para análise`};$('smartUploadHint').className='notice';$('smartUploadHint').textContent='Enviando o vídeo em blocos. O mesmo arquivo será reutilizado se você publicar depois.';await uploadFileChunks(uploadSession,video,'video',start.chunk_size,p=>{videoPct=p;render()});if(thumb)await uploadFileChunks(uploadSession,thumb,'thumbnail',start.chunk_size,p=>{thumbPct=p;render()});await api('/api/dashboard/upload/analyze/'+encodeURIComponent(uploadSession),{method:'POST',body:JSON.stringify({user_context:'',max_age_days:30})});const d=await waitForUploadAnalysis(uploadSession);const p=d.plan||{};$('uploadTitle').value=p.title||'';$('uploadDescription').value=p.description||'';$('uploadTags').value=(p.tags||[]).join(', ');$('smartUploadHint').className='notice good';$('smartUploadHint').textContent=`Transcrição concluída (${fmt(d.transcription?.chars||0)} caracteres, ${d.transcription?.engine||'motor local'}). SEO preparado com o conteúdo real do vídeo. Revise e publique quando quiser.`;toast('Vídeo transcrito e SEO inteligente preparado.')}catch(e){$('smartUploadHint').className='notice bad';$('smartUploadHint').textContent=e.message;toast(e.message,true)}finally{setBusy($('smartAnalyzeUpload'),false)}};'''
text = replace_once(text, old_smart, new_smart, "smart analyze handler")

old_stage = '''$('stageUpload').onclick=async()=>{const video=$('uploadVideo').files[0],thumb=$('uploadThumb').files[0];if(!video)return toast('Selecione o arquivo do vídeo.',true);if(!$('uploadTitle').value.trim())return toast('Informe o título.',true);const visibility=$('uploadVisibility').value;if(visibility==='scheduled'&&!scheduleIso())return toast('Informe uma data/hora válida para agendar.',true);setBusy($('stageUpload'),true,'Preparando');$('publishMessage').className='notice';$('publishMessage').textContent='Criando sessão segura de upload...';try{const start=await api('/api/dashboard/upload/start',{method:'POST',body:JSON.stringify({video_name:video.name,video_size:video.size,thumbnail_name:thumb?.name||null,thumbnail_size:thumb?.size||0,title:$('uploadTitle').value.trim(),description:$('uploadDescription').value,tags:$('uploadTags').value.split(',').map(x=>x.trim()).filter(Boolean),format:$('uploadFormat').value,visibility,publish_at:visibility==='scheduled'?scheduleIso():null})});uploadSession=start.session_id;let videoPct=0,thumbPct=thumb?0:1;const render=()=>{const p=Math.round((videoPct*.9+thumbPct*.1)*100);$('uploadProgress').style.width=p+'%';$('uploadProgressText').textContent=`${p}% enviado para a VPS`};await uploadFileChunks(uploadSession,video,'video',start.chunk_size,p=>{videoPct=p;render()});if(thumb)await uploadFileChunks(uploadSession,thumb,'thumbnail',start.chunk_size,p=>{thumbPct=p;render()});const done=await api('/api/dashboard/upload/finish/'+encodeURIComponent(uploadSession),{method:'POST',body:'{}'});publishAction=done.action_id;$('publishDiff').innerHTML=`<div>Arquivo</div><div>${esc(done.preview.video_name)}</div><div>Título</div><div>${esc(done.preview.title)}</div><div>Formato</div><div>${esc(done.preview.format)}</div><div>Visibilidade</div><div>${esc(done.preview.visibility)}</div><div>Agendamento</div><div>${esc(done.preview.publish_at||'Agora / conforme visibilidade')}</div>`;$('publishPreview').classList.remove('hidden');$('publishMessage').className='notice good';$('publishMessage').textContent='Arquivo preparado. Ainda não foi publicado no YouTube.';render();$('publishPreview').scrollIntoView({behavior:'smooth'})}catch(e){$('publishMessage').className='notice bad';$('publishMessage').textContent=e.message;toast(e.message,true)}finally{setBusy($('stageUpload'),false)}};'''
new_stage = '''$('stageUpload').onclick=async()=>{const video=$('uploadVideo').files[0],thumb=$('uploadThumb').files[0];if(!video)return toast('Selecione o arquivo do vídeo.',true);if(!$('uploadTitle').value.trim())return toast('Informe o título.',true);const visibility=$('uploadVisibility').value;if(visibility==='scheduled'&&!scheduleIso())return toast('Informe uma data/hora válida para agendar.',true);setBusy($('stageUpload'),true,'Preparando');$('publishMessage').className='notice';$('publishMessage').textContent='Preparando sessão segura de upload...';try{const fingerprint=uploadFingerprint(video,thumb);if(uploadSession&&uploadSessionFingerprint!==fingerprint){try{await api('/api/dashboard/upload/'+encodeURIComponent(uploadSession),{method:'DELETE'})}catch{}uploadSession=null;uploadSessionFingerprint=null}if(!uploadSession){const start=await api('/api/dashboard/upload/start',{method:'POST',body:JSON.stringify({video_name:video.name,video_size:video.size,thumbnail_name:thumb?.name||null,thumbnail_size:thumb?.size||0,title:$('uploadTitle').value.trim(),description:$('uploadDescription').value,tags:$('uploadTags').value.split(',').map(x=>x.trim()).filter(Boolean),format:$('uploadFormat').value,visibility,publish_at:visibility==='scheduled'?scheduleIso():null})});uploadSession=start.session_id;uploadSessionFingerprint=fingerprint;let videoPct=0,thumbPct=thumb?0:1;const render=()=>{const p=Math.round((videoPct*.9+thumbPct*.1)*100);$('uploadProgress').style.width=p+'%';$('uploadProgressText').textContent=`${p}% enviado para a VPS`};await uploadFileChunks(uploadSession,video,'video',start.chunk_size,p=>{videoPct=p;render()});if(thumb)await uploadFileChunks(uploadSession,thumb,'thumbnail',start.chunk_size,p=>{thumbPct=p;render()})}else{$('publishMessage').textContent='Reutilizando o arquivo já enviado para a transcrição. Nenhum upload duplicado.'}await api('/api/dashboard/upload/metadata/'+encodeURIComponent(uploadSession),{method:'PUT',body:JSON.stringify({title:$('uploadTitle').value.trim(),description:$('uploadDescription').value,tags:$('uploadTags').value.split(',').map(x=>x.trim()).filter(Boolean),format:$('uploadFormat').value,visibility,publish_at:visibility==='scheduled'?scheduleIso():null,category_id:'27',default_language:'pt-BR'})});const done=await api('/api/dashboard/upload/finish/'+encodeURIComponent(uploadSession),{method:'POST',body:'{}'});publishAction=done.action_id;$('publishDiff').innerHTML=`<div>Arquivo</div><div>${esc(done.preview.video_name)}</div><div>Título</div><div>${esc(done.preview.title)}</div><div>Formato</div><div>${esc(done.preview.format)}</div><div>Visibilidade</div><div>${esc(done.preview.visibility)}</div><div>Agendamento</div><div>${esc(done.preview.publish_at||'Agora / conforme visibilidade')}</div>`;$('publishPreview').classList.remove('hidden');$('publishMessage').className='notice good';$('publishMessage').textContent='Arquivo preparado. Ainda não foi publicado no YouTube.';$('uploadProgress').style.width='100%';$('uploadProgressText').textContent='100% preparado';$('publishPreview').scrollIntoView({behavior:'smooth'})}catch(e){$('publishMessage').className='notice bad';$('publishMessage').textContent=e.message;toast(e.message,true)}finally{setBusy($('stageUpload'),false)}};'''
text = replace_once(text, old_stage, new_stage, "stage upload handler")
text = text.replace("uploadSession=null;publishAction=null;", "uploadSession=null;uploadSessionFingerprint=null;publishAction=null;", 1)
text = text.replace("publishAction=null;uploadSession=null;", "publishAction=null;uploadSession=null;uploadSessionFingerprint=null;", 1)
text = text.replace(
    "O modo inteligente não exige título preenchido. Ele usa transcrição/contexto real antes de propor título, descrição, tags, categoria e playlist. O motor local de áudio será usado quando disponível.",
    "O modo inteligente envia o arquivo em blocos, extrai apenas o áudio no servidor e transcreve com Whisper local. Funciona no PC e no celular sem depender do microfone ou de APIs experimentais do navegador.",
)
path.write_text(text, encoding="utf-8")


# 6) Tests for engine, UI, async routes and MCP channel context.
Path("tests/test_media_transcription_contract.py").write_text(r'''from pathlib import Path


def test_transcription_engine_is_server_side_and_portable():
    code = Path("src/creator_service/media_transcription.py").read_text(encoding="utf-8")
    assert "class WhisperCppTranscriber" in code
    assert "pcm_s16le" in code
    assert '"-ar",\n                "16000"' in code
    assert "subprocess.run" in code
    docker = Path("Dockerfile.server").read_text(encoding="utf-8")
    assert "whisper.cpp" in docker
    assert "ggml-base.bin" in docker
    assert "ffmpeg" in docker
    assert "GGML_NATIVE=OFF" in docker


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
''', encoding="utf-8")

print("media engine v6 patch applied")
