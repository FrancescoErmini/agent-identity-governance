// Shared by the three apps: OIDC Authorization Code + PKCE against Keycloak, no library.
// Each app sets window.APP = { client, scope } before loading this file.
//   CRM and audit console: client crm-web, plain login (no AI, no consent screen).
//   AI assistant: client demo-crm, asks delegation:client:agent-crm-assistant, so Keycloak shows the
//   consent screen once and puts may_act in the token: the assistant may then act for this person only.
const KC = "http://sso.demo.local:8080/realms/ai-demo/protocol/openid-connect";
const REDIRECT = location.origin + "/";

let token = sessionStorage.getItem("token");

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
    client_id: APP.client, response_type: "code", redirect_uri: REDIRECT, scope: APP.scope,
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
    body: new URLSearchParams({ grant_type: "authorization_code", client_id: APP.client, code: p.get("code"),
      redirect_uri: REDIRECT, code_verifier: verifier }),
  });
  const body = await r.json();
  if (!r.ok) return alert("Login failed: " + JSON.stringify(body));
  token = body.access_token;
  sessionStorage.setItem("token", token);
}

function logout() {
  sessionStorage.clear();
  location = `${KC}/logout?` + new URLSearchParams({ client_id: APP.client, post_logout_redirect_uri: REDIRECT });
}

async function call(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });
  if (r.status === 401) { sessionStorage.removeItem("token"); location.reload(); }
  return { ok: r.ok, status: r.status, body: await r.json().catch(() => null) };
}

// Signs in if needed; returns the token's claims, or null while the login page is shown.
async function session() {
  await finishLogin();
  if (!token || claims(token).exp * 1000 < Date.now()) {
    sessionStorage.removeItem("token");
    $("login-view").hidden = false;
    $("login").onclick = login;
    return null;
  }
  const c = claims(token);
  const roles = c.resource_access?.["demo-crm"]?.roles || [];
  $("who").innerHTML = `<b>${esc(c.preferred_username)}</b> <span class="muted">${esc(roles.join(", "))}</span>
    ${c.may_act ? `<span class="badge agent" title="may_act in your token">assistant allowed</span>` : ""}
    <button id="logout" class="small ghost">Sign out</button>`;
  $("logout").onclick = logout;
  return { ...c, roles };
}

function badge(row) {
  if (!row.via_agent) return `<span class="badge person">by ${esc(row.created_by)}</span>`;
  if (row.via_agent === "agent-dq") return `<span class="badge auto">agent-dq (autonomous)</span>`;
  return `<span class="badge agent">proposed by ${esc(row.via_agent)} for ${esc(row.created_by)}</span>`;
}
