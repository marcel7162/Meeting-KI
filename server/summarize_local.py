"""Lokale Zusammenfassung mit einem HuggingFace-Modell (ohne Claude).

Nutzt die `transformers`-Summarization-Pipeline mit einem deutschen Modell.
Läuft komplett lokal (nach dem einmaligen Modell-Download kein Internet nötig).

Hinweis zur Erwartung: Ein kleines lokales Summarizer-Modell liefert eine
kompakte, zusammenhängende Zusammenfassung – aber keine zuverlässig
strukturierten Abschnitte (Entscheidungen, To-dos) wie ein großes LLM.

Voraussetzungen:
    pip install -r requirements-local-summary.txt
    In .env:  SUMMARY_BACKEND=huggingface
    Optional: HF_SUMMARY_MODEL=<modellname>
"""
from __future__ import annotations

import os
from functools import lru_cache

# Standardmodell: deutsches (mehrsprachiges) Summarization-Modell.
DEFAULT_MODEL = "T-Systems-onsite/mt5-small-sum-de-en-v2"

# Grobe Zerlegung des Transkripts in Blöcke (Wörter pro Block). Kleine mT5-Modelle
# verarbeiten nur begrenzt Eingabe – lieber in Blöcken zusammenfassen.
WORDS_PER_CHUNK = 350


@lru_cache(maxsize=1)
def _load_model():
    """Modell + Tokenizer direkt laden (ohne pipeline(), versionsunabhängig)."""
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    model_name = os.getenv("HF_SUMMARY_MODEL", DEFAULT_MODEL)
    print(f"[HF-Summary] lade Modell '{model_name}' ...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    if device == "cuda":
        print("[HF-Summary] nutze GPU (cuda)")
    return tokenizer, model, device


def _chunks(words: list[str], size: int) -> list[str]:
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def _summarize_text(text: str, max_length: int, min_length: int) -> str:
    import torch

    tokenizer, model, device = _load_model()
    inputs = tokenizer(
        text, return_tensors="pt", truncation=True, max_length=512
    ).to(device)
    with torch.no_grad():
        summary_ids = model.generate(
            **inputs,
            max_length=max_length,
            min_length=min_length,
            num_beams=4,
            no_repeat_ngram_size=3,
            length_penalty=1.0,
        )
    return tokenizer.decode(summary_ids[0], skip_special_tokens=True).strip()


def summarize_local(transcript: str) -> str:
    """Erzeugt eine lokale Zusammenfassung als Markdown."""
    transcript = (transcript or "").strip()
    if not transcript:
        return "_(Kein Transkript vorhanden – nichts zusammenzufassen.)_"

    words = transcript.split()
    chunks = _chunks(words, WORDS_PER_CHUNK) if len(words) > WORDS_PER_CHUNK else [transcript]

    print(f"[HF-Summary] fasse {len(chunks)} Abschnitt(e) zusammen ...")
    partial = []
    for idx, chunk in enumerate(chunks, 1):
        try:
            partial.append(_summarize_text(chunk, max_length=130, min_length=25))
        except Exception as exc:  # noqa: BLE001
            print(f"[HF-Summary] Abschnitt {idx} fehlgeschlagen: {exc}")

    if not partial:
        return "_(Lokale Zusammenfassung konnte nicht erzeugt werden.)_"

    # Gesamtüberblick: bei mehreren Abschnitten die Teil-Zusammenfassungen erneut bündeln.
    if len(partial) == 1:
        overview = partial[0]
    else:
        try:
            overview = _summarize_text(" ".join(partial), max_length=180, min_length=40)
        except Exception:  # noqa: BLE001
            overview = " ".join(partial)

    md = ["## Kurzüberblick", "", overview]
    if len(partial) > 1:
        md += ["", "## Abschnittsweise", ""]
        md += [f"- {p}" for p in partial]
    md += [
        "",
        "> _Lokal erstellt mit HuggingFace "
        f"(`{os.getenv('HF_SUMMARY_MODEL', DEFAULT_MODEL)}`), ohne Claude._",
    ]
    return "\n".join(md)


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) != 2:
        print("Aufruf: python summarize_local.py <transkript.txt>")
        raise SystemExit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        print(summarize_local(fh.read()))
