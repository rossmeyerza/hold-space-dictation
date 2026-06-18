const SOURCE = "hold-space-dictation";
const DEFAULT_SETTINGS = {
  model: "small",
  holdDelayMs: 350,
  minRecordingMs: 900
};

let pendingTimer = null;
let pendingTarget = null;
let recordingTarget = null;
let recordingSelection = null;
let recording = false;
let startPromise = null;
let recordingStartedAt = 0;
let spaceDown = false;
let settings = { ...DEFAULT_SETTINGS };

chrome.storage.local.get(DEFAULT_SETTINGS, (stored) => {
  settings = normalizeSettings(stored);
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  settings = normalizeSettings({
    ...settings,
    ...Object.fromEntries(Object.entries(changes).map(([key, change]) => [key, change.newValue]))
  });
});

function normalizeSettings(value) {
  const model = ["small", "medium", "large", "turbo"].includes(value.model)
    ? value.model
    : DEFAULT_SETTINGS.model;
  return {
    model,
    holdDelayMs: clampNumber(value.holdDelayMs, 150, 1500, DEFAULT_SETTINGS.holdDelayMs),
    minRecordingMs: clampNumber(value.minRecordingMs, 0, 3000, DEFAULT_SETTINGS.minRecordingMs)
  };
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isEditable(element) {
  if (!element || element.isContentEditable) return Boolean(element?.isContentEditable);
  if (element.tagName === "TEXTAREA") return !element.disabled && !element.readOnly;
  if (element.tagName !== "INPUT") return false;

  const type = (element.type || "text").toLowerCase();
  const textTypes = new Set([
    "search",
    "tel",
    "text",
    "url"
  ]);
  return textTypes.has(type) && !element.disabled && !element.readOnly;
}

function message(command, payload = {}) {
  return chrome.runtime.sendMessage({ source: SOURCE, command, ...payload });
}

function showStatus(text, state = "recording") {
  let node = document.getElementById("hsd-status");
  if (!node) {
    node = document.createElement("div");
    node.id = "hsd-status";
    document.documentElement.appendChild(node);
  }
  node.dataset.state = state;
  node.textContent = text;
}

function hideStatus(delay = 0) {
  const node = document.getElementById("hsd-status");
  if (!node) return;
  window.setTimeout(() => node.remove(), delay);
}

function dispatchInput(element, inputType, data) {
  element.dispatchEvent(new InputEvent("input", {
    bubbles: true,
    cancelable: false,
    inputType,
    data
  }));
}

function selectionInside(element) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return false;

  const range = selection.getRangeAt(0);
  return element.contains(range.commonAncestorContainer);
}

function saveSelection(element) {
  if (!element?.isContentEditable || !selectionInside(element)) return null;
  const selection = window.getSelection();
  return selection.getRangeAt(0).cloneRange();
}

function restoreSelection(element, range) {
  if (!range || !element?.isContentEditable) return false;
  if (!element.contains(range.commonAncestorContainer)) return false;

  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  return true;
}

function setNativeValue(element, value) {
  const prototype = element instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");

  if (descriptor?.set) {
    descriptor.set.call(element, value);
  } else {
    element.value = value;
  }
}

function insertIntoInput(element, text) {
  const start = element.selectionStart ?? element.value.length;
  const end = element.selectionEnd ?? start;
  const previous = element.value.slice(0, start);
  const next = element.value.slice(end);
  const value = maybePrefixSpace(previous, next, text);

  const newValue = `${previous}${value}${next}`;
  setNativeValue(element, newValue);
  const cursor = start + value.length;
  element.setSelectionRange(cursor, cursor);
  dispatchInput(element, "insertText", value);
}

function insertIntoContentEditable(text) {
  const activeTarget = recordingTarget;
  if (activeTarget) restoreSelection(activeTarget, recordingSelection);

  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return false;

  const range = selection.getRangeAt(0);
  const previous = range.startContainer.textContent?.slice(0, range.startOffset) || "";
  const value = maybePrefixSpace(previous, "", text);

  const inserted = document.execCommand("insertText", false, value);
  if (inserted) return true;

  if (dispatchSyntheticPaste(activeTarget || document.activeElement, value)) return true;

  range.deleteContents();
  const node = document.createTextNode(value);
  range.insertNode(node);
  range.setStartAfter(node);
  range.setEndAfter(node);
  selection.removeAllRanges();
  selection.addRange(range);
  dispatchInput(activeTarget || document.activeElement, "insertText", value);
  return true;
}

function dispatchSyntheticPaste(element, text) {
  if (!element) return false;

  try {
    const data = new DataTransfer();
    data.setData("text/plain", text);
    const event = new ClipboardEvent("paste", {
      bubbles: true,
      cancelable: true,
      clipboardData: data
    });
    return !element.dispatchEvent(event);
  } catch (_error) {
    return false;
  }
}

function maybePrefixSpace(previous, next, text) {
  const trimmed = text.trim();
  if (!trimmed) return "";
  const needsSpaceBefore = previous && !/\s$/.test(previous) && !/^[.,!?;:)]/.test(trimmed);
  const needsSpaceAfter = next && !/^\s/.test(next) && !/[([{]$/.test(trimmed);
  return `${needsSpaceBefore ? " " : ""}${trimmed}${needsSpaceAfter ? " " : ""}`;
}

function insertText(element, text) {
  if (!isEditable(element) || !text.trim()) return;

  element.focus();
  if (element.isContentEditable) {
    insertIntoContentEditable(text);
    return;
  }
  insertIntoInput(element, text);
}

function insertLiteralSpace(element) {
  if (!isEditable(element)) return;
  if (element.isContentEditable) {
    element.focus();
    recordingTarget = element;
    recordingSelection = saveSelection(element);
    insertIntoContentEditable(" ");
    recordingTarget = null;
    recordingSelection = null;
    return;
  }
  const start = element.selectionStart ?? element.value.length;
  const end = element.selectionEnd ?? start;
  const newValue = `${element.value.slice(0, start)} ${element.value.slice(end)}`;
  setNativeValue(element, newValue);
  element.setSelectionRange(start + 1, start + 1);
  dispatchInput(element, "insertText", " ");
}

function resetPending() {
  if (pendingTimer) window.clearTimeout(pendingTimer);
  pendingTimer = null;
  pendingTarget = null;
  recordingSelection = null;
  spaceDown = false;
}

async function startRecording(target) {
  pendingTimer = null;
  pendingTarget = null;
  recording = true;
  recordingTarget = target;
  recordingSelection = saveSelection(target);
  showStatus("Starting microphone...", "transcribing");

  startPromise = message("start", { model: settings.model }).then((response) => {
    if (!response?.ok) throw new Error(response?.error || "Could not start recording");
    recordingStartedAt = Date.now();
    showStatus("Recording - release Space to insert", "recording");
  }).finally(() => {
    startPromise = null;
  });

  await startPromise;
}

async function startContentEditableRecording(target) {
  pendingTimer = null;
  pendingTarget = null;
  recording = true;
  recordingTarget = target;
  recordingSelection = saveSelection(target);
  showStatus("Starting microphone...", "transcribing");

  target.focus();
  await message("key", { key: "BackSpace" });
  recordingSelection = saveSelection(target);
  startPromise = message("start", { model: settings.model }).then((response) => {
    if (!response?.ok) throw new Error(response?.error || "Could not start recording");
    recordingStartedAt = Date.now();
    showStatus("Recording - release Space to insert", "recording");
  }).finally(() => {
    startPromise = null;
  });

  await startPromise;
}

async function stopRecording() {
  const target = recordingTarget;
  const savedSelection = recordingSelection;
  if (startPromise) await startPromise;

  const remainingMs = settings.minRecordingMs - (Date.now() - recordingStartedAt);
  if (remainingMs > 0) {
    showStatus("Finishing capture...", "recording");
    await delay(remainingMs);
  }

  recording = false;
  recordingSelection = savedSelection;
  showStatus("Transcribing...", "transcribing");

  const response = await message("stop");
  if (!response?.ok) throw new Error(response?.error || "Could not transcribe");

  if (target?.isContentEditable && response.text?.trim()) {
    target.focus();
    restoreSelection(target, savedSelection);
    const value = maybePrefixSpace("", "", response.text);
    await message("paste", { text: value });
  } else {
    insertText(target, response.text || "");
  }
  recordingTarget = null;
  recordingSelection = null;
  recordingStartedAt = 0;
  showStatus(response.text ? "Inserted" : "No speech detected", response.text ? "done" : "error");
  hideStatus(1000);
}

document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.altKey || event.ctrlKey || event.metaKey) return;
  const target = event.target;
  if (!isEditable(target)) return;

  if (target.isContentEditable) {
    if (recording) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    if (event.repeat || spaceDown) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    spaceDown = true;
    pendingTarget = target;
    pendingTimer = window.setTimeout(() => {
      startContentEditableRecording(target).catch((error) => {
        recording = false;
        startPromise = null;
        recordingStartedAt = 0;
        recordingTarget = null;
        recordingSelection = null;
        showStatus(error.message, "error");
        hideStatus(1800);
      });
    }, settings.holdDelayMs);
    return;
  }

  event.preventDefault();
  event.stopPropagation();

  if (event.repeat || spaceDown) return;

  spaceDown = true;
  pendingTarget = target;
  pendingTimer = window.setTimeout(() => {
    startRecording(target).catch((error) => {
      recording = false;
      startPromise = null;
      recordingStartedAt = 0;
      recordingTarget = null;
      recordingSelection = null;
      showStatus(error.message, "error");
      hideStatus(1800);
    });
  }, settings.holdDelayMs);
}, true);

document.addEventListener("keyup", (event) => {
  if (event.code !== "Space" || !spaceDown) return;

  const target = pendingTarget || recordingTarget;
  if (target?.isContentEditable && pendingTimer) {
    resetPending();
    return;
  }

  event.preventDefault();
  event.stopPropagation();

  if (pendingTimer) {
    const target = pendingTarget;
    resetPending();
    insertLiteralSpace(target);
    return;
  }

  spaceDown = false;
  if (recording) {
    stopRecording().catch((error) => {
      recording = false;
      startPromise = null;
      recordingStartedAt = 0;
      recordingTarget = null;
      recordingSelection = null;
      showStatus(error.message, "error");
      hideStatus(1800);
    });
  }
}, true);

document.addEventListener("blur", () => {
  if (pendingTimer) resetPending();
}, true);
