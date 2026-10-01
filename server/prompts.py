"""Gemeinsame Prompts für die Zusammenfassung (Claude- und Ollama-Backend)."""

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

Falls das Transkript Sprecher-Kennungen wie "SPRECHER_1:" enthält, ordne
Aussagen und Aufgaben – wo sinnvoll – den jeweiligen Sprechern zu (die echten
Namen sind nicht bekannt).

Bleibe nah am Transkript und erfinde nichts dazu. Wenn das Transkript zu kurz
oder unverständlich ist, weise darauf hin."""

# Für sehr lange Meetings (Map-Reduce): Notizen je Abschnitt erstellen.
CHUNK_NOTES_PROMPT = """Dies ist EIN AUSSCHNITT aus einem längeren Meeting-Transkript.

<ausschnitt>
{transcript}
</ausschnitt>

Fasse die wesentlichen Inhalte dieses Ausschnitts in knappen deutschen
Stichpunkten zusammen (Themen, Ergebnisse, Entscheidungen, Aufgaben, offene
Fragen – soweit im Ausschnitt vorhanden). Nur Stichpunkte, keine Einleitung."""

# Reduce-Schritt: aus den gesammelten Notizen die finale Struktur bauen.
REDUCE_PROMPT = """Unten stehen stichpunktartige Notizen aus den einzelnen
Abschnitten EINES Meetings (in Reihenfolge).

<notizen>
{notes}
</notizen>

Erstelle daraus EINE zusammenhängende, strukturierte Zusammenfassung des
gesamten Meetings mit folgenden Abschnitten (als Markdown, lasse leere
Abschnitte weg):

## Kurzüberblick
## Wichtigste Punkte
## Entscheidungen
## Aufgaben / To-dos
## Offene Fragen

Fasse Dopplungen zusammen und bleibe nah an den Notizen."""
