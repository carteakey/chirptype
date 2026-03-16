# ChirpType

Tap a hotkey, speak, and your words appear — in any app, instantly.

ChirpType is a macOS menu bar dictation tool built on [parakeet-mlx](https://github.com/senstella/parakeet-mlx). It runs entirely on-device using Apple Silicon. No cloud, no API keys, no subscription. Just fast, private speech-to-text that stays out of your way.

**Philosophy:** one small icon in your menu bar, one hotkey, nothing else. It should feel like a native part of the OS — always there, never in the way. Every decision in this project is made in favour of simplicity over features.

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

## Configuration

Settings are stored in `~/.chirptype.json` and persist across restarts. You can also edit them directly in the menu:

- **Model** — pick a Parakeet variant from the submenu (restart to apply)
- **Auto-stop on silence** — toggles 2-second silence detection on/off

`~/.chirptype.json` example:
```json
{
  "hotkey": "alt_r",
  "model": "mlx-community/parakeet-tdt-0.6b-v3",
  "silence": 0.0
}
```

| Key | Default | Options |
|-----|---------|---------|
| `hotkey` | `alt_r` | `alt_r`, `alt`, `ctrl_r`, `f13`–`f19` |
| `model` | `parakeet-tdt-0.6b-v3` | see Model section |
| `silence` | `0.0` (off) | seconds, e.g. `2.0` |

## CLI Flags

| Flag | Description |
|------|-------------|
| `--silence SECS` | Auto-stop after N seconds of silence (overrides config) |
| `--device NAME_OR_ID` | Select a specific input device |
| `--list-devices` | Print available audio input devices and exit |
| `--quiet` / `-q` | Suppress all terminal output except errors |

```bash
chirptype --device "USB Audio" --silence 2.0
chirptype --list-devices
```

## Model

Available models (selectable from the menu):

| Model | Size | Notes |
|-------|------|-------|
| `parakeet-tdt-0.6b-v3` | ~1.2 GB | Default, fast |
| `parakeet-tdt-0.6b-v2` | ~1.2 GB | Previous version |
| `parakeet-tdt-1.1b` | ~2.1 GB | More accurate, slower |

All models are English-only, optimised for Apple Silicon via MLX, and downloaded on first use.

## License

Apache 2.0
