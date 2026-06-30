#!/usr/bin/env python3
import json
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


APP_NAME = "Hold Space Dictation"
MODEL_DIR = Path(os.path.expanduser(os.environ.get("FLOW_MODEL_DIR", "~/.local/lib/whisper")))
THREADS = os.environ.get("FLOW_THREADS", "4")
WHISPER_BIN = os.environ.get("FLOW_WHISPER_BIN", "whisper-cli")
MODEL_FILES = {
    "small": "ggml-small.en.bin",
    "medium": "ggml-medium.en.bin",
    "large": "ggml-large-v3.bin",
    "turbo": "ggml-large-v3-turbo.bin",
}

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


def model_path(model_name):
    filename = MODEL_FILES.get(model_name)
    if not filename:
        raise RuntimeError(f"Unknown model: {model_name}")
    path = MODEL_DIR / filename
    if not path.exists():
        raise RuntimeError(f"Missing model: {path}")
    return path


def normalize_whisper_output(raw):
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"^\[[^]]*\]\s*", "", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def start_recording(model_name):
    global recording
    if recording:
        cancel_recording()
    model = model_path(model_name)

    audio_file = Path(tempfile.gettempdir()) / f"hold-space-dictation-{os.getpid()}.wav"
    if audio_file.exists():
        audio_file.unlink()

    process = subprocess.Popen(
        ["parecord", "--file-format=wav", "--rate=16000", "--channels=1", str(audio_file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    recording = {
        "process": process,
        "audio_file": audio_file,
        "model": model,
    }
    audio_ducker.duck()
    time.sleep(max(0, RECORD_READY_DELAY_MS) / 1000)
    notify(f"Recording ({model_name})...")


def cancel_recording():
    global recording
    if not recording:
        return
    process = recording["process"]
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    audio_ducker.restore()
    recording = None


def transcribe_recording():
    global recording
    if not recording:
        raise RuntimeError("No active recording")

    current = recording
    recording = None
    process = current["process"]
    audio_file = current["audio_file"]

    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    audio_ducker.restore()

    if not audio_file.exists() or audio_file.stat().st_size == 0:
        raise RuntimeError("No audio captured")

    notify("Transcribing...")
    with tempfile.NamedTemporaryFile("w+", delete=False) as err_file:
        err_path = err_file.name

    command = [WHISPER_BIN, "-m", str(current["model"]), "-t", THREADS, "-nt", "-f", str(audio_file)]
    raw = subprocess.run(command, text=True, capture_output=True, check=False)

    if not raw.stdout and re.search(r"vulkan|out of|allocat|gpu|failed to initialize", raw.stderr, re.I):
        cpu_command = [WHISPER_BIN, "-ng", "-m", str(current["model"]), "-t", THREADS, "-nt", "-f", str(audio_file)]
        raw = subprocess.run(cpu_command, text=True, capture_output=True, check=False)

    try:
        os.unlink(err_path)
    except OSError:
        pass

    if raw.returncode != 0 and not raw.stdout:
        detail = " ".join(raw.stderr.splitlines()[-3:])
        raise RuntimeError(f"whisper-cli failed: {detail}")

    text = normalize_whisper_output(raw.stdout)
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
            start_recording(message.get("model", "small"))
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
