// BlockID Business Passport — 3-minute investor pitch (8 slides, one message each, plain words).
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
const N = 9;

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

  const logo = await img("logo-mark-transparent.png");
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
    "AI-analysed, human-approved updates and valuations, an on-chain share register as proof of ownership, " +
    "and dividends paid straight to their wallet.", { x: 0.55, y: 3.85, w: 5.9, h: 1.9, fontSize: 17, color: C.muted, valign: "top" });
  rr(s, 0.55, 5.95, 5.9, 0.6, C.card2, C.teal);
  T(s, "Understand it  ·  Follow it  ·  Own it  ·  Get paid  ·  Check it", { x: 0.55, y: 5.95, w: 5.9, h: 0.6, fontSize: 15, bold: true, color: C.mint, align: "center", valign: "middle" });
  const hs = shot(s, I.hero, 6.6, 1.55, 6.25);
  const hy = 1.55 + hs.h + 0.3;
  [["13", "businesses listed"], ["38", "share records on blockchain"], ["A$87B", "fair value checked by people"]].forEach(([n, l], i) => {
    const x = 6.6 + i * 2.13; rr(s, x, hy, 1.99, 1.05, C.card);
    T(s, n, { x: x + 0.15, y: hy + 0.08, w: 1.7, h: 0.5, fontFace: H, fontSize: 22, bold: true, color: i === 1 ? C.gold : C.teal });
    T(s, l, { x: x + 0.15, y: hy + 0.58, w: 1.75, h: 0.4, fontSize: 11, color: C.muted });
  });
  T(s, "Live today at eth.blockid.au", { x: 6.6, y: hy + 1.2, w: 6.25, h: 0.35, fontSize: 13, color: C.dim, align: "center", italic: true });
  foot(s);
  s.addNotes("[0:00–0:20] Know the business you invest in. BlockID Business Passport gives every shareholder, large or small, a live view of the business they own: updates and valuations analysed by AI and approved by a person, a share register on blockchain as proof of ownership, and dividends paid straight to their wallet.");

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
  s.addNotes("[0:20–0:40] Whether you put in a thousand dollars or a million, investing in a business is hard to follow. You don't really understand it, you lose sight of it after you invest, you're not sure what you own — your stake can shrink and nobody tells you — and dividends are slow or never arrive.");

  // ============ 3. What investors get
  s = newSlide();
  head(s, 3, "The solution", "One passport per business. Five things every investor gets.");
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
  shot(s, I.card, 8.1, 1.75, 4.4, 5.0);
  T(s, "What a shareholder sees", { x: 7.6, y: 6.75, w: 5.4, h: 0.3, fontSize: 11.5, color: C.dim, align: "center", italic: true });
  foot(s);
  s.addNotes("[0:40–1:00] BlockID gives each business a passport, and every investor gets five things: understand it, follow it, own it, get paid, and check it. On the right is what a shareholder sees: the shares they own, their stake, a fair value approved by people, the latest update and the dividend paid to their wallet.");

  // ============ 4. Understand it
  s = newSlide();
  head(s, 4, "Understand it", "A fair value you can trace, approved by a person.");
  shot(s, I.report, 0.55, 1.75, 7.2, 5.1);
  rr(s, 8.2, 1.75, 4.6, 5.05, C.card);
  point(s, 8.45, 2.0, 4.2, "Paste a website. Get a plain report in minutes.");
  point(s, 8.45, 2.8, 4.2, "Clear business score A–E and a low · mid · high value.");
  point(s, 8.45, 3.6, 4.2, "Every figure links to its source. No source, no number.");
  point(s, 8.45, 4.4, 4.2, "A person checks and approves before anyone sees it.");
  T(s, "Canva: A$64B mid value, every source listed, approved by a person.", { x: 8.45, y: 5.45, w: 4.2, h: 0.9, fontSize: 15, bold: true, color: C.gold });
  foot(s);
  s.addNotes("[1:00–1:25] Understand it. Paste any business website and in minutes you get a plain report: a business score, a value range, competitors and the sources behind every number. If there's no source, the number is dropped. A person reviews and approves it before investors see it. Here's Canva.");

  // ============ 5. Own it
  s = newSlide();
  head(s, 5, "Own it", "Your shares are on the record. The record is your proof.", C.purple);
  shot(s, I.cap, 0.55, 1.75, 6.4, 5.1);
  rr(s, 7.4, 1.75, 5.4, 5.05, C.card);
  point(s, 7.65, 2.0, 5.0, "Every holder, wallet and share count in one share register.", C.purple);
  point(s, 7.65, 2.8, 5.0, "Recorded on blockchain and copied to two public blockchains.", C.purple);
  point(s, 7.65, 3.6, 5.0, "New shares need a person's approval — you see the dilution first.", C.purple);
  point(s, 7.65, 4.4, 5.0, "Hold your shares in your own wallet, or sign in with Google.", C.purple);
  T(s, "13 businesses listed · 38 share records on blockchain", { x: 7.65, y: 5.5, w: 5.0, h: 0.8, fontSize: 15, bold: true, color: C.gold });
  foot(s);
  s.addNotes("[1:25–1:45] Own it. When a business lists, its shares are recorded in a share register on blockchain and copied to two public blockchains. That record is your proof of ownership. New shares need a person's approval, and you see the dilution first. You can hold shares in your own wallet or simply sign in with Google.");

  // ============ 6. Follow it + get paid
  s = newSlide();
  head(s, 6, "Follow it · Get paid", "Same update for everyone. Dividends to your wallet.", C.gold);
  shot(s, I.card, 0.9, 1.75, 4.3, 5.05);
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
  s.addNotes("[1:45–2:05] Follow it and get paid. The business shares its numbers on a regular schedule. We turn them into a plain-language update with a fair value, a person approves it, and every investor gets it at the same time. Dividends follow a rule approved once: after each update there are 24 hours to cancel, then the dividend is paid to every wallet automatically — holders pay no fees.");

  // ============ 7. Check it
  s = newSlide();
  head(s, 7, "Check it", "Don't trust us. Check it yourself, in your browser.", C.mint);
  const v = shot(s, I.ok, 0.55, 1.8, 5.95);
  shot(s, I.bad, 6.85, 1.8, 5.95);
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
  T(s, "No login needed: eth.blockid.au/verify", { x: 0.55, y: yv + 1.95, w: 12.2, h: 0.4, fontSize: 16, bold: true, color: C.mint, align: "center" });
  foot(s);
  s.addNotes("[2:05–2:25] Check it. You don't have to trust us. The check page recomputes the report in your own browser and compares it with the record on three blockchains. Change a single number and it turns red. No login needed.");


  // ============ 8. Architecture: how the layers talk
  s = newSlide();
  head(s, 8, "How it's built", "Two blockchain layers. Only approved actions reach them.", C.blue);
  const lab = (y, h, t, sub, c) => {
    rr(s, 0.55, y, 1.75, h, C.card2, c, 0.08);
    T(s, [{ text: t, options: { fontFace: H, fontSize: 12.5, bold: true, color: c, breakLine: true } },
      { text: sub, options: { fontSize: 9.5, color: C.muted } }], { x: 0.62, y, w: 1.62, h, align: "center", valign: "middle", paraSpaceBefore: 2 });
  };
  const box = (x, y, w, h, t, sub, c, fill = C.card) => {
    rr(s, x, y, w, h, fill, c, 0.08);
    T(s, t, { x: x + 0.1, y: y + 0.07, w: w - 0.2, h: 0.34, fontFace: H, fontSize: 12.5, bold: true, color: c, align: "center" });
    if (sub) T(s, sub, { x: x + 0.1, y: y + 0.4, w: w - 0.2, h: h - 0.45, fontSize: 9.5, color: C.text, align: "center", valign: "top" });
  };
  const line = (x1, y1, x2, y2, c = C.muted, both = false) =>
    s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
      flipH: x2 < x1, flipV: y2 < y1, line: { color: c, width: 1.75, endArrowType: "triangle", beginArrowType: both ? "triangle" : undefined } });
  const tag = (x, y, w, t, c) => T(s, t, { x, y, w, h: 0.26, fontSize: 9, italic: true, color: c, align: "center" });

  // row A: people
  lab(1.62, 0.72, "PEOPLE", "who uses it", C.mint);
  box(2.5, 1.62, 2.55, 0.72, "Investors", "portfolio · updates · dividends", C.mint);
  box(5.2, 1.62, 2.55, 0.72, "Businesses", "list · shareholders · updates", C.mint);
  box(7.9, 1.62, 2.55, 0.72, "Approvers", "a person signs every step", C.gold);
  // row B: app + services
  lab(2.62, 1.05, "APP & SERVICES", "off-chain, no keys except issuer", C.teal);
  box(2.5, 2.62, 1.9, 1.05, "Web app", "eth.blockid.au\nGoogle · browser key · MetaMask", C.teal);
  box(4.55, 2.62, 1.9, 1.05, "Analysis", "AI reads sources,\nformula sets value\n(no keys)", C.teal);
  box(6.6, 2.62, 1.75, 1.05, "Approval", "admin wallet signs\none approval", C.gold);
  box(8.5, 2.62, 1.95, 1.05, "Issuer", "only key holder\nisolated network\nacts on approved rows", C.red);
  line(4.41, 3.15, 4.54, 3.15); line(6.46, 3.15, 6.59, 3.15); line(8.36, 3.15, 8.49, 3.15);
  line(3.45, 2.35, 3.45, 2.61, C.muted, true); line(6.47, 2.35, 6.47, 2.61, C.muted, true); line(9.17, 2.35, 9.17, 2.61, C.muted, true);
  // row C: layer 1
  lab(3.97, 1.2, "LAYER 1", "BlockID EVM · chain 262626", C.teal);
  rr(s, 2.5, 3.97, 7.95, 1.2, "10302A", C.teal, 0.08);
  T(s, "BlockID Chain — the share register of record  ·  gas price 0", { x: 2.65, y: 4.02, w: 7.7, h: 0.34, fontFace: H, fontSize: 13, bold: true, color: C.teal });
  ["Identity registry\n(KYC holders)", "Share token\n1 token = 1 share", "Dividends\npaid in mAUD", "Report hash\nfair value proof"].forEach((t, i) => {
    rr(s, 2.65 + i * 1.95, 4.42, 1.8, 0.65, C.card2, C.line, 0.06);
    T(s, t, { x: 2.65 + i * 1.95, y: 4.42, w: 1.8, h: 0.65, fontSize: 10, color: C.text, align: "center", valign: "middle" });
  });
  line(9.47, 3.68, 9.47, 3.96, C.red);
  tag(9.5, 3.68, 1.0, "signs", C.red);
  // row D: layer 2 + ethereum
  lab(5.47, 1.2, "LAYER 2", "HashKey Chain · chain 133", C.gold);
  rr(s, 2.5, 5.47, 5.25, 1.2, "2A2412", C.gold, 0.08);
  T(s, "HashKey Chain — public proof for real-world assets", { x: 2.65, y: 5.52, w: 5.0, h: 0.34, fontFace: H, fontSize: 13, bold: true, color: C.gold });
  ["Mirror share token\n(same balances)", "Cap-table root\n(Merkle)", "Agent provenance\n(who proposed)"].forEach((t, i) => {
    rr(s, 2.65 + i * 1.7, 5.92, 1.58, 0.65, C.card2, C.line, 0.06);
    T(s, t, { x: 2.65 + i * 1.7, y: 5.92, w: 1.58, h: 0.65, fontSize: 9.5, color: C.text, align: "center", valign: "middle" });
  });
  box(7.9, 5.47, 2.55, 1.2, "Ethereum", "Hoodi testnet · chain 560048\nmirror token + cap-table root\n(public anchor)", C.blue);
  line(5.1, 5.18, 5.1, 5.46, C.gold); tag(5.2, 5.18, 2.4, "sync: same balances + root", C.gold);
  line(9.17, 5.18, 9.17, 5.46, C.blue);
  // right: proof column
  rr(s, 10.7, 1.62, 2.1, 5.05, C.card2, C.mint, 0.1);
  await dot(s, fa.FaMagnifyingGlass, 11.45, 1.8, 0.6, C.teal);
  T(s, "Anyone checks", { x: 10.8, y: 2.5, w: 1.9, h: 0.35, fontFace: H, fontSize: 13.5, bold: true, color: C.mint, align: "center" });
  T(s, "/verify recomputes the report hash in the browser and reads it from all 3 chains.\n\nExplorers:\nscan.blockid.au\nHashKey · Etherscan\n\nMatch = ✓\nAny change = ✗",
    { x: 10.85, y: 2.9, w: 1.8, h: 3.6, fontSize: 10.5, color: C.text, align: "center", valign: "top" });
  line(10.46, 4.57, 10.69, 4.57, C.mint); line(10.46, 6.07, 10.69, 6.07, C.mint);
  foot(s);
  s.addNotes("[2:25–2:40] How it's built. People use one web app. Analysis never holds keys; a person approves; only the isolated issuer signs. Layer 1 is our BlockID Chain, the share register of record with zero gas. Layer 2 is HashKey Chain, the public proof layer for real-world assets: the same balances, a cap-table root and a record of which agent proposed what, also anchored on Ethereum. Anyone can check all three from the browser.");

  // ============ 9. Live today + business model + ask
  s = newSlide();
  head(s, 9, "Live today · The ask", "Live today. Looking for pilot businesses and partners.");
  const st = [["13", "businesses listed"], ["38", "share records on blockchain"], ["A$87B", "fair value checked by people"], ["3", "blockchains, every record checkable"]];
  st.forEach((x, i) => {
    const X = 0.55 + i * 2.05; rr(s, X, 1.75, 1.9, 1.45, C.card);
    T(s, x[0], { x: X + 0.15, y: 1.83, w: 1.65, h: 0.7, fontFace: H, fontSize: 28, bold: true, color: i % 2 ? C.gold : C.teal });
    T(s, x[1], { x: X + 0.15, y: 2.55, w: 1.65, h: 0.6, fontSize: 11.5, color: C.muted });
  });
  rr(s, 0.55, 3.4, 3.95, 3.35, C.card);
  T(s, "WHO PAYS", { x: 0.8, y: 3.55, w: 3.5, h: 0.3, fontSize: 11.5, bold: true, color: C.gold, charSpacing: 3 });
  ["Businesses: listing fee + share-register subscription", "Per share transfer fee", "0.5–1% of each dividend round"].forEach((t, i) => point(s, 0.8, 3.95 + i * 0.72, 3.55, t, C.gold, 13.5));
  rr(s, 4.65, 3.4, 3.85, 3.35, C.card);
  T(s, "WHO IT'S FOR", { x: 4.9, y: 3.55, w: 3.5, h: 0.3, fontSize: 11.5, bold: true, color: C.teal, charSpacing: 3 });
  ["Investors, retail and professional", "Businesses raising from them (AU · VN)", "Accelerators, VCs, licensed partners"].forEach((t, i) => point(s, 4.9, 3.95 + i * 0.72, 3.45, t, C.teal, 13.5));

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

  T(s, "We're looking for", { x: 8.95, y: 4.72, w: 3.6, h: 0.35, fontFace: H, fontSize: 16, bold: true, color: C.mint });
  T(s, "Pilot businesses · investor communities · licensed partners", { x: 8.95, y: 5.07, w: 3.6, h: 0.7, fontSize: 13.5, color: C.text });
  T(s, "Long Do · info@blockid.au", { x: 8.95, y: 5.85, w: 3.6, h: 0.35, fontSize: 13, color: C.muted });
  T(s, "linkedin.com/in/dovanlong", { x: 8.95, y: 6.17, w: 3.6, h: 0.35, fontSize: 11.5, color: C.dim });
  foot(s);
  s.addNotes("[2:40–3:00] This is live today: thirteen businesses listed, thirty-eight share records on blockchain and eighty-seven billion dollars of fair value checked by people. Businesses pay a listing fee and a share-register subscription, plus a small fee per transfer and per dividend round. We're looking for pilot businesses, investor communities and licensed partners. Scan to try it, or scan to connect with me. Know the business you invest in. Thank you.");

  const out = "out/BlockID-Business-Passport-3min.pptx";
  await pres.writeFile({ fileName: out });
  console.log("written", out);
})();
