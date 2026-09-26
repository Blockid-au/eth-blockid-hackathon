// Read-only screenshot tour of the live BlockID Studio app (eth.blockid.au) and explorer (scan.blockid.au).
//
// STRICTLY READ-ONLY: this script never clicks Approve / Reject / Grant / Revoke / Submit / Sign /
// Re-sync / Request / Send. The only interactions are: language toggle, <details> expand, stepper
// URL step navigation, the client-side "Show simulated growth" toggle, the client-side "Tamper test",
// admin tab switches, selecting a row in the admin companies table, and the explorer "Holders" tab.
// The admin password login (POST /v1/auth/login) is the only request that touches the server.
//
// Run via ./run.sh (Docker, no host Node needed). Output: docs/screenshots/*.png
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const APP = process.env.APP_URL || "https://eth.blockid.au";
const SCAN = process.env.SCAN_URL || "https://scan.blockid.au";
const OUT = path.resolve(process.env.OUT_DIR || "../../docs/screenshots");
const ADMIN_USER = process.env.ADMIN_USER || "admin";
const ADMIN_PASS = process.env.ADMIN_PASS || "admin";
const VAL_ID = process.env.VAL_ID || "275fa4d16186466d"; // Airwallex, approved
const EBA_TOKEN = "0x95A5a4b82897087B2c044b653B8e6bd617a58718";
const ONLY = process.env.ONLY ? new RegExp(process.env.ONLY) : null; // e.g. ONLY='^1[0-3]' to retake a subset

fs.mkdirSync(OUT, { recursive: true });
const problems = [];
const want = (name) => !ONLY || ONLY.test(name);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------- helpers ---------- */
async function go(page, url, settle = 1800) {
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 }).catch((e) => problems.push(`${url}: ${e.message}`));
  await settle_(page, settle);
}
async function settle_(page, ms = 1500) {
  await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
  await page.evaluate(() => document.fonts && document.fonts.ready).catch(() => {});
  await sleep(ms);
}
async function checkErrors(page, name) {
  const bad = await page.evaluate(() =>
    [...document.querySelectorAll(".banner.bad, .errbox, [role=alert]")]
      .map((e) => e.innerText.trim())
      .filter(Boolean)
  );
  if (bad.length) problems.push(`${name}: error text on page -> ${bad.join(" | ").slice(0, 200)}`);
}
/** Absolute document rect of the first element matching `loc`, optionally widened to `closest(sel)`. */
async function rect(loc, closest) {
  await loc.first().waitFor({ state: "attached", timeout: 15000 });
  return loc.first().evaluate((el, c) => {
    const t = c ? el.closest(c) || el : el;
    const r = t.getBoundingClientRect();
    return { top: r.top + scrollY, bottom: r.bottom + scrollY, left: r.left + scrollX, right: r.right + scrollX };
  }, closest);
}
async function save(page, name, opts) {
  if (!want(name)) return;
  await checkErrors(page, name);
  const file = path.join(OUT, name + ".png");
  await page.screenshot({ path: file, animations: "disabled", caret: "hide", ...opts });
  console.log("saved", name);
}
/** Viewport shot at a given scroll position. */
async function shotView(page, name, y = 0) {
  if (!want(name)) return;
  await page.evaluate((y) => window.scrollTo(0, y), y);
  await sleep(600);
  await save(page, name, { fullPage: false });
  await page.evaluate(() => window.scrollTo(0, 0));
}
/** Full-width band of the page from `top` rect to `bottom` rect (document coordinates). */
async function shotBand(page, name, top, bottom, { padTop = 28, padBottom = 28, maxH = 2600 } = {}) {
  if (!want(name)) return;
  const vw = page.viewportSize().width;
  const docH = await page.evaluate(() => document.documentElement.scrollHeight);
  const y = Math.max(0, Math.floor(top - padTop));
  const h = Math.min(maxH, Math.ceil(Math.min(docH, bottom + padBottom) - y));
  // scroll through the band so lazy / intersection-observer content renders
  await page.evaluate(async ([y, h]) => { for (let s = y; s < y + h; s += 400) { scrollTo(0, s); await new Promise((r) => setTimeout(r, 60)); } scrollTo(0, 0); }, [y, h]);
  await sleep(500);
  await save(page, name, { fullPage: true, clip: { x: 0, y, width: vw, height: h } });
}
async function shotFull(page, name, maxH = 3200) {
  if (!want(name)) return;
  const docH = await page.evaluate(() => document.documentElement.scrollHeight);
  await shotBand(page, name, 0, Math.min(docH, maxH), { padTop: 0, padBottom: 0, maxH });
}

const browser = await chromium.launch();
const desktop = { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: "en-AU", colorScheme: "light", reducedMotion: "reduce" }; // reduced motion = hero demo shows its final state

/* ================= public pages ================= */
{
  const ctx = await browser.newContext(desktop);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`pageerror ${page.url()}: ${e.message}`));

  // Home
  await go(page, APP + "/");
  await page.evaluate(() => localStorage.setItem("lang", "en")).catch(() => {});
  await shotView(page, "01-home-hero");
  if (want("02-home-hero-vi")) {
    await page.locator(".langs button[lang=vi]").click();
    await sleep(900);
    await shotView(page, "02-home-hero-vi");
    await page.locator(".langs button[lang=en]").click();
    await sleep(900);
  }
  { const r = await rect(page.locator("#how")); await shotBand(page, "03-home-how-it-works", r.top, r.bottom, { padTop: 0, padBottom: 0 }); }
  { const r = await rect(page.locator("#walk")); await shotBand(page, "04-home-walkthrough", r.top, r.bottom, { padTop: 0, padBottom: 0 }); }
  { const r = await rect(page.locator("#live")); await shotBand(page, "05-home-live-stats", r.top, r.bottom, { padTop: 0, padBottom: 0 }); }
  { const r = await rect(page.locator("#hsk")); await shotBand(page, "06-home-hashkey-strip", r.top, r.bottom, { padTop: 0, padBottom: 0 }); }

  // New valuation wizard, step 1 with optional metrics expanded
  await go(page, APP + "/start");
  await page.locator("details.srbox > summary").click();
  await sleep(700);
  { const top = await rect(page.locator("section.shellpage").first()); const b = await rect(page.locator("details.srbox"), ".panel"); await shotBand(page, "07-new-wizard-step1", top.top, b.bottom, { padTop: 0, padBottom: 32 }); }

  // Sample report (public)
  await go(page, APP + "/v/sample/report", 2500);
  await shotFull(page, "13-sample-report", 2200);

  // Companies list
  await go(page, APP + "/companies", 2500);
  await shotFull(page, "14-companies-list", 1400);

  // Verify EBA: verified, formula, then client-side tamper test
  await go(page, APP + "/verify/EBA", 3500);
  { const a = await rect(page.locator("section.block, .wrap").first()); const b = await rect(page.locator("#vf-h"), "section"); await shotBand(page, "22-verify-eba-verified", a.top, b.bottom, { padTop: 0, padBottom: 8 }); }
  { const r = await rect(page.locator("#vf-f"), "section"); await shotBand(page, "23-verify-eba-formula", r.top, r.bottom, { padTop: 24, padBottom: 24 }); }
  if (want("24-verify-eba-tamper-mismatch")) {
    await page.locator("button", { hasText: "Tamper test" }).click();
    await sleep(2000);
    await page.evaluate(() => window.scrollTo(0, 0)); await sleep(800);
    const a = await rect(page.locator("section.block, .wrap").first()); const b = await rect(page.locator("#vf-r"), "section");
    // the red banner is expected here; do not flag it as a problem
    const vw = page.viewportSize().width;
    const y = Math.max(0, a.top); const h = Math.min(2600, b.top - 8 - y);
    await page.screenshot({ path: path.join(OUT, "24-verify-eba-tamper-mismatch.png"), animations: "disabled", fullPage: true, clip: { x: 0, y, width: vw, height: h } });
    console.log("saved 24-verify-eba-tamper-mismatch");
  }

  // HashKey page
  await go(page, APP + "/hsk", 3000);
  { const b = await rect(page.locator("#hsk-p"), "section"); await shotBand(page, "25-hsk-contracts-provenance", 0, b.bottom, { padTop: 0, padBottom: 12 }); }
  { const a = await rect(page.locator("#hsk-d"), "section"); const b = await rect(page.locator("#hsk-t"), "section"); await shotBand(page, "26-hsk-dividends-transactions", a.top, b.bottom, { padTop: 24, padBottom: 24 }); }

  // Admin login card (signed out), password tab selected — nothing submitted in this context
  await go(page, APP + "/admin", 2000);
  await page.locator(".login .segs [role=tab]").nth(1).click();
  await sleep(500);
  { const a = await rect(page.locator("section.block").first()); const b = await rect(page.locator(".login")); await shotBand(page, "27-admin-login", a.top, b.bottom, { padTop: 0, padBottom: 48 }); }

  await ctx.close();
}

/* ================= admin session ================= */
{
  const ctx = await browser.newContext(desktop);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`pageerror ${page.url()}: ${e.message}`));
  await go(page, APP + "/admin", 2000);
  await page.locator(".login .segs [role=tab]").nth(1).click();
  await page.locator(".login input[autocomplete=username]").fill(ADMIN_USER);
  await page.locator(".login input[type=password]").fill(ADMIN_PASS);
  await page.locator(".login form button[type=submit]").click(); // login only
  await page.locator(".rail").waitFor({ timeout: 20000 });
  await settle_(page, 3000);

  // Inbox: every queue in flow order, with the next step
  await go(page, APP + "/admin", 2500);
  { const docH = await page.evaluate(() => document.documentElement.scrollHeight); await shotBand(page, "29-admin-approvals", 0, Math.max(docH, 900), { padTop: 0, padBottom: 0, maxH: 1300 }); }
  // One queue item with previous / next (read-only; nothing is clicked)
  await go(page, APP + "/admin/sync", 2500);
  { const docH = await page.evaluate(() => document.documentElement.scrollHeight); await shotBand(page, "29b-admin-queue-item", 0, Math.max(docH, 900), { padTop: 0, padBottom: 0, maxH: 1300 }); }
  await go(page, APP + "/admin/dashboard", 3000);

  // Overview dashboard
  {
    // the platform-value chart keeps its adaptive default range ("Since launch" while the platform is young)
    const a = await rect(page.locator("section.shellpage").first());
    const t = await rect(page.locator("h4", { hasText: /Tokeni[sz]ed companies/ }).first(), ".card, .pane, .panel");
    await shotBand(page, "28-admin-overview", a.top, t.top, { padTop: 0, padBottom: -4 });
    const docH = await page.evaluate(() => document.documentElement.scrollHeight);
    await shotBand(page, "28b-admin-overview-companies-activity", t.top, docH, { padTop: 40, padBottom: 0, maxH: 1000 });
  }
  // Companies: EBA selected through the URL (selection only)
  await go(page, APP + "/admin/companies/EBA", 3000);
  { const docH = await page.evaluate(() => document.documentElement.scrollHeight); const a = await rect(page.locator("section.shellpage")); await shotBand(page, "30-admin-company-detail", a.top, docH, { padTop: 0, padBottom: 0, maxH: 1490 }); }
  await go(page, APP + "/admin/wallets", 2500);
  { const docH = await page.evaluate(() => document.documentElement.scrollHeight); const a = await rect(page.locator("section.shellpage")); await shotBand(page, "31-admin-issuer-wallets", a.top, docH, { padTop: 0, padBottom: 0, maxH: 1600 }); }
  await go(page, APP + "/admin/audit", 2500);
  { const a = await rect(page.locator("section.shellpage")); await shotBand(page, "32-admin-audit-log", a.top, a.top + 1300, { padTop: 0, padBottom: 0 }); }

  // Company ARW: issued on BlockID Chain + Hoodi + HSK, full anonymised cap table (15 holders).
  await go(page, APP + "/c/ARW/overview", 3000);
  { const a = await rect(page.locator("section.shellpage").first()); const b = await rect(page.locator(".kpis")); await shotBand(page, "15-company-arw-tracker-kpis", a.top, b.bottom, { padTop: 0, padBottom: 16 }); }
  await go(page, APP + "/c/ARW/cap-table", 3000);
  { const r = await rect(page.locator("h4", { hasText: "Cap table" }), ".cols, .panel, .pane"); await shotBand(page, "15b-company-arw-cap-table", r.top, r.bottom, { padTop: 16, padBottom: 16, maxH: 1400 }); }
  // Company ART: original holders + 10 anonymised holders minted through the admin-approved flow.
  await go(page, APP + "/c/ART/cap-table", 3000);
  { const r = await rect(page.locator("h4", { hasText: "Cap table" }), ".cols, .panel, .pane"); await shotBand(page, "15c-company-art-cap-table", r.top, r.bottom, { padTop: 16, padBottom: 16, maxH: 1400 }); }

  // Company EBA: fully live
  await go(page, APP + "/c/EBA/issue", 3000);
  { const docH = await page.evaluate(() => document.documentElement.scrollHeight); await shotBand(page, "16-company-eba-tracker-kpis", 0, docH, { padTop: 0, padBottom: 0, maxH: 1200 }); }
  await go(page, APP + "/c/EBA/sync", 3000);
  { const docH = await page.evaluate(() => document.documentElement.scrollHeight); await shotBand(page, "16b-company-eba-sync", 0, docH, { padTop: 0, padBottom: 0, maxH: 1200 }); }
  await go(page, APP + "/c/EBA/overview", 3000);
  if (want("17-company-eba-mark-chart-simulated")) {
    const sim = page.locator("svg.chart").first().locator("xpath=ancestor::*[.//input[@type='checkbox']][1]").locator("input[type=checkbox]").first();
    if (!(await sim.isChecked())) await sim.check();
    await sleep(2500);
    const r = await rect(page.locator("svg.chart").first(), ".panel, .pane, .card");
    await shotBand(page, "17-company-eba-mark-chart-simulated", r.top, r.bottom, { padTop: 16, padBottom: 16 });
  }
  await go(page, APP + "/c/EBA/cap-table", 3000);
  { const r = await rect(page.locator("h4", { hasText: "Cap table" }), ".cols, .panel, .pane"); await shotBand(page, "18-company-eba-cap-table", r.top, r.bottom, { padTop: 16, padBottom: 16 }); }
  await go(page, APP + "/c/EBA/wallet", 3000);
  { const a = await rect(page.locator(".shellmain > .panel")); const b = await rect(page.locator(".shellmain > .panel .cols3")); await shotBand(page, "19-company-eba-contracts-qr", 0, b.bottom, { padTop: 0, padBottom: 24 }); }
  { const a = await rect(page.locator("h4", { hasText: "Add it manually" })); const p = await rect(page.locator(".shellmain > .panel")); await shotBand(page, "20-company-eba-metamask-network", a.top, p.bottom, { padTop: 24, padBottom: 16 }); }
  await go(page, APP + "/c/EBA/mint", 3000);
  { const docH = await page.evaluate(() => document.documentElement.scrollHeight); await shotBand(page, "21-company-eba-cap-tools", 0, docH, { padTop: 0, padBottom: 0, maxH: 1300 }); }
  await go(page, APP + "/c/EBA/activity", 3000);
  { const r = await rect(page.locator(".shellmain > .pane")); await shotBand(page, "21b-company-eba-activity", r.top, r.bottom, { padTop: 16, padBottom: 16, maxH: 900 }); }

  // Finished valuation report (Airwallex). Stepper clicks only switch the client-side view.
  if (want("08-valuation-agent-log")) {
    await go(page, `${APP}/v/${VAL_ID}/research`, 3000);
    const a = await rect(page.locator("section.shellpage").first()); const b = await rect(page.locator(".shellmain > .panel"));
    await shotBand(page, "08-valuation-agent-log", a.top, b.bottom, { padTop: 0, padBottom: 24 });
  }
  await go(page, `${APP}/v/${VAL_ID}/report`, 3000);
  {
    const a = await rect(page.locator(".shellmain > .panel"));
    const b = await rect(page.locator("h4", { hasText: "Valuation range" }), ".card");
    await shotBand(page, "09-valuation-radar-contribution", a.top, b.top, { padTop: 16, padBottom: 0 });
    const c = await rect(page.locator("h4", { hasText: "Analyst narrative" }), ".card");
    await shotBand(page, "10-valuation-range-competitors", b.top, c.top, { padTop: 16, padBottom: 0, maxH: 800 });
    const panel = await rect(page.locator(".shellmain > .panel"));
    await shotBand(page, "11-valuation-narrative-evidence", c.top, panel.bottom, { padTop: 16, padBottom: 16, maxH: 1150 });
  }
  // A valuation that carries agent warnings (first approved one with warnings)
  if (want("12-valuation-warnings")) {
    const list = await (await page.request.get(APP + "/api/v1/studio/valuations")).json().catch(() => []);
    const w = (Array.isArray(list) ? list : list.items || []).find((v) => (v.warnings || []).length > 0 && v.status === "approved");
    if (w) {
      await go(page, `${APP}/v/${w.id}/report`, 3000);
      const b = await rect(page.locator(".banner.warn").first());
      await shotBand(page, "12-valuation-warnings", 0, b.bottom + 520, { padTop: 0, padBottom: 0 });
    } else problems.push("no valuation with warnings found");
  }
  await ctx.close();
}

/* ================= explorer ================= */
{
  const ctx = await browser.newContext(desktop);
  const page = await ctx.newPage();
  await go(page, SCAN + "/", 5000);
  await shotFull(page, "33-scan-home", 1110);
  await go(page, `${SCAN}/token/${EBA_TOKEN}?tab=holders`, 5000);
  const holders = page.getByRole("tab", { name: "Holders" });
  if (await holders.count()) { await holders.first().click(); await settle_(page, 3000); }
  await shotFull(page, "34-scan-eba-token-holders", 1000);
  await ctx.close();
}

/* ================= mobile ================= */
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "en-AU", reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await go(page, APP + "/", 2000);
  await shotView(page, "35-mobile-home");
  await go(page, APP + "/c/EBA/overview", 3000);
  await shotBand(page, "36-mobile-company-eba", 0, 1700, { padTop: 0, padBottom: 0 });
  await go(page, APP + "/verify/EBA", 3500);
  await shotBand(page, "37-mobile-verify-eba", 0, 1500, { padTop: 0, padBottom: 0 });
  await ctx.close();
}

await browser.close();
console.log(problems.length ? "\nPROBLEMS:\n- " + problems.join("\n- ") : "\nno problems detected");
