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
  $("q").oninput = () => loadAccounts();
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
