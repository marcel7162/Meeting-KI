"""Eine vorhandene WAV-Datei nachträglich durch die Pipeline schicken.

Transkribiert (lokal) und – falls aktiviert – fasst mit Claude zusammen, ganz
ohne neue Aufnahme. Das Ergebnis landet wie beim Server in `summaries/`.

Beispiele:
    python process_file.py recordings/meeting_20261001_152504.wav
    python process_file.py C:\\pfad\\zu\\aufnahme.wav

    # alle noch nicht verarbeiteten Aufnahmen auf einmal:
    python process_file.py --all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline import REC_DIR, SUM_DIR, process_wav, startup_hint

load_dotenv()


def _pending_wavs() -> list[Path]:
    """Alle WAVs in recordings/, zu denen es noch keine .md gibt."""
    wavs = sorted(REC_DIR.glob("*.wav"))
    return [w for w in wavs if not (SUM_DIR / f"{w.stem}.md").exists()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WAV-Datei(en) nachträglich transkribieren/zusammenfassen."
    )
    parser.add_argument("wav", nargs="*", help="Pfad(e) zu WAV-Datei(en)")
    parser.add_argument("--all", action="store_true",
                        help="alle noch nicht verarbeiteten WAVs in recordings/")
    args = parser.parse_args()

    startup_hint()

    if args.all:
        targets = _pending_wavs()
        if not targets:
            print("Keine unverarbeiteten WAV-Dateien in recordings/ gefunden.")
            return 0
    elif args.wav:
        targets = [Path(p) for p in args.wav]
    else:
        parser.print_help()
        return 1

    errors = 0
    for wav in targets:
        try:
            process_wav(wav)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"[Fehler] {wav}: {exc}")

    print(f"\nFertig: {len(targets) - errors}/{len(targets)} verarbeitet.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
