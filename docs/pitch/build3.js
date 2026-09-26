// BlockID Startup Passport — 3-minute pitch (7 slides, one key point each)
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const QRCode = require("qrcode");
const fa = require("react-icons/fa6");

const C = {
  bg: "0A1311", card: "12201D", card2: "172A26", line: "25403A",
  text: "F2F7F5", muted: "A9BDB7", dim: "7E948F",
  teal: "22A07F", gold: "E3A83A", blue: "5D8AD6", red: "E4675A", purple: "9B7BD4",
};
const H = "Arial", B = "Calibri";

async function icon(Comp, color = "#FFFFFF", size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color, size: String(size) }));
  return "image/png;base64," + (await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}
async function img(file, { top = 0, height } = {}) {
  const m = await sharp(`img/${file}`).metadata();
  const h = Math.min(height || m.height, m.height - top);
  const buf = await sharp(`img/${file}`).extract({ left: 0, top, width: m.width, height: h }).png().toBuffer();
  return { data: "image/png;base64," + buf.toString("base64"), ratio: m.width / h };
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
  pres.author = "Long Do — Auschain Pty Ltd"; pres.title = "BlockID Startup Passport — 3-minute pitch";

  const T = (s, t, o) => s.addText(t, { isTextBox: true, fontFace: B, color: C.text, margin: 0, ...o });
  const rr = (s, x, y, w, h, fill, line = C.line, r = 0.12) =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: line, width: 1 }, rectRadius: r });
  const arrow = (s, x1, y1, x2, y2, color = C.dim) =>
    s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
      flipH: x2 < x1, flipV: y2 < y1, line: { color, width: 2, endArrowType: "triangle" } });
  const shot = (s, im, x, y, w) => {
    const h = w / im.ratio;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.05, y: y - 0.05, w: w + 0.1, h: h + 0.1, fill: { color: C.line }, line: { color: C.line }, rectRadius: 0.08,
      shadow: { type: "outer", color: "000000", blur: 14, offset: 5, angle: 90, opacity: 0.5 } });
    s.addImage({ data: im.data, x, y, w, h });
    return h;
  };
  const dot = async (s, Comp, x, y, d, fill) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill } });
    s.addImage({ data: await icon(Comp), x: x + d * 0.25, y: y + d * 0.25, w: d * 0.5, h: d * 0.5 });
  };
  // header: step label + key point headline
  const head = (s, n, label, key, color = C.teal) => {
    T(s, `${n} / 7   ·   ${label.toUpperCase()}`, { x: 0.55, y: 0.35, w: 9, h: 0.3, fontSize: 11.5, bold: true, color, charSpacing: 3 });
    T(s, key, { x: 0.55, y: 0.7, w: 12.2, h: 0.8, fontFace: H, fontSize: 30, bold: true });
  };
  const point = (s, x, y, w, t, color = C.teal) => {
    s.addShape(pres.shapes.OVAL, { x, y: y + 0.09, w: 0.16, h: 0.16, fill: { color }, line: { color } });
    T(s, t, { x: x + 0.3, y, w: w - 0.3, h: 0.62, fontSize: 15, color: C.text, valign: "top" });
  };
  const foot = (s) => T(s, "eth.blockid.au  ·  Testnet demo, not an offer of securities", { x: 0.55, y: 7.08, w: 12.2, h: 0.28, fontSize: 9.5, color: C.dim, align: "right" });

  const logo = await img("logo.png");
  const I = {
    hero: await img("01-home-hero.png", { height: 1800 }),
    wizard: await img("07-new-wizard-step1.png", { height: 1500 }),
    radar: await img("canva-report.png", { top: 122, height: 1540 }),
    agents: await img("08-valuation-agent-log.png", { height: 1300 }),
    tracker: await img("16c-company-pending-tracker-admin.png", { height: 1730 }),
    cards: await img("19-company-eba-contracts-qr.png"),
    ok: await img("22-verify-eba-verified.png", { height: 1250 }),
    bad: await img("24-verify-eba-tamper-mismatch.png", { height: 1250 }),
    admin: await img("28-admin-overview.png", { height: 1500 }),
  };

  // ============ 1. Hook
  let s = pres.addSlide(); s.background = { color: C.bg };
  s.addImage({ data: logo.data, x: 0.35, y: 0.35, w: 1.25, h: 1.25 });
  T(s, "BlockID Startup Passport", { x: 1.7, y: 0.72, w: 6, h: 0.5, fontFace: H, fontSize: 20, bold: true });
  T(s, "Know what your startup is worth, and who owns it.", { x: 0.55, y: 1.95, w: 5.6, h: 2.3, fontFace: H, fontSize: 40, bold: true });
  T(s, "Agents propose. Humans approve. Chains prove.", { x: 0.55, y: 4.35, w: 5.6, h: 0.5, fontSize: 20, italic: true, color: C.teal });
  T(s, "AI valuation you can audit + tokenised shares you can prove — for every startup.", { x: 0.55, y: 4.95, w: 5.4, h: 0.8, fontSize: 16, color: C.muted });
  T(s, "Sydney Hackathon · Real-World Ethereum Apps · HashKey Chain (RWA)", { x: 0.55, y: 6.35, w: 5.8, h: 0.35, fontSize: 12, bold: true, color: C.gold });
  shot(s, I.hero, 6.55, 1.2, 6.25);
  foot(s);
  s.addNotes("[0:00–0:20] Every startup has two questions it can't answer cheaply: what are we worth, and who exactly owns us? BlockID answers both. Agents propose, humans approve, chains prove.");

  // ============ 2. Problem → solution
  s = pres.addSlide(); s.background = { color: C.bg };
  head(s, 2, "Problem → solution", "Website in. Cited valuation and verified cap table out.");
  rr(s, 0.55, 1.75, 5.1, 2.35, C.card);
  T(s, "TODAY", { x: 0.85, y: 1.95, w: 3, h: 0.3, fontSize: 11.5, bold: true, color: C.red, charSpacing: 3 });
  point(s, 0.85, 2.35, 4.6, "Cap tables in Excel — nobody can prove ownership", C.red);
  point(s, 0.85, 2.9, 4.6, "Valuations slow, costly and unsourced", C.red);
  point(s, 0.85, 3.45, 4.6, "Shareholders can't verify anything", C.red);
  rr(s, 0.55, 4.3, 5.1, 2.5, C.card2, C.teal);
  T(s, "WITH BLOCKID", { x: 0.85, y: 4.5, w: 3, h: 0.3, fontSize: 11.5, bold: true, color: C.teal, charSpacing: 3 });
  point(s, 0.85, 4.9, 4.6, "Minutes: AI valuation with every figure cited");
  point(s, 0.85, 5.45, 4.6, "One approval: KYC-gated shares on-chain");
  point(s, 0.85, 6.0, 4.6, "Anyone can verify, on three chains");
  shot(s, I.wizard, 6.1, 1.8, 6.7);
  foot(s);
  s.addNotes("[0:20–0:45] Today cap tables live in spreadsheets, valuations are slow and unsourced, and shareholders can't verify anything. With BlockID the founder pastes a website, gets a cited valuation in minutes, and after one approval has KYC-gated shares on-chain that anyone can verify.");

  // ============ 3. Architecture — the whole system at work
  s = pres.addSlide(); s.background = { color: C.bg };
  head(s, 3, "How it works", "Agents propose. Humans approve. Chains prove.", C.gold);
  const cols = [
    { x: 0.5, t: "FOUNDER", c: C.blue, ic: fa.FaUserTie, items: ["Pastes website", "Adds shareholders + wallets", "Optional revenue figures"] },
    { x: 2.62, t: "AI AGENTS", c: C.teal, ic: fa.FaRobot, items: ["Read site · ≤6 pages", "Competitors · ≤3 searches", "Market · cited only", "SVI formula → value"] },
    { x: 4.74, t: "HUMAN GATE", c: C.gold, ic: fa.FaUserCheck, items: ["Admin reviews", "Signs with own wallet", "One approval"] },
    { x: 6.86, t: "ISSUER", c: C.red, ic: fa.FaKey, items: ["Only key holder", "Isolated network", "Acts on approved rows"] },
    { x: 8.98, t: "3 CHAINS", c: C.purple, ic: fa.FaLink, items: ["BlockID EVM · gas 0", "Ethereum Hoodi", "HashKey testnet"] },
    { x: 11.1, t: "PROOF", c: C.teal, ic: fa.FaCircleCheck, items: ["Token in MetaMask", "/verify on 3 chains", "Dashboard · explorer"] },
  ];
  const top = 1.75, colW = 1.75, colH = 4.05;
  for (let i = 0; i < cols.length; i++) {
    const k = cols[i];
    rr(s, k.x, top, colW, colH, C.card, k.c);
    await dot(s, k.ic, k.x + colW / 2 - 0.33, top + 0.2, 0.66, k.c);
    T(s, k.t, { x: k.x, y: top + 0.95, w: colW, h: 0.35, fontFace: H, fontSize: 12.5, bold: true, color: k.c, align: "center" });
    k.items.forEach((it, j) => {
      const y = top + 1.42 + j * 0.62;
      rr(s, k.x + 0.12, y, colW - 0.24, 0.5, C.card2, C.line, 0.08);
      T(s, it, { x: k.x + 0.16, y, w: colW - 0.32, h: 0.5, fontSize: 10.5, color: C.text, align: "center", valign: "middle" });
    });
    if (i < cols.length - 1) arrow(s, k.x + colW + 0.03, top + 0.53, cols[i + 1].x - 0.03, top + 0.53, C.muted);
  }
  // trust boundary markers
  T(s, "no keys", { x: 2.62, y: top + colH + 0.08, w: colW, h: 0.3, fontSize: 10.5, color: C.teal, align: "center", italic: true });
  T(s, "4-eyes", { x: 4.74, y: top + colH + 0.08, w: colW, h: 0.3, fontSize: 10.5, color: C.gold, align: "center", italic: true });
  T(s, "AI can't reach it", { x: 6.86, y: top + colH + 0.08, w: colW, h: 0.3, fontSize: 10.5, color: C.red, align: "center", italic: true });
  T(s, "register → mirror → root", { x: 8.98, y: top + colH + 0.08, w: colW, h: 0.3, fontSize: 10.5, color: C.purple, align: "center", italic: true });
  rr(s, 0.5, 6.3, 12.35, 0.62, C.card2);
  T(s, [
    { text: "Under the hood  ", options: { bold: true, color: C.gold } },
    { text: "LLM: SambaNova → Claude → DeepInfra   ·   Search: Brave → Claude web search   ·   Postgres job queue   ·   Merkle cap-table roots in CapTableAnchor   ·   nginx + Cloudflare, CSP, SSRF-safe crawler", options: { color: C.muted } },
  ], { x: 0.75, y: 6.3, w: 11.9, h: 0.62, fontSize: 11.5, valign: "middle" });
  foot(s);
  s.addNotes("[0:45–1:15] The whole system on one slide. The founder gives a website and a shareholder list. AI agents read six pages, run three searches, and a fixed formula computes the value — the agents hold no keys. A human admin signs one approval. Only then does the isolated issuer, the only component with a key, create the register on our zero-gas chain and mirror it to Ethereum and HashKey. The proof: tokens in MetaMask, a verify page, a public explorer.");

  // ============ 4. Valuation
  s = pres.addSlide(); s.background = { color: C.bg };
  head(s, 4, "Auditable AI valuation", "AI scores. A fixed formula decides. Every figure is cited.");
  shot(s, I.radar, 0.55, 1.8, 8.35);
  rr(s, 9.25, 1.8, 3.55, 4.95, C.card);
  point(s, 9.5, 2.05, 3.2, "7 SVI dimensions, fixed public weights");
  point(s, 9.5, 2.85, 3.2, "Grade A–E → A$ low · mid · high");
  point(s, 9.5, 3.65, 3.2, "Uncited claims are dropped");
  point(s, 9.5, 4.45, 3.2, "Admin can override any AI score");
  T(s, "Canva: 9 competitors · ARR A$6B cited · 10.5x implied · A$64B mid", { x: 9.5, y: 5.35, w: 3.1, h: 1.2, fontSize: 13, color: C.gold, bold: true });
  foot(s);
  s.addNotes("[1:15–1:40] The AI only suggests scores. A fixed, public formula turns seven weighted dimensions into a grade and a valuation range, and any claim without a fetched source is dropped. For Canva it found nine real competitors, a cited ARR of A$6 billion and an implied multiple from its last round.");

  // ============ 5. Issuance
  s = pres.addSlide(); s.background = { color: C.bg };
  head(s, 5, "One approval", "One approval creates the register on three chains.");
  shot(s, I.tracker, 0.55, 1.8, 6.05);
  const ch = shot(s, I.cards, 6.95, 1.8, 5.85);
  const y5 = 1.8 + ch + 0.35;
  [["BlockID EVM", "register of record · gas 0", C.teal], ["Ethereum Hoodi", "paused mirror + Merkle root", C.blue], ["HashKey testnet", "paused mirror + Merkle root", C.gold]].forEach((c, i) => {
    const x = 6.95 + i * 1.98; rr(s, x, y5, 1.87, 1.05, C.card, c[2]);
    T(s, c[0], { x: x + 0.1, y: y5 + 0.12, w: 1.67, h: 0.35, fontFace: H, fontSize: 12.5, bold: true, color: c[2], align: "center" });
    T(s, c[1], { x: x + 0.1, y: y5 + 0.5, w: 1.67, h: 0.45, fontSize: 10.5, color: C.muted, align: "center" });
    if (i < 2) arrow(s, x + 1.88, y5 + 0.52, x + 1.97, y5 + 0.52, C.muted);
  });
  T(s, "Founder watches every step live; shareholders add the token to MetaMask on any chain.", { x: 6.95, y: y5 + 1.25, w: 5.85, h: 0.6, fontSize: 13.5, color: C.text });
  foot(s);
  s.addNotes("[1:40–2:05] One approval. The issuer creates the share register on our zero-gas chain — registry, KYC, shares — then mirrors it with a Merkle root to Ethereum Hoodi and HashKey. The founder watches every step live, and shareholders add the token to MetaMask.");

  // ============ 6. Verify
  s = pres.addSlide(); s.background = { color: C.bg };
  head(s, 6, "Proof", "Anyone can prove the report was never changed.");
  const vh = shot(s, I.ok, 0.55, 1.8, 5.95);
  shot(s, I.bad, 6.85, 1.8, 5.95);
  const yv = 1.8 + vh + 0.3;
  rr(s, 0.55, yv, 5.95, 0.55, C.card2, C.teal); T(s, "✓  Browser = server = on-chain on BlockID · Hoodi · HashKey", { x: 0.7, y: yv, w: 5.7, h: 0.55, fontSize: 13.5, bold: true, color: C.teal, valign: "middle" });
  rr(s, 6.85, yv, 5.95, 0.55, C.card2, C.red); T(s, "✗  Change one score → hash no longer matches", { x: 7.0, y: yv, w: 5.7, h: 0.55, fontSize: 13.5, bold: true, color: C.red, valign: "middle" });
  T(s, "Try it, no login: eth.blockid.au/verify/EBA", { x: 0.55, y: yv + 0.75, w: 12.2, h: 0.4, fontSize: 15, color: C.text });
  foot(s);
  s.addNotes("[2:05–2:25] You don't have to trust us. The verify page recomputes the report hash in your browser and compares it with the hash on all three chains. Change one score and it turns red.");

  // ============ 7. Results + who + ask
  s = pres.addSlide(); s.background = { color: C.bg };
  head(s, 7, "Live today", "Live today — and built for the people who issue equity.");
  const st = [["12", "companies tokenised"], ["36", "token contracts, 3 chains"], ["A$87B", "valuation on-chain"], ["12/12", "hashes verified"]];
  st.forEach((x, i) => {
    const X = 0.55 + i * 2.2; rr(s, X, 1.8, 2.05, 1.5, C.card);
    T(s, x[0], { x: X + 0.18, y: 1.88, w: 1.8, h: 0.75, fontFace: H, fontSize: 30, bold: true, color: i % 2 ? C.gold : C.teal });
    T(s, x[1], { x: X + 0.18, y: 2.65, w: 1.8, h: 0.55, fontSize: 12, color: C.muted });
  });
  shot(s, I.admin, 0.55, 3.6, 4.2);
  rr(s, 5.1, 3.6, 3.95, 3.15, C.card);
  T(s, "WHO BUYS", { x: 5.35, y: 3.75, w: 3, h: 0.3, fontSize: 11.5, bold: true, color: C.gold, charSpacing: 3 });
  ["Founders & SMEs (AU · VN)", "Accelerators & VCs", "Licensed CSF / transfer agents", "RWA ecosystems (HashKey)"].forEach((t, i) => point(s, 5.35, 4.15 + i * 0.52, 3.6, t, C.gold));
  T(s, "Fees: issuance · cap-table SaaS · transfers · dividends", { x: 5.35, y: 6.25, w: 3.6, h: 0.4, fontSize: 11.5, color: C.muted });
  rr(s, 9.35, 1.8, 3.45, 4.95, C.card2, C.teal);
  const qr = await QRCode.toBuffer("https://eth.blockid.au", { width: 600, margin: 1, color: { dark: "#0A1311", light: "#FFFFFF" } });
  s.addImage({ data: "image/png;base64," + qr.toString("base64"), x: 10.12, y: 2.05, w: 1.9, h: 1.9 });
  T(s, "Try it now", { x: 9.5, y: 4.1, w: 3.15, h: 0.45, fontFace: H, fontSize: 20, bold: true, align: "center" });
  T(s, "eth.blockid.au", { x: 9.5, y: 4.55, w: 3.15, h: 0.35, fontSize: 14, color: C.teal, align: "center", bold: true });
  T(s, "Looking for: pilot startups, accelerators, licensed partners", { x: 9.55, y: 5.05, w: 3.05, h: 0.8, fontSize: 12.5, color: C.text, align: "center" });
  T(s, "Long Do · long@blockid.au", { x: 9.5, y: 6.05, w: 3.15, h: 0.35, fontSize: 12, color: C.muted, align: "center" });
  foot(s);
  s.addNotes("[2:25–3:00] This is live today: twelve real companies, thirty-six token contracts on three chains, A$87 billion of valuation on-chain, every hash verified. Our full demo run took Canva from its website to a share register on three chains, a new round, a dividend and a shareholder transfer in eleven minutes. Our customers are founders, accelerators and licensed intermediaries who issue and administer startup equity. Scan the code and try it at eth.blockid.au — we're looking for pilot startups and licensed partners. Thank you.");

  await pres.writeFile({ fileName: "out/BlockID-Startup-Passport-3min.pptx" });
  console.log("written");
})();
