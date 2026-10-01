"""Gemeinsame Verarbeitungs-Pipeline für Meeting-KI.

Wird vom Server (Live-Aufnahme) und vom Skript `process_file.py`
(nachträgliche Verarbeitung einer WAV-Datei) genutzt:

    WAV  ->  Transkription (lokal)  ->  [optional Sprecher-Trennung]
         ->  [optional Zusammenfassung via Claude]  ->  Markdown-Datei
"""
from __future__ import annotations

import os
import wave
from pathlib import Path

from dotenv import load_dotenv

from transcribe import transcribe_segments, segments_to_text

load_dotenv()


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


# Sprecher-Trennung ist optional und standardmäßig aus.
ENABLE_DIARIZATION = _env_flag("ENABLE_DIARIZATION", "false")

# Zusammenfassung an/aus.
ENABLE_SUMMARY = _env_flag("ENABLE_SUMMARY", "true")

# Backend für die Zusammenfassung:
#   claude       -> Anthropic-API (braucht ANTHROPIC_API_KEY)
#   huggingface  -> lokales transformers-Modell (kein Claude, kein Internet nach Download)
#   none         -> keine Zusammenfassung
SUMMARY_BACKEND = os.getenv("SUMMARY_BACKEND", "claude").strip().lower()

SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))

BASE_DIR = Path(__file__).resolve().parent
REC_DIR = BASE_DIR / "recordings"
SUM_DIR = BASE_DIR / "summaries"
REC_DIR.mkdir(exist_ok=True)
SUM_DIR.mkdir(exist_ok=True)


def save_wav(pcm: bytes, path: Path) -> None:
    """16-Bit-Mono-PCM als WAV-Datei schreiben."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16 Bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


def _wav_seconds(wav_path: Path) -> float:
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or SAMPLE_RATE
            return frames / float(rate)
    except Exception:  # noqa: BLE001
        return 0.0


def build_transcript(wav_path: Path) -> str:
    """Transkript erzeugen – optional mit Sprecher-Labels."""
    segments = transcribe_segments(str(wav_path))

    if ENABLE_DIARIZATION:
        try:
            from diarize import diarize, label_segments
            turns = diarize(str(wav_path))
            return label_segments(segments, turns)
        except Exception as exc:  # noqa: BLE001
            print(f"[Pipeline] Sprecher-Trennung fehlgeschlagen ({exc}) – "
                  "erstelle Transkript ohne Sprecher.")

    return segments_to_text(segments)


def _make_summary(transcript: str) -> tuple[str, bool]:
    """Zusammenfassung erzeugen, wenn aktiviert UND API-Key vorhanden."""
    if not ENABLE_SUMMARY or SUMMARY_BACKEND in ("none", "off", ""):
        print("[Pipeline] Zusammenfassung übersprungen.")
        return "_(Zusammenfassung deaktiviert.)_", False

    if SUMMARY_BACKEND in ("claude", "anthropic"):
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("[Pipeline] Zusammenfassung übersprungen (kein ANTHROPIC_API_KEY).")
            return "_(Zusammenfassung übersprungen – kein ANTHROPIC_API_KEY gesetzt.)_", False
        try:
            from summarize import summarize
            return summarize(transcript), True
        except Exception as exc:  # noqa: BLE001
            print(f"[Pipeline] Claude-Zusammenfassung fehlgeschlagen: {exc}")
            return "_(Zusammenfassung fehlgeschlagen – siehe Transkript unten.)_", False

    if SUMMARY_BACKEND in ("ollama", "local-llm"):
        try:
            from summarize_ollama import summarize_ollama
            return summarize_ollama(transcript), True
        except Exception as exc:  # noqa: BLE001
            print(f"[Pipeline] Ollama-Zusammenfassung fehlgeschlagen: {exc}")
            return f"_(Ollama-Zusammenfassung fehlgeschlagen: {exc})_", False

    if SUMMARY_BACKEND in ("huggingface", "hf", "transformers"):
        try:
            from summarize_local import summarize_local
            return summarize_local(transcript), True
        except Exception as exc:  # noqa: BLE001
            print(f"[Pipeline] Lokale HF-Zusammenfassung fehlgeschlagen: {exc}")
            return "_(Lokale Zusammenfassung fehlgeschlagen – siehe Transkript unten.)_", False

    print(f"[Pipeline] Unbekanntes SUMMARY_BACKEND '{SUMMARY_BACKEND}' – übersprungen.")
    return f"_(Unbekanntes SUMMARY_BACKEND: {SUMMARY_BACKEND})_", False


def process_wav(wav_path: str | Path) -> Path:
    """Eine WAV-Datei komplett verarbeiten und die Markdown-Datei schreiben.

    Gibt den Pfad der erzeugten Markdown-Datei zurück. Die Transkription kann
    eine Exception werfen (vom Aufrufer zu behandeln)."""
    wav_path = Path(wav_path)
    if not wav_path.is_file():
        raise FileNotFoundError(f"WAV-Datei nicht gefunden: {wav_path}")

    seconds = _wav_seconds(wav_path)
    title = wav_path.stem
    md_path = SUM_DIR / f"{title}.md"

    print(f"[Pipeline] verarbeite {wav_path.name} ({seconds:.1f}s) ...")
    transcript = build_transcript(wav_path)
    summary, did_summary = _make_summary(transcript)

    summary_block = f"{summary}\n\n---\n\n" if summary else ""
    md = (
        f"# {title}\n\n"
        f"- Aufnahme: `{wav_path.name}`\n"
        f"- Dauer: {seconds:.1f} Sekunden\n"
        f"- Sprecher-Trennung: {'ja' if ENABLE_DIARIZATION else 'nein'}\n"
        f"- Zusammenfassung: {'ja' if did_summary else 'nein'}\n\n"
        f"{summary_block}"
        f"## Vollständiges Transkript\n\n"
        f"{transcript or '_(kein Text erkannt)_'}\n"
    )
    md_path.write_text(md, encoding="utf-8")
    print(f"[Pipeline] ✅ geschrieben: {md_path}")
    return md_path


def startup_hint() -> None:
    """Einmalige Konsolen-Info zum Verarbeitungs-Modus."""
    if not ENABLE_SUMMARY or SUMMARY_BACKEND in ("none", "off", ""):
        print("[Hinweis] Zusammenfassung aus – nur lokale Transkription.")
    elif SUMMARY_BACKEND in ("claude", "anthropic"):
        if os.getenv("ANTHROPIC_API_KEY"):
            print("[Hinweis] Zusammenfassung via Claude (Anthropic-API).")
        else:
            print("[Hinweis] SUMMARY_BACKEND=claude, aber kein ANTHROPIC_API_KEY – "
                  "Zusammenfassung wird übersprungen.")
    elif SUMMARY_BACKEND in ("ollama", "local-llm"):
        print(f"[Hinweis] Zusammenfassung lokal via Ollama "
              f"('{os.getenv('OLLAMA_MODEL', 'qwen2.5:7b-instruct')}', kein Claude).")
    elif SUMMARY_BACKEND in ("huggingface", "hf", "transformers"):
        print("[Hinweis] Zusammenfassung lokal via HuggingFace (kein Claude).")
    else:
        print(f"[Warnung] Unbekanntes SUMMARY_BACKEND '{SUMMARY_BACKEND}'.")

    if ENABLE_DIARIZATION:
        if os.getenv("HUGGINGFACE_TOKEN"):
            print("[Hinweis] Sprecher-Trennung aktiv (pyannote, lokal).")
        else:
            print("[Warnung] ENABLE_DIARIZATION=true, aber HUGGINGFACE_TOKEN fehlt – "
                  "Sprecher-Trennung wird fehlschlagen.")
