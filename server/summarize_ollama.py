"""Starke, strukturierte Zusammenfassung mit einem lokalen LLM über Ollama.

Läuft komplett lokal (kein Claude, kein Internet). Nutzt den gleichen
strukturierten Prompt wie das Claude-Backend und liefert daher gegliederte
Abschnitte (Überblick, Entscheidungen, To-dos ...).

Es werden KEINE zusätzlichen Python-Pakete gebraucht – nur Ollama selbst:

    1. Ollama installieren:         https://ollama.com/download
    2. Modell laden (einmalig):     ollama pull qwen2.5:7b-instruct
    3. In .env:                     SUMMARY_BACKEND=ollama
                                    OLLAMA_MODEL=qwen2.5:7b-instruct

Längere/stärkere Modelle (brauchen mehr RAM/VRAM, dafür bessere Qualität):
    qwen2.5:14b-instruct , llama3.1:8b , mistral-small , qwen2.5:32b-instruct
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from prompts import (
    CHUNK_NOTES_PROMPT,
    PROMPT_TEMPLATE,
    REDUCE_PROMPT,
    SYSTEM_PROMPT,
)

# Ab wie vielen Wörtern auf Map-Reduce (abschnittsweise) umgeschaltet wird.
MAX_WORDS_SINGLE_PASS = 4000
# Wortanzahl pro Abschnitt im Map-Reduce-Modus.
WORDS_PER_CHUNK = 2500


def _host() -> str:
    return os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def _model() -> str:
    return os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")


def _timeout() -> float:
    return float(os.getenv("OLLAMA_TIMEOUT", "600"))


def _num_ctx() -> int:
    # Kontextfenster. Großzügig, damit auch lange Abschnitte reinpassen.
    return int(os.getenv("OLLAMA_NUM_CTX", "8192"))


def _chat(user_prompt: str) -> str:
    """Eine Anfrage an die Ollama-Chat-API; gibt den Antworttext zurück."""
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": _num_ctx()},
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"{_host()}/api/chat"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Ollama nicht erreichbar unter {_host()} ({exc}). "
            "Läuft 'ollama serve' und ist das Modell per 'ollama pull' geladen?"
        ) from exc

    if "error" in body:
        raise RuntimeError(f"Ollama-Fehler: {body['error']}")
    return body.get("message", {}).get("content", "").strip()


def _chunks(words: list[str], size: int) -> list[str]:
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def summarize_ollama(transcript: str) -> str:
    """Erzeugt eine strukturierte Markdown-Zusammenfassung via Ollama."""
    transcript = (transcript or "").strip()
    if not transcript:
        return "_(Kein Transkript vorhanden – nichts zusammenzufassen.)_"

    words = transcript.split()
    model = _model()

    if len(words) <= MAX_WORDS_SINGLE_PASS:
        print(f"[Ollama] erstelle Zusammenfassung mit '{model}' (ein Durchgang) ...")
        result = _chat(PROMPT_TEMPLATE.format(transcript=transcript))
    else:
        chunks = _chunks(words, WORDS_PER_CHUNK)
        print(f"[Ollama] langes Transkript – Map-Reduce über {len(chunks)} Abschnitte "
              f"mit '{model}' ...")
        notes = []
        for idx, chunk in enumerate(chunks, 1):
            print(f"[Ollama]   Abschnitt {idx}/{len(chunks)} ...")
            notes.append(_chat(CHUNK_NOTES_PROMPT.format(transcript=chunk)))
        print("[Ollama]   finale Zusammenfassung ...")
        result = _chat(REDUCE_PROMPT.format(notes="\n\n".join(notes)))

    footer = f"\n\n> _Lokal erstellt mit Ollama (`{model}`), ohne Claude._"
    return result + footer


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) != 2:
        print("Aufruf: python summarize_ollama.py <transkript.txt>")
        raise SystemExit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        print(summarize_ollama(fh.read()))
