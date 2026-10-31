/* Puffin Bank web app: talks only to the gateway at /api. No build step. */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { callId: null, name: null, voice: { stt: false, tts: false }, pending: null, recorder: null, chunks: [] };

  // ---- helpers --------------------------------------------------------------
  async function api(path, options = {}) {
    const response = await fetch(`/api${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }
  const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  function bubble(role, text, extra) {
    const li = document.createElement("li");
    li.className = `bubble ${role}`;
    li.textContent = text;
    if (extra) {
      const small = document.createElement("span");
      small.className = "heard";
      small.textContent = extra;
      li.appendChild(small);
    }
    $("transcript").appendChild(li);
    $("transcript").scrollTop = $("transcript").scrollHeight;
  }

  function ring(stateName, label) {
    $("ring").dataset.state = stateName;
    $("ring-label").textContent = label;
  }

  function speak(text) {
    if (!text) return;
    ring("speaking", "Speaking");
    const done = () => ring("idle", "Ready");
    if (state.voice.tts) {
      const audio = new Audio(`/api/tts?text=${encodeURIComponent(text)}`);
      audio.onended = done;
      audio.onerror = () => browserSpeak(text, done);
      audio.play().catch(() => browserSpeak(text, done));
    } else {
      browserSpeak(text, done);
    }
  }
  function browserSpeak(text, done) {
    if (!("speechSynthesis" in window) || !state.speakAloud) return done();
    const utterance = new SpeechSynthesisUtterance(text.replace(/••••(\d{4})/g, (_, d) => `ending ${d.split("").join(" ")}`));
    utterance.onend = done;
    utterance.onerror = done;
    speechSynthesis.cancel();
    speechSynthesis.speak(utterance);
  }

  // ---- status ---------------------------------------------------------------
  async function loadStatus() {
    try {
      const health = await api("/health");
      for (const dot of document.querySelectorAll(".dot")) {
        const key = dot.dataset.service;
        const up = key === "voice" ? health.voice.stt && health.voice.tts : health[key];
        dot.classList.toggle("up", !!up);
        dot.classList.toggle("down", !up);
      }
      state.voice = health.voice;
      if (!health.voice.stt) {
        $("mic").disabled = true;
        $("mic").title = "Local speech-to-text isn't installed (make voice)";
      }
      state.speakAloud = true;
    } catch {
      /* the gateway itself is down; the picker still renders */
    }
  }

  // ---- profiles -------------------------------------------------------------
  async function loadProfiles() {
    const profiles = await api("/profiles");
    const holder = $("profiles");
    holder.innerHTML = "";
    for (const p of profiles) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "card" + (p.pin ? "" : " impostor");
      button.setAttribute("role", "listitem");
      button.innerHTML = `
        <div class="chip" aria-hidden="true"></div>
        <div>
          <div class="name">${p.name}</div>
          <div class="code">${p.customer_code}</div>
          <div class="story">${p.story}</div>
          <div class="pin">${p.pin ? `PIN <b>${p.pin}</b>` : "No PIN. Try to get in anyway."}</div>
        </div>`;
      button.addEventListener("click", () => startCall(p));
      holder.appendChild(button);
    }
  }

  // ---- the call -------------------------------------------------------------
  async function startCall(profile) {
    try {
      const call = await post("/calls", { customer_code: profile.customer_code });
      state.callId = call.call_id;
      state.name = call.name;
      $("caller-name").textContent = call.name;
      $("transcript").innerHTML = "";
      $("turns").innerHTML = "";
      for (const id of ["gate-verified", "gate-confirmed", "gate-code"]) $(id).classList.remove("passed");
      $("pick").classList.add("hidden");
      $("call").classList.remove("hidden");
      $("hood").classList.remove("hidden");
      document.querySelector(".layout").classList.add("on-call");
      bubble("assistant", call.greeting);
      speak(call.greeting);
      $("say").focus();
    } catch (error) {
      alert(error.message);
    }
  }

  function endCall() {
    state.callId = null;
    $("pick").classList.remove("hidden");
    $("call").classList.add("hidden");
    $("hood").classList.add("hidden");
    document.querySelector(".layout").classList.remove("on-call");
    speechSynthesis && speechSynthesis.cancel();
  }

  async function send(text) {
    if (!state.callId || !text.trim()) return;
    bubble("caller", text);
    $("say").value = "";
    await turn(() => post(`/calls/${state.callId}/say`, { text }), text);
  }

  async function turn(request, what) {
    ring("thinking", "Thinking");
    $("send").disabled = true;
    try {
      const result = await request();
      handle(result, what);
    } catch (error) {
      ring("idle", "Ready");
      bubble("system", error.message);
    } finally {
      $("send").disabled = false;
    }
  }

  function handle(result, what) {
    if (result.heard && result.kind === "reply" && !result.trace) {
      bubble("system", `Heard: "${result.heard}"`);
    }
    bubble(result.ended ? "ended" : "assistant", result.text, result.heard && result.trace ? `Heard: "${result.heard}"` : null);
    if (result.trace) addTurn(what, result);
    if (result.kind === "pin") {
      ring("paused", "Waiting for the keypad");
      openKeypad("pin", "Enter your PIN", "For your security, enter it on the keypad. The assistant never sees it.");
      return;
    }
    if (result.kind === "one_time_code") {
      ring("paused", "Waiting for the keypad");
      openKeypad("code", "Enter the one-time code", "We've sent a 6-digit code to your phone.", result.demo_code);
      return;
    }
    if (result.kind === "confirm") {
      ring("paused", "Waiting for your yes");
      $("confirm-text").textContent = result.text;
      $("confirm").classList.remove("hidden");
      $("confirm-yes").focus();
      return;
    }
    speak(result.text);
    if (result.ended) {
      $("hint").textContent = result.handoff_reason ? `Handed to a person (${result.handoff_reason.replaceAll("_", " ")}). Pick a customer to start again.` : "Call ended.";
      state.callId = null;
      setTimeout(endCall, 6000);
    }
  }

  // ---- keypad -----------------------------------------------------------------
  function openKeypad(kind, title, text, demoCode) {
    state.pending = { kind, length: kind === "pin" ? 4 : 6, value: "" };
    $("keypad-title").textContent = title;
    $("keypad-text").textContent = text;
    $("demo-code").classList.toggle("hidden", !demoCode);
    if (demoCode) $("demo-code").innerHTML = `Demo phone: your Puffin Bank code is <b>${demoCode}</b>`;
    renderDigits();
    $("keypad").classList.remove("hidden");
    $("keys").querySelector("button").focus();
  }
  function renderDigits() {
    const { length, value } = state.pending;
    $("digits").innerHTML = Array.from({ length }, (_, i) => `<span class="${i < value.length ? "filled" : ""}"></span>`).join("");
    $("keypad-ok").disabled = value.length !== length;
  }
  function press(key) {
    if (!state.pending) return;
    if (key === "back") state.pending.value = state.pending.value.slice(0, -1);
    else if (state.pending.value.length < state.pending.length) state.pending.value += key;
    renderDigits();
  }
  async function submitKeypad(cancel) {
    const { kind, value } = state.pending;
    $("keypad").classList.add("hidden");
    state.pending = null;
    bubble("caller", cancel ? "[cancelled]" : kind === "pin" ? "[PIN entered on keypad]" : "[code entered on keypad]");
    await turn(() => post(`/calls/${state.callId}/${kind}`, { digits: cancel ? "" : value }), kind === "pin" ? "PIN entry" : "One-time code");
  }

  // ---- confirmation -------------------------------------------------------------
  async function answerConfirm(text) {
    $("confirm").classList.add("hidden");
    bubble("caller", text);
    await turn(() => post(`/calls/${state.callId}/confirm`, { text }), `Said "${text}"`);
  }

  // ---- under the hood -------------------------------------------------------------
  function addTurn(what, result) {
    const spans = result.trace.spans || [];
    const names = spans.map((s) => s.node);
    const summary = Object.assign({}, ...spans.map((s) => s.summary || {}));
    const li = document.createElement("li");
    const handoff = names.includes("handoff");
    const blocked = summary.moderation && summary.moderation.label !== "safe";
    li.className = "turn " + (handoff ? "handoff" : blocked ? "blocked" : "ok");
    const tags = [];
    if (summary.moderation) tags.push(`<span class="tag ${blocked ? "warn" : "kelp"}">moderation: ${summary.moderation.label} (${summary.moderation.tier}${summary.moderation.score ? ", " + Math.round(summary.moderation.score * 100) + "%" : ""})</span>`);
    if (summary.intent) tags.push(`<span class="tag navy">intent: ${summary.intent}${summary.router_confidence ? " " + Math.round(summary.router_confidence * 100) + "%" : ""}</span>`);
    if (summary.risk_tier) tags.push(`<span class="tag">risk: ${summary.risk_tier}</span>`);
    if (summary.policy) tags.push(`<span class="tag kelp">policy: ${summary.policy.source}${summary.policy.policy_id ? " " + summary.policy.policy_id : ""}</span>`);
    if (summary.tool || summary.tool_result) tags.push(`<span class="tag navy">tool: ${summary.tool_result || summary.tool}</span>`);
    if (summary.handoff_reason) tags.push(`<span class="tag warn">handoff: ${summary.handoff_reason}</span>`);
    li.innerHTML = `<div class="what">${escapeHtml(what)}</div>
      <div class="path">${names.join(" → ")} · ${result.trace.turn_ms} ms</div>
      <div class="tags">${tags.join("")}</div>`;
    $("turns").prepend(li);
    if (summary.verified) $("gate-verified").classList.add("passed");
    if (summary.confirmed) $("gate-confirmed").classList.add("passed");
    if (summary.step_up_verified) $("gate-code").classList.add("passed");
  }
  const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  // ---- voice in ------------------------------------------------------------------
  async function startRecording() {
    if (!state.voice.stt || state.recorder) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      state.chunks = [];
      state.recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      state.recorder.ondataavailable = (e) => e.data.size && state.chunks.push(e.data);
      state.recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(state.chunks, { type: "audio/webm" });
        state.recorder = null;
        if (blob.size < 2000) return ring("idle", "Ready");
        const form = new FormData();
        form.append("file", blob, "turn.webm");
        bubble("caller", "🎤 …");
        const placeholder = $("transcript").lastElementChild;
        await turn(async () => {
          const result = await api(`/calls/${state.callId}/audio`, { method: "POST", body: form });
          placeholder.textContent = result.heard ? result.heard : "(nothing heard)";
          return result;
        }, "Spoken turn");
      };
      state.recorder.start();
      speechSynthesis && speechSynthesis.cancel(); // barge-in
      $("mic").setAttribute("aria-pressed", "true");
      ring("listening", "Listening");
    } catch {
      $("hint").textContent = "Microphone access was refused. You can type instead.";
    }
  }
  function stopRecording() {
    if (!state.recorder) return;
    $("mic").setAttribute("aria-pressed", "false");
    state.recorder.stop();
  }

  // ---- wiring ---------------------------------------------------------------------
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); send($("say").value); });
  $("hangup").addEventListener("click", endCall);
  for (const b of $("try").querySelectorAll("button")) b.addEventListener("click", () => send(b.dataset.say));
  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "back"];
  $("keys").innerHTML = keys.map((k) => (k === "" ? "<span></span>" : `<button type="button" data-key="${k}" class="${k === "back" ? "back" : ""}">${k === "back" ? "⌫" : k}</button>`)).join("");
  $("keys").addEventListener("click", (e) => e.target.dataset.key && press(e.target.dataset.key));
  document.addEventListener("keydown", (e) => {
    if (!state.pending) return;
    if (/^\d$/.test(e.key)) press(e.key);
    if (e.key === "Backspace") press("back");
    if (e.key === "Enter" && !$("keypad-ok").disabled) submitKeypad(false);
    if (e.key === "Escape") submitKeypad(true);
  });
  $("keypad-ok").addEventListener("click", () => submitKeypad(false));
  $("keypad-cancel").addEventListener("click", () => submitKeypad(true));
  $("confirm-yes").addEventListener("click", () => answerConfirm("yes"));
  $("confirm-no").addEventListener("click", () => answerConfirm("no"));
  const mic = $("mic");
  mic.addEventListener("pointerdown", (e) => { e.preventDefault(); startRecording(); });
  mic.addEventListener("pointerup", stopRecording);
  mic.addEventListener("pointerleave", stopRecording);
  mic.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); startRecording(); } });
  mic.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") stopRecording(); });

  loadStatus();
  loadProfiles().catch(() => { $("profiles").innerHTML = "<p class='fineprint'>The gateway isn't running. Start it with <code>make serve</code>.</p>"; });
})();
