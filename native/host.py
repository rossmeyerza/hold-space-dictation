#!/usr/bin/env python3
import json
import os
import queue
import re
import shlex
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path


APP_NAME = "Hold Space Dictation"
# Flow's Parakeet engine: `--stream` reads raw audio from stdin, `FILE.wav` transcribes a file.
TRANSCRIBE_BIN = os.path.expanduser(os.environ.get("FLOW_TRANSCRIBE_BIN", "~/.local/bin/flow-transcribe"))
CHUNK_BYTES = 3200  # 100 ms of 16 kHz mono s16le

recording = None


def env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)).rstrip("%"))
    except (TypeError, ValueError):
        return default


RECORD_READY_DELAY_MS = env_int("FLOW_RECORD_READY_DELAY_MS", 150)
AUDIO_DUCK_ENABLED = os.environ.get("FLOW_AUDIO_DUCK", "1").lower() not in {"0", "false", "off", "no"}
AUDIO_DUCK_HELPER = Path(os.path.expanduser(os.environ.get("FLOW_AUDIO_DUCK_HELPER", "~/.local/bin/flow-audio-duck")))
AUDIO_DUCK_VOLUME = env_int("FLOW_AUDIO_DUCK_VOLUME", 0)
AUDIO_DUCK_FADE_MS = env_int("FLOW_AUDIO_DUCK_FADE_MS", 450)
AUDIO_DUCK_FADE_STEPS = env_int("FLOW_AUDIO_DUCK_FADE_STEPS", 12)


class AudioDucker:
    def __init__(self, enabled=True, helper=None, target_volume=25, fade_ms=450, fade_steps=12):
        self.enabled = enabled
        self.helper = helper
        self.using_helper = False
        self.target_volume = max(0, min(150, target_volume))
        self.fade_ms = max(0, fade_ms)
        self.fade_steps = max(1, fade_steps)
        self.ducked_inputs = []
        self.active = False

    def duck(self):
        if not self.enabled or self.active:
            return
        if self._run_helper("duck"):
            self.using_helper = True
            self.active = True
            return
        try:
            inputs = self._sink_inputs()
            volumes = self._current_volumes()
            ducked = [(sink_id, volumes[sink_id]) for sink_id in inputs if sink_id in volumes]
            if not ducked:
                return

            self.ducked_inputs = ducked
            self.active = True
            for sink_id, volume in ducked:
                self._fade_volume(sink_id, volume, self.target_volume)
        except Exception:
            self.ducked_inputs = []
            self.active = False

    def restore(self):
        if self.using_helper:
            self._run_helper("restore")
            self.using_helper = False
            self.ducked_inputs = []
            self.active = False
            return
        if not self.active or not self.ducked_inputs:
            return
        ducked = self.ducked_inputs
        self.ducked_inputs = []
        self.active = False

        try:
            volumes = self._current_volumes()
            for sink_id, original_volume in ducked:
                self._fade_volume(sink_id, volumes.get(sink_id, self.target_volume), original_volume)
        except Exception:
            pass

    def _sink_inputs(self):
        result = subprocess.run(
            ["pactl", "list", "short", "sink-inputs"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.split()[0] for line in result.stdout.splitlines() if line.split()]

    def _run_helper(self, action):
        if not self.helper or not self.helper.exists() or not os.access(self.helper, os.X_OK):
            return False
        env = os.environ.copy()
        env.setdefault("FLOW_DUCK_VOLUME", f"{self.target_volume}%")
        env.setdefault("FLOW_DUCK_FADE_MS", str(self.fade_ms))
        env.setdefault("FLOW_DUCK_FADE_STEPS", str(self.fade_steps))
        try:
            subprocess.run(
                [str(self.helper), action],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            return True
        except OSError:
            return False

    def _current_volumes(self):
        result = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return {}

        volumes = {}
        current_id = None
        for line in result.stdout.splitlines():
            match = re.match(r"Sink Input #(\d+)", line)
            if match:
                current_id = match.group(1)
                continue
            if not current_id:
                continue
            match = re.search(r"Volume:.*?/\s*(\d+)%\s*/", line)
            if match:
                volumes[current_id] = int(match.group(1))
                current_id = None
        return volumes

    def _fade_volume(self, sink_id, start, end):
        if self.fade_ms <= 0 or self.fade_steps <= 1 or start == end:
            self._set_volume(sink_id, end)
            return

        delay = self.fade_ms / self.fade_steps / 1000
        for step in range(1, self.fade_steps + 1):
            eased = self._smoothstep(step / self.fade_steps)
            volume = round(start + (end - start) * eased)
            self._set_volume(sink_id, volume)
            if step < self.fade_steps:
                time.sleep(delay)

    def _set_volume(self, sink_id, volume):
        try:
            subprocess.run(
                ["pactl", "set-sink-input-volume", sink_id, f"{volume}%"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    @staticmethod
    def _smoothstep(value):
        value = max(0, min(1, value))
        return value * value * (3 - 2 * value)


audio_ducker = AudioDucker(
    enabled=AUDIO_DUCK_ENABLED,
    helper=AUDIO_DUCK_HELPER,
    target_volume=AUDIO_DUCK_VOLUME,
    fade_ms=AUDIO_DUCK_FADE_MS,
    fade_steps=AUDIO_DUCK_FADE_STEPS,
)


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    message_length = struct.unpack("@I", raw_length)[0]
    return json.loads(sys.stdin.buffer.read(message_length).decode("utf-8"))


def write_message(message):
    encoded = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("@I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def notify(body):
    try:
        subprocess.run(
            ["notify-send", "--app-name", APP_NAME, "--expire-time=1800", APP_NAME, body],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def capture_command():
    # Tests replace the microphone with any command that writes 16 kHz mono s16le to stdout.
    if os.environ.get("HOLD_SPACE_CAPTURE"):
        return shlex.split(os.environ["HOLD_SPACE_CAPTURE"])
    return ["parecord", "--raw", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=100"]


class Recording:
    """Record to a WAV file and stream the same audio into Parakeet while the user speaks."""

    def __init__(self):
        self.audio_file = Path(tempfile.gettempdir()) / f"hold-space-dictation-{os.getpid()}.wav"
        self.audio_file.unlink(missing_ok=True)
        self.wav = wave.open(str(self.audio_file), "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(16000)
        self.audio_bytes = 0
        self.chunks = queue.Queue()
        # Start the streamer before the microphone, so the model starts to load first.
        self.streamer = subprocess.Popen([TRANSCRIBE_BIN, "--stream"], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.capture = subprocess.Popen(capture_command(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.writer = threading.Thread(target=self._feed, daemon=True)
        self.reader.start()
        self.writer.start()

    def _read(self):
        try:
            while data := self.capture.stdout.read(CHUNK_BYTES):
                self.wav.writeframes(data)
                self.audio_bytes += len(data)
                self.chunks.put(data)
        finally:
            self.wav.close()
            self.chunks.put(None)

    def _feed(self):
        """A separate thread, so a slow model load never blocks the microphone."""
        try:
            while (data := self.chunks.get()) is not None:
                self.streamer.stdin.write(data)
                self.streamer.stdin.flush()  # unflushed audio would be decoded only after release
            self.streamer.stdin.close()
        except OSError:
            pass  # the streamer failed; text() falls back to the WAV file

    def stop_capture(self):
        if self.capture.poll() is None:
            self.capture.send_signal(signal.SIGINT)
            try:
                self.capture.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.capture.kill()
        self.reader.join(timeout=5)

    def text(self):
        """Return the streamed text, or transcribe the WAV file when the stream failed."""
        self.writer.join(timeout=10)
        try:
            out, _ = self.streamer.communicate(timeout=60)
            if self.streamer.returncode == 0:
                return " ".join(out.decode(errors="replace").split())
        except subprocess.TimeoutExpired:
            self.streamer.kill()
        result = subprocess.run([TRANSCRIBE_BIN, str(self.audio_file)], capture_output=True, text=True,
                                timeout=120, check=False)
        if result.returncode != 0:
            detail = " ".join(result.stderr.splitlines()[-3:])
            raise RuntimeError(f"Transcription failed: {detail}")
        return " ".join(result.stdout.split())

    def discard(self):
        self.stop_capture()
        if self.streamer.poll() is None:
            self.streamer.kill()
            self.streamer.wait(timeout=5)
        self.audio_file.unlink(missing_ok=True)


def start_recording():
    global recording
    if recording:
        cancel_recording()
    if not os.access(TRANSCRIBE_BIN, os.X_OK):
        raise RuntimeError(f"Missing transcriber: {TRANSCRIBE_BIN}")
    recording = Recording()
    audio_ducker.duck()
    time.sleep(max(0, RECORD_READY_DELAY_MS) / 1000)
    notify("Recording...")


def cancel_recording():
    global recording
    if not recording:
        return
    recording.discard()
    audio_ducker.restore()
    recording = None


def transcribe_recording():
    global recording
    if not recording:
        raise RuntimeError("No active recording")
    current = recording
    recording = None
    current.stop_capture()
    audio_ducker.restore()
    if current.audio_bytes == 0:
        current.discard()
        raise RuntimeError("No audio captured")
    try:
        text = current.text()
    finally:
        current.audio_file.unlink(missing_ok=True)
    if not text:
        notify("No speech detected")
        return ""
    notify("Transcription ready")
    return text


def paste_text(text):
    if not text:
        return

    subprocess.run(["wl-copy"], input=text, text=True, check=True)
    subprocess.run(
        ["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def type_text(text):
    if not text:
        return

    subprocess.run(
        ["wtype", "--", text],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def press_key(key):
    allowed = {"BackSpace", "Delete", "Escape"}
    if key not in allowed:
        raise RuntimeError(f"Unsupported key: {key}")

    subprocess.run(
        ["wtype", "-k", key],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def handle(message):
    command = message.get("command")
    request_id = message.get("requestId")

    try:
        if command == "start":
            start_recording()  # an older popup may still send a Whisper model name; it is ignored
            return {"requestId": request_id, "ok": True}
        if command == "stop":
            return {"requestId": request_id, "ok": True, "text": transcribe_recording()}
        if command == "paste":
            paste_text(message.get("text", ""))
            return {"requestId": request_id, "ok": True}
        if command == "type":
            type_text(message.get("text", ""))
            return {"requestId": request_id, "ok": True}
        if command == "key":
            press_key(message.get("key", ""))
            return {"requestId": request_id, "ok": True}
        if command == "cancel":
            cancel_recording()
            return {"requestId": request_id, "ok": True}
        return {"requestId": request_id, "ok": False, "error": f"Unknown command: {command}"}
    except Exception as error:
        return {"requestId": request_id, "ok": False, "error": str(error)}


def main():
    while True:
        message = read_message()
        if message is None:
            cancel_recording()
            return
        write_message(handle(message))


if __name__ == "__main__":
    main()
