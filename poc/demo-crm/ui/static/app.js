// demo-crm UI: OIDC Authorization Code + PKCE against Keycloak, no library.
// The login asks for delegation:client:agent-crm-assistant, so Keycloak shows the consent screen
// and puts may_act in the token: the assistant can then act for this person, and only for them.
const KC = "http://sso.demo.local:8080/realms/ai-demo/protocol/openid-connect";
const CLIENT_ID = "demo-crm";
const SCOPE = "openid delegation:client:agent-crm-assistant";
const REDIRECT = location.origin + "/";

let token = sessionStorage.getItem("token");
let current = null;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const claims = (t) => JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));

async function login() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const state = b64url(crypto.getRandomValues(new Uint8Array(16)));
  sessionStorage.setItem("pkce", JSON.stringify({ verifier, state }));
  location = `${KC}/auth?` + new URLSearchParams({
    client_id: CLIENT_ID, response_type: "code", redirect_uri: REDIRECT, scope: SCOPE,
    code_challenge: challenge, code_challenge_method: "S256", state,
  });
}

async function finishLogin() {
  const p = new URLSearchParams(location.search);
  if (!p.get("code")) return;
  const { verifier, state } = JSON.parse(sessionStorage.getItem("pkce") || "{}");
  history.replaceState(null, "", "/");
  if (p.get("state") !== state) return alert("Login state mismatch");
  const r = await fetch(`${KC}/token`, {
    method: "POST",
    body: new URLSearchParams({ grant_type: "authorization_code", client_id: CLIENT_ID, code: p.get("code"),
      redirect_uri: REDIRECT, code_verifier: verifier }),
  });
  const body = await r.json();
  if (!r.ok) return alert("Login failed: " + JSON.stringify(body));
  token = body.access_token;
  sessionStorage.setItem("token", token);
}

function logout() {
  sessionStorage.clear();
  location = `${KC}/logout?` + new URLSearchParams({ client_id: CLIENT_ID, post_logout_redirect_uri: REDIRECT });
}

async function call(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });
  if (r.status === 401) { sessionStorage.removeItem("token"); location.reload(); }
  return { ok: r.ok, status: r.status, body: await r.json().catch(() => null) };
}

function badge(row) {
  if (!row.via_agent) return `<span class="badge person">by ${esc(row.created_by)}</span>`;
  if (row.via_agent === "agent-dq") return `<span class="badge agent">agent-dq (autonomous)</span>`;
  return `<span class="badge agent">proposed by ${esc(row.via_agent)} for ${esc(row.created_by)}</span>`;
}

async function loadAccounts() {
  const { body } = await call(`/api/accounts?q=${encodeURIComponent($("q").value)}`);
  $("territory").textContent = body?.territory || "";
  $("accounts").innerHTML = (body?.accounts || []).map((a) =>
    `<li data-id="${esc(a.id)}"><b>${esc(a.name)}</b><span class="muted">${esc(a.specialty)} · ${esc(a.city)}</span></li>`).join("");
  $("accounts").querySelectorAll("li").forEach((li) => li.onclick = () => openAccount(li.dataset.id));
}

async function openAccount(id) {
  const { body } = await call(`/api/accounts/${id}`);
  current = body;
  $("acc-title").textContent = `${body.name} · ${body.id}`;
  $("acc-detail").innerHTML = `<p class="muted">${esc(body.specialty)} · ${esc(body.city)}</p>
    <table><tr><th>Date</th><th>Outcome</th><th>Next step</th></tr>${body.visits.map((v) =>
      `<tr><td>${esc(v.visit_date)}</td><td>${esc(v.outcome) || '<span class="warn">missing</span>'}</td><td>${esc(v.next_step) || '<span class="warn">missing</span>'}</td></tr>`).join("")}</table>`;
  $("acc-actions").hidden = false;
  $("manual-note").hidden = false;
  $("transcript").innerHTML = "";
}

async function ask(task) {
  $("transcript").innerHTML = `<p class="muted">The assistant is working: token exchange, then tools through LiteLLM…</p>`;
  const { ok, body } = await call("/assistant/assist", { method: "POST", body: JSON.stringify({ task, account_id: current?.id }) });
  if (!ok) { $("transcript").innerHTML = `<p class="refused">${esc(body?.detail || "error")}</p>`; return; }
  const steps = body.steps.map((s) => {
    const outcome = s.refused_by
      ? `<span class="refused">refused by ${esc(s.refused_by)}</span> <code>${esc(JSON.stringify(s.error))}</code>`
      : `<span class="okay">ok</span>`;
    return `<li><code>${esc(s.tool)}</code> ${outcome}</li>`;
  }).join("");
  $("transcript").innerHTML = `<div class="trace">
      <p class="small muted">Delegated token: sub = <b>${esc(body.acting_for)}</b>, act = <b>${esc(body.act?.client_id)}</b>,
      roles = ${esc(body.roles_in_delegated_token.join(", "))} · ${esc(body.mode)} mode · ${esc(body.correlation_id)}</p>
      <ul>${steps}</ul>${body.answer ? `<p>${esc(body.answer)}</p>` : ""}</div>`;
  loadNotes();
}

async function loadNotes() {
  const { body } = await call("/api/notes");
  $("notes").innerHTML = (body || []).map((n) => `<li>
      <div>${badge(n)} <span class="pill ${n.status}">${esc(n.status)}</span> <span class="muted small">${esc(n.account_id)}</span></div>
      <div>${esc(n.text)}</div>
      ${n.status === "draft" ? `<button class="small" data-confirm="${n.id}">Confirm</button>` : ""}</li>`).join("") || `<li class="muted">No notes yet.</li>`;
  $("notes").querySelectorAll("[data-confirm]").forEach((b) => b.onclick = async () => {
    await call(`/api/notes/${b.dataset.confirm}/confirm`, { method: "POST" }); loadNotes();
  });
}

async function loadReminders() {
  const { body } = await call("/api/reminders");
  $("reminders").innerHTML = (body || []).map((r) => `<li>${badge(r)}
      <div>${esc(r.text)}</div><span class="muted small">${esc(r.visit_id)} · ${esc(r.account_name)}</span></li>`).join("")
    || `<li class="muted">No reminders.</li>`;
}

// --- audit tab ----------------------------------------------------------------------------------
function who(r) {
  if (r.actor_type === "person") return `<span class="badge person">${esc(r.person)} (by hand)</span>`;
  if (r.actor_type === "person via agent")
    return `<span class="badge person">${esc(r.person)}</span> <span class="muted small">through</span> <span class="badge agent">${esc(r.agent)}</span>`;
  if (r.actor_type === "autonomous agent") return `<span class="badge auto">${esc(r.agent)} (autonomous)</span>`;
  return `<span class="muted">unknown</span>`;
}

const KEY_CLAIMS = ["iss", "aud", "sub", "preferred_username", "azp", "act", "may_act", "resource_access", "scope", "territory", "jti", "iat", "exp"];
const highlight = new Set(["sub", "azp", "act", "resource_access"]);
const fmt = (k, v) => (k === "iat" || k === "exp") && v ? `${v} (${new Date(v * 1000).toLocaleTimeString()})`
  : k === "resource_access" ? Object.entries(v).map(([c, r]) => `${c}: ${r.roles.join(", ")}`).join("; ")
  : typeof v === "object" ? JSON.stringify(v) : String(v);

function jwtCard(title, note, header, claims, extra = "") {
  if (!claims) return `<div class="jwt"><h3>${esc(title)}</h3><p class="muted small">${esc(note)}</p></div>`;
  const rows = KEY_CLAIMS.filter((k) => claims[k] !== undefined)
    .map((k) => `<dt>${k}</dt><dd class="${highlight.has(k) ? "key" : ""}">${esc(fmt(k, claims[k]))}</dd>`).join("");
  return `<div class="jwt"><h3>${esc(title)}</h3><p class="muted small">${esc(note)}</p>${extra}
    <dl><dt>header</dt><dd>${esc(header ? `alg ${header.alg} · kid ${String(header.kid).slice(0, 12)}…` : "-")}</dd>${rows}</dl>
    <details><summary class="small">All claims</summary><pre>${esc(JSON.stringify(claims, null, 2))}</pre></details></div>`;
}

async function auditDetail(r, cell) {
  const api = jwtCard("JWT at demo-crm API", r.token_verified ? "signature, issuer and audience verified by demo-crm"
      : `not verified: ${r.token_error || "-"}`, r.token_header, r.token_claims,
    r.detail ? `<p class="refused small">${esc(r.detail)}</p>` : "");
  let gw = "";
  if (!r.correlation_id) {
    gw = jwtCard("JWTs at LiteLLM", "This call did not go through the gateway (no correlation id).");
  } else {
    const { body } = await call(`/api/audit/gateway?correlation_id=${encodeURIComponent(r.correlation_id)}`);
    const seen = (body || []).find((g) => g.upstream_token) || (body || [])[0];
    gw = !seen ? jwtCard("JWTs at LiteLLM", "The gateway saw no Keycloak token with this correlation id: the agent called the API directly.")
      : jwtCard("At LiteLLM: the agent's own token (admission)", `token check ${seen.token_check} · ${seen.path}`,
          seen.admission_token?.header, seen.admission_token?.claims)
        + jwtCard("At LiteLLM: the token forwarded to the MCP server", "LiteLLM checked it belongs to the admitted agent",
          seen.upstream_token?.header, seen.upstream_token?.claims);
  }
  cell.innerHTML = `<p class="small muted">Correlation id: <code>${esc(r.correlation_id || "-")}</code> · ${esc(r.method)} ${esc(r.path)} · HTTP ${r.status}</p>
    <div class="jwts">${api}${gw}</div>`;
}

async function loadAudit() {
  const q = new URLSearchParams({ limit: "200" });
  if ($("f-actor").value) q.set("actor_type", $("f-actor").value);
  if ($("f-writes").checked) q.set("writes_only", "true");
  if ($("f-refused").checked) q.set("outcome", "refused");
  const { ok, body } = await call(`/api/audit?${q}`);
  const tbody = $("audit-table").querySelector("tbody");
  if (!ok) { tbody.innerHTML = `<tr><td colspan="6" class="refused">${esc(body?.detail || "error")}</td></tr>`; return; }
  tbody.innerHTML = body.map((r, i) => `<tr class="row" data-i="${i}">
      <td class="small">${esc(new Date(r.at).toLocaleTimeString())}</td><td>${who(r)}</td>
      <td><code>${esc(r.method)} ${esc(r.path)}</code></td><td class="small">${esc(r.object || "")}</td>
      <td class="${r.outcome === "allowed" ? "okay" : "refused"}">${esc(r.outcome)}</td><td class="small ${r.source?.endsWith(", direct") ? "direct" : "muted"}">${esc(r.source)}</td></tr>`).join("")
    || `<tr><td colspan="6" class="muted">Nothing yet.</td></tr>`;
  tbody.querySelectorAll("tr.row").forEach((tr) => tr.onclick = () => {
    const next = tr.nextElementSibling;
    if (next?.classList.contains("detail")) return next.remove();
    const d = document.createElement("tr");
    d.className = "detail";
    d.innerHTML = `<td colspan="6" class="muted small">Loading…</td>`;
    tr.after(d);
    auditDetail(body[tr.dataset.i], d.firstElementChild);
  });
}

function show(view) {
  for (const v of ["app-view", "audit-view"]) $(v).hidden = v !== view;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  if (view === "audit-view") loadAudit();
}

async function main() {
  await finishLogin();
  if (!token || claims(token).exp * 1000 < Date.now()) {
    sessionStorage.removeItem("token");
    $("login-view").hidden = false;
    $("login").onclick = login;
    return;
  }
  const c = claims(token);
  const roles = c.resource_access?.["demo-crm"]?.roles || [];
  $("who").innerHTML = `<b>${esc(c.preferred_username)}</b> <span class="muted">${esc(roles.join(", "))}</span>
    ${c.may_act ? `<span class="badge agent" title="may_act in your token">assistant allowed</span>` : ""}
    <button id="logout" class="small ghost">Sign out</button>`;
  $("logout").onclick = logout;
  $("app-view").hidden = false;
  if (roles.includes("area-manager")) {
    $("tabs").hidden = false;
    document.querySelectorAll(".tab").forEach((t) => t.onclick = () => show(t.dataset.view));
    ["f-actor", "f-writes", "f-refused"].forEach((id) => $(id).onchange = loadAudit);
    $("f-reload").onclick = loadAudit;
  }
  $("q").oninput = () => loadAccounts();
  $("manual-note").onsubmit = async (e) => {   // AS-IS: the rep writes the note by hand, final at once
    e.preventDefault();
    const text = $("note-text").value.trim();
    if (!text || !current) return;
    const { ok, body } = await call("/api/notes", { method: "POST",
      body: JSON.stringify({ account_id: current.id, text, status: "final" }) });
    if (!ok) return alert(body?.detail || "error");
    $("note-text").value = "";
    loadNotes();
  };
  document.querySelectorAll("[data-task]").forEach((b) => b.onclick = () => ask(b.dataset.task));
  $("run-dq").onclick = async () => {
    $("run-dq").disabled = true;
    await fetch("/scheduler/run?limit=5", { method: "POST" });
    $("run-dq").disabled = false;
    loadReminders();
  };
  loadAccounts(); loadNotes(); loadReminders();
}

main();
