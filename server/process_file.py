"""Eine vorhandene WAV-Datei nachträglich durch die Pipeline schicken.

Transkribiert (lokal), optional mit Sprecher-Trennung und Zusammenfassung – ganz
ohne neue Aufnahme. Das Ergebnis landet wie beim Server in `summaries/`.

Das Transkript wird gecacht (`summaries/<name>.segments.json`). Folgeläufe
(z. B. nur Sprecher-Trennung oder nur Zusammenfassung) nutzen den Cache und
transkribieren NICHT erneut.

Beispiele:
    python process_file.py recordings/meeting_20261001_152504.wav
    python process_file.py --all          # alle unverarbeiteten in recordings/

    # NUR Sprecher-Trennung nachträglich (nutzt gecachtes Transkript, schnell):
    python process_file.py --diarize-only recordings/meeting_...wav

    # erneut zusammenfassen, Transkript aus Cache (keine 20 min Whisper):
    python process_file.py --summary-only recordings/meeting_...wav

    # erzwinge neue Transkription (Cache ignorieren):
    python process_file.py --no-cache recordings/meeting_...wav
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
        description="WAV-Datei(en) nachträglich verarbeiten (mit Transkript-Cache)."
    )
    parser.add_argument("wav", nargs="*", help="Pfad(e) zu WAV-Datei(en)")
    parser.add_argument("--all", action="store_true",
                        help="alle noch nicht verarbeiteten WAVs in recordings/")
    parser.add_argument("--diarize-only", action="store_true",
                        help="nur Sprecher-Trennung (Transkript aus Cache, keine Zusammenfassung)")
    parser.add_argument("--summary-only", action="store_true",
                        help="nur Zusammenfassung (Transkript aus Cache, ohne Sprecher-Trennung)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Cache ignorieren und neu transkribieren")
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

    # Flags in process_wav-Parameter übersetzen
    kwargs: dict = {"use_cache": not args.no_cache}
    if args.diarize_only:
        kwargs.update(diarize=True, summary=False)
    if args.summary_only:
        kwargs.update(diarize=False)

    errors = 0
    for wav in targets:
        try:
            process_wav(wav, **kwargs)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"[Fehler] {wav}: {exc}")

    print(f"\nFertig: {len(targets) - errors}/{len(targets)} verarbeitet.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
