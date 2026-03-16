#!/usr/bin/env python3
"""
ChirpType — macOS menu bar dictation powered by parakeet-mlx

Hotkey: Right Option (⌥ right)
  Press-and-hold : Hold while speaking, release to transcribe.
  Double-tap     : Double-tap to lock recording, tap once more to transcribe.
"""

import threading
import queue
import sys
import time
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
import numpy as np
import mlx.core as mx
import rumps
import sounddevice as sd
from pynput import keyboard
from pynput.keyboard import Key
from parakeet_mlx import from_pretrained

# ---------------------------------------------------------------------------
# Edit these to customise
# ---------------------------------------------------------------------------

MODEL_NAME        = "mlx-community/parakeet-tdt-0.6b-v3"
CHUNK_DURATION    = 1.0   # seconds per audio chunk
HOLD_THRESHOLD    = 0.3   # seconds to distinguish tap from hold
DOUBLE_TAP_WINDOW = 0.4   # seconds to wait for a second tap

ICON_PATH = Path(__file__).parent / "icon.png"
LOG_PATH  = Path.home() / ".chirptype_log.txt"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ICON_IDLE       = ""       # icon only — title cleared when icon is present
ICON_RECORDING  = " rec "
ICON_PROCESSING = " ··· "

IDLE              = "idle"
HOLD_RECORDING    = "hold_recording"
FIRST_TAP_PENDING = "first_tap_pending"
LOCKED_RECORDING  = "locked_recording"

_SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "stop":  "/System/Library/Sounds/Pop.aiff",
}

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
# Menu bar app
# ---------------------------------------------------------------------------

class ChirpTypeApp(rumps.App):
    def __init__(self):
        icon = str(ICON_PATH) if ICON_PATH.exists() else None
        super().__init__("ChirpType", title=" ct " if not icon else "",
                         icon=icon, template=True, quit_button="Quit")
        self.status_item = rumps.MenuItem("Loading…")
        self.words_item  = rumps.MenuItem("Words: 0")
        self.last_item   = rumps.MenuItem("Last: —")
        self.menu = [self.status_item, None, self.words_item, self.last_item]


def set_menu_bar_state(icon_text: str, status: str) -> None:
    if app is None:
        return
    # If the icon file exists: icon is always shown; only add a title when active.
    # If no icon file: use text labels for all states.
    if ICON_PATH.exists():
        app.title = icon_text  # "" for idle, " rec " or " ··· " when active
    else:
        app.title = " ct " if icon_text == ICON_IDLE else icon_text
    app.status_item.title = status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    if not quiet_mode:
        print(msg)


def play_sound(name: str) -> None:
    path = _SOUNDS.get(name)
    if path:
        subprocess.Popen(["afplay", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log_transcription(text: str) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")


def start_recording() -> None:
    global last_audio_time
    last_audio_time = time.time()
    recording.set()
    play_sound("start")
    set_menu_bar_state(ICON_RECORDING, "Recording…")
    log("\n[Recording...] Speak now")


def stop_recording(mode_msg: str = "") -> None:
    recording.clear()
    play_sound("stop")
    set_menu_bar_state(ICON_PROCESSING, "Processing…")
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

    process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
    process.communicate(text.encode('utf-8'))
    log("Copied to clipboard")

    verify = subprocess.run(['pbpaste'], capture_output=True, text=True)
    if verify.stdout != text:
        print("ERROR: Clipboard verification failed", file=sys.stderr)
        return

    time.sleep(0.3)

    result = subprocess.run(
        ['osascript', '-e',
         'tell application "System Events" to keystroke "v" using {command down}'],
        capture_output=True, text=True, timeout=5,
    )

    if result.returncode == 0:
        log("Pasted successfully")
        session_words += len(text.split())
        log_transcription(text)
        preview = text[:60] + ("…" if len(text) > 60 else "")
        if app is not None:
            app.words_item.title = f"Words: {session_words}"
            app.last_item.title  = f"Last: {preview}"
            try:
                rumps.notification("ChirpType", "", preview, sound=False)
            except Exception:
                pass
    else:
        err = result.stderr.strip()
        if "not allowed assistive access" in err.lower():
            print("ERROR: Accessibility permission denied. "
                  "System Settings → Privacy & Security → Accessibility", file=sys.stderr)
        else:
            print(f"ERROR: Paste failed: {err}", file=sys.stderr)


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

                set_menu_bar_state(ICON_IDLE, "Idle")


# ---------------------------------------------------------------------------
# Startup + entry point
# ---------------------------------------------------------------------------

def _startup() -> None:
    set_menu_bar_state(ICON_PROCESSING, "Loading model…")
    log(f"\nLoading {MODEL_NAME}...")

    model = from_pretrained(MODEL_NAME)
    sample_rate = model.preprocessor_config.sample_rate

    if not quiet_mode:
        print(f"Ready — {sample_rate} Hz | hotkey: Right Option (⌥)")

    set_menu_bar_state(ICON_IDLE, "Idle")
    keyboard.Listener(on_press=on_press, on_release=on_release).start()
    threading.Thread(target=transcription_loop, args=(model, sample_rate), daemon=True).start()


def main() -> None:
    global quiet_mode, input_device, silence_duration, app

    parser = argparse.ArgumentParser(description='ChirpType — macOS menu bar dictation')
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
