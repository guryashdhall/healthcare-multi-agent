/* Co-Pilot frontend. Vanilla JS, no build step. */

const state = {
  cases: [],
  specialists: [],     // [{ name, display, icon }]
  orchestrator: null,
  azureConfigured: false,
  activeCase: null,
  agentStreams: {},    // { name: accumulated_text }
  agentFinal: {},      // { name: output dict }
  orchestratorLLM: null,        // raw orchestrator output (with placeholders)
  orchestratorRehydrated: null, // rehydrated orchestrator output
  planView: "clinician",        // "clinician" | "llm"
  ws: null,
  runInProgress: false,         // true between Run click and "done"/blocked event
  pingTimer: null,              // setInterval handle for keep-alive heartbeat
  lastRunRequest: null,         // last payload sent, used for one-click retry on disconnect
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function escapeHTML(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function logEvent(evt) {
  const out = $("#event-log");
  out.textContent += JSON.stringify(evt) + "\n";
  out.scrollTop = out.scrollHeight;
}

// ─────────────── Init ───────────────
async function init() {
  try {
    const r = await fetch("/api/health");
    const h = await r.json();
    state.azureConfigured = !!h.azure_openai_configured;
    $("#conn-dot").classList.add("online");
    $("#engine-hint").textContent = state.azureConfigured
      ? "Azure OpenAI configured. Six agents will stream into the Co-Pilot Workspace."
      : "Azure OpenAI not configured. Use Offline Simulator.";
  } catch (e) {
    $("#engine-hint").textContent = "Could not reach server.";
  }

  await loadCases();
}

async function loadCases() {
  const res = await fetch("/api/cases");
  const data = await res.json();
  state.cases = data.cases || [];
  state.specialists = data.specialists || [];
  state.orchestrator = data.orchestrator || { name: "orchestrator", display: "Orchestrator", icon: "ORC" };

  // Build the agent grid skeleton.
  const grid = $("#agent-grid");
  grid.innerHTML = "";
  for (const s of state.specialists) {
    const panel = document.createElement("div");
    panel.className = "agent-panel";
    panel.dataset.agent = s.name;
    panel.innerHTML = `
      <div class="agent-head">
        <div class="agent-icon">${escapeHTML(s.icon)}</div>
        <div class="agent-name">${escapeHTML(s.display)}</div>
        <div class="agent-light"></div>
      </div>
      <pre class="agent-stream" id="stream-${s.name}"></pre>
      <div class="agent-flag" id="flag-${s.name}"></div>
      <div class="agent-source" id="source-${s.name}"></div>
    `;
    grid.appendChild(panel);
  }

  // Build the case list.
  const list = $("#case-list");
  list.innerHTML = "";
  for (const c of state.cases) {
    const row = document.createElement("div");
    row.className = "case-row";
    row.dataset.id = c.case_id;
    row.innerHTML = `
      <div class="cr-label">${escapeHTML(c.label)}</div>
      <div class="cr-sub">${escapeHTML(c.subtitle || "")}</div>
      <span class="cr-tag ${escapeHTML(c.tag_color)}">${escapeHTML(c.tag)}</span>
    `;
    row.addEventListener("click", () => selectCase(c));
    list.appendChild(row);
  }
}

function selectCase(c) {
  state.activeCase = c;
  $$(".case-row").forEach((r) => r.classList.toggle("active", r.dataset.id === c.case_id));
  $("#case-title").textContent = c.label;
  $("#case-sub").textContent = c.subtitle || "";
  const tag = $("#case-tag");
  tag.textContent = c.tag || "";
  tag.className = `case-tag ${c.tag_color || "neutral"}`;
  renderCaseBody(c.case);
  $("#run-btn").disabled = false;
  resetWorkspace();
  switchTab("case");
}

function renderCaseBody(doc) {
  if (!doc) {
    $("#case-body").innerHTML = '<div class="case-empty">No case data.</div>';
    return;
  }
  const html = [];
  const demo = doc.demographics || {};
  html.push('<div class="case-section">');
  html.push(`  <div class="case-section-title">Patient</div>`);
  html.push('  <div class="case-kv">');
  for (const [k, v] of Object.entries(demo)) {
    html.push(`    <div class="k">${escapeHTML(k.replace(/_/g, " "))}</div><div class="v">${escapeHTML(v)}</div>`);
  }
  html.push('  </div>');
  html.push('</div>');

  if (doc.presenting_complaint) {
    html.push(`<div class="case-section"><div class="case-section-title">Presenting complaint</div><div>${escapeHTML(doc.presenting_complaint)}</div></div>`);
  }
  if (doc.history) {
    html.push('<div class="case-section"><div class="case-section-title">History</div><div class="case-kv">');
    for (const [k, v] of Object.entries(doc.history)) {
      const valStr = Array.isArray(v) ? v.join("; ") : v;
      html.push(`<div class="k">${escapeHTML(k.replace(/_/g, " "))}</div><div class="v">${escapeHTML(valStr)}</div>`);
    }
    html.push('</div></div>');
  }
  if (doc.current_medications) {
    html.push('<div class="case-section"><div class="case-section-title">Current medications</div><ul class="case-med-list">');
    for (const m of doc.current_medications) {
      html.push(`<li><b>${escapeHTML(m.name)}</b> ${escapeHTML(m.dose || "")} ${escapeHTML(m.frequency || "")} — <i>${escapeHTML(m.indication || "")}</i></li>`);
    }
    html.push('</ul></div>');
  }
  if (doc.vitals) {
    html.push('<div class="case-section"><div class="case-section-title">Vitals</div><div class="case-kv">');
    for (const [k, v] of Object.entries(doc.vitals)) {
      html.push(`<div class="k">${escapeHTML(k.replace(/_/g, " "))}</div><div class="v">${escapeHTML(v)}</div>`);
    }
    html.push('</div></div>');
  }
  if (doc.examination) {
    html.push(`<div class="case-section"><div class="case-section-title">Examination</div><div>${escapeHTML(doc.examination)}</div></div>`);
  }
  if (doc.labs) {
    html.push('<div class="case-section"><div class="case-section-title">Labs</div><div class="case-kv">');
    for (const [k, v] of Object.entries(doc.labs)) {
      html.push(`<div class="k">${escapeHTML(k.replace(/_/g, " "))}</div><div class="v">${escapeHTML(v)}</div>`);
    }
    html.push('</div></div>');
  }
  if (doc.imaging_studies) {
    html.push('<div class="case-section"><div class="case-section-title">Imaging</div><div class="case-kv">');
    for (const [k, v] of Object.entries(doc.imaging_studies)) {
      html.push(`<div class="k">${escapeHTML(k.replace(/_/g, " "))}</div><div class="v">${escapeHTML(v)}</div>`);
    }
    html.push('</div></div>');
  }
  if (doc.clinicians_initial_plan) {
    html.push('<div class="case-section"><div class="case-section-title">Clinician\u2019s initial plan</div><ol class="case-plan-list">');
    for (const p of doc.clinicians_initial_plan) {
      html.push(`<li>${escapeHTML(p)}</li>`);
    }
    html.push('</ol></div>');
  }
  $("#case-body").innerHTML = html.join("\n");
}

function resetWorkspace() {
  state.agentStreams = {};
  state.agentFinal = {};
  state.orchestratorLLM = null;
  state.orchestratorRehydrated = null;
  state.planView = "clinician";
  $$(".toggle-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "clinician"));
  for (const s of state.specialists) {
    $(`#stream-${s.name}`).textContent = "";
    $(`#flag-${s.name}`).textContent = "";
    $(`#flag-${s.name}`).style.display = "none";
    $(`#source-${s.name}`).textContent = "";
    document.querySelector(`.agent-panel[data-agent="${s.name}"]`)?.classList.remove("running", "done", "error", "has-flag");
  }
  $("#orch-stream").textContent = "";
  $("#orch-light").classList.remove("running", "done", "error");
  $("#plan-summary").textContent = "Run the co-pilot to populate.";
  $("#cross-flags").innerHTML = "—";
  $("#cross-flags-rail").innerHTML = "—";
  $("#ranked-actions").innerHTML = "";
  $("#patient-facing").textContent = "";
  $("#event-log").textContent = "";
}

// ─────────────── Tabs ───────────────
function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
}
$$(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

// ─────────────── Plan view toggle ───────────────
$$(".toggle-btn").forEach((b) => {
  b.addEventListener("click", () => {
    state.planView = b.dataset.view;
    $$(".toggle-btn").forEach((x) => x.classList.toggle("active", x === b));
    renderPlan();
  });
});

// ─────────────── Run ───────────────
$("#run-btn").addEventListener("click", () => {
  if (!state.activeCase) return;
  runCoPilot(state.activeCase);
});

function currentEngine() {
  const r = document.querySelector('input[name="engine"]:checked');
  return r ? r.value : "azure_openai";
}

function runCoPilot(c) {
  resetWorkspace();
  $("#copilot-engine-tag").textContent = `engine: ${currentEngine()}`;
  switchTab("copilot");

  setLastRun({ Status: "running", Engine: currentEngine() });
  hideConnectionBanner();
  state.runInProgress = true;

  if (state.ws) {
    try { state.ws.close(); } catch {}
  }
  stopHeartbeat();

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/run`);
  state.ws = ws;
  const payload = {
    mode: "copilot",
    case_id: c.case_id,
    case_json: c.case,
    engine: currentEngine(),
  };
  state.lastRunRequest = payload;

  ws.onopen = () => {
    ws.send(JSON.stringify(payload));
    startHeartbeat(ws);
  };
  ws.onmessage = (msg) => handleEvent(JSON.parse(msg.data));
  ws.onerror = () => logEvent({ type: "ws_error" });
  ws.onclose = (ev) => {
    logEvent({ type: "ws_closed", data: { code: ev.code, reason: ev.reason || null } });
    stopHeartbeat();
    // If the connection dropped mid-run (often because the browser tab was
    // backgrounded for too long and the OS killed the socket), surface a
    // clear retry banner instead of silently appearing frozen.
    if (state.runInProgress) {
      state.runInProgress = false;
      showConnectionBanner(c);
    }
  };
}

// ─────────────── Keep-alive heartbeat ───────────────
// Send a ping every 5s while a run is in progress. The server replies "pong"
// and treats inactivity as a dead client. Without this, Chrome aggressively
// throttles backgrounded tabs and the WS can be killed within ~30s.
function startHeartbeat(ws) {
  stopHeartbeat();
  state.pingTimer = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: "ping", ts: Date.now() })); } catch {}
    }
  }, 5000);
}

function stopHeartbeat() {
  if (state.pingTimer) {
    clearInterval(state.pingTimer);
    state.pingTimer = null;
  }
}

// ─────────────── Disconnect / retry banner ───────────────
// Surfaces a clear "connection dropped" message at the top of the page when
// the WebSocket closes mid-run. Styling lives in styles.css (.conn-banner)
// so this file just manages structure and the retry handler.
function showConnectionBanner(caseDoc) {
  let banner = $("#conn-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "conn-banner";
    banner.className = "conn-banner";
    document.body.appendChild(banner);
  }
  banner.innerHTML = `
    <span><b>Connection dropped.</b> Tab backgrounded too long, or network blip.
    The agents may still be running on the server, but events stopped streaming.</span>
    <button id="conn-retry" class="retry">Re-run now</button>
    <button id="conn-dismiss" class="dismiss">Dismiss</button>
  `;
  banner.classList.add("visible");
  $("#conn-retry").onclick = () => {
    hideConnectionBanner();
    runCoPilot(caseDoc);
  };
  $("#conn-dismiss").onclick = hideConnectionBanner;
}

function hideConnectionBanner() {
  const banner = $("#conn-banner");
  if (banner) banner.classList.remove("visible");
}

// ─────────────── Page-visibility logging ───────────────
// Helpful both for debugging on stage and as a hook for any future
// auto-recover logic. Background tabs in Chrome can have WS reads throttled
// after ~30s of being hidden.
document.addEventListener("visibilitychange", () => {
  logEvent({ type: "tab_visibility", data: { hidden: document.hidden } });
});

function setLastRun(kv) {
  const t = $("#last-run");
  t.innerHTML = "";
  for (const [k, v] of Object.entries(kv)) {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.innerHTML = `<span>${escapeHTML(k)}</span><span>${escapeHTML(String(v))}</span>`;
    t.appendChild(row);
  }
}

// ─────────────── Events ───────────────
function handleEvent(evt) {
  logEvent(evt);
  switch (evt.type) {
    case "stage_start":
    case "stage_end":
      // existing safety stages - we mostly just log them
      break;

    case "agent_start": {
      const name = evt.data.name;
      const el = document.querySelector(`.agent-panel[data-agent="${name}"]`);
      if (el) {
        el.classList.add("running");
      } else if (name === "orchestrator") {
        $("#orch-light").classList.add("running");
      }
      state.agentStreams[name] = "";
      break;
    }

    case "agent_token": {
      const { name, delta } = evt.data;
      state.agentStreams[name] = (state.agentStreams[name] || "") + delta;
      const target = name === "orchestrator" ? $("#orch-stream") : $(`#stream-${name}`);
      if (target) target.textContent = state.agentStreams[name];
      break;
    }

    case "agent_final": {
      const { name, output, source, error } = evt.data;
      state.agentFinal[name] = output;
      const panel = document.querySelector(`.agent-panel[data-agent="${name}"]`);
      if (panel) {
        panel.classList.remove("running");
        panel.classList.add(error ? "error" : "done");
      } else if (name === "orchestrator") {
        $("#orch-light").classList.remove("running");
        $("#orch-light").classList.add(error ? "error" : "done");
        state.orchestratorLLM = output;
        renderPlan();
      }
      const src = $(`#source-${name}`);
      if (src) src.textContent = error ? `source: ${source} \u00b7 ${error}` : `source: ${source}`;

      // Pretty-print final output into the panel so the audience can read it.
      const stream = name === "orchestrator" ? $("#orch-stream") : $(`#stream-${name}`);
      if (stream && output && Object.keys(output).length) {
        stream.textContent = JSON.stringify(output, null, 2);
      }

      // Per-agent flag chip for the demo.
      const flagEl = $(`#flag-${name}`);
      if (flagEl) {
        const flagText = computeAgentFlag(name, output);
        if (flagText) {
          flagEl.textContent = flagText;
          flagEl.style.display = "block";
          panel?.classList.add("has-flag");
        }
      }
      break;
    }

    case "rehydration":
      state.orchestratorRehydrated = evt.data.rehydrated_orchestrator;
      renderPlan();
      break;

    case "blocked":
      state.runInProgress = false;
      stopHeartbeat();
      $("#plan-summary").textContent = `BLOCKED: ${evt.data.reason}`;
      setLastRun({ Status: "BLOCKED", Reason: evt.data.reason });
      break;

    case "pong":
      // Keep-alive ack; nothing to render. Counts as activity for tab focus.
      break;

    case "done":
      state.runInProgress = false;
      stopHeartbeat();
      setLastRun({
        Status: evt.data.status,
        "Elapsed (ms)": evt.data.elapsed_ms,
        Agents: evt.data.agent_count ?? "—",
        "Cross-flags": evt.data.cross_flag_count ?? "—",
      });
      // Auto-jump to the Plan tab once the orchestrator delivers.
      if (evt.data.status === "completed") {
        setTimeout(() => switchTab("plan"), 400);
      }
      break;

    case "audit_written":
      // No-op in UI; available via Audit tab refresh.
      break;

    case "error":
      $("#plan-summary").textContent = `Error: ${evt.data?.message || "unknown"}`;
      break;
  }
}

// Compute a short "headline" flag from each agent's structured output.
function computeAgentFlag(name, out) {
  if (!out) return "";
  if (name === "pharmacy" && Array.isArray(out.interactions)) {
    const high = out.interactions.find((i) => i.severity === "high");
    if (high) return `High-severity interaction: ${(high.drugs || []).join(" + ")}`;
  }
  if (name === "triage" && out.urgency === "immediate") {
    return "Immediate triage";
  }
  if (name === "triage" && out.urgency === "urgent") {
    return "Urgent triage";
  }
  if (name === "bias_check" && Array.isArray(out.biases) && out.biases.length > 0) {
    return `${out.biases.length} cognitive bias flag${out.biases.length === 1 ? "" : "s"}`;
  }
  if (name === "differential" && Array.isArray(out.ranked_dx)) {
    const top = out.ranked_dx[0];
    if (top?.probability === "high") return `Top dx: ${top.dx}`;
  }
  return "";
}

// ─────────────── Plan renderer ───────────────
function renderPlan() {
  const out = state.planView === "clinician" ? state.orchestratorRehydrated : state.orchestratorLLM;
  if (!out) return;

  const summary = out.summary || "(no summary)";
  $("#plan-summary").innerHTML = decoratePlaceholders(summary);

  const cf = Array.isArray(out.cross_flags) ? out.cross_flags : [];
  const cfHtml = cf.length
    ? cf.map((f) => `
        <div class="cross-flag severity-${escapeHTML(f.severity || "high")}">
          <div class="cf-flag">${escapeHTML(f.flag)}</div>
          <div class="cf-agents">agents: ${(f.agents || []).map(escapeHTML).join(", ")}</div>
        </div>`).join("")
    : '<div style="font-size:12.5px; color:var(--ink-soft)">No cross-agent convergence detected.</div>';
  $("#cross-flags").innerHTML = cfHtml;
  $("#cross-flags-rail").innerHTML = cf.length
    ? cf.map((f) => `<div class="cross-flag severity-${escapeHTML(f.severity || "high")}"><div class="cf-flag">${escapeHTML(f.flag)}</div></div>`).join("")
    : '<div style="font-size:12px; color:var(--ink-soft)">No cross-flags yet.</div>';

  const actions = Array.isArray(out.ranked_actions) ? out.ranked_actions : [];
  $("#ranked-actions").innerHTML = actions.map((a) => `
    <li>
      <div class="ra-action">${decoratePlaceholders(a.action)}<span class="pill ${escapeHTML(a.priority || "med")}">${escapeHTML(a.priority || "med")}</span></div>
      <div class="ra-rationale">${decoratePlaceholders(a.rationale || "")}</div>
      <div class="ra-agents">supporting: ${(a.agents_supporting || []).map(escapeHTML).join(", ")}</div>
    </li>
  `).join("");

  const pf = out.patient_facing || "";
  $("#patient-facing").innerHTML = decoratePlaceholders(pf);
}

function decoratePlaceholders(s) {
  const html = escapeHTML(s || "");
  return html.replace(/\[([A-Z_]+_\d+)\]/g, '<span class="placeholder">[$1]</span>');
}

// ─────────────── Audit ───────────────
$("#audit-refresh").addEventListener("click", refreshAudit);
$("#audit-verify").addEventListener("click", refreshAudit);

async function refreshAudit() {
  // Cache-bust on every click so the browser never serves a stale audit view
  // after a fresh run. Belt-and-suspenders alongside the server's no-store
  // headers.
  const res = await fetch(`/api/audit?t=${Date.now()}`, { cache: "no-store" });
  const data = await res.json();
  $("#audit-body").textContent = data.events.length
    ? data.events.map((e) => JSON.stringify(e, null, 2)).join("\n\n")
    : "No audit events yet.";
  const a = $("#audit-assert");
  if (data.phi_check.passed) {
    a.textContent = `\u2713 0 raw PHI strings across ${data.events.length} events (scanned ${data.phi_check.scanned_strings} known strings).`;
    a.className = "audit-assert pass";
  } else {
    a.textContent = `\u2717 FAIL \u2014 leaked: ${data.phi_check.leaked.join(", ")}`;
    a.className = "audit-assert fail";
  }
}

// ─────────────── Paste modal ───────────────
$("#open-paste").addEventListener("click", () => {
  $("#paste-text").value = "";
  $("#paste-modal").hidden = false;
});
$("#paste-cancel").addEventListener("click", () => {
  $("#paste-modal").hidden = true;
});
$("#paste-load").addEventListener("click", () => {
  const raw = $("#paste-text").value.trim();
  if (!raw) return;
  let caseDoc;
  try {
    caseDoc = JSON.parse(raw);
  } catch {
    caseDoc = {
      demographics: { patient_name: "Audience Case", age: "?", sex: "?" },
      presenting_complaint: raw.slice(0, 4000),
      current_medications: [],
      clinicians_initial_plan: [],
    };
  }
  const c = {
    case_id: "audience_paste",
    label: "Audience-pasted case",
    subtitle: "Live demo input",
    tag: "Pasted just now",
    tag_color: "neutral",
    case: caseDoc,
  };
  state.cases.push(c);
  const row = document.createElement("div");
  row.className = "case-row";
  row.dataset.id = c.case_id;
  row.innerHTML = `
    <div class="cr-label">${escapeHTML(c.label)}</div>
    <div class="cr-sub">${escapeHTML(c.subtitle)}</div>
    <span class="cr-tag ${c.tag_color}">${escapeHTML(c.tag)}</span>
  `;
  row.addEventListener("click", () => selectCase(c));
  $("#case-list").appendChild(row);
  $("#paste-modal").hidden = true;
  selectCase(c);
});

init();
