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

  await page.goto("http://localhost:3000/");
  await page.click("#login");
  await page.fill("#username", "luca");
  await page.fill("#password", "luca");
  await page.click("#kc-login");
  await page.waitForLoadState("networkidle");
  await shot("act1-consent");
  await page.click("input[name=accept], button[name=accept]");
  await page.waitForSelector("#accounts li");
  await page.locator("#accounts li").first().click();
  await page.waitForSelector("#acc-actions:not([hidden])");
  await shot("act1-territory");

  await runTask("summary", "draft_visit_note");
  await shot("act2-draft-note");
  await runTask("team_report", "get_team_report");
  await shot("act3-team-report-refused");
  await page.click("#run-dq");
  await page.waitForFunction(() => document.querySelectorAll("#reminders li .badge").length > 0, null, { timeout: 30000 });
  await shot("act4-agent-dq-reminders");
  await runTask("forbidden_tool", "create_reminder");
  await shot("act5a-tool-not-allowed");
  await runTask("final_note", "Violated guardrail");
  await shot("act5b-final-note-guardrail");
  await runTask("bypass_gateway", "POST /notes (direct)");
  await page.waitForTimeout(800);
  await shot("act6-direct-call-stored-as-draft");
  await browser.close();
  console.log(`screens in ${out}`);
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
