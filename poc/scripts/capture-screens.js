// Screenshots of the demo, one per step of DEMO.md, for the evidence folder.
// Three apps: demo-crm (:3000, no AI), the AI assistant (:3001) and the audit console (:3002).
// Needs Node and Playwright: npm i -D playwright && npx playwright install chromium
// Usage (fresh stack, /etc/hosts has sso.demo.local): node scripts/capture-screens.js evidence/<run>/screens
const { chromium } = require("playwright");
const fs = require("fs");
const out = process.argv[2] || "evidence/screens";
fs.mkdirSync(out, { recursive: true });
const CRM = "http://localhost:3000/", ASSISTANT = "http://localhost:3001/", AUDIT = "http://localhost:3002/";

(async () => {
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });   // localhost only
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const crm = await context.newPage(), assistant = await context.newPage(), audit = await context.newPage();
  const shot = (page, name) => page.screenshot({ path: `${out}/${name}.png` });

  const signIn = async (page, url, consent) => {
    await page.goto(url);
    await page.click("#login");
    await page.waitForURL((u) => !u.href.startsWith(url) || u.searchParams.has("code") || false, { timeout: 15000 }).catch(() => {});
    await page.locator("#username, input[name=accept], button[name=accept], #app-view:not([hidden])").first().waitFor({ timeout: 30000 });
    if (await page.locator("#username").count()) {               // first app: the Keycloak login form
      await page.fill("#username", "luca");
      await page.fill("#password", "luca");
      await page.click("#kc-login");
    }
    const accept = page.locator("input[name=accept], button[name=accept]");
    const app = page.locator("#app-view:not([hidden])");
    await accept.or(app).first().waitFor({ timeout: 30000 });      // the consent screen shows only the first time
    if (await accept.count()) {
      if (consent) await consent(page);
      await accept.first().click();
    }
    await page.waitForSelector("#app-view:not([hidden])");
  };
  const runTask = async (task, expect) => {
    await assistant.bringToFront();
    await assistant.click(`[data-task=${task}]`);
    await assistant.waitForFunction((t) => document.querySelector("#transcript").textContent.includes(t), expect, { timeout: 60000 })
      .catch(async (e) => { console.error(await assistant.locator("#transcript").innerText()); throw e; });
    await assistant.waitForTimeout(500);
  };
  // Audit console: reload, open the newest row matching `match`, wait for its JWT cards
  const openAudit = async (match, cards = 2) => {
    await audit.bringToFront();
    await audit.click("#f-reload");
    await audit.waitForSelector("#audit-table tr.row");
    const rows = audit.locator("#audit-table tr.row");
    for (let i = 0; i < await rows.count(); i++) {
      if (match(await rows.nth(i).innerText())) { await rows.nth(i).click(); break; }
    }
    await audit.waitForFunction((n) => document.querySelectorAll(".jwts .jwt").length >= n, cards, { timeout: 10000 });
    await audit.waitForTimeout(300);
  };

  // AS-IS: the CRM, no AI
  await signIn(crm, CRM);
  await crm.locator("#accounts li").first().click();
  await crm.waitForSelector("#manual-note:not([hidden])");
  await shot(crm, "1-as-is-crm");
  await crm.fill("#note-text", "Met the doctor, follow up in two weeks.");
  await crm.click("#manual-note button[type=submit]");
  await crm.waitForFunction(() => document.querySelector("#notes").textContent.includes("follow up in two weeks"));
  await shot(crm, "2-as-is-manual-note");
  await signIn(audit, AUDIT);
  await openAudit((t) => t.includes("by hand") && t.includes("POST /notes"));
  await shot(audit, "3-as-is-audit-luca-by-hand");

  // TO-BE, delegated: the assistant app asks for consent the first time
  await signIn(assistant, ASSISTANT, (p) => shot(p, "4-to-be-consent"));
  await runTask("summary", "draft_visit_note");
  await shot(assistant, "5-to-be-assistant-draft-note");
  await crm.bringToFront();
  await crm.reload();
  await crm.waitForFunction(() => document.querySelector("#notes").textContent.includes("proposed by"));
  await shot(crm, "6-to-be-draft-waiting-in-crm");
  await openAudit((t) => t.includes("through") && t.includes("POST /notes") && t.includes("MCP server"), 3);
  await shot(audit, "7-to-be-audit-luca-through-agent-jwts");
  await runTask("team_report", "get_team_report");
  await shot(assistant, "8-to-be-team-report-refused");

  // TO-BE, autonomous
  await assistant.click("#run-dq");
  await assistant.waitForFunction(() => document.querySelectorAll("#dq li").length > 0, null, { timeout: 30000 });
  await shot(assistant, "9-to-be-agent-dq-run");
  await openAudit((t) => t.includes("autonomous") && t.includes("POST /reminders"), 3);
  await shot(audit, "10-to-be-audit-agent-dq-autonomous");

  // Controls
  await runTask("forbidden_tool", "create_reminder");
  await shot(assistant, "11a-control-tool-not-allowed");
  await runTask("final_note", "Violated guardrail");
  await shot(assistant, "11b-control-final-note-guardrail");
  await runTask("bypass_gateway", "POST /notes (direct)");
  await shot(assistant, "12-control-direct-call");
  await openAudit((t) => t.includes("crm-assistant, direct"), 2);
  await shot(audit, "13-control-audit-direct-call-no-gateway-jwt");

  await browser.close();
  console.log(`screens in ${out}`);
})().catch(async (e) => { console.error("FAILED", e.message); process.exit(1); });
