// Read-only smoke test of the flow shell: visits every step / workspace / admin screen, reports JS errors,
// the final URL (redirects) and saves a screenshot per screen. Never clicks an action button.
// Usage (Docker): see run.sh; OUT_DIR sets where PNGs go.
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const APP = process.env.APP_URL || "https://eth.blockid.au";
const OUT = path.resolve(process.env.OUT_DIR || "/tmp/flow-smoke");
const VAL_ID = process.env.VAL_ID || "275fa4d16186466d";
const TK = process.env.TK || "EBA";
fs.mkdirSync(OUT, { recursive: true });
const problems = [];

const browser = await chromium.launch();
async function tour(ctx, list, tag) {
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`${tag} ${page.url()}: pageerror ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|401|403|404/.test(m.text())) problems.push(`${tag} ${page.url()}: console ${m.text().slice(0, 160)}`); });
  for (const [name, url] of list) {
    await page.goto(APP + url, { waitUntil: "networkidle", timeout: 60000 }).catch((e) => problems.push(`${url}: ${e.message}`));
    await page.waitForTimeout(1200);
    const info = await page.evaluate(() => ({
      h1: document.querySelector("main h1, main h2")?.textContent?.trim().slice(0, 70),
      rail: document.querySelectorAll(".rail .ri").length,
      wide: document.documentElement.scrollWidth > window.innerWidth + 1,
    }));
    console.log(`${tag} ${name.padEnd(22)} ${url.padEnd(34)} -> ${new URL(page.url()).pathname.padEnd(32)} rail=${info.rail} h1="${info.h1}"${info.wide ? " HORIZONTAL-SCROLL" : ""}`);
    if (info.wide) problems.push(`${tag} ${url}: horizontal scroll`);
    await page.screenshot({ path: path.join(OUT, `${tag}-${name}.png`), fullPage: false });
    const bad = await page.evaluate(() => { const t = document.querySelector("main")?.innerText || ""; const m = t.match(/.{0,40}(NaN|undefined|\[object Object\]|Infinity|null%).{0,30}/g) || []; const banners = [...document.querySelectorAll(".banner.bad, .err, [role=alert]")].map((e) => e.innerText.trim()).filter(Boolean); return { m: m.slice(0, 3), banners: banners.slice(0, 3) }; });
    if (bad.m.length || bad.banners.length) problems.push(`${tag} ${url}: TEXT ${JSON.stringify(bad)}`.slice(0, 400));
  }
  return page;
}

const pub = [
  ["home", "/"], ["start", "/start"], ["new-redirect", "/new"], ["sample", "/v/sample"],
  ["val-auto", `/v/${VAL_ID}`], ["val-research", `/v/${VAL_ID}/research`], ["val-ticker", `/v/${VAL_ID}/ticker`],
  ["co-auto", `/c/${TK}`], ["co-issue", `/c/${TK}/issue`], ["co-sync", `/c/${TK}/sync`], ["co-wallet", `/c/${TK}/wallet`],
  ["co-updates", "/c/CNV/updates"], ["inv-demo", "/i/demo"], ["inv-demo-pos", "/i/demo/CNV"],
  ["co-cap", `/c/${TK}/cap-table`], ["co-activity", `/c/${TK}/activity`], ["co-mint-locked", `/c/${TK}/mint`], ["co-div-locked", `/c/${TK}/dividends`], ["companies", "/companies"],
];
const desk = await browser.newContext({ viewport: { width: 1360, height: 900 } });
await tour(desk, pub, "d");

// admin (password login only)
const adm = await browser.newContext({ viewport: { width: 1360, height: 900 } });
const p = await adm.newPage();
await p.goto(APP + "/admin", { waitUntil: "networkidle" });
await p.locator(".login .segs [role=tab]").nth(1).click();
await p.locator(".login input[autocomplete=username]").fill(process.env.ADMIN_USER || "admin");
await p.locator(".login input[type=password]").fill(process.env.ADMIN_PASS || "admin");
await p.locator(".login form button[type=submit]").click();
await p.waitForTimeout(2500);
await p.close();
await tour(adm, [
  ["ad-inbox", "/admin"], ["ad-dash", "/admin/dashboard"], ["ad-val", "/admin/valuations"], ["ad-iss", "/admin/issuance"],
  ["ad-sync", "/admin/sync"], ["ad-mints", "/admin/mints"], ["ad-divs", "/admin/dividends"], ["ad-policies", "/admin/policies"], ["ad-co-divs", "/c/CNV/dividends"], ["ad-updates", "/admin/updates"], ["ad-co-updates", "/c/CNV/updates"], ["ad-tr", "/admin/transfers"], ["ad-cos", `/admin/companies/${TK}`],
  ["ad-wallets", "/admin/wallets"], ["ad-audit", "/admin/audit"], ["ad-bogus", "/admin/nope"], ["ad-co-team", `/c/${TK}/team`],
  ["ad-ret", `/admin/valuations/xyz?return=%2Fv%2F${VAL_ID}%2Fticker`],
], "a");

const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
await tour(mob, [["m-inv-demo", "/i/demo"], ["m-inv-pos", "/i/demo/CNV"], ["m-start", "/start"], ["m-co", `/c/${TK}/overview`], ["m-val", `/v/${VAL_ID}/report`], ["m-home", "/"]], "m");

await browser.close();
console.log(problems.length ? "\nPROBLEMS:\n" + problems.join("\n") : "\nno problems");
