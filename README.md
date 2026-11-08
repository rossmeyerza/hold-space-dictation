# Hold Space Dictation

Chrome extension for local push-to-talk dictation. Hold `Space` in an editable field, speak, release `Space`, and the extension inserts a local transcription into the field.

The extension is built for Linux desktops. It uses a Chrome MV3 extension plus a native messaging host that runs local command-line tools.

## Features

- Hold `Space` in inputs, textareas, and contenteditable fields to dictate.
- Tap `Space` normally to insert a normal space.
- Local streaming transcription: the native host sends the audio to a transcriber while you speak,
  so the text is ready about 0.25 s after the release tail (default 500 ms) ends.
- Configurable hold delay and minimum capture duration from the extension popup.
- Configurable release tail to keep recording briefly after Space is released.
- Optional PulseAudio/PipeWire audio ducking through `pactl`, if available.
- If streaming fails, the host transcribes the saved recording instead.

## Requirements

Required:

- Google Chrome or Chromium with extension developer mode enabled.
- `parecord` for microphone capture.
- A transcriber command, set with `FLOW_TRANSCRIBE_BIN` (default `~/.local/bin/flow-transcribe`).
  See [Transcriber](#transcriber). The author uses Parakeet Unified English through transcribe.cpp.
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

- Hold delay before dictation starts.
- Minimum capture duration before transcription starts.
- Release tail after you let go of `Space`, useful when you release slightly before your final words finish.

## Transcriber

The native host does not include a speech model. It runs the command in `FLOW_TRANSCRIBE_BIN` in two ways:

- `<command> --stream`: the host writes raw 16 kHz mono signed 16-bit little-endian audio to stdin while
  you speak, and closes stdin when you release `Space`. The command prints the transcript to stdout and
  exits with code 0.
- `<command> <file.wav>`: the fallback when streaming fails. The command prints the transcript of a
  16 kHz mono PCM16 WAV file.

The author's command is `flow-transcribe`, which streams into NVIDIA Parakeet Unified English 0.6B with
[transcribe.cpp](https://github.com/handy-computer/transcribe.cpp) on the GPU. Any command with this
interface works, for example a short script around whisper.cpp.

## Native Host Configuration

The native host reads environment variables when Chrome starts it.

| Variable | Default | Description |
|---|---:|---|
| `FLOW_TRANSCRIBE_BIN` | `~/.local/bin/flow-transcribe` | Transcriber command (see [Transcriber](#transcriber)) |
| `FLOW_RECORD_READY_DELAY_MS` | `150` | Delay before reporting recording as ready |
| `FLOW_AUDIO_DUCK` | `1` | Set to `0`, `false`, `off`, or `no` to disable ducking |
| `FLOW_AUDIO_DUCK_HELPER` | `~/.local/bin/flow-audio-duck` | Shared ducking helper used when executable |
| `FLOW_AUDIO_DUCK_VOLUME` | `0` | Target playback stream volume while recording |
| `FLOW_AUDIO_DUCK_FADE_MS` | `450` | Fade duration for duck/restore transitions |
| `FLOW_AUDIO_DUCK_FADE_STEPS` | `12` | Number of volume steps used during each fade |
| `FLOW_DUCK_PAUSE` | `1` | When using the shared helper, pause currently playing MPRIS players after fading down |
| `FLOW_DUCK_RESUME_DELAY_MS` | `250` | Delay after resuming players before fading volumes back up |

Audio ducking is best-effort. By default the shared helper fades active streams to zero, pauses players that were already playing, resumes those players on restore, then fades volume back up. If `pactl`, `playerctl`, or an audio stream is unavailable, dictation continues.

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
