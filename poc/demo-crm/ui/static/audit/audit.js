// The audit console: who did what in demo-crm, with the JWT that reached the API and the JWTs LiteLLM checked.
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
  const tbody = $("audit-table").querySelector("tbody");
  tbody.innerHTML = `<tr><td colspan="6" class="muted">Loading…</td></tr>`;
  const { ok, body } = await call(`/api/audit?${q}`);
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

(async () => {
  const c = await session();
  if (!c) return;
  $("app-view").hidden = false;
  if (!c.roles.includes("area-manager")) {
    $("audit-table").querySelector("tbody").innerHTML = `<tr><td colspan="6" class="refused">The audit trail is for area managers.</td></tr>`;
    return;
  }
  ["f-actor", "f-writes", "f-refused"].forEach((id) => $(id).onchange = loadAudit);
  $("f-reload").onclick = loadAudit;
  window.onfocus = loadAudit;
  await loadAudit();
})();
