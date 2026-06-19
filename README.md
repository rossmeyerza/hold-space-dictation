# Hold Space Dictation

Chrome extension for local push-to-talk dictation. Hold `Space` in an editable field, speak, release `Space`, and the extension inserts a local Whisper transcription into the field.

The extension is built for Linux desktops. It uses a Chrome MV3 extension plus a native messaging host that runs local command-line tools.

## Features

- Hold `Space` in inputs, textareas, and contenteditable fields to dictate.
- Tap `Space` normally to insert a normal space.
- Local transcription through `whisper-cli` from whisper.cpp.
- Configurable Whisper model, hold delay, and minimum capture duration from the extension popup.
- Configurable release tail to keep recording briefly after Space is released.
- Optional PulseAudio/PipeWire audio ducking through `pactl`, if available.
- GPU transcription retry on CPU when whisper reports GPU or allocation failures.

## Requirements

Required:

- Google Chrome or Chromium with extension developer mode enabled.
- `parecord` for microphone capture.
- `whisper-cli` from [whisper.cpp](https://github.com/ggerganov/whisper.cpp).
- A whisper.cpp `.bin` model in `~/.local/lib/whisper/`, or a custom model directory via `FLOW_MODEL_DIR`.
- `wl-copy` and `wtype` for native paste/type fallback paths on Wayland.

Optional:

- `pactl` for audio ducking. If it is unavailable or unsupported, dictation still works normally.
- `notify-send` for desktop notifications from the native host.

## Install

1. Clone this repository.

```bash
git clone https://github.com/rossmeyerza/hold-space-dictation.git
cd hold-space-dictation
```

2. Open `chrome://extensions`.
3. Enable Developer mode.
4. Click "Load unpacked" and select this repository directory.
5. Copy the extension ID shown by Chrome.
6. Install the native messaging host.

```bash
./scripts/install-native-host.sh <extension-id>
```

7. Reload the extension in `chrome://extensions`.

## Use

Focus an input, textarea, or contenteditable field.

- Tap `Space` for a normal space.
- Hold `Space` for about 350ms to start recording.
- Speak.
- Release `Space` to transcribe and insert the text.

Click the extension icon to configure:

- Whisper model: small, medium, large, or turbo.
- Hold delay before dictation starts.
- Minimum capture duration before transcription starts.
- Release tail after you let go of `Space`, useful when you release slightly before your final words finish.

## Models

The native host defaults to:

```text
~/.local/lib/whisper/ggml-small.en.bin
```

Expected model filenames:

| Popup model | Filename |
|---|---|
| `small` | `ggml-small.en.bin` |
| `medium` | `ggml-medium.en.bin` |
| `large` | `ggml-large-v3.bin` |
| `turbo` | `ggml-large-v3-turbo.bin` |

Set `FLOW_MODEL_DIR` if your models live somewhere else.

## Native Host Configuration

The native host reads environment variables when Chrome starts it.

| Variable | Default | Description |
|---|---:|---|
| `FLOW_MODEL_DIR` | `~/.local/lib/whisper` | Directory containing whisper.cpp `.bin` models |
| `FLOW_THREADS` | `4` | Thread count passed to `whisper-cli` |
| `FLOW_WHISPER_BIN` | `whisper-cli` | Whisper CLI binary name or absolute path |
| `FLOW_RECORD_READY_DELAY_MS` | `150` | Delay before reporting recording as ready |
| `FLOW_AUDIO_DUCK` | `1` | Set to `0`, `false`, `off`, or `no` to disable ducking |
| `FLOW_AUDIO_DUCK_VOLUME` | `25` | Target playback stream volume while recording |
| `FLOW_AUDIO_DUCK_FADE_MS` | `450` | Fade duration for duck/restore transitions |
| `FLOW_AUDIO_DUCK_FADE_STEPS` | `12` | Number of volume steps used during each fade |

Audio ducking is best-effort. If `pactl` is missing, cannot connect to the audio server, or a playback stream disappears, the native host ignores that failure and continues dictation.

## Native Messaging

Chrome communicates with the native host declared in:

```text
native/com.ross.hold_space_dictation.json.template
```

The install script writes Chrome's native host manifest to:

```text
~/.config/google-chrome/NativeMessagingHosts/com.ross.hold_space_dictation.json
```

For Chromium variants, you may need to adapt the target directory in `scripts/install-native-host.sh`.

## Limitations

- Linux and Wayland-oriented by default.
- Browser pages can handle contenteditable input differently, so some sites may behave better than others.
- Chrome must be reloaded after installing or changing the native host manifest.

## License

MIT. See [LICENSE](LICENSE).
