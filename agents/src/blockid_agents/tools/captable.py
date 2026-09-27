"""Initial cap table: percentages -> whole shares (decimals = 0).

Largest-remainder (Hamilton) allocation: every holder gets floor(pct * total / 100) shares, then the
leftover shares go one each to the largest fractional remainders (ties: input order). The result
always sums to exactly `total_shares`.
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from eth_utils import is_address, is_checksum_address, to_checksum_address

PCT_TOLERANCE = Decimal("0.005")


class CapTableError(ValueError):
    pass


def checksum(addr: str) -> str:
    """EIP-55: mixed-case input must carry a valid checksum; all-lower/upper input is normalised."""
    a = (addr or "").strip()
    if not is_address(a):
        raise CapTableError(f"not an EVM address: {addr!r}")
    body = a[2:]
    if body != body.lower() and body != body.upper() and not is_checksum_address(a):
        raise CapTableError(f"bad EIP-55 checksum (check for a typo): {addr!r}")
    if int(body, 16) == 0:
        raise CapTableError("the zero address is not a wallet")
    return to_checksum_address(a)


def validate(holders: list[dict]) -> list[dict]:
    if not holders:
        raise CapTableError("at least one holder is required")
    out, seen = [], set()
    total = Decimal(0)
    for h in holders:
        name = str(h.get("name", "")).strip()
        if not name:
            raise CapTableError("every holder needs a name")
        wallet = checksum(str(h.get("wallet", "")))
        if wallet in seen:
            raise CapTableError(f"duplicate wallet {wallet}")
        seen.add(wallet)
        try:
            pct = Decimal(str(h.get("pct")))
        except (InvalidOperation, TypeError):
            raise CapTableError(f"bad pct for {name}") from None
        if not pct.is_finite() or pct <= 0 or pct > 100:
            raise CapTableError(f"pct for {name} must be > 0 and <= 100")
        total += pct
        out.append({"name": name[:200], "wallet": wallet, "pct": pct})
    if abs(total - Decimal(100)) > PCT_TOLERANCE:
        raise CapTableError(f"percentages sum to {total}, must be 100.00")
    return out


def allocate(holders: list[dict], total_shares: int) -> list[dict]:
    """Validate and allocate. Returns [{name, wallet, pct, shares}] summing to total_shares."""
    if int(total_shares) <= 0:
        raise CapTableError("total_shares must be positive")
    total_shares = int(total_shares)
    hs = validate(holders)
    pct_sum = sum(h["pct"] for h in hs)  # normalise tiny rounding (e.g. 33.33 * 3)
    exact = [h["pct"] * total_shares / pct_sum for h in hs]
    base = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exact]
    left = total_shares - sum(base)
    order = sorted(range(len(hs)), key=lambda i: (-(exact[i] - base[i]), i))
    for i in order[:left]:
        base[i] += 1
    out = []
    for h, s in zip(hs, base):
        if s <= 0:
            raise CapTableError(f"{h['name']} would receive 0 shares — increase total_shares or pct")
        out.append({**h, "pct": float(h["pct"]), "shares": s})
    return out
