# ChirpType 🐦

Tap a hotkey, speak, and your words appear — in any app, instantly.

Runs entirely on-device. macOS uses Apple Silicon; Windows uses a local CPU
backend. No cloud, no API keys, no subscription.

> One icon in your menu bar or system tray. One hotkey. Nothing else.

## Install

### macOS

```bash
brew install uv ffmpeg
git clone https://github.com/carteakey/chirptype
cd chirptype
uv venv
uv pip install -r requirements.txt
./start.sh
```

Grant **Microphone** and **Accessibility** permissions when prompted.

To auto-start at login, add `start.sh` to **System Settings → General → Login Items**.

### Windows

Install Python 3.10+, [uv](https://docs.astral.sh/uv/), and Git, then run these
commands in PowerShell:

```powershell
git clone https://github.com/carteakey/chirptype
cd chirptype
uv venv
uv pip install -r requirements.txt
.\start.bat
```

Grant **Microphone** access in **Settings → Privacy & security → Microphone**.
The app uses **Right Alt** as its hotkey. On some keyboard layouts Right Alt is
AltGr; switch the hotkey in `chirptype.py` if that conflicts with your layout.

Windows uses the `base.en` faster-whisper model and transcribes after recording
stops, so it does not show the macOS live preview. The model downloads on first
run and runs locally on the CPU.

## Usage

**Hotkey:** Right Option `⌥` on macOS; Right Alt on Windows

| | |
|---|---|
| Hold | speak → release to transcribe |
| Double-tap | locks recording → tap again to stop |

Text is pasted directly into whatever app is in focus. Each transcription is
appended to `.chirptype_log.txt` in your home directory.

## start.sh

```bash
./start.sh          # start in background
./start.sh stop     # stop
./start.sh logs     # tail output log
```

The Windows equivalent is `start.bat`, `start.bat stop`, and `start.bat logs`.
The PowerShell implementation is also available as `start.ps1`.

## Configuration

Edit the constants at the top of `chirptype.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `MODEL_NAME` | platform-specific | Model to load |
| `HOLD_THRESHOLD` | `0.3` | Seconds to distinguish tap from hold |
| `DOUBLE_TAP_WINDOW` | `0.4` | Window for double-tap detection |

CLI flags: `--silence SECS`, `--device NAME_OR_ID`, `--list-devices`, `--quiet`

## Model

macOS default: **[mlx-community/parakeet-tdt-0.6b-v3](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3)** — NVIDIA Parakeet-TDT 0.6B, English-only, ~1.2 GB, downloaded on first run.

Windows default: **`base.en`** via faster-whisper — English-only. It downloads
on first run and runs locally on the CPU. Change `WINDOWS_MODEL_NAME` near the
top of `chirptype.py` to use another faster-whisper model such as `small.en`.

Other macOS options: `parakeet-tdt-0.6b-v2`, `parakeet-tdt-1.1b` (~2.1 GB, more accurate).

## License

Apache 2.0
