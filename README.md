# ChirpType

macOS menu bar dictation powered by [parakeet-mlx](https://github.com/senstella/parakeet-mlx). Tap a hotkey, speak, and your words are instantly transcribed and pasted into any app.

Requires Apple Silicon.

## Prerequisites

1. **uv** — `brew install uv`
2. **ffmpeg** — `brew install ffmpeg`
3. **Microphone permission** — macOS will prompt on first run
4. **Accessibility permission** — required for auto-paste
   - System Settings → Privacy & Security → Accessibility → add Terminal (or your shell)

## Install

```bash
git clone https://github.com/carteakey/chirptype
cd chirptype
./install.sh
```

This installs the `chirptype` command via `uv tool install` and registers a LaunchAgent so it auto-starts at login. The menu bar icon appears immediately.

**Uninstall:**
```bash
./install.sh uninstall
```

## Development

```bash
uv run python chirptype.py
```

## Recording

**Hotkey:** Right Option (⌥ right)

| Mode | How |
|------|-----|
| Press-and-hold | Hold ⌥ right while speaking → release to transcribe |
| Double-tap lock | Tap ⌥ right twice → speak → tap once more to transcribe |

Transcription is pasted automatically into your active text field. A **ChirpType** notification shows a preview of what was pasted.

## Menu Bar

| Label | State |
|-------|-------|
| `ct`  | Idle — ready to record |
| `rec` | Recording |
| `···` | Processing transcription |

The menu also shows the last transcribed text and a **Quit** option.

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--silence SECS` | `0` (off) | Auto-stop after N seconds of silence |
| `--device NAME_OR_ID` | system default | Select a specific input device |
| `--list-devices` | — | Print available audio input devices and exit |
| `--quiet` / `-q` | off | Suppress all terminal output except errors |

**Example — use an external USB mic, auto-stop after 2 s of silence:**
```bash
chirptype --device "USB Audio" --silence 2.0
```

**List available input devices:**
```bash
chirptype --list-devices
```

To pass flags via the LaunchAgent, edit `~/Library/LaunchAgents/com.chirptype.plist`.

## Model

Default model: **[mlx-community/parakeet-tdt-0.6b-v3](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3)**
- Architecture: NVIDIA Parakeet-TDT 0.6 B (Token-and-Duration Transducer)
- Optimised for Apple Silicon via MLX
- English only, ~1.2 GB on disk (downloaded on first run)

To swap models, edit `MODEL_NAME` in `chirptype.py`.

## Configuration

Edit `chirptype.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `MODEL_NAME` | `mlx-community/parakeet-tdt-0.6b-v3` | Parakeet model to load |
| `CHUNK_DURATION` | `1.0` | Audio chunk size in seconds |
| `HOLD_THRESHOLD` | `0.3` | Seconds to distinguish a tap from a hold |
| `DOUBLE_TAP_WINDOW` | `0.4` | Window for double-tap detection (seconds) |

## License

Apache 2.0
