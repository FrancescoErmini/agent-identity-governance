// The AI assistant app: a separate app next to demo-crm. The person's token goes to crm-assistant,
// which exchanges it for a delegated one (sub = person, act = agent) and calls tools through LiteLLM.
async function ask(task, message) {
  $("transcript").innerHTML = `<p class="muted">The assistant is working: token exchange, then tools through LiteLLM…</p>`;
  const { ok, body } = await call("/assistant/assist", { method: "POST",
    body: JSON.stringify({ task, account_id: $("account").value || null, message }) });
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
      <ul>${steps}</ul>${body.answer ? `<p>${esc(body.answer)}</p>` : ""}
      ${body.steps.some((s) => s.tool === "draft_visit_note" && s.result) ? `<p class="small">The draft is waiting in demo-crm for your confirmation.</p>` : ""}</div>`;
}

(async () => {
  if (!(await session())) return;
  document.querySelectorAll("[data-task]").forEach((b) => b.onclick = () => ask(b.dataset.task));
  const { body } = await call("/api/accounts?limit=50");
  $("territory").textContent = body?.territory || "";
  $("account").innerHTML = (body?.accounts || []).map((a) =>
    `<option value="${esc(a.id)}">${esc(a.name)} · ${esc(a.city)}</option>`).join("");
  const health = await fetch("/assistant/health").then((r) => r.json()).catch(() => ({}));
  if (health.mode === "model") {
    $("chat").hidden = false;
    $("chat").onsubmit = (e) => { e.preventDefault(); if ($("message").value.trim()) ask("chat", $("message").value.trim()); };
  }
  $("run-dq").onclick = async () => {
    $("run-dq").disabled = true;
    const r = await fetch("/scheduler/run?limit=5", { method: "POST" }).then((x) => x.json()).catch(() => ({}));
    $("run-dq").disabled = false;
    const made = (r.steps || []).filter((s) => s.tool === "create_reminder");
    $("dq").innerHTML = made.map((s) => `<li><span class="badge auto">agent-dq (autonomous)</span>
      <div class="small">${s.result ? esc(s.result.text) : `<span class="refused">${esc(JSON.stringify(s.error))}</span>`}</div></li>`).join("")
      || `<li class="muted">Nothing to remind: every visit is complete.</li>`;
  };
  $("app-view").hidden = false;                 // shown once everything is wired
})();
