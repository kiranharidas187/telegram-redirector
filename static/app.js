const SIGNAL_COLORS = ["#4FB8A8", "#5FA8D8", "#7BC0A0", "#4F9DC4", "#8FC9C0", "#6FB093"];

const state = {
  config: { channels: [], speech_rate: 175, volume: 1.0 },
  voices: [],
  listening: false,
  sse: null,
};

// ------------------------------------------------------------------- dom

const loginScreen = document.getElementById("login-screen");
const consoleScreen = document.getElementById("console-screen");

const phoneForm = document.getElementById("phone-form");
const phoneInput = document.getElementById("phone-input");
const codeForm = document.getElementById("code-form");
const codeInput = document.getElementById("code-input");
const changeNumberBtn = document.getElementById("change-number-btn");
const passwordForm = document.getElementById("password-form");
const passwordInput = document.getElementById("password-input");
const loginError = document.getElementById("login-error");

const onAirDot = document.getElementById("on-air-dot");
const connectedAsEl = document.getElementById("connected-as");
const logoutBtn = document.getElementById("logout-btn");

const channelList = document.getElementById("channel-list");
const channelEmpty = document.getElementById("channel-empty");
const tuneInBtn = document.getElementById("tune-in-btn");

const rateInput = document.getElementById("rate-input");
const rateValue = document.getElementById("rate-value");
const volumeInput = document.getElementById("volume-input");
const volumeValue = document.getElementById("volume-value");

const restartBanner = document.getElementById("restart-banner");
const restartBtn = document.getElementById("restart-btn");
const listenToggleBtn = document.getElementById("listen-toggle-btn");
const listenerError = document.getElementById("listener-error");

const logList = document.getElementById("log-list");
const logEmpty = document.getElementById("log-empty");

const tuneInModal = document.getElementById("tune-in-modal");
const tuneInCloseBtn = document.getElementById("tune-in-close-btn");
const dialogSearch = document.getElementById("dialog-search");
const dialogList = document.getElementById("dialog-list");
const dialogLoading = document.getElementById("dialog-loading");

// ------------------------------------------------------------------- api

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15000);
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
      signal: controller.signal,
    });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("Request timed out after 15s — is the server still running?");
    }
    throw new Error(`Couldn't reach the server: ${err.message}`);
  } finally {
    clearTimeout(timeoutId);
  }
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json() : null;
  if (!res.ok) {
    throw new Error(body?.detail || res.statusText);
  }
  return body;
}

// ----------------------------------------------------------------- login

function showLogin() {
  loginScreen.hidden = false;
  consoleScreen.hidden = true;
}

function showStep(name) {
  phoneForm.hidden = name !== "phone";
  codeForm.hidden = name !== "code";
  passwordForm.hidden = name !== "password";
}

function showLoginError(message) {
  loginError.textContent = message;
  loginError.hidden = false;
}

function clearLoginError() {
  loginError.hidden = true;
}

phoneForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearLoginError();
  try {
    await api("/api/auth/send-code", {
      method: "POST",
      body: JSON.stringify({ phone: phoneInput.value.trim() }),
    });
    showStep("code");
  } catch (err) {
    showLoginError(err.message);
  }
});

codeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearLoginError();
  try {
    const result = await api("/api/auth/verify-code", {
      method: "POST",
      body: JSON.stringify({ code: codeInput.value.trim() }),
    });
    if (result.status === "awaiting_password") {
      showStep("password");
    } else {
      await enterConsole(result.name);
    }
  } catch (err) {
    showLoginError(err.message);
  }
});

passwordForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearLoginError();
  try {
    const result = await api("/api/auth/verify-password", {
      method: "POST",
      body: JSON.stringify({ password: passwordInput.value }),
    });
    await enterConsole(result.name);
  } catch (err) {
    showLoginError(err.message);
  }
});

changeNumberBtn.addEventListener("click", () => showStep("phone"));

logoutBtn.addEventListener("click", async () => {
  if (!confirm("Log out of Telegram? You'll need to enter your phone and code again.")) return;
  await api("/api/auth/logout", { method: "POST" });
  stopSSE();
  showLogin();
  showStep("phone");
  phoneInput.value = "";
  codeInput.value = "";
  passwordInput.value = "";
});

async function checkAuthStatus() {
  const status = await api("/api/auth/status");
  if (status.status === "connected") {
    await enterConsole(status.name);
  } else if (status.status === "awaiting_password") {
    showLogin();
    showStep("password");
  } else if (status.status === "awaiting_code") {
    showLogin();
    showStep("code");
  } else {
    showLogin();
    showStep("phone");
  }
}

// --------------------------------------------------------------- console

async function enterConsole(name) {
  loginScreen.hidden = true;
  consoleScreen.hidden = false;
  connectedAsEl.textContent = `Connected as ${name}`;
  await loadConsoleData();
}

async function loadConsoleData() {
  const [config, voices, listenerStatus] = await Promise.all([
    api("/api/config"),
    api("/api/voices"),
    api("/api/listener/status"),
  ]);
  state.config = config;
  state.voices = voices;
  state.listening = listenerStatus.listening;

  rateInput.value = config.speech_rate;
  rateValue.textContent = config.speech_rate;
  const volumePct = Math.round(config.volume * 100);
  volumeInput.value = volumePct;
  volumeValue.textContent = `${volumePct}%`;

  renderChannels();
  updateListenToggle();
  connectSSE();
}

function signalColorFor(index) {
  return SIGNAL_COLORS[index % SIGNAL_COLORS.length];
}

let saveTimer = null;

function onConfigEdited() {
  if (state.listening) {
    restartBanner.hidden = false;
  }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveConfig, 500);
}

async function saveConfig() {
  try {
    state.config = await api("/api/config", {
      method: "PUT",
      body: JSON.stringify(state.config),
    });
  } catch (err) {
    console.error("Failed to save config:", err.message);
  }
}

function renderChannels() {
  channelList.innerHTML = "";
  const channels = state.config.channels;
  channelEmpty.hidden = channels.length > 0;

  channels.forEach((ch, index) => {
    const li = document.createElement("li");
    li.className = "channel-strip";
    li.dataset.channelId = String(ch.id);

    const top = document.createElement("div");
    top.className = "channel-strip-top";

    const dot = document.createElement("span");
    dot.className = "signal-dot" + (ch.enabled && !ch.muted ? " enabled" : "");
    dot.style.setProperty("--signal-color", signalColorFor(index));
    top.appendChild(dot);

    const title = document.createElement("span");
    title.className = "channel-title" + (ch.muted ? " muted-title" : "");
    title.textContent = ch.title;
    top.appendChild(title);

    const switchLabel = document.createElement("label");
    switchLabel.className = "switch";
    switchLabel.title = ch.enabled ? "Enabled" : "Disabled";
    const switchInput = document.createElement("input");
    switchInput.type = "checkbox";
    switchInput.checked = ch.enabled;
    switchInput.addEventListener("change", () => {
      ch.enabled = switchInput.checked;
      onConfigEdited();
      renderChannels();
    });
    const switchTrack = document.createElement("span");
    switchTrack.className = "switch-track";
    switchLabel.append(switchInput, switchTrack);
    top.appendChild(switchLabel);

    li.appendChild(top);

    const controls = document.createElement("div");
    controls.className = "channel-strip-controls";

    const voiceSelect = document.createElement("select");
    voiceSelect.className = "voice-select field-input";
    const autoOpt = document.createElement("option");
    autoOpt.value = "auto";
    autoOpt.textContent = "Auto";
    voiceSelect.appendChild(autoOpt);
    state.voices.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = v.name;
      voiceSelect.appendChild(opt);
    });
    voiceSelect.value = ch.voice || "auto";
    voiceSelect.addEventListener("change", () => {
      ch.voice = voiceSelect.value;
      onConfigEdited();
    });
    controls.appendChild(voiceSelect);

    const previewBtn = document.createElement("button");
    previewBtn.type = "button";
    previewBtn.className = "btn btn-ghost btn-small";
    previewBtn.textContent = "Preview";
    previewBtn.addEventListener("click", () => previewVoice(ch));
    controls.appendChild(previewBtn);

    const muteBtn = document.createElement("button");
    muteBtn.type = "button";
    muteBtn.className = "btn btn-ghost btn-small";
    muteBtn.textContent = ch.muted ? "Unmute" : "Mute";
    muteBtn.addEventListener("click", () => {
      ch.muted = !ch.muted;
      onConfigEdited();
      renderChannels();
    });
    controls.appendChild(muteBtn);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn btn-ghost btn-small remove-channel-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => {
      state.config.channels = state.config.channels.filter((c) => c.id !== ch.id);
      onConfigEdited();
      renderChannels();
    });
    controls.appendChild(removeBtn);

    li.appendChild(controls);
    channelList.appendChild(li);
  });
}

async function previewVoice(ch) {
  try {
    await api("/api/voices/preview", {
      method: "POST",
      body: JSON.stringify({
        voice: ch.voice === "auto" ? null : ch.voice,
        text: `This is ${ch.title}.`,
      }),
    });
  } catch (err) {
    alert(`Couldn't preview that voice: ${err.message}`);
  }
}

rateInput.addEventListener("input", () => {
  rateValue.textContent = rateInput.value;
  state.config.speech_rate = Number(rateInput.value);
  onConfigEdited();
});

volumeInput.addEventListener("input", () => {
  const pct = Number(volumeInput.value);
  volumeValue.textContent = `${pct}%`;
  state.config.volume = pct / 100;
  onConfigEdited();
});

function updateListenToggle() {
  onAirDot.classList.toggle("live", state.listening);
  listenToggleBtn.textContent = state.listening ? "Stop listening" : "Apply & start listening";
  listenToggleBtn.classList.toggle("stop", state.listening);
}

listenToggleBtn.addEventListener("click", async () => {
  listenerError.hidden = true;
  try {
    if (state.listening) {
      await api("/api/listener/stop", { method: "POST" });
      state.listening = false;
    } else {
      clearTimeout(saveTimer);
      await saveConfig();
      await api("/api/listener/start", { method: "POST" });
      state.listening = true;
    }
    restartBanner.hidden = true;
    updateListenToggle();
  } catch (err) {
    listenerError.textContent = err.message;
    listenerError.hidden = false;
  }
});

restartBtn.addEventListener("click", async () => {
  listenerError.hidden = true;
  try {
    clearTimeout(saveTimer);
    await saveConfig();
    await api("/api/listener/stop", { method: "POST" });
    await api("/api/listener/start", { method: "POST" });
    state.listening = true;
    restartBanner.hidden = true;
    updateListenToggle();
  } catch (err) {
    listenerError.textContent = err.message;
    listenerError.hidden = false;
  }
});

// ------------------------------------------------------------- tune-in

let allDialogs = [];

async function openTuneInModal() {
  tuneInModal.hidden = false;
  dialogSearch.value = "";
  dialogList.innerHTML = "";
  dialogLoading.hidden = false;
  dialogLoading.style.cursor = "";
  dialogLoading.onclick = null;
  dialogLoading.textContent = "Fetching your channels…";
  try {
    allDialogs = await api("/api/dialogs");
    dialogLoading.hidden = true;
    renderDialogList("");
  } catch (err) {
    dialogLoading.textContent = `Couldn't load channels: ${err.message} (click to retry)`;
    dialogLoading.style.cursor = "pointer";
    dialogLoading.onclick = () => openTuneInModal();
  }
}

function closeTuneInModal() {
  tuneInModal.hidden = true;
}

tuneInBtn.addEventListener("click", openTuneInModal);
tuneInCloseBtn.addEventListener("click", closeTuneInModal);
tuneInModal.addEventListener("click", (e) => {
  if (e.target === tuneInModal) closeTuneInModal();
});

dialogSearch.addEventListener("input", () => {
  renderDialogList(dialogSearch.value.trim().toLowerCase());
});

function renderDialogList(query) {
  dialogList.innerHTML = "";
  const configuredIds = new Set(state.config.channels.map((c) => c.id));
  const filtered = allDialogs.filter((d) => (d.title || "").toLowerCase().includes(query));

  filtered.forEach((d) => {
    const li = document.createElement("li");
    li.className = "dialog-row";

    const name = document.createElement("span");
    name.className = "dialog-row-name";
    name.textContent = d.title;
    li.appendChild(name);

    const kind = document.createElement("span");
    kind.className = "dialog-row-kind";
    kind.textContent = d.kind;
    li.appendChild(kind);

    const alreadyAdded = configuredIds.has(d.id);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-small " + (alreadyAdded ? "btn-ghost" : "btn-primary");
    btn.textContent = alreadyAdded ? "Added" : "Add";
    btn.disabled = alreadyAdded;
    btn.addEventListener("click", () => {
      state.config.channels.push({
        id: d.id,
        title: d.title,
        username: d.username,
        enabled: true,
        muted: false,
        voice: "auto",
      });
      onConfigEdited();
      renderChannels();
      renderDialogList(query);
    });
    li.appendChild(btn);

    dialogList.appendChild(li);
  });
}

// -------------------------------------------------------------- activity

function connectSSE() {
  if (state.sse) return;
  state.sse = new EventSource("/api/activity/stream");
  state.sse.onmessage = (e) => {
    const item = JSON.parse(e.data);
    addLogEntry(item);
    pulseChannel(item.channel_id);
  };
}

function stopSSE() {
  state.sse?.close();
  state.sse = null;
}

function colorForChannelId(id) {
  const index = state.config.channels.findIndex((c) => c.id === id);
  return signalColorFor(index === -1 ? 0 : index);
}

function addLogEntry(item) {
  logEmpty.hidden = true;

  const li = document.createElement("li");
  li.className = "log-entry";

  const dot = document.createElement("span");
  dot.className = "signal-dot enabled pulse";
  dot.style.setProperty("--signal-color", colorForChannelId(item.channel_id));
  li.appendChild(dot);

  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = item.ts;
  li.appendChild(time);

  const channel = document.createElement("span");
  channel.className = "log-channel";
  channel.textContent = item.channel_title;
  li.appendChild(channel);

  const text = document.createElement("p");
  text.className = "log-text";
  text.textContent = item.text;
  li.appendChild(text);

  logList.prepend(li);
  while (logList.children.length > 50) {
    logList.removeChild(logList.lastChild);
  }
}

function pulseChannel(id) {
  const strip = channelList.querySelector(`[data-channel-id="${CSS.escape(String(id))}"]`);
  const dot = strip?.querySelector(".signal-dot");
  if (!dot) return;
  dot.classList.remove("pulse");
  void dot.offsetWidth; // restart the animation
  dot.classList.add("pulse");
}

// ---------------------------------------------------------------- start

checkAuthStatus().catch((err) => {
  console.error(err);
  showLogin();
  showStep("phone");
});
