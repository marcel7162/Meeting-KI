"""Lokale Transkription von Audio mit faster-whisper.

Der Rohton verlässt damit nicht das eigene Netz – nur der fertige Text geht
später zur Zusammenfassung an Claude.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from faster_whisper import WhisperModel


@dataclass
class Segment:
    start: float  # Sekunden
    end: float    # Sekunden
    text: str


@lru_cache(maxsize=1)
def _load_model() -> WhisperModel:
    """Whisper-Modell laden (nur einmal, danach gecacht)."""
    model_size = os.getenv("WHISPER_MODEL", "small")
    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    print(f"[Whisper] lade Modell '{model_size}' ({device}/{compute_type}) ...")
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def transcribe_segments(wav_path: str) -> list[Segment]:
    """Transkribiert eine WAV-Datei und liefert Segmente mit Zeitstempeln."""
    model = _load_model()
    language = os.getenv("WHISPER_LANGUAGE", "").strip() or None

    print(f"[Whisper] transkribiere {wav_path} ...")
    segments, info = model.transcribe(wav_path, language=language, vad_filter=True)

    print(f"[Whisper] erkannte Sprache: {info.language} "
          f"(Wahrscheinlichkeit {info.language_probability:.2f})")

    result: list[Segment] = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            result.append(Segment(start=seg.start, end=seg.end, text=text))
    return result


def segments_to_text(segments: list[Segment]) -> str:
    """Segmente zu einem zusammenhängenden Text verbinden (ohne Sprecher)."""
    return " ".join(s.text for s in segments).strip()


def transcribe(wav_path: str) -> str:
    """Bequemer Aufruf: transkribiert und gibt reinen Text zurück."""
    return segments_to_text(transcribe_segments(wav_path))


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) != 2:
        print("Aufruf: python transcribe.py <datei.wav>")
        raise SystemExit(1)
    print(transcribe(sys.argv[1]))
