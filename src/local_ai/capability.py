from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
import os
import platform
import shutil
import subprocess
from typing import Any


class CapabilityProfile(str, Enum):
    NATIVE_ONLY = "native_only"
    LOCAL_LITE = "local_lite"
    LOCAL_STANDARD = "local_standard"
    LOCAL_PRO = "local_pro"


@dataclass(frozen=True)
class HardwareSnapshot:
    os_name: str
    architecture: str
    cpu_count: int
    ram_mb: int | None
    gpu_name: str | None
    vram_mb: int | None
    nvidia_available: bool
    ollama_available: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ram_mb() -> int | None:
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            state = MEMORYSTATUSEX()
            state.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                return int(state.ullTotalPhys // (1024 * 1024))
        except Exception:
            return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        return int(page_size * pages // (1024 * 1024))
    except Exception:
        return None


def _nvidia_gpu() -> tuple[str | None, int | None, bool]:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return None, None, False
    try:
        result = subprocess.run(
            [
                binary,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=4,
        )
        first = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        if not first:
            return None, None, False
        name, memory = [part.strip() for part in first.rsplit(",", 1)]
        return name or None, int(float(memory)), True
    except Exception:
        return None, None, False


def probe_hardware() -> HardwareSnapshot:
    gpu_name, vram_mb, nvidia = _nvidia_gpu()
    return HardwareSnapshot(
        os_name=platform.system() or os.name,
        architecture=platform.machine() or "unknown",
        cpu_count=max(1, os.cpu_count() or 1),
        ram_mb=_ram_mb(),
        gpu_name=gpu_name,
        vram_mb=vram_mb,
        nvidia_available=nvidia,
        ollama_available=shutil.which("ollama") is not None,
    )


def classify_hardware(snapshot: HardwareSnapshot) -> CapabilityProfile:
    """Choose a conservative local inference profile.

    We intentionally require a supported NVIDIA GPU for automatic local-model
    activation. CPU-only devices keep the native deterministic engine instead
    of silently turning a phone or weak laptop into a space heater.
    """

    if not snapshot.nvidia_available or not snapshot.vram_mb:
        return CapabilityProfile.NATIVE_ONLY

    ram = snapshot.ram_mb or 0
    vram = snapshot.vram_mb
    if vram >= 8192 and ram >= 16384 and snapshot.cpu_count >= 8:
        return CapabilityProfile.LOCAL_PRO
    if vram >= 4096 and ram >= 8192 and snapshot.cpu_count >= 4:
        return CapabilityProfile.LOCAL_STANDARD
    if vram >= 2048 and ram >= 6144:
        return CapabilityProfile.LOCAL_LITE
    return CapabilityProfile.NATIVE_ONLY
