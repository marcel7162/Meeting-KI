"""Optionale Sprecher-Trennung (Diarization) mit pyannote.audio.

Ordnet Audio-Abschnitten Sprecher zu ("SPRECHER_1", "SPRECHER_2", ...). Die
Modelle kennen keine Namen, nur unterschiedliche Stimmen. Mit einem einzelnen,
weit entfernten MEMS-Mikrofon ist die Genauigkeit begrenzt.

Voraussetzungen (siehe README):
    pip install -r requirements-diarization.txt
    HUGGINGFACE_TOKEN in .env  (Modell-Nutzungsbedingungen auf huggingface.co
    für "pyannote/speaker-diarization-3.1" akzeptieren)
    ENABLE_DIARIZATION=true in .env
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from transcribe import Segment


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@lru_cache(maxsize=1)
def _load_pipeline():
    from pyannote.audio import Pipeline

    token = os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        raise RuntimeError("HUGGINGFACE_TOKEN fehlt (in .env eintragen).")

    print("[Diarize] lade pyannote-Pipeline ...")
    model_id = "pyannote/speaker-diarization-3.1"
    # pyannote 3.1+ nennt den Parameter "token"; aeltere Versionen "use_auth_token".
    try:
        pipeline = Pipeline.from_pretrained(model_id, token=token)
    except TypeError:
        pipeline = Pipeline.from_pretrained(model_id, use_auth_token=token)
    if pipeline is None:
        raise RuntimeError(
            "pyannote-Pipeline konnte nicht geladen werden. Hast du die "
            "Nutzungsbedingungen von 'pyannote/speaker-diarization-3.1' UND "
            "'pyannote/segmentation-3.0' auf huggingface.co akzeptiert und ist der "
            "HUGGINGFACE_TOKEN gueltig?"
        )

    # Auf GPU verschieben, falls verfügbar
    try:
        import torch

        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
            print("[Diarize] nutze GPU (cuda)")
    except Exception:  # noqa: BLE001
        pass

    return pipeline


def _wav_to_tensor(wav_path: str):
    """WAV selbst mit NumPy laden und als Torch-Tensor (1, N) @16 kHz liefern.

    Vermeidet, dass pyannote die Datei über torchaudio/torchcodec lädt – das
    bräuchte sonst installiertes FFmpeg (libtorchcodec_core*.dll)."""
    import torch

    from transcribe import WHISPER_SAMPLE_RATE, _load_audio

    audio = _load_audio(wav_path)  # float32-Mono @16 kHz
    waveform = torch.from_numpy(audio).unsqueeze(0)  # Form (1, Samples)
    return {"waveform": waveform, "sample_rate": WHISPER_SAMPLE_RATE}


def diarize(wav_path: str) -> list[SpeakerTurn]:
    """Ermittelt, wann welcher Sprecher aktiv war."""
    pipeline = _load_pipeline()
    print(f"[Diarize] analysiere Sprecher in {wav_path} ...")
    annotation = pipeline(_wav_to_tensor(wav_path))

    turns: list[SpeakerTurn] = []
    for segment, _, speaker in annotation.itertracks(yield_label=True):
        turns.append(SpeakerTurn(start=segment.start, end=segment.end, speaker=speaker))

    # Sprecher-Kennungen zu lesbaren Labels vereinheitlichen
    mapping: dict[str, str] = {}
    for turn in turns:
        if turn.speaker not in mapping:
            mapping[turn.speaker] = f"SPRECHER_{len(mapping) + 1}"
    for turn in turns:
        turn.speaker = mapping[turn.speaker]

    print(f"[Diarize] {len(mapping)} Sprecher erkannt.")
    return turns


def _speaker_for(segment: Segment, turns: list[SpeakerTurn]) -> str:
    """Ordnet einem Transkript-Segment den am stärksten überlappenden Sprecher zu."""
    best_speaker = "SPRECHER_?"
    best_overlap = 0.0
    for turn in turns:
        overlap = min(segment.end, turn.end) - max(segment.start, turn.start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker
    return best_speaker


def label_segments(segments: list[Segment], turns: list[SpeakerTurn]) -> str:
    """Baut ein Transkript mit Sprecher-Präfixen und fasst aufeinanderfolgende
    Beiträge desselben Sprechers zusammen."""
    lines: list[str] = []
    current_speaker = None
    current_text: list[str] = []

    def flush() -> None:
        if current_speaker is not None and current_text:
            lines.append(f"{current_speaker}: {' '.join(current_text).strip()}")

    for seg in segments:
        speaker = _speaker_for(seg, turns)
        if speaker != current_speaker:
            flush()
            current_speaker = speaker
            current_text = [seg.text]
        else:
            current_text.append(seg.text)
    flush()

    return "\n".join(lines).strip()
