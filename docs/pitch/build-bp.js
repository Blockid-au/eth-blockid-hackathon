// BlockID Business Passport — 3-minute investor pitch (13 slides, one message each, plain words).
// Copy follows docs/FACTS.md (Messaging). Screenshots: live eth.blockid.au, 27 Sep 2026 (img/bp-*.png).
// Founder contact QR: img/founder-qr.jpg (owner-supplied image) is placed as-is (never resized out of ratio, cropped or re-encoded).
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const QRCode = require("qrcode");
const fa = require("react-icons/fa6");

const C = {
  bg: "0A1311", card: "12201D", card2: "172A26", line: "25403A",
  text: "F2F7F5", muted: "A9BDB7", dim: "7E948F",
  teal: "22A07F", mint: "7FE0C2", gold: "E3A83A", blue: "5D8AD6", red: "E4675A", purple: "9B7BD4",
};
const H = "Arial", B = "Calibri";
const N = 13;

async function icon(Comp, color = "#FFFFFF", size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color, size: String(size) }));
  return "image/png;base64," + (await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}
/** Crop a screenshot (pixel box) and return data + aspect ratio. */
async function img(file, box) {
  const m = await sharp(`img/${file}`).metadata();
  const b = { left: 0, top: 0, width: m.width, height: m.height, ...box };
  b.width = Math.min(b.width, m.width - b.left); b.height = Math.min(b.height, m.height - b.top);
  const buf = await sharp(`img/${file}`).extract(b).png().toBuffer();
  return { data: "image/png;base64," + buf.toString("base64"), ratio: b.width / b.height };
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
  pres.author = "Long Do — Auschain Pty Ltd"; pres.title = "BlockID Business Passport — 3-minute pitch";

  const T = (s, t, o) => s.addText(t, { isTextBox: true, fontFace: B, color: C.text, margin: 0, ...o });
  const rr = (s, x, y, w, h, fill, line = C.line, r = 0.12) =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 1 }, rectRadius: r });
  const shot = (s, im, x, y, w, maxH) => {
    let h = w / im.ratio;
    if (maxH && h > maxH) { h = maxH; w = h * im.ratio; }
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.05, y: y - 0.05, w: w + 0.1, h: h + 0.1, fill: { color: C.line }, line: { color: C.line }, rectRadius: 0.08,
      shadow: { type: "outer", color: "000000", blur: 14, offset: 5, angle: 90, opacity: 0.5 } });
    s.addImage({ data: im.data, x, y, w, h });
    return { w, h };
  };

  // live screenshot of eth.blockid.au (img/live-*.png, 1440x900 @2x, light theme) inside a browser window with its real URL
  async function live(name, crop = {}) {
    const f = `img/live-${name}.png`, m = await sharp(f).metadata();
    const b = { left: 0, top: 0, width: m.width, height: m.height, ...Object.fromEntries(Object.entries(crop).map(([k, v]) => [k, v * 2])) };
    b.height = Math.min(b.height, m.height - b.top);
    const buf = await sharp(f).extract(b).png().toBuffer();
    return { data: "image/png;base64," + buf.toString("base64"), ratio: b.width / b.height };
  }
  const browser = (s, im, x, y, w, url) => {
    const bar = 0.3, h = w / im.ratio;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.04, y: y - 0.04, w: w + 0.08, h: h + bar + 0.08, fill: { color: "D9DFDD" }, line: { color: "D9DFDD" }, rectRadius: 0.07,
      shadow: { type: "outer", color: "000000", blur: 16, offset: 6, angle: 90, opacity: 0.55 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: bar, fill: { color: "ECEFEE" }, line: { color: "ECEFEE" } });
    ["FF5F57", "FEBC2E", "28C840"].forEach((c, i) => s.addShape(pres.shapes.OVAL, { x: x + 0.12 + i * 0.17, y: y + 0.095, w: 0.11, h: 0.11, fill: { color: c }, line: { color: c } }));
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.7, y: y + 0.05, w: Math.min(w - 0.9, 4.2), h: 0.2, fill: { color: "FFFFFF" }, line: { color: "D9DFDD" }, rectRadius: 0.05 });
    T(s, url, { x: x + 0.8, y: y + 0.05, w: Math.min(w - 1.0, 4.0), h: 0.2, fontSize: 8.5, color: "4A5A56", valign: "middle" });
    s.addImage({ data: im.data, x, y: y + bar, w, h });
    return { w, h: h + bar };
  };
  const dot = async (s, Comp, x, y, d, fill) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill } });
    s.addImage({ data: await icon(Comp), x: x + d * 0.25, y: y + d * 0.25, w: d * 0.5, h: d * 0.5 });
  };
  const head = (s, n, label, key, color = C.teal) => {
    T(s, `${n} / ${N}   ·   ${label.toUpperCase()}`, { x: 0.55, y: 0.35, w: 9, h: 0.3, fontSize: 11.5, bold: true, color, charSpacing: 3 });
    T(s, key, { x: 0.55, y: 0.7, w: 12.2, h: 0.8, fontFace: H, fontSize: 30, bold: true });
  };
  const point = (s, x, y, w, t, color = C.teal, size = 16) => {
    s.addShape(pres.shapes.OVAL, { x, y: y + 0.1, w: 0.16, h: 0.16, fill: { color }, line: { color } });
    T(s, t, { x: x + 0.32, y, w: w - 0.32, h: 0.7, fontSize: size, color: C.text, valign: "top" });
  };
  const foot = (s) => T(s, "eth.blockid.au  ·  Testnet demo. Not an offer of securities or financial advice.",
    { x: 0.55, y: 7.08, w: 12.2, h: 0.28, fontSize: 9.5, color: C.dim, align: "right" });
  const newSlide = () => { const s = pres.addSlide(); s.background = { color: C.bg }; return s; };

  // shared look for native charts on the dark deck: one series, teal marks, muted axis text, no grid
  const chartBase = (o) => ({
    chartColors: [C.teal], showLegend: false, showValue: true, dataLabelColor: C.text, dataLabelFontSize: 12, dataLabelFontBold: true,
    catAxisLabelColor: C.muted, catAxisLabelFontSize: 11, catAxisLabelFontFace: B, valAxisHidden: true,
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, catAxisLineShow: false, valAxisLineShow: false,
    plotArea: { fill: { color: C.card } }, chartArea: { fill: { color: C.card } }, barGapWidthPct: 55, ...o,
  });
  const src = (s, t, x, y, w) => T(s, t, { x, y, w, h: 0.45, fontSize: 8.5, color: C.dim, valign: "top" });
  const tile = (s, x, y, w, h, big, t, color = C.teal) => {
    rr(s, x, y, w, h, C.card);
    T(s, big, { x: x + 0.2, y: y + 0.12, w: w - 0.4, h: 0.6, fontFace: H, fontSize: 26, bold: true, color });
    T(s, t, { x: x + 0.2, y: y + 0.72, w: w - 0.4, h: h - 0.8, fontSize: 11.5, color: C.muted, valign: "top" });
  };

  const logo = await img("logo-mark-transparent.png");
  const L = {
    portfolio: await live("portfolio"), position: await live("position"), updates: await live("position-updates"),
    report: await live("report-score"), cap: await live("captable"), admin: await live("admin"), hsk: await live("hsk"),
    ok: await live("verify-ok", { top: 160, height: 640 }), bad: await live("verify-bad", { top: 160, height: 640 }),
  };
  const I = {
    hero: await img("bp-hero.png", { top: 120, height: 1180 }),
    card: await img("bp-hero-card.png"),
    report: await img("bp-report.png", { left: 690, top: 610, width: 2030, height: 1600 }),
    cap: await img("bp-captable.png", { left: 660, top: 690, width: 1990, height: 1560 }),
    ok: await img("bp-verify-ok.png", { left: 288, top: 1030, width: 2300, height: 770 }),
    bad: await img("bp-verify-bad.png", { left: 288, top: 1030, width: 2300, height: 770 }),
  };

  // ============ 1. Hero + elevator pitch
  let s = newSlide();
  s.addImage({ data: logo.data, x: 0.45, y: 0.4, w: 0.9, h: 0.9 });
  T(s, "BlockID Business Passport", { x: 1.5, y: 0.6, w: 6, h: 0.5, fontFace: H, fontSize: 20, bold: true });
  T(s, [
    { text: "Know the business", options: { color: C.text, breakLine: true } },
    { text: "you invest in.", options: { color: C.mint } },
  ], { x: 0.55, y: 1.75, w: 6.2, h: 1.9, fontFace: H, fontSize: 46, bold: true });
  T(s, "BlockID Business Passport gives every shareholder, large or small, a live view of the business they own: " +
    "updates and valuations checked and approved by people, a share register on blockchain as proof of ownership, " +
    "and dividends paid straight to their wallet.", { x: 0.55, y: 3.85, w: 5.9, h: 1.9, fontSize: 17, color: C.muted, valign: "top" });
  rr(s, 0.55, 5.95, 5.9, 0.6, C.card2, C.teal);
  T(s, "Understand it  ·  Follow it  ·  Own it  ·  Get paid  ·  Check it", { x: 0.55, y: 5.95, w: 5.9, h: 0.6, fontSize: 15, bold: true, color: C.mint, align: "center", valign: "middle" });
  const hs = browser(s, L.portfolio, 6.85, 1.5, 5.75, "eth.blockid.au/i  ·  demo investor account");
  const hy = 1.5 + hs.h + 0.25;
  [["14", "sample listings, live on testnet"], ["42", "share records on blockchain"], ["3", "chains, every record checkable"]].forEach(([n, l], i) => {
    const x = 6.6 + i * 2.13; rr(s, x, hy, 1.99, 1.05, C.card);
    T(s, n, { x: x + 0.15, y: hy + 0.08, w: 1.7, h: 0.5, fontFace: H, fontSize: 22, bold: true, color: i === 1 ? C.gold : C.teal });
    T(s, l, { x: x + 0.15, y: hy + 0.58, w: 1.75, h: 0.4, fontSize: 11, color: C.muted });
  });
  foot(s);

  s.addNotes("[0:00–0:12] Know the business you invest in. BlockID Business Passport gives every shareholder, large or small, a live view of the business they own: checked updates and valuations, a share register on blockchain as proof of ownership, and dividends paid straight to their wallet.");
  // ============ 2. Problem
  s = newSlide();
  head(s, 2, "The problem", "Investing in a business is hard to follow.", C.red);
  const pains = [
    [fa.FaFileCircleQuestion, "You don't really understand the business", "Reports are long, late or missing. The numbers are hard to compare."],
    [fa.FaEyeSlash, "You lose sight of it after you invest", "Sales, profit and new share sales happen without you seeing them."],
    [fa.FaFileSignature, "You're not sure what you own", "Ownership sits in a spreadsheet. Your stake can shrink and no one tells you."],
    [fa.FaHourglassHalf, "Dividends are slow, or never arrive", "Paperwork and bank transfers, if they happen at all."],
  ];
  for (let i = 0; i < pains.length; i++) {
    const x = 0.55 + i * 3.1;
    rr(s, x, 1.95, 2.9, 3.9, C.card, C.line);
    await dot(s, pains[i][0], x + 0.3, 2.25, 0.8, C.red);
    T(s, pains[i][1], { x: x + 0.3, y: 3.25, w: 2.35, h: 1.1, fontFace: H, fontSize: 18, bold: true, valign: "top" });
    T(s, pains[i][2], { x: x + 0.3, y: 4.45, w: 2.35, h: 1.2, fontSize: 14, color: C.muted, valign: "top" });
  }
  T(s, "Big or small, most investors in a business face the same four gaps.", { x: 0.55, y: 6.2, w: 12.2, h: 0.5, fontSize: 18, color: C.gold, bold: true });
  foot(s);

  s.addNotes("[0:12–0:24] Today investors lose sight of a business the day they invest. The numbers are hard to trust, ownership sits in a spreadsheet, so a stake can shrink without notice, and dividends are slow or never arrive.");
  // ============ 3. Market: size and the unmet need (sources: docs/MARKET-EVIDENCE.md)
  s = newSlide();
  head(s, 3, "The market", "Trillions in private businesses. Investors still can't see inside.", C.gold);
  rr(s, 0.55, 1.7, 7.25, 4.95, C.card);
  T(s, "How big is it? (US$ trillion)", { x: 0.8, y: 1.82, w: 6.8, h: 0.35, fontFace: H, fontSize: 14, bold: true });
  s.addChart(pres.charts.BAR, [{ name: "US$ trillion",
    labels: ["Global venture capital invested, 2025", "Company equity tracked on Carta today", "Tokenised assets by 2030 (base case)", "Alternative assets under management, 2030"],
    values: [0.43, 4.5, 5.5, 32] }],
    chartBase({ x: 0.7, y: 2.25, w: 6.95, h: 3.75, barDir: "bar", dataLabelFormatCode: '"$"0.0#"T"', dataLabelPosition: "outEnd", catAxisLabelFontSize: 11.5 }));
  src(s, "Sources: Crunchbase, Jan 2026 ($425B VC in 2025) · Carta.com, 2026 ($4.5T+ on platform) · Citi GPS, Jun 2026 ($5.5T base case) · Preqin, Oct 2025 ($32T by 2030).", 0.8, 6.08, 6.8);
  tile(s, 8.0, 1.7, 4.8, 1.55, "11%", "of value paid back to private-equity investors in 2024, the lowest in a decade (2014–17 average: 29%). Bain, Mar 2025", C.red);
  tile(s, 8.0, 3.4, 4.8, 1.55, "2.81M + 1M+", "businesses in Australia (ABS, Jun 2026) and Vietnam (NSO, 2025). SMEs are ~90% of all firms (World Bank).", C.gold);
  tile(s, 8.0, 5.1, 4.8, 1.55, "16%", "of alternative assets are held by individuals, who own ~50% of global wealth: retail access is the growth path. Bain, 2023");
  foot(s);

  s.addNotes("[0:24–0:42] The need is large. Alternative assets are heading to thirty-two trillion dollars by 2030 (Preqin), and venture investors put in four hundred and twenty-five billion in 2025 (Crunchbase). Yet in 2024 private equity paid back just eleven percent of its value, a ten-year low (Bain). Australia has 2.8 million businesses and Vietnam over a million, and individuals hold half of global wealth but only sixteen percent of alternatives. Investors need trusted values, regular updates and dividends on time.");
  // ============ 4. What investors get
  s = newSlide();
  head(s, 4, "The solution", "One passport per business. Five things every investor gets.");
  const pillars = [
    [fa.FaBookOpen, "Understand it", "A plain report. Every number linked to where it came from.", C.teal],
    [fa.FaChartLine, "Follow it", "Regular updates and a fair value, approved by a person.", C.blue],
    [fa.FaShieldHalved, "Own it", "Your shares on a public share register — your proof.", C.purple],
    [fa.FaWallet, "Get paid", "Dividends go straight into your wallet, automatically.", C.gold],
    [fa.FaMagnifyingGlass, "Check it", "Anyone can check the numbers and the register.", C.mint],
  ];
  for (let i = 0; i < pillars.length; i++) {
    const [ic, t, d, c] = pillars[i];
    const y = 1.8 + i * 1.0;
    rr(s, 0.55, y, 6.6, 0.85, C.card, c);
    await dot(s, ic, 0.72, y + 0.13, 0.6, c);
    T(s, t, { x: 1.5, y, w: 1.8, h: 0.85, fontFace: H, fontSize: 17, bold: true, color: c, valign: "middle" });
    T(s, d, { x: 3.3, y, w: 3.75, h: 0.85, fontSize: 14, color: C.text, valign: "middle" });
  }
  browser(s, L.position, 7.45, 1.8, 5.35, "eth.blockid.au/i/demo/EBA");
  T(s, "What a shareholder sees: the live demo account", { x: 7.6, y: 6.75, w: 5.4, h: 0.3, fontSize: 11.5, color: C.dim, align: "center", italic: true });
  foot(s);

  s.addNotes("[0:42–0:52] So we built one passport per business. Every investor can understand it, follow it, own it, get paid, and check it for themselves.");
  // ============ 5. Understand it
  s = newSlide();
  head(s, 5, "Understand it", "A fair value you can trace, approved by a person.");
  browser(s, L.report, 0.55, 1.75, 7.4, "eth.blockid.au/v/be5a8a832b474459/report  ·  Canva");
  rr(s, 8.2, 1.75, 4.6, 5.05, C.card);
  point(s, 8.45, 2.0, 4.2, "Paste a website. Get a plain report in minutes.");
  point(s, 8.45, 2.8, 4.2, "Clear business score A–E and a low · mid · high value.");
  point(s, 8.45, 3.6, 4.2, "Every figure links to its source. No source, no number.");
  point(s, 8.45, 4.4, 4.2, "A person checks and approves before anyone sees it.");
  T(s, "Canva: A$64B mid value, every source listed, approved by a person.", { x: 8.45, y: 5.45, w: 4.2, h: 0.9, fontSize: 15, bold: true, color: C.gold });
  foot(s);

  s.addNotes("[0:52–1:05] Understand it. Paste a website and get a plain report in minutes: a grade from A to E and a low, mid and high value. Independent research does the legwork, every figure links to its source, and a person approves it before anyone sees it.");
  // ============ 6. Own it
  s = newSlide();
  head(s, 6, "Own it", "Your shares are on the record. The record is your proof.", C.purple);
  browser(s, L.cap, 0.55, 1.75, 6.65, "eth.blockid.au/c/ARW/cap-table");
  rr(s, 7.4, 1.75, 5.4, 5.05, C.card);
  point(s, 7.65, 2.0, 5.0, "Every holder, wallet and share count in one share register.", C.purple);
  point(s, 7.65, 2.8, 5.0, "Recorded on blockchain and copied to two public blockchains.", C.purple);
  point(s, 7.65, 3.6, 5.0, "New shares need a person's approval — you see the dilution first.", C.purple);
  point(s, 7.65, 4.4, 5.0, "Hold your shares in your own wallet, or sign in with Google.", C.purple);
  T(s, "14 sample listings · 42 share records on blockchain", { x: 7.65, y: 5.5, w: 5.0, h: 0.8, fontSize: 15, bold: true, color: C.gold });
  foot(s);

  s.addNotes("[1:05–1:15] Own it. Every holder and share count sits in one share register on blockchain, copied to Ethereum and HashKey Chain. New shares need a person's approval, and investors see the dilution first.");
  // ============ 7. Follow it + get paid
  s = newSlide();
  head(s, 7, "Follow it · Get paid", "Same update for everyone. Dividends to your wallet.", C.gold);
  browser(s, L.updates, 0.55, 1.8, 5.1, "eth.blockid.au/i/demo/EBA");
  const steps = [
    ["1", "Business shares its numbers", "weekly, monthly, quarterly or yearly", C.blue],
    ["2", "Plain-language update + fair value", "a person approves it before it goes out", C.teal],
    ["3", "Every investor gets it at once", "record stored on blockchain, anyone can check", C.purple],
    ["4", "Dividend rule approved once", "24 hours to cancel, then paid to every wallet — no fees for holders", C.gold],
  ];
  steps.forEach(([n, t, d, c], i) => {
    const y = 1.8 + i * 1.22;
    rr(s, 5.9, y, 6.9, 1.05, C.card, c);
    s.addShape(pres.shapes.OVAL, { x: 6.1, y: y + 0.24, w: 0.58, h: 0.58, fill: { color: c }, line: { color: c } });
    T(s, n, { x: 6.1, y: y + 0.24, w: 0.58, h: 0.58, fontFace: H, fontSize: 18, bold: true, align: "center", valign: "middle" });
    T(s, t, { x: 6.95, y: y + 0.12, w: 5.7, h: 0.45, fontFace: H, fontSize: 17, bold: true });
    T(s, d, { x: 6.95, y: y + 0.55, w: 5.7, h: 0.4, fontSize: 13.5, color: C.muted });
  });
  foot(s);

  s.addNotes("[1:15–1:27] Follow it and get paid. The business shares its numbers on a schedule; a person approves the update and every investor gets it at the same time. Dividends go to every wallet, with no fees for holders.");
  // ============ 8. Check it
  s = newSlide();
  head(s, 8, "Check it", "Don't trust us. Check it yourself, in your browser.", C.mint);
  const v = browser(s, L.ok, 0.55, 1.8, 5.95, "eth.blockid.au/verify/EBA");
  browser(s, L.bad, 6.85, 1.8, 5.95, "eth.blockid.au/verify/EBA  ·  tamper test");
  const yv = 1.8 + v.h + 0.35;
  rr(s, 0.55, yv, 5.95, 0.7, C.card2, C.teal);
  T(s, "✓  The report matches the record on 3 blockchains", { x: 0.75, y: yv, w: 5.6, h: 0.7, fontSize: 15, bold: true, color: C.teal, valign: "middle" });
  rr(s, 6.85, yv, 5.95, 0.7, C.card2, C.red);
  T(s, "✗  Change one number and it turns red", { x: 7.05, y: yv, w: 5.6, h: 0.7, fontSize: 15, bold: true, color: C.red, valign: "middle" });
  const vs = [[fa.FaFileLines, "1. Your browser hashes the report"], [fa.FaLink, "2. Reads the hash from BlockID, HashKey, Ethereum"], [fa.FaCircleCheck, "3. Same = ✓   ·   changed = ✗"]];
  for (let i = 0; i < vs.length; i++) {
    const x = 0.55 + i * 4.12, y = yv + 0.95;
    rr(s, x, y, 3.95, 0.8, C.card);
    await dot(s, vs[i][0], x + 0.15, y + 0.12, 0.56, i === 2 ? C.teal : C.blue);
    T(s, vs[i][1], { x: x + 0.85, y, w: 3.0, h: 0.8, fontSize: 13.5, color: C.text, valign: "middle" });
  }
  foot(s);


  s.addNotes("[1:27–1:37] Check it. Don't trust us. Your browser hashes the report and compares it with three blockchains. Change one number and it turns red.");
  // ============ 9. Investor protection: what investors get, what businesses must do
  s = newSlide();
  head(s, 9, "Investor protection", "Real benefits for investors. Clear duties for the business.", C.teal);
  rr(s, 0.55, 1.7, 4.1, 4.95, C.card);
  T(s, "INVESTORS GET", { x: 0.8, y: 1.85, w: 3.6, h: 0.3, fontSize: 11.5, bold: true, color: C.teal, charSpacing: 3 });
  ["A checked value: every figure sourced, approved by a person", "The same update as everyone, at the same time", "Proof of ownership: a live share register on blockchain", "Dividends on schedule, straight to the wallet, no fees", "Dilution shown before any new shares are issued"]
    .forEach((t, i) => point(s, 0.8, 2.3 + i * 0.84, 3.7, t, C.teal, 13));
  rr(s, 4.8, 1.7, 4.1, 4.95, C.card);
  T(s, "THE BUSINESS MUST", { x: 5.05, y: 1.85, w: 3.6, h: 0.3, fontSize: 11.5, bold: true, color: C.gold, charSpacing: 3 });
  ["Keep a share register: already the law (AU Corporations Act s169 · VN Law on Enterprises 2020 Art. 122)", "Report on schedule; CSF companies report yearly, audit above A$3M raised (ASIC RG 261)", "Get a person to approve every new share, dividend and transfer", "Answer the risks the numbers flag, on the record"]
    .forEach((t, i) => point(s, 5.05, 2.3 + i * 1.04, 3.7, t, C.gold, 13));
  rr(s, 9.05, 1.7, 3.75, 3.4, C.card);
  T(s, "Cash back to PE investors (% of NAV)", { x: 9.25, y: 1.82, w: 3.4, h: 0.35, fontFace: H, fontSize: 12.5, bold: true });
  s.addChart(pres.charts.BAR, [{ name: "% of NAV", labels: ["2014–17 average", "2024"], values: [29, 11] }],
    chartBase({ x: 9.2, y: 2.2, w: 3.45, h: 2.45, barDir: "col", dataLabelFormatCode: '0"%"', dataLabelPosition: "outEnd", valAxisMaxVal: 35, valAxisMinVal: 0 }));
  src(s, "Bain Global PE Report, Mar 2025", 9.25, 4.68, 3.4);
  tile(s, 9.05, 5.25, 3.75, 1.4, "A$837.7M", "lost to investment scams in Australia in 2025. NASC, Targeting Scams 2025", C.red);
  foot(s);

  s.addNotes("[1:37–1:57] What does each side get? Investors get a checked value, the same update at the same time, proof of ownership and dividends on time. In return the business keeps a live share register, which Australian and Vietnamese law already require, reports on schedule (ASIC RG 261 for crowd-funded companies), and gets a person to approve every new share and dividend. With A$838 million lost to investment scams in Australia in 2025, checkable records matter.");
  // ============ 10. Custody and tokenised assets: why the design matters next
  s = newSlide();
  head(s, 10, "Custody · Tokenised assets", "Built for the tokenised future: clear custody from day one.", C.purple);
  rr(s, 0.55, 1.7, 6.6, 4.95, C.card);
  T(s, "Tokenised real-world assets on-chain (US$ billion)", { x: 0.8, y: 1.82, w: 6.2, h: 0.35, fontFace: H, fontSize: 14, bold: true });
  s.addChart(pres.charts.BAR, [{ name: "US$ billion", labels: ["Mar 2025", "Jan 2026", "Mar 2026", "May 2026", "Oct 2026"], values: [6.6, 21, 26.4, 31.4, 38.7] }],
    chartBase({ x: 0.7, y: 2.25, w: 6.3, h: 3.75, barDir: "col", dataLabelFormatCode: '"$"0.0"B"', dataLabelPosition: "outEnd", valAxisMinVal: 0, valAxisMaxVal: 45 }));
  src(s, "rwa.xyz \"distributed\" assets, excl. stablecoins (1 Oct 2026: $38.66B, 5.02M holders). Earlier points: PYMNTS, ByteTree, Yellow citing rwa.xyz.", 0.8, 6.08, 6.2);
  tile(s, 7.35, 1.7, 5.45, 1.3, "$5.5T by 2030", "tokenised assets, Citi GPS base case (Jun 2026; bear $2.7T, bull $8.2T)", C.purple);
  rr(s, 7.35, 3.15, 5.45, 1.75, C.card);
  T(s, "THE RULES ARE ARRIVING", { x: 7.6, y: 3.27, w: 5, h: 0.3, fontSize: 11, bold: true, color: C.gold, charSpacing: 3 });
  T(s, [
    { text: "Dec 2024  EU MiCA: custody and segregation of client assets", options: { breakLine: true } },
    { text: "Sep 2025  Vietnam Resolution 05/2025: 5-year crypto-asset pilot", options: { breakLine: true } },
    { text: "Jan 2026  Vietnam Law 71/2025: digital assets are property", options: { breakLine: true } },
    { text: "Apr 2026  Australia Digital Assets Framework: licensed custody platforms" },
  ], { x: 7.6, y: 3.6, w: 5.1, h: 1.25, fontSize: 11.5, color: C.text, paraSpaceAfter: 3, valign: "top" });
  rr(s, 7.35, 5.05, 5.45, 1.6, C.card2, C.teal);
  T(s, "BLOCKID CUSTODY DESIGN", { x: 7.6, y: 5.15, w: 5, h: 0.3, fontSize: 11, bold: true, color: C.teal, charSpacing: 3 });
  T(s, "Keys sit in one locked-down signing service, never with the research tools · every holder verified (KYC) · records on 3 chains · a licensed custodian plugs in, investors keep the proof", { x: 7.6, y: 5.47, w: 5.05, h: 1.1, fontSize: 12.5, color: C.text, valign: "top" });
  foot(s);

  s.addNotes("[1:57–2:15] This also prepares for tokenised assets. Tokenised real-world assets on-chain grew from about seven to thirty-nine billion dollars in nineteen months (rwa.xyz), and Citi expects five and a half trillion by 2030. New rules in Europe, Vietnam and Australia require proper custody. In BlockID, keys sit in one locked-down signing service, every holder is verified, every record is on three chains, and a licensed custodian can plug in.");
  // ============ 11. Architecture: how the layers talk
  s = newSlide();
  head(s, 11, "How it works", "People decide. Every step is on the record.", C.blue);
  browser(s, L.admin, 0.55, 1.75, 6.05, "eth.blockid.au/admin  ·  every step waits for a person");
  browser(s, L.hsk, 6.75, 1.75, 6.05, "eth.blockid.au/hsk  ·  HashKey Chain, chain 133");
  const flow = [["Research drafts", "public sources gathered and checked; drafts only, no access to keys", C.teal],
    ["A person approves", "a named reviewer signs; no one can approve their own request", C.gold],
    ["Recorded on chain", "any EVM chain, L1 or L2; live on BlockID Chain, Ethereum and HashKey", C.purple]];
  flow.forEach(([t, d, c], i) => {
    const x = 0.55 + i * 4.13;
    rr(s, x, 6.0, 3.95, 0.82, C.card, c);
    T(s, t, { x: x + 0.18, y: 6.04, w: 3.6, h: 0.36, fontFace: H, fontSize: 14, bold: true, color: c });
    T(s, d, { x: x + 0.18, y: 6.4, w: 3.65, h: 0.38, fontSize: 10.5, color: C.muted });
    if (i < 2) T(s, "→", { x: x + 3.93, y: 6.0, w: 0.22, h: 0.82, fontSize: 16, bold: true, color: C.muted, align: "center", valign: "middle" });
  });
  foot(s);

  s.addNotes("[2:15–2:30] How it works. Research tools draft, but they never touch keys. A named person reviews and approves every valuation, new share and dividend, and no one can approve their own request. Only then is it written to the chain, and anyone can check the record. It runs on any EVM chain, layer 1 or layer 2: today BlockID Chain, Ethereum and HashKey Chain.");
  // ============ 12. Team: who executes (owner-confirmed facts, docs/TEAM.md)
  s = newSlide();
  head(s, 12, "The team", "Built by founders who have run tech at scale.", C.mint);
  const people = [
    ["DL", "Do Van Long", "Founder & CEO", C.teal, [
      "Former CTO of major Vietnamese corporations",
      "Founded Vietnam Blockchain Corporation (2016) and Auschain (Sydney)",
      "Built Agridential, national-scale blockchain traceability"]],
    ["TT", "Truong Quoc Tuan", "Co-founder", C.gold, [
      "Former CTO of major Vietnamese corporations",
      "Capital-markets experience (Dragon Capital Group)",
      "Investor, partner and finance side of BlockID"]],
  ];
  people.forEach(([ini, name, role, c, pts], i) => {
    const x = 0.55 + i * 6.2;
    rr(s, x, 1.7, 6.05, 3.2, C.card, c);
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.95, w: 0.95, h: 0.95, fill: { color: c }, line: { color: c } });
    T(s, ini, { x: x + 0.3, y: 1.95, w: 0.95, h: 0.95, fontFace: H, fontSize: 24, bold: true, align: "center", valign: "middle", color: C.bg });
    T(s, name, { x: x + 1.45, y: 1.95, w: 4.4, h: 0.45, fontFace: H, fontSize: 21, bold: true });
    T(s, role, { x: x + 1.45, y: 2.42, w: 4.4, h: 0.35, fontSize: 14, color: c, bold: true });
    pts.forEach((t, j) => point(s, x + 0.3, 3.1 + j * 0.42, 5.6, t, c, 13));
    rr(s, x + 0.3, 4.35, 5.45, 0.38, C.card2, c, 0.08);
    T(s, "Australia Global Talent visa (subclass 858)", { x: x + 0.3, y: 4.35, w: 5.45, h: 0.38, fontSize: 12.5, bold: true, color: C.text, align: "center", valign: "middle" });
  });
  const teams = [
    [fa.FaCode, "Tech team in Vietnam", "Blockchain, AI and fintech engineers (Vietnam Blockchain Corporation, since 2016)", C.blue],
    [fa.FaHandshake, "Business team in Sydney", "Pilots, partners and licensing in Australia (Auschain)", C.gold],
    [fa.FaLayerGroup, "Built end to end, in house", "Smart contracts, research tools, secure signing service, web app, 3 chains", C.teal],
  ];
  for (let i = 0; i < teams.length; i++) {
    const [ic, t, d, c] = teams[i], x = 0.55 + i * 4.13;
    rr(s, x, 5.1, 3.95, 1.6, C.card);
    await dot(s, ic, x + 0.2, 5.28, 0.6, c);
    T(s, t, { x: x + 0.95, y: 5.25, w: 2.9, h: 0.42, fontFace: H, fontSize: 14, bold: true, color: c });
    T(s, d, { x: x + 0.95, y: 5.68, w: 2.9, h: 0.95, fontSize: 11.5, color: C.muted, valign: "top" });
  }
  foot(s);
  s.addNotes("[2:30–2:45] Who builds it? Founder Do Van Long and co-founder Truong Quoc Tuan are both former CTOs of major Vietnamese corporations and hold Australia's Global Talent visa. A strong tech team in Vietnam and a business team in Sydney built this whole system in house, ready to grow globally.");

  // ============ 13. Live today + business model + ask
  s = newSlide();
  head(s, 13, "Join us", "A real app, ready to run on your chain."); 
  const st = [["14", "sample listings live on testnet"], ["42", "share-token contracts"], ["3", "chains: BlockID L1, Ethereum, HashKey L2"]];
  st.forEach((x, i) => {
    const X = 0.55 + i * 2.72; rr(s, X, 1.75, 2.57, 1.2, C.card);
    T(s, x[0], { x: X + 0.18, y: 1.8, w: 2.2, h: 0.6, fontFace: H, fontSize: 26, bold: true, color: i % 2 ? C.gold : C.teal });
    T(s, x[1], { x: X + 0.18, y: 2.4, w: 2.3, h: 0.5, fontSize: 11.5, color: C.muted });
  });
  const asks = [
    ["Ethereum investors", "Back our first pilots in Australia and Vietnam: real businesses, real shareholders, on Ethereum rails.", C.teal],
    ["L1 and L2 teams", "Run BlockID on your chain as a real-world-asset case: share registers, updates, dividends and checks. Any EVM chain.", C.gold],
    ["Licensed partners", "Custody, offerings and transfer services, so investors keep their rights and their proof.", C.purple],
  ];
  asks.forEach(([t, d, c], i) => {
    const y = 3.15 + i * 1.2;
    rr(s, 0.55, y, 7.95, 1.05, C.card, c);
    T(s, t, { x: 0.8, y: y + 0.08, w: 7.5, h: 0.4, fontFace: H, fontSize: 16, bold: true, color: c });
    T(s, d, { x: 0.8, y: y + 0.48, w: 7.5, h: 0.52, fontSize: 12.5, color: C.text });
  });
  T(s, "Revenue: listing fee · share-register subscription · small transfer and dividend fees", { x: 0.55, y: 6.78, w: 7.95, h: 0.3, fontSize: 11, color: C.dim });

  // right column: founder contact card (owner's original image, untouched) + app QR
  rr(s, 8.7, 1.75, 4.1, 5.0, C.card2, C.teal);
  const founderQR = "img/founder-qr.jpg";
  {
    // placed as-is: original file bytes and aspect ratio (no crop, resize filter or re-encode) so the code still scans
    const m = await sharp(founderQR).metadata();
    const w = 2.75, h = w * m.height / m.width;
    s.addImage({ path: founderQR, x: 8.85, y: 1.9, w, h });
    T(s, "Connect with the founder", { x: 8.85, y: 1.9 + h + 0.04, w, h: 0.28, fontSize: 11, bold: true, align: "center" });
  }
  const qr = await QRCode.toBuffer("https://eth.blockid.au", { width: 600, margin: 1, color: { dark: "#0A1311", light: "#FFFFFF" } });
  s.addImage({ data: "image/png;base64," + qr.toString("base64"), x: 11.72, y: 1.95, w: 0.95, h: 0.95 });
  T(s, "Try it now", { x: 11.62, y: 2.93, w: 1.15, h: 0.26, fontSize: 10.5, bold: true, align: "center" });
  T(s, "eth.blockid.au", { x: 11.62, y: 3.17, w: 1.15, h: 0.24, fontSize: 9, color: C.teal, align: "center" });

  T(s, "Know the business you invest in.", { x: 8.95, y: 4.72, w: 3.6, h: 0.7, fontFace: H, fontSize: 16, bold: true, color: C.mint });
  T(s, "Long Do · admin@blockid.au", { x: 8.95, y: 5.5, w: 3.6, h: 0.35, fontSize: 13, color: C.muted });
  T(s, "linkedin.com/in/dovanlong", { x: 8.95, y: 5.82, w: 3.6, h: 0.35, fontSize: 11.5, color: C.dim });
  T(s, "eth.blockid.au · hr.blockid.au", { x: 8.95, y: 6.14, w: 3.6, h: 0.35, fontSize: 11.5, color: C.teal });
  foot(s);
  s.addNotes("[2:45–3:00] Everything you saw runs today on testnet, across BlockID Chain, Ethereum and HashKey Chain. We invite Ethereum investors to back our first pilots in Australia and Vietnam, and layer one and layer two teams to run BlockID on their chain as a real-world-asset case. Licensed partners can bring custody and offerings. Know the business you invest in. Try it at eth.blockid.au.");

  const out = "out/BlockID-Business-Passport-3min.pptx";
  await pres.writeFile({ fileName: out });
  console.log("written", out);
})();
