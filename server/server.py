"""Meeting-KI Server.

Nimmt den Audiostream des ESP32 per TCP entgegen. Der ESP startet die Aufnahme
automatisch, sobald er Strom bekommt und sich verbindet (CTRL_START). Wird der
ESP vom Strom getrennt, erkennt der Server den Abbruch und beendet + wertet die
Aufnahme automatisch aus (WAV + Transkript + Zusammenfassung).

Da ein Stromverlust oft kein sauberes TCP-Ende sendet, erkennt der Server das
Ende zusätzlich über einen Watchdog: kommt für RX_IDLE_TIMEOUT Sekunden kein
Audio mehr, gilt die Verbindung als getrennt.

Protokoll (mit Framing, muss zur Firmware passen):
    Jeder Frame:  [1 Byte Typ][4 Byte Länge, little-endian][Nutzdaten]
      Typ 0x01 = AUDIO   -> Nutzdaten = 16-Bit-PCM (mono, little-endian)
      Typ 0x02 = CONTROL -> Nutzdaten = 1 Byte (0x10=START, 0x11=STOP)

Tastatur im Server-Fenster (optionale manuelle Steuerung / Beenden):
    s + Enter   Aufnahme starten
    e + Enter   Aufnahme beenden
    q + Enter   Server beenden
"""
from __future__ import annotations

import os
import socket
import struct
import threading
import time
from datetime import datetime

from dotenv import load_dotenv

from pipeline import REC_DIR, SAMPLE_RATE, process_wav, save_wav, startup_hint

load_dotenv()

LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8888"))

# Nach so vielen Sekunden ohne empfangene Daten gilt der ESP als getrennt
# (z. B. Stromverlust ohne sauberes TCP-Ende) -> Aufnahme beenden + auswerten.
RX_IDLE_TIMEOUT = float(os.getenv("RX_IDLE_TIMEOUT", "4.0"))

# Protokoll-Konstanten
MSG_AUDIO = 0x01
MSG_CONTROL = 0x02
CTRL_START = 0x10
CTRL_STOP = 0x11


class AudioReceiver:
    """Nimmt eine ESP32-Verbindung an, parst Frames und puffert Audio."""

    def __init__(self, on_stop) -> None:
        self._lock = threading.Lock()
        self._recording = False
        self._buffer = bytearray()
        self._client_connected = False
        self._stop = threading.Event()
        self._on_stop = on_stop  # Callback(pcm_bytes) beim Beenden einer Aufnahme
        self._last_rx = 0.0      # Zeitpunkt der letzten empfangenen Daten (Watchdog)

    # --- Aufnahmesteuerung ---------------------------------------------------
    def start_recording(self) -> bool:
        with self._lock:
            if self._recording:
                return False
            self._buffer = bytearray()
            self._recording = True
        print("[Server] ⏺  Aufnahme läuft ...")
        return True

    def stop_recording(self) -> bytes:
        with self._lock:
            if not self._recording:
                return b""
            self._recording = False
            data = bytes(self._buffer)
            self._buffer = bytearray()
        print(f"[Server] ⏹  Aufnahme beendet ({len(data) / (SAMPLE_RATE * 2):.1f}s)")
        return data

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def client_connected(self) -> bool:
        return self._client_connected

    def shutdown(self) -> None:
        self._stop.set()

    # --- Netzwerk ------------------------------------------------------------
    def serve_forever(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((LISTEN_HOST, LISTEN_PORT))
        srv.listen(1)
        srv.settimeout(1.0)
        print(f"[Server] warte auf ESP32 an {LISTEN_HOST}:{LISTEN_PORT} ...")

        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            print(f"[Server] ESP32 verbunden: {addr[0]}:{addr[1]}")
            self._client_connected = True
            try:
                self._handle_client(conn)
            finally:
                self._client_connected = False
                # Falls die Verbindung mitten in einer Aufnahme abreißt:
                if self.is_recording:
                    print("[Server] Verbindung getrennt während der Aufnahme – "
                          "verarbeite bisher Empfangenes.")
                    self._on_stop(self.stop_recording())
            print("[Server] warte auf neue Verbindung ...")

        srv.close()

    def _recv_exact(self, conn: socket.socket, n: int) -> bytes | None:
        """Genau n Bytes lesen; None bei Verbindungsende oder RX-Watchdog."""
        buf = bytearray()
        while len(buf) < n and not self._stop.is_set():
            try:
                chunk = conn.recv(n - len(buf))
            except socket.timeout:
                # Watchdog: zu lange keine Daten während der Aufnahme -> getrennt
                if self.is_recording and (time.time() - self._last_rx) > RX_IDLE_TIMEOUT:
                    print("[Server] kein Audio mehr (Watchdog) – Aufnahme wird beendet.")
                    return None
                continue
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
            self._last_rx = time.time()
        return bytes(buf) if len(buf) == n else None

    def _handle_client(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        self._last_rx = time.time()
        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        with conn:
            while not self._stop.is_set():
                header = self._recv_exact(conn, 5)
                if header is None:
                    break
                msg_type = header[0]
                (length,) = struct.unpack_from("<I", header, 1)

                payload = self._recv_exact(conn, length) if length else b""
                if payload is None:
                    break

                if msg_type == MSG_AUDIO:
                    with self._lock:
                        if self._recording:
                            self._buffer.extend(payload)
                elif msg_type == MSG_CONTROL and payload:
                    self._handle_control(payload[0])

    def _handle_control(self, command: int) -> None:
        if command == CTRL_START:
            print("[Server] ESP: START (automatisch)")
            self.start_recording()
        elif command == CTRL_STOP:
            print("[Server] ESP: STOP")
            pcm = self.stop_recording()
            self._on_stop(pcm)


def _process_recording(pcm: bytes) -> None:
    """Aufnahme als WAV speichern und durch die Pipeline schicken."""
    if not pcm:
        print("[Server] Aufnahme war leer – nichts zu verarbeiten.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    wav_path = REC_DIR / f"meeting_{stamp}.wav"
    save_wav(pcm, wav_path)
    seconds = len(pcm) / (SAMPLE_RATE * 2)
    print(f"[Server] Aufnahme gespeichert: {wav_path} ({seconds:.1f}s)")

    try:
        process_wav(wav_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[Server] Verarbeitung fehlgeschlagen: {exc}")


def _process_in_background(pcm: bytes) -> None:
    """Verarbeitung in eigenem Thread, damit der Empfang nicht blockiert."""
    threading.Thread(target=_process_recording, args=(pcm,), daemon=True).start()


def main() -> None:
    startup_hint()

    receiver = AudioReceiver(on_stop=_process_in_background)
    net_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    net_thread.start()

    print("\nDer ESP startet die Aufnahme automatisch beim Verbinden; beim "
          "Trennen (Strom weg) wird sie beendet und ausgewertet.")
    print("Tastatur (optional):  s = starten | e = beenden | q = Server beenden\n")
    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "s":
                receiver.start_recording()
            elif cmd == "e":
                _process_in_background(receiver.stop_recording())
            elif cmd == "q":
                break
            elif cmd:
                print("[Server] Unbekannter Befehl. s / e / q.")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        receiver.shutdown()
        print("\n[Server] beendet.")


if __name__ == "__main__":
    main()
