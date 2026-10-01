// Live screenshots of eth.blockid.au for the deck (light theme, 1440x900 @2x) -> img/live-*.png, used by build-bp.js browser().
// Run: sudo docker run --rm --network host --ipc host --user $(id -u):$(id -g) -e HOME=/tmp -v $PWD:/w \
//   -v $PWD/../../scripts/screenshots/node_modules:/w/node_modules -w /w mcr.microsoft.com/playwright:v1.63.0-noble node capture-live.mjs
import { chromium } from "playwright";
const APP = "https://eth.blockid.au";
const b = await chromium.launch();
async function ctxFor() { const c = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light", locale: "en-AU" }); return c; }
async function go(p, url) { await p.goto(url, { waitUntil: "networkidle", timeout: 60000 }).catch(() => {}); await p.evaluate(() => document.fonts && document.fonts.ready); await p.waitForTimeout(1500); }
async function shot(p, name, y = 0, h = 900) {
  await p.evaluate((y) => scrollTo(0, y), y); await p.waitForTimeout(700);
  await p.screenshot({ path: `img/live-${name}.png`, clip: { x: 0, y: 0, width: 1440, height: h } });
  console.log(name, p.url());
}
let c = await ctxFor(); let p = await c.newPage();
await go(p, APP + "/"); await shot(p, "home");
await go(p, APP + "/i"); await shot(p, "portfolio");
await go(p, APP + "/i/demo/EBA"); await shot(p, "position");
const y = await p.evaluate(() => { const e = [...document.querySelectorAll("h2,h3,div")].find((x) => /^Dividends paid to your wallet/.test(x.textContent || "")); return e ? e.getBoundingClientRect().top + scrollY - 260 : 300; });
await shot(p, "position-updates", y);
await go(p, APP + "/v/be5a8a832b474459/report"); await shot(p, "report");
const y2 = await p.evaluate(() => { const e = [...document.querySelectorAll("h2,h3,h4,div,p")].find((x) => (x.textContent || "").trim().startsWith("Business score profile")); return e ? e.getBoundingClientRect().top + scrollY - 120 : 600; });
await shot(p, "report-score", y2);
await go(p, APP + "/c/ARW/cap-table"); await shot(p, "captable");
await go(p, APP + "/verify/EBA"); await p.getByText(/hash matches/i).first().waitFor({ timeout: 30000 }).catch(() => {}); await p.waitForTimeout(1000); await shot(p, "verify-ok");
await p.getByRole("button", { name: /Tamper test/i }).click().catch(() => {}); await p.waitForTimeout(2000); await shot(p, "verify-bad");
await go(p, APP + "/hsk"); await shot(p, "hsk");
await go(p, APP + "/i/offerings"); await shot(p, "offerings");
await go(p, APP + "/c/EBA/activity"); await shot(p, "activity");
await go(p, "https://scan.blockid.au/token/0x95A5a4b82897087B2c044b653B8e6bd617a58718?tab=holders"); await p.waitForTimeout(3000); await shot(p, "scan-holders");
await c.close();
// admin console (public demo admin account)
c = await ctxFor(); p = await c.newPage();
const r = await c.request.post(APP + "/api/v1/auth/login", { data: { username: "admin", password: "admin" } }); console.log("admin login", r.status());
await go(p, APP + "/admin"); await shot(p, "admin");
await c.close();
await b.close();
