// hr.blockid.au UI audit: every page/tab at several widths; reports page-wide horizontal scroll and the elements causing it.
import { chromium } from "playwright";
import path from "node:path"; import fs from "node:fs";
const HR = process.env.HR_URL || "https://hr.blockid.au";
const P = process.env.HR_PERSON || "t_eb30a2edede5";
const OUT = process.env.OUT_DIR || "/tmp/hr-audit"; fs.mkdirSync(OUT, { recursive: true });
const pages = [["home", "/"], ["new", "/new"], ["newp", "/new/person"], ["me", "/me"], ["method", "/method"], ["404", "/zzz"]];
for (const t of ["", "/score", "/fit", "/cv", "/cvreview", "/verification", "/assessment", "/sources"]) pages.push([`p${t.replace("/", "-")}`, `/p/${P}${t}`]);
if (process.env.HR_TEAM) for (const t of ["", "/people", "/gaps", "/sources"]) pages.push([`r${t.replace("/", "-")}`, `/r/${process.env.HR_TEAM}${t}`]);
const widths = (process.env.WIDTHS || "360,390,768,1024,1360").split(",").map(Number);
const b = await chromium.launch();
for (const w of widths) {
  const ctx = await b.newContext({ viewport: { width: w, height: 860 }, isMobile: w < 800, deviceScaleFactor: 1 });
  const pg = await ctx.newPage();
  if (process.env.LOCAL_DIST) { // serve a local build on the real host (API stays live)
    await pg.route(/^https:\/\/hr\.blockid\.au\/(?!api\/|rpc)/, async (route) => {
      const u = new URL(route.request().url()); let f = path.join(process.env.LOCAL_DIST, u.pathname);
      if (!u.pathname.startsWith("/assets/") || !fs.existsSync(f)) { if (u.pathname.startsWith("/assets/") ) return route.continue(); if (!fs.existsSync(f) || fs.statSync(f).isDirectory()) f = path.join(process.env.LOCAL_DIST, "index.html"); }
      return route.fulfill({ path: f });
    });
  }
  pg.on("pageerror", (e) => console.log(`  [${w}] pageerror ${e.message}`));
  for (const [n, u] of pages) {
    await pg.goto(HR + u, { waitUntil: "networkidle", timeout: 60000 }).catch((e) => console.log("goto", e.message));
    await pg.waitForTimeout(800);
    const r = await pg.evaluate(() => {
      const vw = document.documentElement.clientWidth, sw = document.documentElement.scrollWidth;
      const off = [];
      for (const el of document.querySelectorAll("body *")) {
        const rc = el.getBoundingClientRect(); if (!rc.width) continue;
        if (rc.right > vw + 1 || rc.left < -1) {
          // skip if an ancestor clips it
          let a = el.parentElement, clipped = false;
          while (a && a !== document.body) { const s = getComputedStyle(a); if (/(auto|scroll|hidden|clip)/.test(s.overflowX)) { const ar = a.getBoundingClientRect(); if (ar.right <= vw + 1) { clipped = true; break; } } a = a.parentElement; }
          if (!clipped) off.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} r=${Math.round(rc.right)} w=${Math.round(rc.width)} "${(el.innerText||"").trim().slice(0,40).replace(/\n/g," ")}"`);
        }
      }
      // inner scroll boxes that overflow (fine, but noted), and text clipped
      return { vw, sw, off: off.slice(0, 8), h1: document.querySelector("h1,h2")?.textContent?.slice(0, 50) };
    });
    const flag = r.sw > r.vw + 1 ? `OVERFLOW sw=${r.sw}` : "ok";
    console.log(`[${w}] ${n.padEnd(14)} ${flag}  h1="${r.h1}"`); if (r.sw > r.vw + 1) r.off.forEach((o) => console.log("     " + o));
    await pg.screenshot({ path: path.join(OUT, `${w}-${n}.png`), fullPage: true });
  }
  await ctx.close();
}
await b.close();
