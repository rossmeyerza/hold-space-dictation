const HOST_NAME = "com.ross.hold_space_dictation";

let port = null;
let nextRequestId = 1;
const pending = new Map();

function ensurePort() {
  if (port) return port;

  port = chrome.runtime.connectNative(HOST_NAME);

  port.onMessage.addListener((message) => {
    const requestId = message && message.requestId;
    const callbacks = pending.get(requestId);
    if (!callbacks) return;
    pending.delete(requestId);

    if (message.ok) {
      callbacks.resolve(message);
    } else {
      callbacks.reject(new Error(message.error || "Native host failed"));
    }
  });

  port.onDisconnect.addListener(() => {
    const error = new Error(chrome.runtime.lastError?.message || "Native host disconnected");
    for (const callbacks of pending.values()) callbacks.reject(error);
    pending.clear();
    port = null;
  });

  return port;
}

function sendNative(command, payload = {}) {
  const requestId = nextRequestId++;
  const nativePort = ensurePort();

  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject });
    nativePort.postMessage({ requestId, command, ...payload });
  });
}

function notify(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon-128.png",
    title,
    message
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.source !== "hold-space-dictation") return false;

  (async () => {
    if (message.command === "start") {
      await sendNative("start", { model: message.model || "small" });
      notify("Dictation", "Recording...");
      sendResponse({ ok: true });
      return;
    }

    if (message.command === "stop") {
      const result = await sendNative("stop");
      const text = result.text || "";
      notify("Dictation", text ? "Inserted transcription." : "No speech detected.");
      sendResponse({ ok: true, text });
      return;
    }

    if (message.command === "paste") {
      await sendNative("paste", { text: message.text || "" });
      sendResponse({ ok: true });
      return;
    }

    if (message.command === "type") {
      await sendNative("type", { text: message.text || "" });
      sendResponse({ ok: true });
      return;
    }

    if (message.command === "key") {
      await sendNative("key", { key: message.key || "" });
      sendResponse({ ok: true });
      return;
    }

    if (message.command === "cancel") {
      await sendNative("cancel");
      sendResponse({ ok: true });
      return;
    }

    sendResponse({ ok: false, error: `Unknown command: ${message.command}` });
  })().catch((error) => {
    sendResponse({ ok: false, error: error.message });
  });

  return true;
});
