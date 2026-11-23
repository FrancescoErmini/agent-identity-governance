// Screenshots of the demo in the UI, one per act, for the evidence folder.
// Needs Node and Playwright: npm i -D playwright && npx playwright install chromium
// Usage (stack running, /etc/hosts has sso.demo.local): node scripts/capture-screens.js evidence/<run>/screens
const { chromium } = require("playwright");
const fs = require("fs");
const out = process.argv[2] || "evidence/screens";
fs.mkdirSync(out, { recursive: true });

(async () => {
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });   // localhost only
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const shot = (name) => page.screenshot({ path: `${out}/${name}.png` });
  const runTask = async (task, expect) => {
    await page.click(`[data-task=${task}]`);
    await page.waitForFunction((t) => document.querySelector("#transcript").textContent.includes(t), expect, { timeout: 60000 });
    await page.waitForTimeout(500);
  };

  // Audit tab: open the newest row matching `match`, wait for its JWT cards
  const openAudit = async (match, cards = 2) => {
    await page.click("[data-view=audit-view]");
    await page.waitForSelector("#audit-table tr.row");
    const rows = page.locator("#audit-table tr.row");
    for (let i = 0; i < await rows.count(); i++) {
      if (match(await rows.nth(i).innerText())) { await rows.nth(i).click(); break; }
    }
    await page.waitForFunction((n) => document.querySelectorAll(".jwts .jwt").length >= n, cards, { timeout: 10000 });
    await page.waitForTimeout(300);
  };

  await page.goto("http://localhost:3000/");
  await page.click("#login");
  await page.fill("#username", "luca");
  await page.fill("#password", "luca");
  await page.click("#kc-login");
  await page.waitForLoadState("networkidle");
  await shot("0-consent");
  await page.click("input[name=accept], button[name=accept]");
  await page.waitForSelector("#accounts li");
  await page.locator("#accounts li").first().click();
  await page.waitForSelector("#acc-actions:not([hidden])");
  await shot("1-login-territory");

  // AS-IS: Luca writes the note by hand, then the audit names him
  await page.fill("#note-text", "Met the doctor, follow up in two weeks.");
  await page.click("#manual-note button[type=submit]");
  await page.waitForFunction(() => document.querySelector("#notes").textContent.includes("follow up in two weeks"));
  await shot("2-as-is-manual-note");
  await openAudit((t) => t.includes("by hand") && t.includes("POST /notes"));
  await shot("3-as-is-audit-luca-by-hand");
  await page.click("[data-view=app-view]");

  // TO-BE, delegated
  await runTask("summary", "draft_visit_note");
  await shot("4-to-be-assistant-draft-note");
  await openAudit((t) => t.includes("through") && t.includes("POST /notes") && t.includes("MCP server"), 3);
  await shot("5-to-be-audit-luca-through-agent-jwts");
  await page.click("[data-view=app-view]");
  await runTask("team_report", "get_team_report");
  await shot("6-to-be-team-report-refused");

  // TO-BE, autonomous
  await page.click("#run-dq");
  await page.waitForFunction(() => document.querySelectorAll("#reminders li .badge").length > 0, null, { timeout: 30000 });
  await shot("7-to-be-agent-dq-reminders");
  await openAudit((t) => t.includes("autonomous") && t.includes("POST /reminders"), 3);
  await shot("8-to-be-audit-agent-dq-autonomous");
  await page.click("[data-view=app-view]");

  // Controls
  await runTask("forbidden_tool", "create_reminder");
  await shot("9a-control-tool-not-allowed");
  await runTask("final_note", "Violated guardrail");
  await shot("9b-control-final-note-guardrail");
  await runTask("bypass_gateway", "POST /notes (direct)");
  await page.waitForTimeout(800);
  await shot("10-control-direct-call-stored-as-draft");
  await openAudit((t) => t.includes("crm-assistant, direct"), 2);
  await shot("11-control-audit-direct-call-no-gateway-jwt");
  await browser.close();
  console.log(`screens in ${out}`);
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
