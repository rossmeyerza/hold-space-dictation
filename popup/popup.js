const DEFAULT_SETTINGS = {
  model: "small",
  holdDelayMs: 350,
  minRecordingMs: 900
};

const controls = {
  model: document.getElementById("model"),
  holdDelayMs: document.getElementById("holdDelayMs"),
  minRecordingMs: document.getElementById("minRecordingMs")
};

const holdDelayValue = document.getElementById("holdDelayValue");
const minRecordingValue = document.getElementById("minRecordingValue");
const status = document.getElementById("status");
const reset = document.getElementById("reset");

function updateOutputs() {
  holdDelayValue.textContent = `${controls.holdDelayMs.value}ms`;
  minRecordingValue.textContent = `${controls.minRecordingMs.value}ms`;
}

function showSaved() {
  status.textContent = "Saved";
  window.setTimeout(() => {
    status.textContent = "Saved";
  }, 800);
}

function readControls() {
  return {
    model: controls.model.value,
    holdDelayMs: Number(controls.holdDelayMs.value),
    minRecordingMs: Number(controls.minRecordingMs.value)
  };
}

function applySettings(settings) {
  controls.model.value = settings.model;
  controls.holdDelayMs.value = settings.holdDelayMs;
  controls.minRecordingMs.value = settings.minRecordingMs;
  updateOutputs();
}

async function save() {
  updateOutputs();
  status.textContent = "Saving...";
  await chrome.storage.local.set(readControls());
  showSaved();
}

chrome.storage.local.get(DEFAULT_SETTINGS, (settings) => {
  applySettings(settings);
});

for (const control of Object.values(controls)) {
  control.addEventListener("input", save);
}

reset.addEventListener("click", async () => {
  applySettings(DEFAULT_SETTINGS);
  await save();
});
