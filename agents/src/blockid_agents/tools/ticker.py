"""ASX-style 3-letter ticker suggestions.

Rules, in order of preference (each yields at most one candidate):
  initials    first letters of the first three words (names with 3+ words)
  first+two   first letter of word 1 + first two letters of word 2
  consonants  first letter + the next two consonants
  first3      first three letters
Corporate noise words (PTY, LTD, GROUP, ...) are dropped first. Offensive / reserved codes are
never suggested. `suggest` always returns exactly three candidates with their availability,
available ones first; when the rules run out, extra letter combinations from the name are used.
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from typing import Iterable

STOPWORDS = {"PTY", "LTD", "LIMITED", "THE", "GROUP", "HOLDINGS", "AUSTRALIA", "CO", "INC", "JSC", "VIETNAM",
             # Vietnamese legal forms: Cong ty (company), Co phan (joint stock), TNHH (LLC), MTV, Tap doan (group)
             "CONG", "TY", "PHAN", "TNHH", "MTV", "TAP", "DOAN"}
VOWELS = set("AEIOU")

BLOCKLIST = {
    # offensive / embarrassing
    "ASS", "CUM", "CUN", "DIC", "DIK", "DIE", "FAG", "FAP", "FCK", "FKU", "FUC", "FUK", "FUQ", "GAY", "GOD", "JEW",
    "KKK", "KYS", "NAZ", "NIG", "NGR", "PEE", "PIS", "POO", "POS", "PUS", "RAP", "SEX", "SHT", "SLT", "STD", "TIT",
    "TWT", "VAG", "WTF", "XXX", "HOE", "HOR", "LSD", "ISI", "SUX", "ANL", "BUM", "COC", "COK", "CUC", "DMN", "HEL",
    # reserved: currencies, chains, exchanges, platform names, test codes
    "AUD", "USD", "EUR", "GBP", "JPY", "CNY", "VND", "SGD", "NZD", "ETH", "BTC", "SOL", "BNB", "XRP", "USX",
    "ASX", "ASC", "SEC", "RBA", "ATO", "GOV", "BID", "BLK", "API", "NUL", "NIL", "NAN", "TST", "TES", "SYS",
    "ADM", "WWW", "DEV", "ROO", "ERR",
}

TICKER_RE = re.compile(r"^[A-Z]{3}$")


def _ascii_upper(text: str) -> str:
    text = text.replace("Đ", "D").replace("đ", "d")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()


DIGITS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]


def words(name: str) -> list[str]:
    # Digits become words ("Go1" -> GO ONE) so short brand names still yield letter-based codes.
    ws = [DIGITS[int(w)] if w.isdigit() else w for w in re.findall(r"[A-Z]+|[0-9]", _ascii_upper(name))]
    return [w for w in ws if w not in STOPWORDS]


def _rule_candidates(ws: list[str]) -> list[tuple[str, str]]:
    joined = "".join(ws)
    out: list[tuple[str, str]] = []
    if len(ws) >= 3:
        out.append(("".join(w[0] for w in ws[:3]), "initials"))
    if len(ws) >= 2 and len(ws[1]) >= 2:
        out.append((ws[0][0] + ws[1][:2], "first+two"))
    if joined:
        cons = [c for c in joined[1:] if c not in VOWELS]
        if len(cons) >= 2:
            out.append((joined[0] + "".join(cons[:2]), "consonants"))
    if len(joined) >= 3:
        out.append((joined[:3], "first3"))
    return out


def _fallback_candidates(ws: list[str]) -> Iterable[tuple[str, str]]:
    joined = "".join(ws) or "X"
    first, rest = joined[0], joined[1:]
    for a, b in itertools.combinations(range(len(rest)), 2):  # first letter + any two later letters, in order
        yield first + rest[a] + rest[b], "letters"
    for a, b in itertools.product("ABCDEFGHIJKLMNOPQRSTUVWXYZ", repeat=2):
        yield first + a + b, "variant"


def valid(ticker: str) -> bool:
    return bool(TICKER_RE.match(ticker)) and ticker not in BLOCKLIST


def suggest(name: str, taken: Iterable[str] = ()) -> list[dict]:
    taken_set = {t.upper() for t in taken}
    ws = words(name)
    seen: set[str] = set()
    ordered: list[tuple[str, str]] = []
    for t, rule in _rule_candidates(ws):
        if valid(t) and t not in seen:
            seen.add(t)
            ordered.append((t, rule))

    available = [(t, r) for t, r in ordered if t not in taken_set]
    unavailable = [(t, r) for t, r in ordered if t in taken_set]
    if len(available) < 3:
        for t, r in _fallback_candidates(ws):
            if valid(t) and t not in seen and t not in taken_set:
                seen.add(t)
                available.append((t, r))
                if len(available) >= 3:
                    break
    picked = (available + unavailable)[:3]
    return [{"ticker": t, "available": t not in taken_set, "rule": r} for t, r in picked]
