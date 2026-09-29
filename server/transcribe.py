"""Lokale Transkription von Audio mit faster-whisper.

Der Rohton verlässt damit nicht das eigene Netz – nur der fertige Text geht
später zur Zusammenfassung an Claude.
"""
from __future__ import annotations

import os
from functools import lru_cache

from faster_whisper import WhisperModel


@lru_cache(maxsize=1)
def _load_model() -> WhisperModel:
    """Whisper-Modell laden (nur einmal, danach gecacht)."""
    model_size = os.getenv("WHISPER_MODEL", "small")
    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    print(f"[Whisper] lade Modell '{model_size}' ({device}/{compute_type}) ...")
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def transcribe(wav_path: str) -> str:
    """Transkribiert eine WAV-Datei und gibt den zusammenhängenden Text zurück."""
    model = _load_model()
    language = os.getenv("WHISPER_LANGUAGE", "").strip() or None

    print(f"[Whisper] transkribiere {wav_path} ...")
    segments, info = model.transcribe(wav_path, language=language, vad_filter=True)

    print(f"[Whisper] erkannte Sprache: {info.language} "
          f"(Wahrscheinlichkeit {info.language_probability:.2f})")

    parts = [seg.text.strip() for seg in segments]
    text = " ".join(p for p in parts if p)
    return text.strip()


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) != 2:
        print("Aufruf: python transcribe.py <datei.wav>")
        raise SystemExit(1)
    print(transcribe(sys.argv[1]))
