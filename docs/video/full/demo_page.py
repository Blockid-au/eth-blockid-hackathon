#!/usr/bin/env python3
"""Write web/app/public/deck/demo.html (video, clickable chapters, Why BlockID, Join us, links) from chapters-3min.txt."""
import html, os
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "..", "web", "app", "public", "deck", "demo.html")
ch = [l.split("\t") for l in open(os.path.join(HERE, "chapters-3min.txt")).read().splitlines()]
DUR3, DURF = os.environ.get("DUR3", "2:58"), os.environ.get("DURF", "5:15")
def secs(t): m, s = t.split(":"); return int(m) * 60 + int(s)
items = "\n".join(f'<li><button type="button" data-t="{secs(t)}"><span class="t">{t}</span><span><b>{html.escape(lab)}</b><br>{html.escape(msg)}</span></button></li>' for t, lab, msg in ch)
why = [
 ("A measurable pain", "Private-equity investors got back only 11% of NAV in 2024, a ten-year low (Bain). After investing, holders of private businesses lose sight of value, dilution and dividends."),
 ("A large, growing market", "Alternative assets head to $32T by 2030 (Preqin); tokenised assets to $5.5T by 2030 (Citi); on-chain real-world assets grew 5.9× in 19 months to $38.7B (rwa.xyz)."),
 ("People decide, records prove", "Research tools draft but never hold keys; a named person approves every valuation, new share and dividend, and no one can approve their own request; every step is recorded on chain, and anyone can re-check a report on 3 chains in their browser."),
 ("Investor-first, compliance-ready", "A live share register (already a legal duty in Australia and Vietnam), scheduled updates, dilution shown first, gasless dividends, and a custody model ready for MiCA, Vietnam's 2025 pilot and Australia's Digital Assets Framework."),
 ("Execution", "The whole flow runs end to end on testnet (14 sample listings, 42 token contracts, 552 Python + 37 Solidity tests), built in house by two former CTOs of major Vietnamese corporations on Australia's Global Talent visa, with a tech team in Vietnam and a business team in Sydney. No real users yet: pilots are next."),
]
join = [
 ("Ethereum investors", "Back our first pilots in Australia and Vietnam: real businesses and real shareholders on Ethereum rails."),
 ("L1 and L2 teams", "Run BlockID on your chain as a working real-world-asset case: share registers, updates, dividends and public checks. EVM-native, already live on BlockID Chain, Ethereum and HashKey Chain."),
 ("Licensed partners", "Custody, offerings and transfer services, so investors keep their rights and their proof."),
]
li = lambda xs: "\n".join(f"<li><b>{html.escape(a)}.</b> {html.escape(b)}</li>" for a, b in xs)
page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BlockID Business Passport · Demo</title>
<meta name="description" content="{DUR3} demo of BlockID Business Passport: know the business you invest in.">
<link rel="icon" href="/favicon.svg">
<style>
:root{{--bg:#0A1311;--card:#12201D;--line:#25403A;--text:#F2F7F5;--muted:#A9BDB7;--dim:#7E948F;--teal:#22A07F;--mint:#7FE0C2;--gold:#E3A83A}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}}
.wrap{{max-width:1280px;margin:0 auto;padding:28px 16px 48px}}a{{color:var(--mint)}}
header{{display:flex;align-items:center;gap:12px;margin-bottom:18px}}header img{{width:40px;height:40px}}header b{{font-size:18px}}
.eyebrow{{color:var(--teal);letter-spacing:.2em;font-size:12px;font-weight:700;text-transform:uppercase}}
h1{{font-size:clamp(28px,4.5vw,44px);line-height:1.15;margin:6px 0 10px}}h1 span{{color:var(--mint)}}
.lead{{color:var(--muted);max-width:820px;margin:0 0 22px}}
video{{width:100%;border-radius:12px;border:1px solid var(--line);background:#000;display:block}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:18px}}
.chap{{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:6px}}
.chap button{{all:unset;cursor:pointer;display:flex;gap:10px;width:100%;padding:8px;border-radius:8px;color:var(--muted);font-size:14px}}
.chap button:hover,.chap button:focus-visible{{background:#172A26;color:var(--text);outline:2px solid var(--line)}}.chap b{{color:var(--text)}}
.t{{color:var(--gold);font-variant-numeric:tabular-nums;min-width:38px;font-weight:700}}
h2{{font-size:22px;margin:30px 0 12px}}ol.why,ul.join{{margin:0;padding-left:22px}}ol.why li,ul.join li{{margin:0 0 10px;color:var(--muted)}}ol.why b,ul.join b{{color:var(--text)}}
.links{{display:flex;flex-wrap:wrap;gap:10px}}.links a{{display:inline-block;padding:9px 14px;border:1px solid var(--line);border-radius:8px;background:var(--card);text-decoration:none}}
.links a.primary{{background:var(--teal);color:#fff;border-color:var(--teal)}}
footer{{color:var(--dim);font-size:13px;margin-top:34px}}
</style></head><body><div class="wrap">
<header><img src="/logo-mark-transparent.png" alt=""><b>BlockID Business Passport</b></header>
<div class="eyebrow">EAG Global Buildathon · Demo video ({DUR3})</div>
<h1>Know the business <span>you invest in.</span></h1>
<p class="lead">A live, checked view of every business you own: updates and valuations approved by people, a share register on blockchain as proof of ownership, and dividends paid straight to your wallet. Every app scene in the video is a live recording of eth.blockid.au on testnet (sample data).</p>
<video id="v" controls preload="metadata" playsinline poster="/deck/demo-poster.png">
<source src="/deck/blockid-business-passport-demo-3min-captions.mp4" type="video/mp4"></video>
<p style="color:var(--dim);font-size:13px;margin:8px 0 0">Captions burned in · <a href="/deck/blockid-business-passport-demo-3min.mp4">clean video</a> · <a href="/deck/blockid-business-passport-demo-3min.srt">captions file</a> · <a href="/deck/blockid-business-passport-full-demo-captions.mp4">full walkthrough ({DURF})</a></p>
<div class="card"><div class="eyebrow" style="margin-bottom:8px">Chapters</div><ol class="chap">
{items}
</ol></div>
<h2>Why BlockID</h2>
<ol class="why">
{li(why)}
</ol>
<h2>Join us: a real app, ready to run on your chain</h2>
<ul class="join">
{li(join)}
</ul>
<h2>Deck, script and sources</h2>
<div class="links">
<a class="primary" href="https://eth.blockid.au">Try the app (no sign-up)</a>
<a href="/deck/BlockID-Business-Passport-3min.pdf">Pitch deck (PDF)</a>
<a href="/deck/BlockID-Business-Passport-3min.pptx">Pitch deck (PPTX)</a>
<a href="https://github.com/Blockid-au/eth-blockid-hackathon/blob/main/docs/VIDEO-SCRIPT.md">Video script and timestamps</a>
<a href="https://github.com/Blockid-au/eth-blockid-hackathon/blob/main/docs/MARKET-EVIDENCE.md">Market evidence (sources)</a>
<a href="https://github.com/Blockid-au/eth-blockid-hackathon">Source code (MIT)</a>
<a href="https://devfolio.co/projects/blockid-startup-passport-5dc5">Devfolio submission</a>
</div>
<footer>Testnet demo. Not an offer of securities or financial advice. 14 sample listings are built from public information, not customers; no real users yet. Contact: admin@blockid.au</footer>
</div>
<script src="/deck/demo.js" defer></script>
</body></html>
"""
open(OUT, "w").write(page)
print("written", os.path.normpath(OUT))
