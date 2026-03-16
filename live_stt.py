#!/usr/bin/env python3
"""
ChirpType — macOS menu bar dictation powered by parakeet-mlx

Hotkey: Right Option (⌥ right)

Two recording modes:
  Press-and-hold : Hold hotkey while speaking, release to transcribe.
  Double-tap     : Double-tap to lock recording, tap once more to transcribe.
"""

import threading
import queue
import sys
import time
import subprocess
import argparse
import numpy as np
import mlx.core as mx
import rumps
import sounddevice as sd
from pynput import keyboard
from pynput.keyboard import Key
from parakeet_mlx import from_pretrained

MODEL_NAME = "mlx-community/parakeet-tdt-0.6b-v3"
CHUNK_DURATION = 1.0

# Seconds held before a keypress is treated as "hold" rather than a tap.
HOLD_THRESHOLD = 0.3
# Seconds within which a second tap must arrive to count as a double-tap.
DOUBLE_TAP_WINDOW = 0.4

# Menu bar icon states
ICON_IDLE       = "🎙"
ICON_RECORDING  = "🔴"
ICON_PROCESSING = "⏳"

# --- State machine ---
# IDLE              : not recording
# HOLD_RECORDING    : recording started by a hold; release will stop + transcribe
# FIRST_TAP_PENDING : first quick tap detected; still recording, waiting for a
#                     possible second tap within DOUBLE_TAP_WINDOW
# LOCKED_RECORDING  : double-tap confirmed; recording until a single tap stops it
IDLE = "idle"
HOLD_RECORDING = "hold_recording"
FIRST_TAP_PENDING = "first_tap_pending"
LOCKED_RECORDING = "locked_recording"

_SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "stop":  "/System/Library/Sounds/Pop.aiff",
}

state = IDLE
state_lock = threading.Lock()

recording = threading.Event()   # .set() = recording, .clear() = stopped
audio_queue: queue.Queue = queue.Queue()
hotkey_active = False           # True while hotkey is currently held
hotkey_press_time = 0.0
_double_tap_timer: threading.Timer | None = None

quiet_mode = False
input_device: str | int | None = None
silence_duration: float = 0.0  # 0 = disabled
last_audio_time: float = 0.0

app: "ChirpTypeApp | None" = None


# ---------------------------------------------------------------------------
# Menu bar app
# ---------------------------------------------------------------------------

class ChirpTypeApp(rumps.App):
    def __init__(self):
        super().__init__("ChirpType", title=ICON_IDLE, quit_button="Quit")
        self.status_item = rumps.MenuItem("Idle")
        self.last_item   = rumps.MenuItem("Last: —")
        self.menu = [self.status_item, None, self.last_item]


def set_menu_bar_state(icon: str, status: str) -> None:
    if app is not None:
        app.title = icon
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


def start_recording() -> None:
    global last_audio_time
    last_audio_time = time.time()  # reset silence clock
    recording.set()
    play_sound("start")
    set_menu_bar_state(ICON_RECORDING, "Recording…")
    log("\n[Recording...] Speak now")


def stop_recording(mode_msg: str = "") -> None:
    recording.clear()
    play_sound("stop")
    set_menu_bar_state(ICON_PROCESSING, "Processing…")
    suffix = f" ({mode_msg})" if mode_msg else ""
    log(f"\n[Stopped{suffix}] Processing transcription...")


def _check_silence() -> None:
    """Auto-stop if audio has been below threshold for silence_duration seconds."""
    global state
    if silence_duration <= 0 or last_audio_time == 0.0:
        return
    if time.time() - last_audio_time >= silence_duration:
        with state_lock:
            if state in (HOLD_RECORDING, FIRST_TAP_PENDING, LOCKED_RECORDING):
                stop_recording("silence")
                state = IDLE


# ---------------------------------------------------------------------------
# Hotkey state-machine callbacks
# ---------------------------------------------------------------------------

def on_hotkey_activated() -> None:
    """Called the moment the hotkey becomes pressed."""
    global state, hotkey_press_time, hotkey_active, _double_tap_timer

    with state_lock:
        if hotkey_active:
            return  # guard against spurious repeat events
        hotkey_active = True
        hotkey_press_time = time.time()

        if state == IDLE:
            start_recording()
            state = HOLD_RECORDING

        elif state == FIRST_TAP_PENDING:
            # Second tap within the window → lock recording mode
            if _double_tap_timer is not None:
                _double_tap_timer.cancel()
                _double_tap_timer = None
            state = LOCKED_RECORDING
            log("[Locked] Recording is locked — tap hotkey again to stop")

        elif state == LOCKED_RECORDING:
            # Tap while locked → stop and transcribe
            stop_recording("locked mode")
            state = IDLE


def on_hotkey_deactivated() -> None:
    """Called the moment the hotkey is released."""
    global state, hotkey_active, _double_tap_timer

    with state_lock:
        if not hotkey_active:
            return
        hotkey_active = False
        held_duration = time.time() - hotkey_press_time

        if state == HOLD_RECORDING:
            if held_duration >= HOLD_THRESHOLD:
                # Long hold → stop and transcribe on release
                stop_recording("hold mode")
                state = IDLE
            else:
                # Quick tap → wait to see if a second tap follows
                state = FIRST_TAP_PENDING
                log("[Tap] Double-tap to lock, or wait to cancel")
                _double_tap_timer = threading.Timer(DOUBLE_TAP_WINDOW, _double_tap_timeout)
                _double_tap_timer.start()

        # Releasing while LOCKED_RECORDING or FIRST_TAP_PENDING is intentional no-op.


def _double_tap_timeout() -> None:
    """Fires DOUBLE_TAP_WINDOW seconds after the first quick tap.
    If no second tap arrived, treat it as a single tap: stop and transcribe."""
    global state, _double_tap_timer
    with state_lock:
        if state == FIRST_TAP_PENDING:
            stop_recording("single tap")
            state = IDLE
        _double_tap_timer = None


# ---------------------------------------------------------------------------
# pynput keyboard listeners
# ---------------------------------------------------------------------------

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
    process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
    process.communicate(text.encode('utf-8'))

    log("Copied to clipboard")

    verify = subprocess.run(['pbpaste'], capture_output=True, text=True)
    if verify.stdout != text:
        print("ERROR: Clipboard verification failed", file=sys.stderr)
        return

    time.sleep(0.3)

    applescript = 'tell application "System Events" to keystroke "v" using {command down}'
    result = subprocess.run(['osascript', '-e', applescript],
                            capture_output=True, text=True, timeout=5)

    if result.returncode == 0:
        log("Pasted successfully")
        preview = text[:60] + ("…" if len(text) > 60 else "")
        if app is not None:
            app.last_item.title = f"Last: {preview}"
            try:
                rumps.notification("ChirpType", "", preview, sound=False)
            except Exception:
                pass
    else:
        error_msg = result.stderr.strip()
        if "not allowed assistive access" in error_msg.lower():
            print("ERROR: Accessibility permission denied", file=sys.stderr)
            print("Go to: System Settings > Privacy & Security > Accessibility",
                  file=sys.stderr)
        else:
            print(f"ERROR: Paste failed: {error_msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Audio + transcription
# ---------------------------------------------------------------------------

def audio_callback(indata, frames, time_info, status) -> None:
    global last_audio_time
    if status and not quiet_mode:
        print(f"Audio status: {status}", file=sys.stderr)
    if recording.is_set():
        audio_queue.put(indata.copy())
        if silence_duration > 0:
            rms = float(np.sqrt(np.mean(indata ** 2)))
            if rms > 0.01:  # ~-40 dBFS — catches quiet speech
                last_audio_time = time.time()


def transcription_loop(model, sample_rate: int) -> None:
    chunk_size = int(sample_rate * CHUNK_DURATION)

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype='float32',
                        blocksize=chunk_size, callback=audio_callback,
                        device=input_device):
        while True:
            recording.wait()  # block until recording starts

            with model.transcribe_stream(context_size=(256, 256)) as transcriber:
                # Flush stale audio accumulated while we weren't transcribing
                while not audio_queue.empty():
                    audio_queue.get()

                last_text = ""

                while recording.is_set():
                    _check_silence()
                    try:
                        audio_chunk = audio_queue.get(timeout=0.1)
                        audio_mlx = mx.array(audio_chunk.flatten())
                        transcriber.add_audio(audio_mlx)

                        result = transcriber.result
                        if result.text != last_text and not quiet_mode:
                            print(f"\rTranscription: {result.text}", end='', flush=True)
                            last_text = result.text
                    except queue.Empty:
                        continue

                result = transcriber.result

                if not quiet_mode:
                    print(f"\n\nFinal transcription:\n{result.text}\n")

                    if result.sentences:
                        print("Timestamps:")
                        for sentence in result.sentences:
                            print(f"  [{sentence.start:.2f}s - {sentence.end:.2f}s] {sentence.text}")
                        print()

                if result.text.strip():
                    copy_and_paste(result.text)

                set_menu_bar_state(ICON_IDLE, "Idle")


# ---------------------------------------------------------------------------
# Startup (runs in background thread so menu bar appears immediately)
# ---------------------------------------------------------------------------

def _startup(model_name: str) -> None:
    set_menu_bar_state(ICON_PROCESSING, "Loading model…")
    if not quiet_mode:
        print("\nLoading model...")

    model = from_pretrained(model_name)
    sample_rate = model.preprocessor_config.sample_rate

    if not quiet_mode:
        print(f"Model loaded: {model_name}")
        print(f"Sample rate: {sample_rate} Hz")
        if input_device is not None:
            print(f"Input device: {input_device}")
        if silence_duration > 0:
            print(f"Auto-silence: {silence_duration}s")
        print("\n" + "=" * 60)
        print("Hotkey: Right Option (⌥ right)")
        print("  Press-and-hold → release to transcribe")
        print("  Double-tap     → locked recording, tap again to transcribe")
        print("=" * 60 + "\n")

    set_menu_bar_state(ICON_IDLE, "Idle")

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    threading.Thread(target=transcription_loop, args=(model, sample_rate),
                     daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    global quiet_mode, input_device, silence_duration, app

    parser = argparse.ArgumentParser(description='ChirpType — macOS menu bar dictation')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress all output except errors')
    parser.add_argument('--device', default=None,
                        help='Input device name or index (default: system default)')
    parser.add_argument('--list-devices', action='store_true',
                        help='List available audio input devices and exit')
    parser.add_argument('--silence', type=float, default=0.0, metavar='SECS',
                        help='Auto-stop after N seconds of silence (0 = off, default)')
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        sys.exit(0)

    quiet_mode = args.quiet
    silence_duration = args.silence
    input_device = args.device
    if isinstance(input_device, str) and input_device.isdigit():
        input_device = int(input_device)

    if not quiet_mode:
        print("=" * 60)
        print("ChirpType — macOS menu bar dictation")
        print("=" * 60)

    app = ChirpTypeApp()
    threading.Thread(target=_startup, args=(MODEL_NAME,), daemon=True).start()
    app.run()  # blocks main thread with NSApplication event loop


if __name__ == "__main__":
    main()
