import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
for (const n of ["progress", "close"]) { await p.goto(`file:///w/${n}.html`, { waitUntil: "networkidle" }); await p.waitForTimeout(500); await p.screenshot({ path: `slide-${n}.png` }); }
await b.close();
