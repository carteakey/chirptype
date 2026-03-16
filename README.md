# ChirpType 🐦

Tap a hotkey, speak, and your words appear — in any app, instantly.

Runs entirely on-device via Apple Silicon. No cloud, no API keys, no subscription.

> One icon in your menu bar. One hotkey. Nothing else.

## Install

```bash
brew install uv ffmpeg
git clone https://github.com/carteakey/chirptype
cd chirptype
uv pip install -r requirements.txt
./start.sh
```

Grant **Microphone** and **Accessibility** permissions when prompted.

To auto-start at login, add `start.sh` to **System Settings → General → Login Items**.

## Usage

**Hotkey:** Right Option `⌥`

| | |
|---|---|
| Hold | speak → release to transcribe |
| Double-tap | locks recording → tap again to stop |

Text is pasted directly into whatever app is in focus. Each transcription is appended to `~/.chirptype_log.txt`.

## start.sh

```bash
./start.sh          # start in background
./start.sh stop     # stop
./start.sh logs     # tail output log
```

## Configuration

Edit the constants at the top of `chirptype.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `MODEL_NAME` | `parakeet-tdt-0.6b-v3` | Model to load |
| `HOLD_THRESHOLD` | `0.3` | Seconds to distinguish tap from hold |
| `DOUBLE_TAP_WINDOW` | `0.4` | Window for double-tap detection |

CLI flags: `--silence SECS`, `--device NAME_OR_ID`, `--list-devices`, `--quiet`

## Model

Default: **[mlx-community/parakeet-tdt-0.6b-v3](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3)** — NVIDIA Parakeet-TDT 0.6B, English-only, ~1.2 GB, downloaded on first run.

Other options: `parakeet-tdt-0.6b-v2`, `parakeet-tdt-1.1b` (~2.1 GB, more accurate).

## License

Apache 2.0
