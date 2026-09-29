"""Zusammenfassung eines Meeting-Transkripts mit Claude (Anthropic-API)."""
from __future__ import annotations

import os

import anthropic

SYSTEM_PROMPT = (
    "Du bist ein Assistent, der Meeting-Mitschriften auswertet. "
    "Du erhältst das Roh-Transkript eines Meetings (automatisch per Spracherkennung "
    "erzeugt, daher können Namen/Wörter fehlerhaft sein). Erstelle eine klare, "
    "sachliche Zusammenfassung auf Deutsch."
)

PROMPT_TEMPLATE = """Hier ist das Transkript eines Meetings:

<transkript>
{transcript}
</transkript>

Erstelle eine strukturierte Zusammenfassung mit folgenden Abschnitten
(als Markdown, lasse leere Abschnitte weg):

## Kurzüberblick
Zwei bis drei Sätze, worum es im Meeting ging.

## Wichtigste Punkte
- Die zentralen besprochenen Themen und Ergebnisse als Aufzählung.

## Entscheidungen
- Getroffene Entscheidungen (falls vorhanden).

## Aufgaben / To-dos
- Konkrete nächste Schritte, wenn möglich mit verantwortlicher Person.

## Offene Fragen
- Ungeklärte Punkte (falls vorhanden).

Bleibe nah am Transkript und erfinde nichts dazu. Wenn das Transkript zu kurz
oder unverständlich ist, weise darauf hin."""


def summarize(transcript: str) -> str:
    """Fasst ein Transkript zusammen und gibt Markdown zurück."""
    transcript = (transcript or "").strip()
    if not transcript:
        return "_(Kein Transkript vorhanden – die Aufnahme enthielt keinen erkennbaren Text.)_"

    client = anthropic.Anthropic()  # liest ANTHROPIC_API_KEY aus der Umgebung
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    print(f"[Claude] erstelle Zusammenfassung mit Modell '{model}' ...")
    message = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": PROMPT_TEMPLATE.format(transcript=transcript)}
        ],
    )

    return "".join(block.text for block in message.content if block.type == "text").strip()


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) != 2:
        print("Aufruf: python summarize.py <transkript.txt>")
        raise SystemExit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        print(summarize(fh.read()))
