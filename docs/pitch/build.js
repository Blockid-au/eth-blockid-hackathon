// BlockID Startup Passport — 3-minute pitch deck (EAG Global Buildathon, Sydney, 26 Sep 2026)
const pptxgen = require("pptxgenjs");
const sharp = require("sharp");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const QRCode = require("qrcode");
const fa = require("react-icons/fa6");

// ---------- palette (from the BlockID brand: ink, eucalyptus, wattle gold)
const C = {
  bg: "0A1311", card: "12201D", card2: "172A26", line: "25403A",
  text: "F2F7F5", muted: "A9BDB7", dim: "7E948F",
  teal: "22A07F", tealDk: "0E6B55", gold: "E3A83A", red: "E4675A",
};
const H = "Arial", B = "Calibri";
const W = 13.333, HH = 7.5;

async function icon(Comp, color = "#FFFFFF", size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
async function crop(file, { top = 0, height, width } = {}) {
  const img = sharp(`img/${file}`); const m = await img.metadata();
  const w = width || m.width; const h = Math.min(height || m.height, m.height - top);
  const buf = await sharp(`img/${file}`).extract({ left: 0, top, width: w, height: h }).png().toBuffer();
  return { data: "image/png;base64," + buf.toString("base64"), ratio: w / h };
}
async function full(file) {
  const m = await sharp(`img/${file}`).metadata();
  const buf = await sharp(`img/${file}`).png().toBuffer();
  return { data: "image/png;base64," + buf.toString("base64"), ratio: m.width / m.height };
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.author = "Long Do — Auschain Pty Ltd";
  pres.company = "BlockID";
  pres.title = "BlockID Startup Passport — pitch";

  const txt = (s, t, o) => s.addText(t, { isTextBox: true, fontFace: B, color: C.text, margin: 0, ...o });
  const title = (s, t, sub) => {
    txt(s, t, { x: 0.6, y: 0.45, w: 12.1, h: 0.75, fontFace: H, fontSize: 32, bold: true });
    if (sub) txt(s, sub, { x: 0.6, y: 1.2, w: 12.1, h: 0.45, fontSize: 16, color: C.muted });
  };
  const card = (s, x, y, w, h, fill = C.card) =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: C.line, width: 0.75 }, rectRadius: 0.12 });
  const shot = (s, im, x, y, w) => {
    const h = w / im.ratio;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.04, y: y - 0.04, w: w + 0.08, h: h + 0.08, fill: { color: C.line }, line: { color: C.line }, rectRadius: 0.08,
      shadow: { type: "outer", color: "000000", blur: 12, offset: 4, angle: 90, opacity: 0.45 } });
    s.addImage({ data: im.data, x, y, w, h });
    return h;
  };
  const chip = (s, t, x, y, w, color = C.teal) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.36, fill: { color: C.card2 }, line: { color }, rectRadius: 0.18 });
    txt(s, t, { x, y, w, h: 0.36, fontSize: 11.5, color, align: "center", valign: "middle", bold: true });
  };
  const iconDot = async (s, Comp, x, y, d = 0.62, fill = C.teal) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill } });
    s.addImage({ data: await icon(Comp), x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52 });
  };
  const foot = (s, n) => txt(s, `BlockID Startup Passport · eth.blockid.au · Testnet demo, not an offer of securities   ${n}`,
    { x: 0.6, y: 7.05, w: 12.1, h: 0.3, fontSize: 9.5, color: C.dim, align: "right" });

  const logo = await full("logo.png");
  const linkedinCard = await full("linkedin-qr-card.png");
  const S = {
    hero: await crop("01-home-hero.png", { height: 1800 }),
    radar: await full("09-valuation-radar-contribution.png"),
    agents: await crop("08-valuation-agent-log.png", { height: 1552 }),
    tracker: await crop("15-company-arw-tracker-kpis.png", { height: 1730 }),
    cards: await full("19-company-eba-contracts-qr.png"),
    ok: await crop("22-verify-eba-verified.png", { height: 1560 }),
    bad: await crop("24-verify-eba-tamper-mismatch.png", { height: 1560 }),
    admin: await crop("28-admin-overview.png", { height: 1500 }),
    arch: await full("architecture.png"),
    scan: await crop("34-scan-eba-token-holders.png", { height: 1500 }),
  };

  // ===== 1. Hero
  let s = pres.addSlide(); s.background = { color: C.bg };
  s.addImage({ data: logo.data, x: 0.45, y: 0.95, w: 5.4, h: 5.4 });
  txt(s, "EAG GLOBAL BUILDATHON · SYDNEY · 26 SEP 2026", { x: 6.1, y: 1.0, w: 6.8, h: 0.35, fontSize: 12, color: C.gold, bold: true, charSpacing: 3 });
  txt(s, "Know what your startup is worth, and who owns it.", { x: 6.1, y: 1.45, w: 6.8, h: 2.05, fontFace: H, fontSize: 38, bold: true });
  txt(s, "Agents propose. Humans approve. Chains prove.", { x: 6.1, y: 3.6, w: 6.8, h: 0.45, fontSize: 20, italic: true, color: C.teal });
  txt(s, "AI values a startup from its website with every figure cited; one human approval issues KYC-gated shares on a zero-gas chain and anchors the cap table on Ethereum and HashKey Chain.",
    { x: 6.1, y: 4.15, w: 6.6, h: 1.1, fontSize: 15.5, color: C.muted });
  chip(s, "Sydney Hackathon", 6.1, 5.45, 1.95); chip(s, "Real-World Ethereum Apps", 8.15, 5.45, 2.55); chip(s, "HashKey Chain · RWA", 10.8, 5.45, 2.1, C.gold);
  txt(s, "eth.blockid.au   ·   github.com/Blockid-au/eth-blockid-hackathon", { x: 6.1, y: 6.05, w: 6.8, h: 0.35, fontSize: 13, color: C.text });
  s.addNotes("0:00–0:15. I'm Long Do, founder of BlockID. Our promise in one line: know what your startup is worth, and who owns it. Agents propose, humans approve, chains prove.");

  // ===== 2. Why
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "Why: startup equity still lives in spreadsheets", "Founders, investors and regulators all pay for it");
  const probs = [
    [fa.FaFileExcel, "Cap tables in Excel", "Share registers are emailed files. Nobody can prove who owns what, or when it changed."],
    [fa.FaMagnifyingGlassDollar, "Valuations are opaque", "Early-stage valuations are expensive, slow and rarely show their sources or maths."],
    [fa.FaEyeSlash, "Owners can't verify", "Investors trust PDFs. Dividends and new issuances are manual and error-prone."],
  ];
  for (let i = 0; i < 3; i++) {
    const x = 0.6 + i * 4.1; card(s, x, 1.95, 3.85, 3.2);
    await iconDot(s, probs[i][0], x + 0.35, 2.3, 0.75, i === 1 ? C.gold : C.teal);
    txt(s, probs[i][1], { x: x + 0.35, y: 3.25, w: 3.2, h: 0.5, fontFace: H, fontSize: 20, bold: true });
    txt(s, probs[i][2], { x: x + 0.35, y: 3.8, w: 3.2, h: 1.2, fontSize: 14.5, color: C.muted });
  }
  card(s, 0.6, 5.45, 12.1, 1.3, C.card2);
  txt(s, [{ text: "A$5.4bn", options: { fontFace: H, fontSize: 30, bold: true, color: C.gold } },
    { text: "   across ~390 Australian startup deals in 2025 — each needs a valuation and a share register.", options: { fontSize: 15.5, color: C.text } }],
    { x: 0.95, y: 5.6, w: 11.4, h: 0.7, valign: "middle" });
  txt(s, "Source: Cut Through Venture & Folklore, State of Australian Startup Funding 2025", { x: 0.95, y: 6.3, w: 11.4, h: 0.3, fontSize: 10, color: C.dim });
  foot(s, 2);
  s.addNotes("0:15–0:35. Why we built this: equity for small companies is still managed in spreadsheets; valuations are opaque; shareholders cannot verify anything. In Australia alone about A$5.4bn went into ~390 startup deals last year — every one needs this.");

  // ===== 3. Elevator pitch + 3 steps
  s = pres.addSlide(); s.background = { color: C.bg };
  txt(s, "ELEVATOR PITCH", { x: 0.6, y: 0.5, w: 6, h: 0.35, fontSize: 12, color: C.gold, bold: true, charSpacing: 3 });
  txt(s, "BlockID turns your company website into an evidence-cited valuation in minutes, then turns your shareholder list into a verified, KYC-gated cap table you can grow and pay dividends from — on-chain, with AI that never holds the keys.",
    { x: 0.6, y: 0.95, w: 12.1, h: 1.6, fontFace: H, fontSize: 23, bold: true });
  const steps = [
    [fa.FaRobot, "1 · Agents propose", "AI reads the website, finds competitors (3 searches), scores 7 SVI dimensions. A fixed formula computes the value; the report hash is recorded.", C.teal],
    [fa.FaUserCheck, "2 · Humans approve", "An admin with their own wallet reviews valuation and shareholders, and signs one approval. Agents have no keys and no route to the issuer.", C.gold],
    [fa.FaLink, "3 · Chains prove", "The isolated issuer creates the register on zero-gas BlockID EVM, then mirrors and anchors it on Ethereum Hoodi and HashKey Chain.", "5D8AD6"],
  ];
  for (let i = 0; i < 3; i++) {
    const x = 0.6 + i * 4.1; card(s, x, 2.85, 3.85, 3.65);
    await iconDot(s, steps[i][0], x + 0.35, 3.15, 0.8, steps[i][3]);
    txt(s, steps[i][1], { x: x + 0.35, y: 4.15, w: 3.2, h: 0.5, fontFace: H, fontSize: 20, bold: true, color: steps[i][3] });
    txt(s, steps[i][2], { x: x + 0.35, y: 4.7, w: 3.25, h: 1.7, fontSize: 14, color: C.muted });
    if (i < 2) txt(s, "→", { x: x + 3.85, y: 4.25, w: 0.25, h: 0.5, fontSize: 22, color: C.dim, align: "center" });
  }
  foot(s, 3);
  s.addNotes("0:35–0:55. The pitch: website in, cited valuation out; shareholder list in, verified on-chain cap table out. Three steps — agents propose, humans approve, chains prove.");

  // ===== 4. Architecture
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "How it works", "The only component with a key is an isolated issuer that acts on human-approved rows");
  { const w = 8.3; const h = w / S.arch.ratio; s.addImage({ data: S.arch.data, x: 0.6, y: 1.85, w, h }); }
  const archPts = [
    ["LangGraph agents", "least-privilege policy in code; LLM only scores"],
    ["Approval gates", "SIWE / admin session, atomic claims, audit log"],
    ["Isolated issuer", "own network; AI worker cannot reach it"],
    ["3 chains", "BlockID EVM 262626 · Hoodi 560048 · HashKey 133"],
  ];
  archPts.forEach((p, i) => {
    const y = 1.9 + i * 1.18; card(s, 9.15, y, 3.55, 1.02);
    txt(s, p[0], { x: 9.35, y: y + 0.12, w: 3.2, h: 0.35, fontFace: H, fontSize: 15, bold: true, color: i === 2 ? C.gold : C.teal });
    txt(s, p[1], { x: 9.35, y: y + 0.48, w: 3.2, h: 0.5, fontSize: 12.5, color: C.muted });
  });
  txt(s, "12 architecture diagrams in the repo: docs/ARCHITECTURE-DIAGRAMS.md", { x: 0.6, y: 6.62, w: 8.3, h: 0.3, fontSize: 11, color: C.dim });
  foot(s, 4);
  s.addNotes("0:55–1:10. Architecture: agents in a LangGraph pipeline with permissions enforced in code; human approval gates; an isolated issuer — the only key holder — on its own network; three chains. Full diagrams are in the repo.");

  // ===== 5. AI valuation
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "Auditable AI valuation", "LLM suggests scores · code computes · every figure links to a fetched source");
  shot(s, S.radar, 0.6, 1.95, 8.2);
  const valPts = [
    [fa.FaGlobe, "6 pages + 3 searches", "Bounded research budget: competitors, market, valuation benchmark"],
    [fa.FaCalculator, "Fixed SVI formula", "7 weighted dimensions → grade A–E → A$ low · mid · high"],
    [fa.FaQuoteRight, "Cited or dropped", "Findings citing a page the agent did not fetch are removed"],
  ];
  for (let i = 0; i < 3; i++) {
    const y = 1.95 + i * 1.45; await iconDot(s, valPts[i][0], 9.2, y + 0.05, 0.6);
    txt(s, valPts[i][1], { x: 9.95, y, w: 2.8, h: 0.4, fontFace: H, fontSize: 16, bold: true });
    txt(s, valPts[i][2], { x: 9.95, y: y + 0.42, w: 2.8, h: 0.85, fontSize: 12.5, color: C.muted });
  }
  txt(s, "Example: Airwallex → 8 competitors from search (Wise, Revolut, OFX, Payoneer…) → SVI 54.5 (C)", { x: 0.6, y: 6.35, w: 12.1, h: 0.35, fontSize: 13, color: C.gold });
  foot(s, 5);
  s.addNotes("1:10–1:35. The valuation: the agent reads six pages, runs exactly three searches, and scores seven SVI dimensions. The model only suggests scores; a fixed public formula computes the value, and anything not backed by a fetched source is dropped. For Airwallex it found eight real competitors from search.");

  // ===== 6. One approval → three chains
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "One approval → three chains", "Created on zero-gas BlockID EVM first, then synced to Ethereum and HashKey — live tracker for the founder");
  const th = shot(s, S.tracker, 0.6, 1.95, 6.3);
  shot(s, S.cards, 7.2, 1.95, 5.5);
  const cy = 1.95 + 5.5 / S.cards.ratio + 0.35;
  chip(s, "BlockID EVM · 262626 · gas 0", 7.2, cy, 2.75); chip(s, "Ethereum Hoodi · 560048", 10.05, cy, 2.65, "5D8AD6");
  chip(s, "HashKey Chain testnet · 133", 7.2, cy + 0.5, 2.75, C.gold); chip(s, "Add to MetaMask · QR", 10.05, cy + 0.5, 2.65, C.muted);
  txt(s, "Paused mirror token + Merkle root of the cap table on every chain; shareholders import the token and prove their balance.",
    { x: 7.2, y: cy + 1.05, w: 5.5, h: 0.8, fontSize: 13.5, color: C.muted });
  foot(s, 6);
  s.addNotes("1:35–2:00. One human approval. The issuer creates the register on our zero-gas chain — registry, token, KYC, shares — then mirrors it to Ethereum Hoodi and HashKey Chain. The founder watches every step live; shareholders add the token to MetaMask on any of the three chains.");

  // ===== 7. Verify
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "Anyone can verify it", "keccak256 of the report recomputed in the browser = server = on-chain on 3 chains. Change one score → mismatch.");
  const vh = shot(s, S.ok, 0.6, 1.95, 5.95);
  shot(s, S.bad, 6.75, 1.95, 5.95);
  const vy = 1.95 + vh + 0.3;
  chip(s, "✓ Verified on BlockID · Hoodi · HashKey", 0.6, vy, 3.6); chip(s, "✗ Tamper test: one score changed", 6.75, vy, 3.4, C.red);
  txt(s, "Try it: eth.blockid.au/verify/EBA — no login needed", { x: 0.6, y: vy + 0.6, w: 12.1, h: 0.4, fontSize: 15, color: C.text });
  foot(s, 7);
  s.addNotes("2:00–2:15. And you don't have to trust us: /verify recomputes the report hash in your browser and compares it with the hash stored on all three chains. Change a single score and it turns red.");

  // ===== 8. Results
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "What we shipped — live, not a mock-up", "https://eth.blockid.au · https://scan.blockid.au · HashKey testnet contracts");
  const stats = [["7", "companies tokenised\nfrom real websites"], ["21", "share-token contracts\non 3 chains"], ["A$444M", "marked valuation\nunder management"], ["100%", "report hashes verified\non every chain"]];
  stats.forEach((st, i) => {
    const x = 0.6 + i * 3.05; card(s, x, 1.9, 2.85, 1.85);
    txt(s, st[0], { x: x + 0.25, y: 2.0, w: 2.4, h: 0.95, fontFace: H, fontSize: 40, bold: true, color: i % 2 ? C.gold : C.teal });
    txt(s, st[1], { x: x + 0.25, y: 2.95, w: 2.45, h: 0.7, fontSize: 13, color: C.muted });
  });
  shot(s, S.admin, 0.6, 4.1, 5.0);
  const res = ["140+ automated tests (110 backend, 30 Foundry) · internal security review fixed", "Merkle dividends paid on-chain; relayer pays holders' gas", "Blockscout explorer + zero-gas Cosmos EVM chain we operate", "12 architecture diagrams · 39-screen feature gallery · open source (MIT)"];
  res.forEach((r, i) => txt(s, r, { x: 5.95, y: 4.15 + i * 0.66, w: 6.75, h: 0.6, fontSize: 14.5, bullet: true, color: C.text }));
  foot(s, 8);
  s.addNotes("2:15–2:35. Results: seven real companies tokenised from their websites, twenty-one share-token contracts across three chains, A$444M of marked valuation, every report hash verified. 140+ tests, a security review, dividends paid on-chain, our own zero-gas chain and explorer.");

  // ===== 9. Who buys it
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "Who buys it", "Start with the people who issue and administer startup equity");
  const buyers = [
    [fa.FaRocket, "Founders & SMEs (AU · VN)", "Valuation + share register + dividends without a law-firm bill"],
    [fa.FaSeedling, "Accelerators & VCs", "Portfolio cap tables, standard valuations, verifiable reporting"],
    [fa.FaHandshake, "CSF intermediaries & transfer agents", "Licensed partners who need compliant, auditable registers"],
    [fa.FaBuildingColumns, "RWA ecosystems (HashKey)", "Tokenised private equity as a compliant real-world asset"],
  ];
  for (let i = 0; i < 4; i++) {
    const x = 0.6 + (i % 2) * 6.1, y = 1.9 + Math.floor(i / 2) * 1.55; card(s, x, y, 5.9, 1.35);
    await iconDot(s, buyers[i][0], x + 0.3, y + 0.33, 0.7, i === 3 ? C.gold : C.teal);
    txt(s, buyers[i][1], { x: x + 1.2, y: y + 0.2, w: 4.5, h: 0.45, fontFace: H, fontSize: 17, bold: true });
    txt(s, buyers[i][2], { x: x + 1.2, y: y + 0.66, w: 4.5, h: 0.6, fontSize: 13.5, color: C.muted });
  }
  card(s, 0.6, 5.1, 12.1, 1.65, C.card2);
  txt(s, "REVENUE", { x: 0.9, y: 5.25, w: 3, h: 0.3, fontSize: 11, bold: true, color: C.gold, charSpacing: 3 });
  const rev = [["Issuance fee", "per company"], ["Cap-table SaaS", "annual"], ["Transfer agent", "per transfer"], ["Dividends", "0.5–1% per round"], ["Custody", "on AUM, via licensed partner"]];
  rev.forEach((r, i) => {
    const x = 0.9 + i * 2.4;
    txt(s, r[0], { x, y: 5.65, w: 2.3, h: 0.45, fontFace: H, fontSize: 16, bold: true });
    txt(s, r[1], { x, y: 6.1, w: 2.3, h: 0.45, fontSize: 12.5, color: C.muted });
  });
  foot(s, 9);
  s.addNotes("2:35–2:45. Who buys: founders and SMEs in Australia and Vietnam, accelerators and VCs, licensed crowd-funding intermediaries and transfer agents, and RWA ecosystems like HashKey. Revenue: issuance fees, cap-table SaaS, transfer-agent fees, a small share of dividend rounds, custody via partners.");

  // ===== 10. Trust & compliance
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "Built for trust and compliance", "Testnet today — designed for a licensed path");
  const trust = [
    [fa.FaKey, "Agents never hold keys", "Isolated issuer on its own network, acts only on atomically claimed, admin-approved rows"],
    [fa.FaIdCard, "KYC on every transfer", "ERC-3643-style IdentityRegistry: shares can only move to verified wallets"],
    [fa.FaShieldHalved, "Hardened platform", "SSRF-safe crawler, CSRF origin checks, CSP, RPC allowlist, rate limits"],
    [fa.FaScaleBalanced, "Regulatory path", "AU Digital Assets Framework (from Apr 2027), CSF / AFSL partner, audited ERC-3643"],
  ];
  for (let i = 0; i < 4; i++) {
    const y = 1.9 + i * 1.22; await iconDot(s, trust[i][0], 0.7, y + 0.1, 0.72, i === 3 ? C.gold : C.teal);
    txt(s, trust[i][1], { x: 1.65, y, w: 5.3, h: 0.45, fontFace: H, fontSize: 17, bold: true });
    txt(s, trust[i][2], { x: 1.65, y: y + 0.46, w: 5.3, h: 0.65, fontSize: 13, color: C.muted });
  }
  { const h = shot(s, S.scan, 7.1, 1.95, 5.6);
    txt(s, "Every share token is public on scan.blockid.au (Blockscout): holders, transfers, contract", { x: 7.1, y: 2.15 + h, w: 5.6, h: 0.5, fontSize: 11.5, color: C.dim }); }
  foot(s, 10);
  s.addNotes("Q&A backup. Trust: agents never hold keys; KYC is enforced on every transfer; the platform passed an internal security review; and the legal path runs through Australia's Digital Assets Framework and licensed CSF/AFSL partners.");

  // ===== 11. Roadmap
  s = pres.addSlide(); s.background = { color: C.bg };
  title(s, "Roadmap", "From hackathon to pilot");
  const road = [
    ["NOW · 2 weeks", C.teal, ["Safe 2-of-3 multisig for admin roles", "Invariant + Halmos CI for contracts", "On-chain monitoring and tracing", "Valuation eval / red-team harness"]],
    ["NEXT · Q4 2026", C.gold, ["Pilot with 5–10 AU & VN startups", "Real KYC (FrankieOne, VNPT/FPT eKYC)", "Calibrated multiples + backtests", "EAS valuation attestations"]],
    ["LATER · 2027", "5D8AD6", ["Licensed partner / Digital Assets Framework", "Audited ERC-3643 suite, HashKey mainnet", "Scoped agent permissions (7702 / 7579)", "ERC-8004 agent identity & reputation"]],
  ];
  road.forEach((r, i) => {
    const x = 0.6 + i * 4.1; card(s, x, 1.9, 3.85, 4.75);
    txt(s, r[0], { x: x + 0.3, y: 2.1, w: 3.3, h: 0.45, fontFace: H, fontSize: 17, bold: true, color: r[1] });
    txt(s, r[2].map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < r[2].length - 1 } })),
      { x: x + 0.3, y: 2.7, w: 3.35, h: 3.7, fontSize: 14, color: C.text, paraSpaceAfter: 10, valign: "top" });
  });
  foot(s, 11);
  s.addNotes("2:45–2:55. Next two weeks: multisig admin, stronger contract CI and monitoring. Q4: a pilot with 5–10 startups, real KYC and calibrated valuations. 2027: licensed partner, audited ERC-3643, HashKey mainnet.");

  // ===== 12. Team + ask
  s = pres.addSlide(); s.background = { color: C.bg };
  s.addImage({ data: logo.data, x: 0.45, y: 0.6, w: 2.4, h: 2.4 });
  txt(s, "Try it now.", { x: 3.1, y: 0.9, w: 9.5, h: 0.9, fontFace: H, fontSize: 40, bold: true });
  txt(s, "Know what your startup is worth, and who owns it.", { x: 3.1, y: 1.85, w: 9.5, h: 0.5, fontSize: 20, italic: true, color: C.teal });
  card(s, 0.6, 3.25, 7.3, 3.45);
  txt(s, "Long Do (Đỗ Văn Long)", { x: 0.9, y: 3.45, w: 4.6, h: 0.45, fontFace: H, fontSize: 19, bold: true });
  txt(s, "Founder & CEO, Auschain Pty Ltd (BlockID.au, StartupValueIndex.com)", { x: 0.9, y: 3.9, w: 4.6, h: 0.4, fontSize: 13, color: C.gold });
  const bio = ["23+ years in IT; founder of Vietnam Blockchain Corporation — 50+ blockchain projects, 45+ awards", "National-scale deployments: Agridential, CovidPass.vn (with Vietnam's Ministry of Health)", "DBA candidate, SSBM Geneva — thesis: the Startup Value Index (SVI)"];
  txt(s, bio.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < bio.length - 1 } })), { x: 0.9, y: 4.38, w: 4.5, h: 2.15, fontSize: 13, color: C.text, paraSpaceAfter: 7, valign: "top" });
  s.addImage({ data: linkedinCard.data, x: 5.65, y: 3.45, w: 2.05, h: 2.05 });
  txt(s, "Connect on LinkedIn", { x: 5.65, y: 5.65, w: 2.05, h: 0.3, fontSize: 11, color: C.teal, bold: true, align: "center" });
  txt(s, "Scan to connect with Long Do", { x: 5.65, y: 5.95, w: 2.05, h: 0.3, fontSize: 9.5, color: C.dim, align: "center" });
  card(s, 8.2, 3.25, 4.5, 3.45, C.card2);
  const qr = await QRCode.toBuffer("https://eth.blockid.au", { width: 600, margin: 1, color: { dark: "#0A1311", light: "#FFFFFF" } });
  s.addImage({ data: "image/png;base64," + qr.toString("base64"), x: 8.5, y: 3.5, w: 1.75, h: 1.75 });
  txt(s, "WE'RE LOOKING FOR", { x: 10.45, y: 3.5, w: 2.1, h: 0.3, fontSize: 10.5, bold: true, color: C.gold, charSpacing: 2 });
  txt(s, "Pilot startups, accelerators, licensed CSF partners, HashKey ecosystem support", { x: 10.45, y: 3.85, w: 2.1, h: 1.45, fontSize: 12.5, color: C.text });
  txt(s, [{ text: "eth.blockid.au", options: { breakLine: true, bold: true } }, { text: "scan.blockid.au", options: { breakLine: true } }, { text: "github.com/Blockid-au/eth-blockid-hackathon", options: { breakLine: true } }, { text: "long@blockid.au", options: { breakLine: true } }, { text: "linkedin.com/in/dovanlong", options: { hyperlink: { url: "https://www.linkedin.com/in/dovanlong", tooltip: "Long Do on LinkedIn" }, color: C.teal, bold: true } }],
    { x: 8.5, y: 5.35, w: 4.1, h: 1.3, fontSize: 12, color: C.text });
  foot(s, 12);
  s.addNotes("2:55–3:00. Try it now at eth.blockid.au — the QR code takes you there. We're looking for pilot startups, accelerators and licensed partners. Thank you.");

  await pres.writeFile({ fileName: "out/BlockID-Startup-Passport-pitch.pptx" });
  console.log("written");
})();
