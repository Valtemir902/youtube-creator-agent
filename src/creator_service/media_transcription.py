from __future__ import annotations

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
