// demo-crm, the everyday CRM: accounts, visits, notes written by hand. No AI here.
// Notes an assistant proposed (TO-BE) still land here as drafts, and only the rep confirms them.
let current = null;

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
  $("manual-note").hidden = false;
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

(async () => {
  if (!(await session())) return;
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
  window.onfocus = () => { loadNotes(); loadReminders(); };   // picks up what agents did in the other apps
  await Promise.all([loadAccounts(), loadNotes(), loadReminders()]);
  $("app-view").hidden = false;
})();
