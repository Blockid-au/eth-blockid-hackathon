// First-visit check: the demo account opens with no login -> portfolio -> account -> list a business.
import { chromium } from "playwright";
const APP = process.env.APP_URL || "https://eth.blockid.au";
const OUT = process.env.OUT_DIR || "/tmp/try-demo";
const b = await chromium.launch();
const problems = [];
async function run(label, viewport, scheme) {
  const ctx = await b.newContext({ viewport, colorScheme: scheme });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => problems.push(`${label} pageerror ${e.message}`));
  p.on("console", (m) => { if (m.type() === "error" && !/favicon|cloudflareinsights|gsi/.test(m.text())) problems.push(`${label} console ${m.text()}`); });
  const shot = async (n) => {
    const wide = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    if (wide) problems.push(`${label} ${n} HORIZONTAL-SCROLL`);
    const txt = await p.evaluate(() => document.body.innerText);
    if (/\bNaN\b|undefined|\[object Object\]/.test(txt)) problems.push(`${label} ${n} bad text`);
    await p.screenshot({ path: `${OUT}/${label}-${n}.png`, fullPage: true });
  };
  await p.goto(APP + "/", { waitUntil: "networkidle" });
  await shot("home");
  const t0 = Date.now();
  await p.goto(APP + "/i", { waitUntil: "networkidle" });
  console.log(label, "demo account open in", Date.now() - t0, "ms");
  await shot("portfolio");
  const me = await p.evaluate(() => fetch("/api/v1/auth/me").then((r) => r.json()));
  console.log(label, "me", JSON.stringify(me));
  await p.goto(APP + "/i/demo/ARW", { waitUntil: "networkidle" });
  await shot("demo-position");
  await p.goto(APP + "/i/account", { waitUntil: "networkidle" });
  console.log(label, "demo account:", me.auth_method === "demo");
  await shot("account");
  await p.goto(APP + "/start", { waitUntil: "networkidle" });
  await shot("start");
  // reload keeps the same session / wallet
  await p.reload({ waitUntil: "networkidle" });
  const me2 = await p.evaluate(() => fetch("/api/v1/auth/me").then((r) => r.json()));
  console.log(label, "same wallet after reload:", me2.address === me.address);
  await ctx.close();
}
await run("d", { width: 1360, height: 900 }, "light");
await run("m", { width: 390, height: 844 }, "dark");
await b.close();
console.log(problems.length ? problems.join("\n") : "no problems");
