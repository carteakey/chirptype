#!/usr/bin/env python3
"""
ChirpType — desktop dictation powered by a local speech-to-text model

Hotkey: Right Option (⌥) on macOS; Right Alt on Windows
  Press-and-hold : Hold while speaking, release to transcribe.
  Double-tap     : Double-tap to lock recording, tap once more to transcribe.
"""

from __future__ import annotations

import threading
import queue
import sys
import time
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
import numpy as np
import sounddevice as sd
from pynput import keyboard
from pynput.keyboard import Key

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

if IS_MACOS:
    import mlx.core as mx
    import rumps
    from parakeet_mlx import from_pretrained
elif IS_WINDOWS:
    import pyperclip
    import pystray
    from PIL import Image
    from faster_whisper import WhisperModel
else:
    raise RuntimeError("ChirpType currently supports macOS and Windows.")

# ---------------------------------------------------------------------------
# Edit these to customise
# ---------------------------------------------------------------------------

VERSION           = "0.1.0"
MAC_MODEL_NAME     = "mlx-community/parakeet-tdt-0.6b-v3"
WINDOWS_MODEL_NAME = "base.en"
MODEL_NAME         = MAC_MODEL_NAME if IS_MACOS else WINDOWS_MODEL_NAME
CHUNK_DURATION     = 1.0   # seconds per audio chunk
HOLD_THRESHOLD     = 0.3   # seconds to distinguish tap from hold
DOUBLE_TAP_WINDOW  = 0.4   # seconds to wait for a second tap

ICON_PATH     = Path(__file__).parent / "icon.png"
ICON_REC_PATH = Path(__file__).parent / "icon_rec.png"
LOG_PATH      = Path.home() / ".chirptype_log.txt"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICON_IDLE       = "idle"
ICON_RECORDING  = "recording"
ICON_PROCESSING = "processing"

IDLE              = "idle"
HOLD_RECORDING    = "hold_recording"
FIRST_TAP_PENDING = "first_tap_pending"
LOCKED_RECORDING  = "locked_recording"

_SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "stop":  "/System/Library/Sounds/Pop.aiff",
} if IS_MACOS else {}

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

state = IDLE
state_lock = threading.Lock()
recording = threading.Event()
audio_queue: queue.Queue = queue.Queue()
hotkey_active = False
hotkey_press_time = 0.0
_double_tap_timer: threading.Timer | None = None

quiet_mode = False
input_device: str | int | None = None
silence_duration: float = 0.0
last_audio_time: float = 0.0
session_words: int = 0

app: "ChirpTypeApp | None" = None


# ---------------------------------------------------------------------------
# Tray/menu bar app
# ---------------------------------------------------------------------------

if IS_MACOS:
    class ChirpTypeApp(rumps.App):
        def __init__(self):
            super().__init__("ChirpType", title="", icon=str(ICON_PATH),
                             template=True, quit_button="Quit")
            self.title_item  = rumps.MenuItem(f"ChirpType v{VERSION}")
            self.words_item  = rumps.MenuItem("Words: 0")
            self.last_item   = rumps.MenuItem("Last: —")
            self.copy_item   = rumps.MenuItem("Copy last transcript", callback=self._copy_last)
            self._last_text  = ""
            self.menu = [self.title_item, None, self.words_item, self.last_item, self.copy_item]

        def _copy_last(self, _) -> None:
            if self._last_text:
                copy_to_clipboard(self._last_text)

        def update_transcript(self, text: str, words: int) -> None:
            self._last_text       = text
            self.words_item.title = f"Words: {words}"
            preview = text[:60] + ("…" if len(text) > 60 else "")
            self.last_item.title  = f"Last: {preview}"

        def notify(self, message: str) -> None:
            try:
                rumps.notification("ChirpType", "", message, sound=False)
            except Exception:
                pass
else:
    class ChirpTypeApp:
        """Windows system-tray wrapper for the same small app surface."""

        def __init__(self):
            self._last_text = ""
            self._words = 0
            self.tray = pystray.Icon(
                "ChirpType",
                self._load_icon(ICON_PATH),
                f"ChirpType v{VERSION}",
                menu=pystray.Menu(
                    pystray.MenuItem(
                        lambda _: f"ChirpType v{VERSION}",
                        None,
                        enabled=False,
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem(
                        lambda _: f"Words: {self._words}",
                        None,
                        enabled=False,
                    ),
                    pystray.MenuItem(
                        self._last_label,
                        None,
                        enabled=False,
                    ),
                    pystray.MenuItem("Copy last transcript", self._copy_last),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Quit", self._quit),
                ),
            )

        @staticmethod
        def _load_icon(path: Path):
            with Image.open(path) as image:
                return image.convert("RGBA")

        def _last_label(self, _) -> str:
            preview = self._last_text[:60] + ("…" if len(self._last_text) > 60 else "")
            return f"Last: {preview or '—'}"

        def _copy_last(self, _, __) -> None:
            if self._last_text:
                copy_to_clipboard(self._last_text)

        def _quit(self, icon, _) -> None:
            icon.stop()

        def update_transcript(self, text: str, words: int) -> None:
            self._last_text = text
            self._words = words
            self.tray.update_menu()

        def notify(self, message: str) -> None:
            try:
                self.tray.notify(message, "ChirpType")
            except Exception:
                pass

        def run(self) -> None:
            self.tray.run()


def set_menu_bar_state(state_name: str) -> None:
    if app is None:
        return
    if IS_MACOS:
        if state_name == ICON_IDLE:
            app.icon     = str(ICON_PATH)
            app.template = True
        else:
            app.icon     = str(ICON_REC_PATH)
            app.template = False
        app.title = ""
    else:
        app.tray.icon = app._load_icon(
            ICON_PATH if state_name == ICON_IDLE else ICON_REC_PATH
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    if not quiet_mode:
        print(msg)


def play_sound(name: str) -> None:
    if IS_WINDOWS:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_OK if name == "start" else winsound.MB_ICONASTERISK)
        except Exception:
            pass
        return

    path = _SOUNDS.get(name)
    if path:
        subprocess.Popen(["afplay", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log_transcription(text: str) -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")


def copy_to_clipboard(text: str) -> None:
    if IS_WINDOWS:
        pyperclip.copy(text)
    else:
        subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE).communicate(
            text.encode("utf-8")
        )


def read_clipboard() -> str:
    if IS_WINDOWS:
        return pyperclip.paste()
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout


def start_recording() -> None:
    global last_audio_time
    _drain_audio_queue()
    last_audio_time = time.time()
    recording.set()
    play_sound("start")
    set_menu_bar_state(ICON_RECORDING)
    log("\n[Recording...] Speak now")


def stop_recording(mode_msg: str = "") -> None:
    recording.clear()
    play_sound("stop")
    set_menu_bar_state(ICON_PROCESSING)
    log(f"\n[Stopped{f' ({mode_msg})' if mode_msg else ''}] Processing...")


def _check_silence() -> None:
    global state
    if silence_duration <= 0 or last_audio_time == 0.0:
        return
    if time.time() - last_audio_time >= silence_duration:
        with state_lock:
            if state in (HOLD_RECORDING, FIRST_TAP_PENDING, LOCKED_RECORDING):
                stop_recording("silence")
                state = IDLE


# ---------------------------------------------------------------------------
# Hotkey state machine
# ---------------------------------------------------------------------------

def on_hotkey_activated() -> None:
    global state, hotkey_press_time, hotkey_active, _double_tap_timer

    with state_lock:
        if hotkey_active:
            return
        hotkey_active = True
        hotkey_press_time = time.time()

        if state == IDLE:
            start_recording()
            state = HOLD_RECORDING

        elif state == FIRST_TAP_PENDING:
            if _double_tap_timer is not None:
                _double_tap_timer.cancel()
                _double_tap_timer = None
            state = LOCKED_RECORDING
            log("[Locked] Tap hotkey again to stop")

        elif state == LOCKED_RECORDING:
            stop_recording("locked mode")
            state = IDLE


def on_hotkey_deactivated() -> None:
    global state, hotkey_active, _double_tap_timer

    with state_lock:
        if not hotkey_active:
            return
        hotkey_active = False
        held = time.time() - hotkey_press_time

        if state == HOLD_RECORDING:
            if held >= HOLD_THRESHOLD:
                stop_recording("hold mode")
                state = IDLE
            else:
                state = FIRST_TAP_PENDING
                log("[Tap] Double-tap to lock, or wait to cancel")
                _double_tap_timer = threading.Timer(DOUBLE_TAP_WINDOW, _double_tap_timeout)
                _double_tap_timer.start()


def _double_tap_timeout() -> None:
    global state, _double_tap_timer
    with state_lock:
        if state == FIRST_TAP_PENDING:
            stop_recording("single tap")
            state = IDLE
        _double_tap_timer = None


def on_press(key) -> None:
    if key == Key.alt_r:
        on_hotkey_activated()


def on_release(key) -> None:
    if key == Key.alt_r:
        on_hotkey_deactivated()


# ---------------------------------------------------------------------------
# Clipboard + paste
# ---------------------------------------------------------------------------

def copy_and_paste(text: str) -> None:
    global session_words

    try:
        copy_to_clipboard(text)
        verify = read_clipboard()
    except Exception as exc:
        print(f"ERROR: Clipboard unavailable: {exc}", file=sys.stderr)
        return

    log("Copied to clipboard")

    if verify != text:
        print("ERROR: Clipboard verification failed", file=sys.stderr)
        return

    time.sleep(0.3)

    if IS_WINDOWS:
        try:
            controller = keyboard.Controller()
            with controller.pressed(Key.ctrl):
                controller.press("v")
            paste_succeeded = True
            paste_error = ""
        except Exception as exc:
            paste_succeeded = False
            paste_error = str(exc)
    else:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using {command down}'],
            capture_output=True, text=True, timeout=5,
        )
        paste_succeeded = result.returncode == 0
        paste_error = result.stderr.strip()

    if paste_succeeded:
        log("Pasted successfully")
        session_words += len(text.split())
        log_transcription(text)
        preview = text[:60] + ("…" if len(text) > 60 else "")
        if app is not None:
            app.update_transcript(text, session_words)
            app.notify(preview)
    else:
        if "not allowed assistive access" in paste_error.lower():
            print("ERROR: Accessibility permission denied. "
                  "System Settings → Privacy & Security → Accessibility", file=sys.stderr)
        else:
            print(f"ERROR: Paste failed: {paste_error}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Audio + transcription
# ---------------------------------------------------------------------------

def audio_callback(indata, frames, time_info, status) -> None:
    global last_audio_time
    if status and not quiet_mode:
        print(f"Audio status: {status}", file=sys.stderr)
    if recording.is_set():
        audio_queue.put(indata.copy())
        if silence_duration > 0 and float(np.sqrt(np.mean(indata ** 2))) > 0.01:
            last_audio_time = time.time()


def transcription_loop(model, sample_rate: int) -> None:
    chunk_size = int(sample_rate * CHUNK_DURATION)

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype='float32',
                        blocksize=chunk_size, callback=audio_callback,
                        device=input_device):
        while True:
            recording.wait()

            if IS_WINDOWS:
                _transcribe_windows_recording(model)
                continue

            with model.transcribe_stream(context_size=(256, 256)) as transcriber:
                while not audio_queue.empty():
                    audio_queue.get()

                last_text = ""

                while recording.is_set():
                    _check_silence()
                    try:
                        transcriber.add_audio(mx.array(audio_queue.get(timeout=0.1).flatten()))
                        result = transcriber.result
                        if result.text != last_text and not quiet_mode:
                            print(f"\rTranscription: {result.text}", end='', flush=True)
                            last_text = result.text
                    except queue.Empty:
                        continue

                result = transcriber.result
                if not quiet_mode:
                    print(f"\n\nFinal: {result.text}\n")

                if result.text.strip():
                    copy_and_paste(result.text)

                set_menu_bar_state(ICON_IDLE)


def _drain_audio_queue() -> list[np.ndarray]:
    chunks = []
    while True:
        try:
            chunks.append(audio_queue.get_nowait())
        except queue.Empty:
            return chunks


def _transcribe_windows_recording(model) -> None:
    """Transcribe one completed recording with faster-whisper."""
    chunks = []

    while recording.is_set():
        _check_silence()
        try:
            chunks.append(audio_queue.get(timeout=0.1))
        except queue.Empty:
            continue

    # Capture callbacks that raced with recording.clear().
    chunks.extend(_drain_audio_queue())
    set_menu_bar_state(ICON_PROCESSING)

    if not chunks:
        set_menu_bar_state(ICON_IDLE)
        return

    audio = np.concatenate(chunks, axis=0).flatten()
    log("\nTranscribing...")

    try:
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=True,
        )
        text = "".join(segment.text for segment in segments).strip()
    except Exception as exc:
        print(f"ERROR: Transcription failed: {exc}", file=sys.stderr)
        set_menu_bar_state(ICON_IDLE)
        return

    if text:
        log(f"\nFinal: {text}\n")
        copy_and_paste(text)

    set_menu_bar_state(ICON_IDLE)


# ---------------------------------------------------------------------------
# Startup + entry point
# ---------------------------------------------------------------------------

def _startup() -> None:
    set_menu_bar_state(ICON_PROCESSING)
    log(f"\nLoading {MODEL_NAME}...")

    if IS_MACOS:
        model = from_pretrained(MODEL_NAME)
        sample_rate = model.preprocessor_config.sample_rate
    else:
        model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        sample_rate = 16_000

    if not quiet_mode:
        hotkey_name = "Right Option (⌥)" if IS_MACOS else "Right Alt"
        backend_name = "parakeet-mlx" if IS_MACOS else "faster-whisper"
        print(f"Ready — {sample_rate} Hz | {backend_name} | hotkey: {hotkey_name}")

    set_menu_bar_state(ICON_IDLE)
    keyboard.Listener(on_press=on_press, on_release=on_release).start()
    threading.Thread(target=transcription_loop, args=(model, sample_rate), daemon=True).start()


def main() -> None:
    global quiet_mode, input_device, silence_duration, app

    parser = argparse.ArgumentParser(description='ChirpType — local desktop dictation')
    parser.add_argument('--quiet', '-q', action='store_true')
    parser.add_argument('--device', default=None, help='Input device name or index')
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--silence', type=float, default=0.0, metavar='SECS',
                        help='Auto-stop after N seconds of silence (0 = off)')
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        sys.exit(0)

    quiet_mode       = args.quiet
    silence_duration = args.silence
    input_device     = args.device
    if isinstance(input_device, str) and input_device.isdigit():
        input_device = int(input_device)

    app = ChirpTypeApp()
    threading.Thread(target=_startup, daemon=True).start()
    app.run()


if __name__ == "__main__":
    main()
