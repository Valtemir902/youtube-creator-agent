from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class MediaTranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaTranscriptionResult:
    text: str
    engine: str
    language: str
    chars: int


@lru_cache(maxsize=2)
def _model(model_name: str, threads: int):
    from pywhispercpp.model import Model

    return Model(
        model_name,
        n_threads=threads,
        print_progress=False,
        print_realtime=False,
        print_timestamps=False,
    )


class WhisperCppTranscriber:
    """Server-side transcription for desktop and mobile browser uploads.

    ffmpeg comes from the imageio-ffmpeg wheel and whisper.cpp from the
    pywhispercpp wheel, avoiding OS package-manager dependencies on the VPS.
    """

    def __init__(self, *, model: str | None = None):
        self.model_name = (model or os.environ.get("YCA_WHISPER_MODEL", "base")).strip() or "base"
        self.threads = max(1, min(8, int(os.environ.get("YCA_WHISPER_THREADS", "4"))))
        self.timeout = max(60, min(7200, int(os.environ.get("YCA_TRANSCRIPTION_TIMEOUT_SECONDS", "1800"))))

    @staticmethod
    def ffmpeg_binary() -> str:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe

            return str(get_ffmpeg_exe())
        except Exception as exc:
            raise MediaTranscriptionError("FFmpeg empacotado não está disponível no servidor.") from exc

    def ready(self) -> bool:
        try:
            ffmpeg = Path(self.ffmpeg_binary())
            if not ffmpeg.is_file():
                return False
            _model(self.model_name, self.threads)
            return True
        except Exception:
            return False

    @staticmethod
    def _tail(value: str, limit: int = 1200) -> str:
        value = (value or "").strip()
        return value[-limit:] if len(value) > limit else value

    def transcribe(self, media_path: str | Path, *, language: str = "auto") -> MediaTranscriptionResult:
        source = Path(media_path).resolve()
        if not source.is_file():
            raise MediaTranscriptionError("Arquivo de mídia não encontrado para transcrição.")
        lang = (language or "auto").strip().lower()
        if not lang or len(lang) > 12:
            lang = "auto"

        with tempfile.TemporaryDirectory(prefix="yca-transcribe-") as tmp_raw:
            wav = Path(tmp_raw) / "audio.wav"
            ffmpeg_cmd = [
                self.ffmpeg_binary(),
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
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise MediaTranscriptionError("Falha ao extrair o áudio do vídeo.") from exc
            if result.returncode != 0 or not wav.is_file() or wav.stat().st_size < 128:
                detail = self._tail(result.stderr)
                raise MediaTranscriptionError(f"Não foi possível extrair uma faixa de áudio válida. {detail}".strip())

            try:
                model = _model(self.model_name, self.threads)
                options = {} if lang == "auto" else {"language": lang}
                segments = model.transcribe(str(wav), **options)
            except Exception as exc:
                raise MediaTranscriptionError(f"Falha no reconhecimento de fala: {exc}") from exc

            text = " ".join(
                str(getattr(segment, "text", "")).strip()
                for segment in segments
                if str(getattr(segment, "text", "")).strip()
            ).strip()
            if not text:
                raise MediaTranscriptionError("Nenhuma fala compreensível foi encontrada no vídeo.")
            return MediaTranscriptionResult(
                text=text,
                engine=f"pywhispercpp/{self.model_name}",
                language=lang,
                chars=len(text),
            )
