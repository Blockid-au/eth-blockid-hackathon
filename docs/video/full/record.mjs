// Screen-records the live app for the full demo video (docs/video/full).
// Each clip: open the page, start a CDP screencast (JPEG frames + timestamps), run scripted actions with a visible
// cursor, hold until the clip's target length, stop. build.py turns frames into constant-30fps clips.
// Usage (Docker, see README): node record.mjs [clipId ...]   — durations come from durations.json (written by build.py --durations)
import { chromium } from "playwright";
import fs from "node:fs";

const APP = process.env.APP_URL || "https://eth.blockid.au";
const HR = process.env.HR_URL || "https://hr.blockid.au";
const OUT = "clips";
const DUR = JSON.parse(fs.readFileSync("durations.json", "utf8"));
const only = process.argv.slice(2);

const CURSOR = `
(() => {
  if (window.__cur) return; window.__cur = 1;
  const add = () => {
    const c = document.createElement('div');
    c.id = '__cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-3px 0 0 -3px;z-index:2147483647;pointer-events:none;transition:transform .08s';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 14 L10.5 20.5 L13 19.4 L10.1 13 L16 13 Z" fill="#111" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      r.style.cssText = 'position:fixed;left:' + (e.clientX - 18) + 'px;top:' + (e.clientY - 18) + 'px;width:36px;height:36px;border-radius:50%;border:3px solid #0f9d6e;z-index:2147483646;pointer-events:none;opacity:.9;transition:transform .45s ease-out,opacity .45s ease-out';
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.body) add(); else addEventListener('DOMContentLoaded', add);
})();`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let mouse = { x: 720, y: 400 };

async function move(p, x, y, steps = 30) {
  await p.mouse.move(x, y, { steps });
  mouse = { x, y };
}
async function moveTo(p, loc, steps = 30) {
  const el = typeof loc === "string" ? p.locator(loc).first() : loc.first();
  await el.scrollIntoViewIfNeeded({ timeout: 4000 }).catch(() => {});
  const b = await el.boundingBox();
  if (!b) return false;
  await move(p, b.x + Math.min(b.width / 2, 120), b.y + b.height / 2, steps);
  return true;
}
async function click(p, loc) {
  if (await moveTo(p, loc)) { await sleep(250); await p.mouse.down(); await sleep(60); await p.mouse.up(); }
}
/** Smooth scroll by dy pixels over ms milliseconds. */
async function scroll(p, dy, ms) {
  await p.evaluate(async ([dy, ms]) => {
    const y0 = scrollY, t0 = performance.now();
    await new Promise((res) => {
      const f = (t) => {
        const k = Math.min(1, (t - t0) / ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        scrollTo(0, y0 + dy * e);
        k < 1 ? requestAnimationFrame(f) : res();
      };
      requestAnimationFrame(f);
    });
  }, [dy, ms]);
}
async function goto(p, url) {
  await p.goto(url, { waitUntil: "networkidle", timeout: 60000 }).catch(() => {});
  await p.evaluate(() => document.fonts && document.fonts.ready).catch(() => {});
  await sleep(800);
}
const tab = (p, name) => p.getByRole("link", { name, exact: false });

const CLIPS = {
  // investor portfolio
  async r01(p, end) {
    await goto(p, APP + "/");
    await this.start();
    await move(p, 330, 260, 20); await sleep(2200);
    await moveTo(p, p.getByText("You're in the demo account").or(p.getByText("demo account"))); await sleep(1400);
    await scroll(p, 620, 2200); await sleep(1500);
    await scroll(p, -620, 900);
    await click(p, p.locator("header").getByRole("link", { name: "My portfolio" }));
    await p.waitForLoadState("networkidle").catch(() => {}); await sleep(1500);
    const tiles = p.locator(".kpi, .stat, .tile").filter({ hasText: /A\$/ });
    for (let i = 0; i < Math.min(4, await tiles.count()); i++) { await moveTo(p, tiles.nth(i), 18); await sleep(700); }
    await scroll(p, 330, 1800);
    await moveTo(p, p.getByText("ETH BlockID Australia").first()); await sleep(800);
  },
  // one holding
  async r02(p) {
    await goto(p, APP + "/i/demo/EBA");
    await this.start();
    await move(p, 300, 230, 20); await sleep(1500);
    const tiles = p.locator("main").getByText(/A\$100k|2\.67%|533\.33/);
    for (let i = 0; i < Math.min(3, await tiles.count()); i++) { await moveTo(p, tiles.nth(i), 18); await sleep(900); }
    await scroll(p, 300, 1600); await sleep(1500);
    await moveTo(p, p.getByText(/Dividends paid/i).first()); await sleep(1200);
    await scroll(p, 420, 2000); await sleep(600);
    await moveTo(p, p.getByText(/August 2026 update/).first()); await sleep(600);
  },
  // business side: paste a website
  async r03(p) {
    await goto(p, APP + "/start");
    await this.start();
    await sleep(800);
    const input = p.locator("main input").first();
    await click(p, input); await sleep(300);
    await input.pressSequentially("canva.com", { delay: 110 });
    await sleep(1600);
    await moveTo(p, p.getByRole("button", { name: /Start evaluation/i })); await sleep(1600);
    const more = p.getByText(/Add your numbers/i).first();
    await click(p, more); await sleep(1200);
    await scroll(p, 380, 1800);
  },
  async r04(p) {
    await goto(p, APP + "/v/be5a8a832b474459/research");
    await this.start();
    await move(p, 640, 300, 20); await sleep(1500);
    const steps = p.locator("main li, main .step, main .row").filter({ hasText: /Read website|business profile|competitors|market|score/i });
    const n = await steps.count();
    for (let i = 0; i < Math.min(n, 6); i++) { await moveTo(p, steps.nth(i), 18); await sleep(1300); }
    await moveTo(p, p.getByText(/Findings that cite a page/).first()); await sleep(1500);
  },
  async r05(p) {
    await goto(p, APP + "/v/be5a8a832b474459/report");
    await this.start();
    await move(p, 360, 330, 20); await sleep(2200);
    await scroll(p, 560, 2400); await sleep(1800);
    await moveTo(p, p.getByText("How the score is built").first()); await sleep(1200);
    await scroll(p, 520, 2400); await sleep(1200);
    await moveTo(p, p.getByText(/Method:/).first()); await sleep(1500);
    await moveTo(p, p.getByText(/Competitors/).first()); await sleep(1200);
  },
  async r06(p) {
    await goto(p, APP + "/admin");
    await this.start();
    await sleep(700);
    await click(p, p.getByRole("tab", { name: /Username|account/i })); await sleep(500);
    const inputs = p.locator("form input");
    await click(p, inputs.nth(0)); await inputs.nth(0).pressSequentially("admin", { delay: 80 });
    await click(p, inputs.nth(1)); await inputs.nth(1).pressSequentially("admin", { delay: 80 });
    await sleep(300);
    await click(p, p.locator("form button[type=submit]"));
    await p.waitForLoadState("networkidle").catch(() => {}); await sleep(2200);
    await sleep(1500);
    for (const q of [/^\s*2\s*Issuance/i, /^\s*5\s*Dividends/i]) {
      const l = p.locator("aside a, nav a").filter({ hasText: q }).first();
      if (await l.count()) { await click(p, l); await p.waitForLoadState("networkidle").catch(() => {}); await sleep(2000); }
    }
  },
  async r07(p) {
    await goto(p, APP + "/c/ARW/cap-table");
    await this.start();
    await move(p, 700, 330, 20); await sleep(1500);
    const rows = p.locator("main table tbody tr");
    for (let i = 0; i < Math.min(5, await rows.count()); i++) { await moveTo(p, rows.nth(i), 14); await sleep(600); }
    await moveTo(p, p.locator("main svg").last()); await sleep(1500);
    await scroll(p, 420, 2400); await sleep(800);
  },
  async r08(p) {
    await goto(p, APP + "/i/offerings");
    await this.start();
    await move(p, 600, 300, 20); await sleep(1200);
    await moveTo(p, p.locator("main").getByText(/ETH BlockID Australia/).first()); await sleep(1000);
    await scroll(p, 350, 1800); await sleep(1200);
    await this.nav(APP + "/c/EBA/activity");
    await move(p, 700, 330, 20); await sleep(1000);
    const div = p.locator("main").getByText(/dividend/i);
    for (let i = 0; i < Math.min(3, await div.count()); i++) { await moveTo(p, div.nth(i), 16); await sleep(700); }
  },
  async r09(p) {
    await goto(p, APP + "/verify/EBA");
    await p.getByText(/hash matches/i).first().waitFor({ timeout: 30000 }).catch(() => {});
    await this.start();
    await move(p, 500, 360, 20);
    await moveTo(p, p.getByText(/hash matches/i).first()); await sleep(1400);
    await moveTo(p, p.getByText("Browser hash").first()); await sleep(800);
    await moveTo(p, p.getByText("Server hash").first()); await sleep(800);
    await moveTo(p, p.getByText("On-chain hash").first()); await sleep(900);
    await click(p, p.getByRole("button", { name: /Tamper test/i }));
    await sleep(900);
    await p.evaluate(() => scrollTo({ top: 0, behavior: "smooth" })); await sleep(1200);
    await moveTo(p, p.locator("main").getByText(/does not match|doesn't match|changed|mismatch/i).first()); await sleep(1500);
  },
  async r10(p) {
    await goto(p, APP + "/hsk");
    await this.start();
    await move(p, 500, 300, 20); await sleep(1500);
    await moveTo(p, p.getByText(/AI proposes/i).first()); await sleep(1500);
    await scroll(p, 420, 2000);
    await moveTo(p, p.getByText("Agent provenance").first()); await sleep(1300);
    await moveTo(p, p.getByText("Identity registry").first()); await sleep(600);
    await moveTo(p, p.getByText("Share token").first()); await sleep(600);
    await moveTo(p, p.getByText("Cap table anchor").first()); await sleep(600);
    await scroll(p, 380, 1600);
  },
  async r11(p) {
    await goto(p, HR + "/");
    await this.start();
    await move(p, 330, 260, 20); await sleep(2000);
    await this.nav(HR + "/p/t_ec96a8db33ef/overview");
    await move(p, 900, 330, 20); await sleep(1800);
    await moveTo(p, p.getByText(/Raised the score/i).first()); await sleep(1000);
    await click(p, p.getByRole("tab", { name: /^Fit/ }).or(p.locator("main a, main button").filter({ hasText: /^Fit/ })).first());
    await sleep(1500);
    await scroll(p, 330, 1800);
    const rows = p.locator("main table tbody tr, main tr");
    for (let i = 1; i < Math.min(6, await rows.count()); i++) { await moveTo(p, rows.nth(i), 14); await sleep(600); }
  },
};

const b = await chromium.launch({ args: ["--hide-scrollbars", "--font-render-hinting=none"] });
for (const [id, fn] of Object.entries(CLIPS)) {
  if (only.length && !only.includes(id)) continue;
  const target = DUR[id];
  const ctx = await b.newContext({ viewport: { width: 1440, height: 810 }, deviceScaleFactor: 4 / 3, colorScheme: "light", locale: "en-AU" });
  await ctx.addInitScript(CURSOR);
  const p = await ctx.newPage();
  const dir = `${OUT}/${id}`;
  fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });
  const cdp = await ctx.newCDPSession(p);
  const frames = [];
  let t0 = null;
  cdp.on("Page.screencastFrame", async (f) => {
    const ts = f.metadata.timestamp;
    if (t0 === null) t0 = ts;
    const name = String(frames.length).padStart(5, "0") + ".jpg";
    fs.writeFileSync(`${dir}/${name}`, Buffer.from(f.data, "base64"));
    frames.push([name, ts - t0]);
    cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  });
  let started = 0;
  const self = {
    async start() {
      await p.mouse.move(mouse.x, mouse.y);
      await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
      started = Date.now();
      // nudge a first frame
      await p.evaluate(() => { document.body.style.outline = "0px solid transparent"; });
    },
    async nav(url) { await p.goto(url, { waitUntil: "networkidle", timeout: 60000 }).catch(() => {}); await sleep(500); },
  };
  try { await fn.call(self, p); } catch (e) { console.log(id, "action error:", e.message.split("\n")[0]); }
  const left = target * 1000 - (Date.now() - started);
  if (left > 0) await sleep(left);
  await cdp.send("Page.stopScreencast").catch(() => {});
  await sleep(300);
  fs.writeFileSync(`${dir}/frames.json`, JSON.stringify({ target, actual: (Date.now() - started) / 1000, frames }));
  console.log(id, "target", target.toFixed(1), "actual", ((Date.now() - started) / 1000).toFixed(1), "frames", frames.length, left < 0 ? "OVER by " + (-left / 1000).toFixed(1) + "s" : "");
  await ctx.close();
}
await b.close();
