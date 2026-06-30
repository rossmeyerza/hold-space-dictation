# Hold Space Dictation — Agent Guidelines

## What This Is

A Chrome MV3 extension for local push-to-talk dictation. The user holds `Space` in an editable browser field, the content script asks a native messaging host to record audio, and the resulting local Whisper transcription is inserted back into the page.

## Files

```
hold-space-dictation/
├── manifest.json      — Chrome MV3 manifest
├── src/               — background service worker, content script, overlay CSS
├── popup/             — extension popup settings UI
├── native/host.py     — native messaging host: recording, transcription, paste/type fallback, audio ducking
├── scripts/           — native host installer and shared Flow/extension ducking helper
├── README.md          — user-facing setup and configuration docs
├── LICENSE            — MIT license
└── AGENTS.md          — this file
```

## Architecture

- `src/content.js` owns browser input handling: tap-vs-hold detection, status overlay, target/selection preservation, Chrome storage settings, and insertion into normal inputs/contenteditable fields.
- `src/background.js` owns the Chrome native messaging port and request/response routing to the native host.
- `native/host.py` owns local OS work: `parecord`, `whisper-cli`, `wl-copy`, `wtype`, desktop notifications, and optional audio ducking through `scripts/flow-audio-duck` / `~/.local/bin/flow-audio-duck`.
- `popup/popup.*` owns user settings stored in `chrome.storage.local`.

## Recording Lifecycle

1. Content script detects a held `Space` after `holdDelayMs`.
2. Content script sends `start` with the selected model to the background worker.
3. Background worker forwards `start` to `native/host.py`.
4. Native host starts `parecord`, then best-effort ducks active playback streams.
5. On key release, content script waits until `minRecordingMs` has elapsed before sending `stop`; this avoids clipping very short utterances.
6. Native host stops `parecord`, restores ducked/paused playback, runs `whisper-cli`, and returns text.
7. Content script inserts the returned text into the original target.

## Audio Ducking

- Audio ducking should be shared through `scripts/flow-audio-duck` where possible because Flow and FlowD call the installed copy at `~/.local/bin/flow-audio-duck`.
- `pactl` and `playerctl` are optional. Missing tools, unsupported audio servers, vanished streams, or command failures must never break dictation.
- Keep ducking best-effort and scoped to active playback: save original stream volumes, fade to `FLOW_AUDIO_DUCK_VOLUME` / `FLOW_DUCK_VOLUME` (default `0`), pause players that were already playing, resume them on restore, then fade volume back up.
- Default fade and pause settings are controlled by `FLOW_AUDIO_DUCK_FADE_MS`, `FLOW_AUDIO_DUCK_FADE_STEPS`, `FLOW_DUCK_PAUSE`, and `FLOW_DUCK_RESUME_DELAY_MS`.

## Settings

Chrome storage settings live in `src/content.js` and `popup/popup.js`. Keep defaults in sync between those two files.

Current browser settings:

- `model`
- `holdDelayMs`
- `minRecordingMs`

Native host settings are environment variables documented in `README.md`, currently prefixed with `FLOW_`.

## Public Repo Constraints

- Do not add user-specific absolute paths. Use `~`, environment variables, or repo-relative paths in docs/config.
- Keep Linux/Wayland assumptions explicit in README.
- Keep optional dependencies optional: `pactl` and `notify-send` should be best-effort.
- The MIT license names Ross Meyer as copyright holder.

## Validation

- `node --check src/content.js`
- `node --check popup/popup.js`
- `python -c "import py_compile; py_compile.compile('native/host.py', cfile='/tmp/hold-space-host.pyc', doraise=True)"`
- `git diff --check`

## Git

- Repo: https://github.com/rossmeyerza/hold-space-dictation
- Main branch: `main`
- Conventional commits: `feat / fix / refactor / docs / chore`
