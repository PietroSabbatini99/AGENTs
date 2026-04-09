// ---------------------------------------------------------------------------
// Agent Team — single-page UI
// ---------------------------------------------------------------------------

const AGENT_COLORS = {
  atlas: "var(--atlas)",
  iris: "var(--iris)",
  vitruvio: "var(--vitruvio)",
  nova: "var(--nova)",
  solon: "var(--solon)",
};

const state = {
  agents: [],
  config: { api_key_set: false, api_key_masked: "", model: "" },
  selectedKb: null,
  sending: false,
};

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const chatLog = $("#chat-log");
const chatInput = $("#chat-input");
const chatForm = $("#chat-form");
const sendBtn = $("#send-btn");
const statusLabel = $("#status");
const attachBtn = $("#attach-btn");
const attachInput = $("#attach-input");
const dropZone = $("#drop-zone");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function colorFor(agentKey) {
  return AGENT_COLORS[agentKey] || "var(--custom)";
}

function appendUserMessage(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function appendSystemMessage(text) {
  const el = document.createElement("div");
  el.className = "msg system";
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function appendErrorMessage(text) {
  const el = document.createElement("div");
  el.className = "msg error";
  el.textContent = `Error: ${text}`;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function startAgentBubble(agentKey, agentName) {
  const el = document.createElement("div");
  el.className = "msg agent";
  el.dataset.agent = agentKey;

  const who = document.createElement("div");
  who.className = "who";
  const dot = document.createElement("span");
  dot.className = "dot";
  dot.style.background = colorFor(agentKey);
  const name = document.createElement("span");
  name.textContent = agentName;
  const role = document.createElement("span");
  role.className = "role";
  const profile = state.agents.find((a) => a.key === agentKey);
  role.textContent = profile ? "· " + profile.role : "";

  who.appendChild(dot);
  who.appendChild(name);
  who.appendChild(role);

  const body = document.createElement("div");
  body.className = "body";

  el.appendChild(who);
  el.appendChild(body);
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return body;
}

function setStatus(text, cls = "") {
  statusLabel.textContent = text;
  statusLabel.className = "status " + cls;
}

// ---------------------------------------------------------------------------
// State / fetch
// ---------------------------------------------------------------------------

async function refreshState() {
  const r = await fetch("/api/state");
  const data = await r.json();
  state.agents = data.agents;
  state.config = data.config;
  renderRoster();
  renderTeamTab();
  renderKbAgents();
  renderSettingsTab();
}

function renderRoster() {
  const ul = $("#roster-list");
  ul.innerHTML = "";
  state.agents.forEach((a) => {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = colorFor(a.key);
    const nm = document.createElement("span");
    nm.className = "rname";
    nm.textContent = a.name;
    const rl = document.createElement("span");
    rl.className = "rrole";
    rl.textContent = a.role;
    li.appendChild(dot);
    li.appendChild(nm);
    li.appendChild(rl);
    ul.appendChild(li);
  });
}

function renderTeamTab() {
  const ul = $("#team-roster");
  ul.innerHTML = "";
  state.agents.forEach((a) => {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = colorFor(a.key);

    const col = document.createElement("div");
    col.className = "tcol";
    const nm = document.createElement("div");
    nm.className = "tname";
    nm.textContent = a.name;
    const rl = document.createElement("div");
    rl.className = "trole";
    rl.textContent = a.role + (a.is_custom ? " · custom" : "");
    col.appendChild(nm);
    col.appendChild(rl);

    li.appendChild(dot);
    li.appendChild(col);

    if (a.is_custom) {
      const btn = document.createElement("button");
      btn.className = "tdelete";
      btn.textContent = "Remove";
      btn.onclick = async () => {
        if (!confirm(`Remove ${a.name} from the team?`)) return;
        await fetch(`/api/agents/${a.key}`, { method: "DELETE" });
        await refreshState();
      };
      li.appendChild(btn);
    }
    ul.appendChild(li);
  });
}

function renderKbAgents() {
  const ul = $("#kb-agent-list");
  ul.innerHTML = "";
  state.agents.forEach((a) => {
    const li = document.createElement("li");
    if (state.selectedKb === a.key) li.classList.add("active");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = colorFor(a.key);
    const nm = document.createElement("span");
    nm.textContent = a.name;
    li.appendChild(dot);
    li.appendChild(nm);
    li.onclick = () => {
      state.selectedKb = a.key;
      renderKbAgents();
      loadKbSources(a.key);
    };
    ul.appendChild(li);
  });
  if (state.selectedKb === null && state.agents.length) {
    state.selectedKb = state.agents[0].key;
    renderKbAgents();
    loadKbSources(state.selectedKb);
  }
}

async function loadKbSources(agentKey) {
  const agent = state.agents.find((a) => a.key === agentKey);
  if (!agent) return;
  $("#kb-agent-name").textContent = agent.name;
  $("#kb-agent-role").textContent = agent.role;
  const r = await fetch(`/api/rag/${agentKey}`);
  const data = await r.json();
  const ul = $("#kb-sources");
  ul.innerHTML = "";
  if (!data.sources.length) {
    $("#kb-empty").style.display = "block";
    return;
  }
  $("#kb-empty").style.display = "none";
  data.sources.forEach((s) => {
    const li = document.createElement("li");
    const info = document.createElement("div");
    const nm = document.createElement("div");
    nm.textContent = s.name;
    const meta = document.createElement("div");
    meta.className = "src-meta";
    meta.textContent = `${s.kind.toUpperCase()} · ${s.chunk_count} chunks · ${s.added_at.split("T")[0]}`;
    info.appendChild(nm);
    info.appendChild(meta);

    const del = document.createElement("button");
    del.textContent = "Remove";
    del.onclick = async () => {
      if (!confirm(`Remove "${s.name}"?`)) return;
      await fetch(`/api/rag/${agentKey}/${s.id}`, { method: "DELETE" });
      loadKbSources(agentKey);
    };

    li.appendChild(info);
    li.appendChild(del);
    ul.appendChild(li);
  });
}

function renderSettingsTab() {
  const input = $("#api-key-input");
  input.value = "";
  input.placeholder = state.config.api_key_set
    ? `Saved: ${state.config.api_key_masked}`
    : "sk-ant-…";
  $("#model-input").value = state.config.model || "";
  const status = $("#api-key-status");
  if (state.config.api_key_set) {
    status.textContent = `API key linked · ${state.config.api_key_masked}`;
    status.className = "api-key-status set";
  } else {
    status.textContent = "No API key saved yet.";
    status.className = "api-key-status";
  }
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

$$(".tab").forEach((btn) => {
  btn.onclick = () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".panel").forEach((p) => p.classList.remove("active"));
    $(`.panel[data-panel="${btn.dataset.tab}"]`).classList.add("active");
  };
});

// ---------------------------------------------------------------------------
// Chat sending with SSE streaming
// ---------------------------------------------------------------------------

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  await sendMessage();
});

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

async function sendMessage() {
  if (state.sending) return;
  const text = chatInput.value.trim();
  if (!text) return;

  if (!state.config.api_key_set) {
    appendErrorMessage("Link your Anthropic account in Settings first.");
    return;
  }

  state.sending = true;
  sendBtn.disabled = true;
  setStatus("thinking…", "");

  appendUserMessage(text);
  chatInput.value = "";

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });

    if (!resp.ok || !resp.body) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      appendErrorMessage(err.error || "Request failed");
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentBody = null;
    let currentAgent = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const ev = parseSseEvent(raw);
        if (!ev) continue;

        if (ev.event === "start") {
          const { kind, specialist, rounds } = ev.data;
          if (kind === "ask") {
            appendSystemMessage(`→ asking ${specialist}`);
          } else if (kind === "brief") {
            appendSystemMessage("→ briefing the whole team");
          } else if (kind === "discuss") {
            appendSystemMessage(`→ discussion · ${rounds} round${rounds > 1 ? "s" : ""}`);
          }
        } else if (ev.event === "token") {
          const { agent_key, agent_name, text } = ev.data;
          if (currentAgent !== agent_key) {
            currentAgent = agent_key;
            currentBody = startAgentBubble(agent_key, agent_name);
          }
          currentBody.textContent += text;
          chatLog.scrollTop = chatLog.scrollHeight;
        } else if (ev.event === "error") {
          appendErrorMessage(ev.data.message || "unknown error");
        } else if (ev.event === "done") {
          setStatus("done", "ok");
          setTimeout(() => setStatus(""), 1200);
        }
      }
    }
  } catch (e) {
    appendErrorMessage(e.message || String(e));
  } finally {
    state.sending = false;
    sendBtn.disabled = false;
  }
}

function parseSseEvent(block) {
  const lines = block.split("\n");
  let event = "message";
  let data = "";
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch {
    return { event, data: {} };
  }
}

// ---------------------------------------------------------------------------
// Chat file uploads (to the shared workspace)
// ---------------------------------------------------------------------------

attachBtn.addEventListener("click", () => attachInput.click());
attachInput.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  await uploadToChat(file);
  attachInput.value = "";
});

// Drag-and-drop anywhere in the chat panel.
const chatPanel = $(".panel[data-panel='chat']");
["dragenter", "dragover"].forEach((evt) => {
  chatPanel.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.remove("hidden");
  });
});
["dragleave", "drop"].forEach((evt) => {
  chatPanel.addEventListener(evt, (e) => {
    e.preventDefault();
    if (evt === "dragleave" && e.target !== dropZone) return;
    dropZone.classList.add("hidden");
  });
});
chatPanel.addEventListener("drop", async (e) => {
  e.preventDefault();
  dropZone.classList.add("hidden");
  const file = e.dataTransfer?.files?.[0];
  if (file) await uploadToChat(file);
});

async function uploadToChat(file) {
  setStatus(`uploading ${file.name}…`);
  const form = new FormData();
  form.append("file", file);
  try {
    const r = await fetch("/api/upload", { method: "POST", body: form });
    const data = await r.json();
    if (!r.ok) {
      appendErrorMessage(data.detail || "upload failed");
      setStatus("");
      return;
    }
    appendSystemMessage(`📎 ${data.name} · ${data.kind.toUpperCase()} · ${data.chars} chars — shared with the team`);
    setStatus("uploaded", "ok");
    setTimeout(() => setStatus(""), 1200);
  } catch (e) {
    appendErrorMessage(e.message || String(e));
    setStatus("");
  }
}

// ---------------------------------------------------------------------------
// Knowledge: per-agent RAG uploads
// ---------------------------------------------------------------------------

$("#kb-upload").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file || !state.selectedKb) return;
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`/api/rag/${state.selectedKb}`, {
    method: "POST",
    body: form,
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    alert(data.detail || "upload failed");
    return;
  }
  e.target.value = "";
  loadKbSources(state.selectedKb);
});

// ---------------------------------------------------------------------------
// Team: add agent form
// ---------------------------------------------------------------------------

$("#add-agent-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const name = form.name.value.trim();
  const role = form.role.value.trim();
  const system_prompt = form.system_prompt.value.trim();
  const status = $("#add-agent-status");
  status.textContent = "";
  status.className = "status";

  const r = await fetch("/api/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, role, system_prompt }),
  });
  const data = await r.json();
  if (!r.ok) {
    status.textContent = data.detail || "failed";
    status.className = "status err";
    return;
  }
  form.reset();
  status.textContent = `${data.agent.name} joined the team.`;
  status.className = "status ok";
  await refreshState();
});

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const api_key = form.api_key.value;
  const model = form.model.value;
  const status = $("#settings-status");
  status.textContent = "";
  status.className = "status";

  const body = {};
  if (api_key) body.api_key = api_key;
  if (model) body.model = model;

  const r = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    status.textContent = "save failed";
    status.className = "status err";
    return;
  }
  status.textContent = "saved";
  status.className = "status ok";
  await refreshState();
});

// ---------------------------------------------------------------------------
// Workspace reset
// ---------------------------------------------------------------------------

$("#reset-workspace").addEventListener("click", async () => {
  if (!confirm("Wipe the shared workspace (messages, documents, decisions)?")) return;
  await fetch("/api/workspace/reset", { method: "POST" });
  chatLog.innerHTML = "";
  appendSystemMessage("Workspace cleared.");
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

refreshState().then(() => {
  if (!state.config.api_key_set) {
    appendSystemMessage(
      "Welcome. Open Settings to link your Anthropic API key, then type a brief, ask a specialist (@Atlas), or /discuss a topic."
    );
  } else {
    appendSystemMessage(
      "Ready. Plain text → team brief. @Atlas <q> → ask one specialist. /discuss <topic> → round-robin."
    );
  }
});
