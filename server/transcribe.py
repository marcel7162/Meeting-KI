"""Lokale Transkription von Audio mit faster-whisper.

Der Rohton verlässt damit nicht das eigene Netz – nur der fertige Text geht
später zur Zusammenfassung an Claude.
"""
from __future__ import annotations

import os
import wave
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from faster_whisper import WhisperModel

WHISPER_SAMPLE_RATE = 16000  # faster-whisper erwartet 16 kHz mono


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


def _load_audio(wav_path: str) -> np.ndarray:
    """Liest eine PCM-WAV mit der Standardbibliothek als float32-Mono bei 16 kHz.

    Bewusst ohne PyAV/ffmpeg, um Versionskonflikte (`av.open metadata_errors`)
    zu vermeiden. Unterstützt 8/16/32-bit-PCM, mono oder stereo."""
    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sampwidth == 1:        # 8-bit PCM ist vorzeichenlos (0..255)
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 2:      # 16-bit
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:      # 32-bit
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Nicht unterstützte WAV-Bittiefe: {sampwidth * 8} bit")

    if n_channels > 1:        # auf Mono mischen
        data = data.reshape(-1, n_channels).mean(axis=1)

    if framerate != WHISPER_SAMPLE_RATE and data.size:  # auf 16 kHz resamplen
        new_len = int(round(data.size * WHISPER_SAMPLE_RATE / framerate))
        if new_len > 0:
            old_idx = np.linspace(0.0, 1.0, data.size, endpoint=False)
            new_idx = np.linspace(0.0, 1.0, new_len, endpoint=False)
            data = np.interp(new_idx, old_idx, data).astype(np.float32)

    return np.ascontiguousarray(data, dtype=np.float32)


def transcribe_segments(wav_path: str) -> list[Segment]:
    """Transkribiert eine WAV-Datei und liefert Segmente mit Zeitstempeln."""
    model = _load_model()
    language = os.getenv("WHISPER_LANGUAGE", "").strip() or None

    print(f"[Whisper] transkribiere {wav_path} ...")
    audio = _load_audio(wav_path)
    segments, info = model.transcribe(audio, language=language, vad_filter=True)

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
