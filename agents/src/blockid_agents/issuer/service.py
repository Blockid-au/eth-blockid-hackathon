"""Issuer operations. Each public method processes ONE admin-approved DB row and records every tx in studio.events.

Chains: `local` = BlockID Chain (262626, events.chain='blockid'); external sync targets, in this order:
`hoodi` = Ethereum Hoodi (560048, 'hoodi') and `hsk` = HashKey Chain testnet (133, 'hsk').
ONE admin approval (`issue`) runs the whole chain: issue on BlockID Chain, then mirror + anchor the cap table on
every external target. Per-chain progress lives in studio.companies.sync (see syncstate.py); `anchor` re-runs only
the chains that are missing or failed. All operations are idempotent enough to be retried after a failure (contracts already deployed are reused,
shares already issued are not issued twice, claims already paid are skipped).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from dataclasses import dataclass

from web3 import Web3

from . import syncstate
from .chain import Chain, Receipt
from .config import IssuerConfig
from .merkle import build_tree

log = logging.getLogger(__name__)

LOCAL, HOODI, HSK = "blockid", "hoodi", "hsk"
_KEEP = object()


class InsufficientFunds(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    """An external chain the BlockID cap table is mirrored to and anchored on."""
    key: str                 # 'hoodi' | 'hsk' (= events.chain)
    chain: Chain
    anchor: str              # CapTableAnchor address on that chain
    currency: str = "ETH"

    @property
    def cols(self) -> dict[str, str]:
        return syncstate.COLUMNS[self.key]

    @property
    def label(self) -> str:
        return syncstate.LABELS[self.key]

    @property
    def mirrored_kind(self) -> str:
        return f"{self.key}_mirrored"


def _iso() -> str:
    return datetime.now(UTC).isoformat()


def _units(wei: int) -> str:
    return f"{wei / 1e18:.6f}".rstrip("0").rstrip(".")
YEAR = 365 * 24 * 3600
CLAIM_WINDOW = 30 * 24 * 3600


def k(text: str) -> bytes:
    return Web3.keccak(text=text)


def cs(addr: str) -> str:
    return Web3.to_checksum_address(addr)


def _cents(mark: Any) -> int:
    return int((Decimal(str(mark)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"[:1000]


class Service:
    def __init__(self, cfg: IssuerConfig, store, local: Chain, hoodi: Chain | None = None,
                 relayer: Chain | None = None, hsk: Chain | None = None):
        self.cfg, self.store, self.local, self.hoodi, self.hsk = cfg, store, local, hoodi, hsk
        self.relayer = relayer or local  # relayer signer on the local chain (claimFor)
        self.targets: dict[str, Target] = {}
        if hoodi is not None and cfg.hoodi_captable_anchor:
            self.targets[HOODI] = Target(HOODI, hoodi, cfg.hoodi_captable_anchor, "ETH")
        if hsk is not None and cfg.hsk_captable_anchor:
            self.targets[HSK] = Target(HSK, hsk, cfg.hsk_captable_anchor, "HSK")
        self._busy: set[str] = set()  # one job per company / mint / dividend at a time (duplicate POSTs are no-ops)
        self._busy_lock = threading.Lock()

    @contextmanager
    def _exclusive(self, key: str):
        with self._busy_lock:
            if key in self._busy:
                log.warning("%s already in progress; duplicate request ignored", key)
                yield False
                return
            self._busy.add(key)
        try:
            yield True
        finally:
            with self._busy_lock:
                self._busy.discard(key)

    def _landed_issue(self, token, ref: bytes, from_block: int) -> Receipt | None:
        """A SharesIssued log with this resolution ref already on chain? (retry after an ambiguous failure)"""
        try:
            logs = token.events.SharesIssued().get_logs(from_block=max(0, int(from_block or 0)),
                                                         argument_filters={"resolutionRef": ref})
        except Exception:  # noqa: BLE001 - cannot tell -> caller must not re-send blindly
            log.exception("SharesIssued lookup failed")
            raise
        if not logs:
            return None
        lg = logs[-1]
        return Receipt(tx_hash=Web3.to_hex(lg["transactionHash"]), block=int(lg["blockNumber"]), status=1, gas_used=0,
                       contract_address=None, logs=[])

    @classmethod
    def from_env(cls, cfg: IssuerConfig | None = None) -> Service:
        from .keys import load_account
        from .store import Store

        cfg = cfg or IssuerConfig()
        pw_dir = cfg.keystore_password_dir or cfg.keystore_dir
        deployer = load_account(cfg.deployer_account, cfg.keystore_dir, pw_dir)
        local = Chain(LOCAL, cfg.local_rpc_url, cfg.local_chain_id, deployer, min_gas_price=cfg.local_min_gas_price)
        hoodi = Chain(HOODI, cfg.hoodi_rpc_url, cfg.hoodi_chain_id, deployer) if cfg.hoodi_rpc_url else None
        hsk = (Chain(HSK, cfg.hsk_rpc_url, cfg.hsk_chain_id, deployer, min_gas_price=cfg.hsk_min_gas_price,
                     read_lag_s=float(os.environ.get("HSK_READ_LAG_S", "3")))
               if cfg.hsk_rpc_url else None)
        try:
            relayer = local.with_account(load_account(cfg.relayer_account, cfg.keystore_dir, pw_dir))
        except FileNotFoundError:
            log.warning("relayer keystore missing; deployer will submit claimFor")
            relayer = None
        store = Store(cfg.database_url)
        store.migrate()
        return cls(cfg, store, local, hoodi, relayer, hsk)

    # ================================================================== helpers
    def _event(self, company_id, kind, chain=None, rec: Receipt | None = None, **data) -> None:
        self.store.add_event(company_id, kind, chain, rec.tx_hash if rec else None, rec.block if rec else None, data)

    def _now(self, chain: Chain) -> int:
        try:
            return max(int(time.time()), int(chain.w3.eth.get_block("latest")["timestamp"]))
        except Exception:  # noqa: BLE001
            return int(time.time())

    def _key(self, ch: Chain) -> str:
        return ch.name if ch.name in (LOCAL, HOODI, HSK) else LOCAL

    def _deployed(self, ch: Chain, cid, contract: str, rec: Receipt | None, address: str) -> None:
        if rec is not None and cid is not None:
            self._event(cid, "deployed", self._key(ch), rec, contract=contract, address=address)

    def _ensure_registry(self, ch: Chain, addr: str | None, save, cid=None) -> Any:
        if addr:
            reg = ch.contract("IdentityRegistry", addr)
        else:
            reg, rec = ch.deploy("IdentityRegistry", ch.address)
            save(reg.address)
            self._deployed(ch, cid, "IdentityRegistry", rec, reg.address)
        role = reg.functions.KYC_AGENT_ROLE().call()
        if not reg.functions.hasRole(role, ch.address).call():
            ch.transact(reg.functions.grantRole(role, ch.address))
        return reg

    def _ensure_token(self, ch: Chain, c: dict, reg, addr: str | None, save) -> tuple[Any, Receipt | None]:
        if addr:
            return ch.contract("BlockIDShareToken", addr), None
        params = (
            c["name"], c["ticker"], c["name"], "", "ORD", reg.address, ch.address, ch.address, 0,
            self.cfg.max_shareholders, k(f"studio-company:{c['id']}:{c.get('valuation_id') or ''}"),
        )
        token, rec = ch.deploy("BlockIDShareToken", params)
        save(token.address)
        self._deployed(ch, c["id"], "BlockIDShareToken", rec, token.address)
        return token, rec

    def _kyc(self, ch: Chain, reg, wallet: str, name: str, company_id: int | None, record: bool = True) -> Receipt | None:
        if reg.functions.isVerified(cs(wallet)).call():
            return None
        exp = self._now(ch) + YEAR
        rec = ch.transact(reg.functions.registerInvestor(cs(wallet), self.cfg.kyc_country, exp, k(name)))
        if record:
            self._event(company_id, "kyc", self._key(ch), rec, wallet=cs(wallet), name=name, registry=reg.address)
        return rec

    def _drip_if_needed(self, wallet: str, company_id: int | None) -> Receipt | None:
        if self.local.balance(wallet) >= self.cfg.drip_below_wei:
            return None
        rec = self.local.transfer(cs(wallet), self.cfg.drip_wei)
        self._event(company_id, "drip", LOCAL, rec, wallet=cs(wallet), amount_wei=str(self.cfg.drip_wei))
        return rec

    @staticmethod
    def _targets(holders: list[dict]) -> dict[str, dict]:
        """wallet(lower) -> {wallet, name, shares} (duplicate wallets summed)."""
        out: dict[str, dict] = {}
        for h in holders:
            w = h["wallet"].lower()
            e = out.setdefault(w, {"wallet": cs(h["wallet"]), "name": h["name"], "shares": 0})
            e["shares"] += int(h["shares"])
        return out

    def _fail_company(self, company_id: int, e: BaseException, set_status: bool = True) -> None:
        log.exception("company %s failed", company_id)
        try:
            if set_status:
                self.store.update_company(company_id, status="failed", error=_err(e))
            else:
                self.store.update_company(company_id, error=_err(e))
        except Exception:
            log.exception("could not record failure for company %s", company_id)

    # ------------------------------------------------------------------ sync state (studio.companies.sync)
    def _sync(self, cid: int, *, errors: dict | None = None, clear: tuple = (), step: Any = _KEEP, **fields) -> dict:
        """Read-modify-write of the sync dict (the issuer is its only writer; jobs are serialised)."""
        try:
            c = self.store.company(cid) or {}
            s = syncstate.view(c)
            s.update(fields)
            for key in clear:
                s["errors"].pop(key, None)
            if errors:
                s["errors"].update(errors)
            if step is not _KEEP:
                s["step"] = ({**step, "at": _iso()} if step else None)
            s["updated_at"] = _iso()
            self.store.update_company(cid, sync=s)
            return s
        except Exception:  # noqa: BLE001 - progress reporting must never break an issuance
            log.exception("sync state update failed for company %s", cid)
            return {}

    def _step(self, cid: int, chain: str, action: str, n: int | None = None, of: int | None = None) -> None:
        self._sync(cid, step={"chain": chain, "action": action, "n": n, "of": of})

    def _report_hash(self, c: dict) -> bytes:
        """keccak256 of the canonical valuation report (studio/report_hash.py); stored on the company row."""
        if c.get("valuation_report_hash"):
            return bytes.fromhex(c["valuation_report_hash"][2:])
        vid = c.get("valuation_id")
        row = self.store.valuation(vid) if vid and hasattr(self.store, "valuation") else None
        if row:
            from ..studio.report_hash import report_hash_from_row

            h = report_hash_from_row(row)
            self.store.update_company(c["id"], valuation_report_hash=h)
            c["valuation_report_hash"] = h
            return bytes.fromhex(h[2:])
        log.warning("company %s: valuation %s not found; anchoring keccak(valuation id)", c["id"], vid)
        return k(str(vid or ""))

    # ================================================================== issue (BlockID Chain) -> sync all chains
    def issue(self, company_id: int) -> None:
        """ONE admin approval: issue on BlockID Chain, then mirror + anchor on Hoodi and HSK (no second gate)."""
        with self._exclusive(f"company:{company_id}") as ok:
            if not ok:
                return
            c = self.store.company(company_id)  # re-read inside the lock: status is the source of truth
            if not c:
                raise LookupError(f"company {company_id} not found")
            if c["status"] != "issuing":
                log.warning("issue: company %s is %s, expected issuing; skipped", company_id, c["status"])
                return
            self._sync(company_id, blockid="running", clear=(LOCAL,), started_at=_iso(), finished_at=None,
                       step={"chain": LOCAL, "action": "start"})
            try:
                self._issue(c)
            except Exception as e:  # noqa: BLE001
                self._fail_company(company_id, e)
                self._sync(company_id, blockid="failed", errors={LOCAL: _err(e)}, step=None, finished_at=_iso())
                return
            self._sync(company_id, blockid="done")
            self._sync_external(company_id, list(syncstate.EXTERNAL))

    def _issue(self, c: dict) -> None:
        cid, L, st = c["id"], self.local, self.store
        self._step(cid, LOCAL, "deploy_registry")
        reg = self._ensure_registry(L, c.get("local_registry"), lambda a: st.update_company(cid, local_registry=a), cid)
        self._step(cid, LOCAL, "deploy_token")
        token, _ = self._ensure_token(L, c, reg, c.get("local_token"), lambda a: st.update_company(cid, local_token=a))
        if not c.get("local_distributor"):
            self._step(cid, LOCAL, "deploy_distributor")
            dist, rec = L.deploy("DividendDistributor", token.address, L.address)
            st.update_company(cid, local_distributor=dist.address)
            self._deployed(L, cid, "DividendDistributor", rec, dist.address)

        last: Receipt | None = None
        ref = k(f"studio-issue:{cid}")
        holders = list(self._targets(st.holders(cid)).values())
        for i, h in enumerate(holders, 1):
            self._step(cid, LOCAL, "kyc", i, len(holders))
            self._kyc(L, reg, h["wallet"], h["name"], cid)
            self._drip_if_needed(h["wallet"], cid)
            have = token.functions.balanceOf(h["wallet"]).call()
            if have < h["shares"]:
                self._step(cid, LOCAL, "mint", i, len(holders))
                last = L.transact(token.functions.issue(h["wallet"], h["shares"] - have, ref))
                self._event(cid, "issued", LOCAL, last, wallet=h["wallet"], name=h["name"],
                            shares=h["shares"] - have, token=token.address, n=i, of=len(holders))

        self._step(cid, LOCAL, "anchor_valuation")
        mark = Decimal(str(c.get("share_price_aud") or 1))
        cents = _cents(mark)
        rh = self._report_hash(c)
        rec = L.transact(token.functions.anchorValuation(rh, cents))
        self._event(cid, "valuation_anchored", LOCAL, rec, mark_aud=str(mark), per_share_cents=cents,
                    valuation_aud=str(c["valuation_aud"]), valuation_id=c.get("valuation_id"),
                    report_hash="0x" + rh.hex())
        lm = st.latest_mark(cid)
        if not lm or lm.get("source") != "issuance":
            st.add_mark(cid, c["valuation_aud"], mark, "issuance", c.get("valuation_id"))
        st.update_company(cid, local_block=(last or rec).block, status="issued", error=None)

    # ================================================================== external chains (mirror + CapTableAnchor)
    def anchor(self, company_id: int) -> None:
        """Admin retry / re-sync: runs only the external chains that are missing or failed."""
        with self._exclusive(f"company:{company_id}") as ok:
            if ok:
                self._anchor_locked(company_id)

    def _anchor_locked(self, company_id: int) -> None:
        c = self.store.company(company_id)
        if not c:
            raise LookupError(f"company {company_id} not found")
        if c["status"] != "anchoring":
            log.warning("anchor: company %s is %s, expected anchoring; skipped", company_id, c["status"])
            return
        if not c.get("local_token"):
            self._fail_company(company_id, RuntimeError("company has no BlockID Chain token (not issued)"))
            return
        todo = syncstate.missing(c)
        self._sync(company_id, started_at=_iso(), finished_at=None)
        self._sync_external(company_id, todo)

    def _sync_external(self, cid: int, chains: list[str]) -> None:
        """Sync the given external chains in order (Hoodi, then HSK); a failing chain never blocks the next one."""
        self.store.update_company(cid, status="anchoring", error=None)
        for key in syncstate.EXTERNAL:
            if key in chains:
                self._sync_one(cid, key)
        self._finish(cid)

    def _finish(self, cid: int) -> None:
        s = self._sync(cid, step=None, finished_at=_iso())
        c = self.store.company(cid) or {}
        s = s or syncstate.view(c)
        errs = s.get("errors") or {}
        err = "; ".join(f"{syncstate.LABELS.get(ch, ch)}: {e}" for ch, e in errs.items() if e) or None
        self.store.update_company(cid, status=syncstate.overall(s), error=err[:1000] if err else None)

    def _sync_one(self, cid: int, key: str) -> None:
        t = self.targets.get(key)
        if t is None:
            env = "HOODI" if key == HOODI else "HSK"
            msg = f"{syncstate.LABELS[key]} is not configured ({env}_RPC_URL / {env}_CAPTABLE_ANCHOR)"
            self._sync(cid, **{key: "skipped"}, errors={key: msg})
            self._event(cid, "sync_skipped", key, error=msg)
            return
        self._sync(cid, **{key: "running"}, clear=(key,), step={"chain": key, "action": "check_balance"})
        self._event(cid, "sync_started", key, chain_id=t.chain.chain_id)
        try:
            c = self.store.company(cid)
            self._preflight(t, c)
            self._sync_and_anchor(c, t)
        except Exception as e:  # noqa: BLE001 - recorded per chain; the other chains still run
            log.exception("company %s: %s sync failed", cid, key)
            self._sync(cid, **{key: "failed"}, errors={key: _err(e)})
            self._event(cid, "sync_failed", key, error=_err(e)[:500])
            return
        self._sync(cid, **{key: "done"})

    def _preflight(self, t: Target, c: dict) -> None:
        ch = t.chain
        ch.check_chain_id()
        n = len(self.store.holders(c["id"])) + 1
        units = (self.cfg.sync_gas_existing if c.get(t.cols["token"]) else self.cfg.sync_gas_fresh) \
            + self.cfg.sync_gas_per_holder * n
        need = units * ch.expected_gas_price()
        have = ch.balance(ch.address)
        if have < need:
            raise InsufficientFunds(
                f"issuer {ch.address} has {_units(have)} {t.currency} on {t.label}, needs about {_units(need)} "
                f"{t.currency} ({units:,} gas); top up the issuer wallet and retry")

    def reanchor(self, company_id: int) -> None:
        """After a mint / revaluation: refresh every external mirror that was synced and anchor a new root."""
        c = self.store.company(company_id)
        if not c or not c.get("local_token"):
            return
        if c["status"] not in ("anchored", "partially_anchored"):
            try:  # no mirror to refresh yet, but keep the studio cap table equal to the chain
                self.snapshot(c)
            except Exception as e:  # noqa: BLE001
                log.warning("reanchor %s: holder reconcile failed: %s", company_id, e)
            return
        s = syncstate.view(c)
        chains = [ch for ch in syncstate.EXTERNAL if s[ch] == "done"]
        if not chains:
            return
        for key in chains:
            self._sync_one(company_id, key)
        self._finish(company_id)

    LOG_CHUNK = 5_000  # the BlockID RPC rejects eth_getLogs ranges over 10,000 blocks
    _seen_wallets: dict[int, set[str]] = {}  # company id -> every wallet seen by the last snapshot

    def refresh(self, company_id: int) -> None:
        """Admin "Refresh from chain": rebuild studio.holders from BlockID Chain balances, clear the error, then
        re-sync every external chain (mirror balances + new Merkle root). Safe to run any time; idempotent."""
        with self._exclusive(f"company:{company_id}") as ok:
            if not ok:
                return
            c = self.store.company(company_id)
            if not c or not c.get("local_token"):
                log.warning("refresh: company %s is not issued on BlockID Chain; skipped", company_id)
                return
            try:
                _, balances, supply = self.snapshot(c)  # reconciles studio.holders as a side effect
            except Exception as e:  # noqa: BLE001
                log.exception("refresh %s: snapshot failed", company_id)
                self.store.update_company(company_id, error=f"refresh: {_err(e)}"[:1000])
                return
            self._event(company_id, "refreshed", LOCAL, holders=len(balances), supply=supply)
            self._sync(company_id, started_at=_iso(), finished_at=None)
            self._sync_external(company_id, list(syncstate.EXTERNAL))  # clears the error, _finish sets status

    def _transfer_receivers(self, token, from_block: int, to_block: int) -> set[str]:
        out: set[str] = set()
        start = max(int(from_block or 0), 0)
        while start <= to_block:
            end = min(start + self.LOG_CHUNK - 1, to_block)
            for ev in token.events.Transfer().get_logs(from_block=start, to_block=end):
                to = ev["args"]["to"]
                if int(to, 16):
                    out.add(to)
            start = end + 1
        return out

    def snapshot(self, c: dict) -> tuple[int, dict[str, int], int]:
        """(local block, {wallet: balance>0}, totalSupply) of the BlockID Chain share token.
        Wallets come from studio.holders plus every Transfer receiver since the token was deployed (secondary
        transfers are not in studio.holders); studio.holders is then reconciled to the chain balances."""
        L = self.local
        token = L.contract("BlockIDShareToken", c["local_token"])
        blk = L.block_number()
        wallets = {h["wallet"].lower(): cs(h["wallet"]) for h in self.store.holders(c["id"])}
        # local_block is set after issuance; the token was deployed a few blocks earlier
        first = max(int(c.get("local_block") or 0) - 200, 0)
        try:
            for to in self._transfer_receivers(token, first, blk):
                wallets.setdefault(to.lower(), cs(to))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"could not scan share transfers on BlockID Chain: {e}") from e

        def bal(w: str) -> int:
            try:
                return int(token.functions.balanceOf(w).call(block_identifier=blk))
            except Exception:  # noqa: BLE001 - node without historical state
                return int(token.functions.balanceOf(w).call())

        balances = {w: b for w in wallets.values() if (b := bal(w)) > 0}
        try:
            supply = int(token.functions.totalSupply().call(block_identifier=blk))
        except Exception:  # noqa: BLE001
            supply = int(token.functions.totalSupply().call())
        if sum(balances.values()) != supply:
            raise RuntimeError(f"cap table incomplete: sum(balances)={sum(balances.values())} != totalSupply={supply}")
        self._seen_wallets[c["id"]] = set(wallets.values())  # incl. zero balances, for mirror clean-up
        changed = self.store.reconcile_holders(c["id"], balances)
        if changed:
            log.info("company %s: studio.holders reconciled to chain (%s)", c["id"], changed)
        return blk, balances, supply

    def _sync_and_anchor(self, c: dict, t: Target | None = None) -> None:
        t = t or self.targets.get(HOODI)
        if t is None:
            raise RuntimeError("external chain not configured")
        if not c.get("local_token"):
            raise RuntimeError("company has no BlockID Chain token (not issued)")
        cid, H, st, cols, key = c["id"], t.chain, self.store, t.cols, t.key
        blk, balances, supply = self.snapshot(c)
        names = {h["wallet"].lower(): h["name"] for h in st.holders(cid)}

        # ---- mirror register (paused: display/verification copy, not tradable)
        self._step(cid, key, "deploy_registry")
        reg = self._ensure_registry(H, c.get(cols["registry"]),
                                    lambda a: st.update_company(cid, **{cols["registry"]: a}), cid)
        self._step(cid, key, "deploy_token")
        token, deploy_rec = self._ensure_token(H, c, reg, c.get(cols["token"]),
                                               lambda a: st.update_company(cid, **{cols["token"]: a}))
        mirror_txs: list[Receipt] = [deploy_rec] if deploy_rec else []
        ref = k(f"studio-mirror:{cid}:{blk}")
        wallets = {w.lower(): w for w in balances}
        # every wallet that ever held shares locally may hold a stale mirror balance (a transfer lowers the sender,
        # a full exit removes it from studio.holders), so shrink those first, then top up the rest
        ever = dict(wallets)
        for w in self._seen_wallets.get(cid, ()):
            ever.setdefault(w.lower(), w)
        for h in st.holders(cid):
            ever.setdefault(h["wallet"].lower(), cs(h["wallet"]))
        for w in ever.values():
            want = balances.get(w, 0)
            have = int(token.functions.balanceOf(w).call())
            if have > want:
                self._step(cid, key, "mirror_reduce")
                mirror_txs.append(H.transact(token.functions.cancel(w, have - want, ref)))
        for i, w in enumerate(wallets.values(), 1):
            self._step(cid, key, "mirror_balances", i, len(wallets))
            want = balances.get(w, 0)
            have = int(token.functions.balanceOf(w).call())
            if want > have:
                r = self._kyc(H, reg, w, names.get(w.lower(), w), cid, record=False)
                if r:
                    mirror_txs.append(r)
                mirror_txs.append(H.transact(token.functions.issue(w, want - have, ref)))
        mirror_supply = int(token.functions.totalSupply().call())
        if mirror_supply != supply:  # never anchor a root over a mirror that disagrees with the register
            raise RuntimeError(f"mirror supply {mirror_supply} != BlockID Chain supply {supply} after sync")
        local_tok = self.local.contract("BlockIDShareToken", c["local_token"])
        cents = int(local_tok.functions.valuationPerShareCents().call())
        vh = local_tok.functions.valuationReportHash().call()
        if (int(token.functions.valuationPerShareCents().call()) != cents
                or token.functions.valuationReportHash().call() != vh):
            mirror_txs.append(H.transact(token.functions.anchorValuation(vh, cents)))
        if not token.functions.paused().call():
            self._step(cid, key, "pause")
            mirror_txs.append(H.transact(token.functions.pause()))
        if mirror_txs:
            self._event(cid, t.mirrored_kind, key, mirror_txs[-1], registry=reg.address, token=token.address,
                        holders=len(balances), total_supply=supply, local_block=blk, txs=len(mirror_txs),
                        deploy_tx=deploy_rec.tx_hash if deploy_rec else None, paused=True)

        # ---- CapTableAnchor.anchor(ticker, localToken, 262626, localBlock, root, totalSupply, uri)
        self._step(cid, key, "anchor_root")
        tree = build_tree(balances)
        anchor = H.contract("CapTableAnchor", t.anchor)
        uri = f"{self.cfg.public_base_url.rstrip('/')}/c/{c['ticker']}"
        rec = H.transact(anchor.functions.anchor(c["ticker"], cs(c["local_token"]), self.cfg.local_chain_id, blk,
                                                 bytes.fromhex(tree.root[2:]), supply, uri))
        idx = None
        try:
            idx = int(anchor.events.Anchored().process_receipt({"logs": rec.logs}, errors=_discard())[0]["args"]["anchorIndex"])
        except Exception:  # noqa: BLE001
            idx = int(anchor.functions.anchorCount(c["ticker"]).call()) - 1
        self._event(cid, "anchored", key, rec, merkle_root=tree.root, local_block=blk, local_chain_id=self.cfg.local_chain_id,
                    total_supply=supply, holders=len(balances), anchor_index=idx, contract=anchor.address, uri=uri,
                    chain_id=H.chain_id)
        st.update_company(cid, **{cols["merkle_root"]: tree.root, cols["anchor_tx"]: rec.tx_hash,
                                  cols["block"]: rec.block, cols["anchored_at"]: datetime.now(UTC)})

    # ================================================================== revalue
    def revalue(self, company_id: int) -> None:
        """Anchor the latest mark on the BlockID token, then re-anchor every synced external chain."""
        c = self.store.company(company_id)
        if not c or not c.get("local_token"):
            log.warning("revalue: company %s not issued; skipped", company_id)
            return
        try:
            m = self.store.latest_mark(company_id)
            if m:
                cents = _cents(m["mark_aud"])
                token = self.local.contract("BlockIDShareToken", c["local_token"])
                rh = self._report_hash(c)
                rec = self.local.transact(token.functions.anchorValuation(rh, cents))
                self._event(company_id, "valuation_anchored", LOCAL, rec, mark_aud=str(m["mark_aud"]),
                            per_share_cents=cents, valuation_aud=str(m["valuation_aud"]), mark_id=m["id"],
                            report_hash="0x" + rh.hex())
        except Exception as e:  # noqa: BLE001
            self._fail_company(company_id, e, set_status=False)
            return
        self.reanchor(company_id)

    # ================================================================== backfill: valuation REPORT hash
    def reanchor_valuation(self, company_id: int) -> None:
        """Recompute the report hash from the stored valuation, store it, and anchorValuation(report_hash, current cents)
        on BlockID Chain and on every existing mirror (Hoodi / HSK). Only the hash changes; cents stay as they are."""
        c = self.store.company(company_id)
        if not c or not c.get("local_token"):
            log.warning("reanchor_valuation: company %s not issued; skipped", company_id)
            return
        try:
            c["valuation_report_hash"] = None  # force recompute from studio.valuations
            rh = self._report_hash(c)
            token = self.local.contract("BlockIDShareToken", c["local_token"])
            cents = int(token.functions.valuationPerShareCents().call()) or _cents(c.get("share_price_aud") or 1)
            if token.functions.valuationReportHash().call() != rh:
                rec = self.local.transact(token.functions.anchorValuation(rh, cents))
                self._event(company_id, "valuation_anchored", LOCAL, rec, per_share_cents=cents,
                            report_hash="0x" + rh.hex(), backfill=True)
            for key, t in self.targets.items():
                addr = c.get(t.cols["token"])
                if not addr:
                    continue
                try:
                    m = t.chain.contract("BlockIDShareToken", addr)
                    if m.functions.valuationReportHash().call() != rh:
                        rec = t.chain.transact(m.functions.anchorValuation(rh, cents))
                        self._event(company_id, "valuation_anchored", key, rec, per_share_cents=cents,
                                    report_hash="0x" + rh.hex(), backfill=True)
                except Exception as e:  # noqa: BLE001 - one chain must not block the others
                    log.exception("reanchor_valuation %s on %s failed", company_id, key)
                    self._fail_company(company_id, e, set_status=False)
        except Exception as e:  # noqa: BLE001
            self._fail_company(company_id, e, set_status=False)

    # ================================================================== mint
    def mint(self, mint_id: int) -> None:
        with self._exclusive(f"mint:{mint_id}") as ok:
            if ok:
                self._mint(mint_id)

    def _mint(self, mint_id: int) -> None:
        st = self.store
        m = st.claim_mint(mint_id)  # approved -> minting, atomically; anything else is not ours to execute
        if not m:
            log.warning("mint %s is not in status 'approved'; skipped", mint_id)
            return
        c = st.company(m["company_id"])
        try:
            if not c or not c.get("local_token") or not c.get("local_registry"):
                raise RuntimeError("company not issued on BlockID Chain")
            L = self.local
            reg = L.contract("IdentityRegistry", c["local_registry"])
            token = L.contract("BlockIDShareToken", c["local_token"])
            self._issue_mint(c, reg, token, m)
        except Exception as e:
            log.exception("mint %s failed", mint_id)
            st.update_mint(mint_id, status="failed")
            if c:
                st.update_company(c["id"], error=f"mint {mint_id}: {_err(e)}")
            return
        self.reanchor(c["id"])

    def _issue_mint(self, c: dict, reg, token, m: dict) -> Receipt:
        """Issue one claimed mint row on BlockID Chain (KYC + gas first) and record it; never issues twice."""
        st, L, cid, mint_id = self.store, self.local, c["id"], m["id"]
        to = cs(m["to_wallet"])
        ref = k(f"studio-mint:{mint_id}")
        # a retried mint (failed -> re-approved) may have landed before the failure: never issue twice
        rec = self._landed_issue(token, ref, c.get("local_block") or 0)
        if rec is None:
            self._kyc(L, reg, to, m["holder_name"], cid)
            self._drip_if_needed(to, cid)
            rec = L.transact(token.functions.issue(to, int(m["shares"]), ref))
        else:
            log.warning("mint %s already on chain in %s; not re-sent", mint_id, rec.tx_hash)
        # holders row follows the chain balance (idempotent across retries)
        have = sum(int(h["shares"]) for h in st.holders(cid) if h["wallet"].lower() == to.lower())
        delta = int(token.functions.balanceOf(to).call()) - have
        if delta > 0:
            st.add_holder_shares(cid, to, m["holder_name"], delta)
        st.update_mint(mint_id, status="minted", tx_hash=rec.tx_hash)
        extra = {"offering_id": m["offering_id"]} if m.get("offering_id") else {}
        self._event(cid, "minted", LOCAL, rec, mint_id=mint_id, wallet=to, name=m["holder_name"],
                    shares=int(m["shares"]), reason=m.get("reason"), **extra)
        return rec

    # ================================================================== share offering settlement (ONE job)
    def settle_offering(self, offering_id: int) -> None:
        with self._exclusive(f"offering:{offering_id}") as ok:
            if ok:
                self._settle_offering(offering_id)

    def _settle_offering(self, oid: int) -> None:
        """Mint every approved allocation of a settling offering on BlockID Chain, then re-sync the public copies
        ONCE (one Hoodi + one HSK round for the whole offering). Only 'approved' mint rows are executed; rows already
        minted are skipped and a retried row is checked on chain first, so a repeated call never issues twice."""
        st = self.store
        o = st.offering(oid)
        if not o or o["status"] != "settling":
            log.warning("offering %s is %s, not settling; skipped", oid, o["status"] if o else "missing")
            return
        c = st.company(o["company_id"])
        issued = []
        try:
            if not c or not c.get("local_token") or not c.get("local_registry"):
                raise RuntimeError("company not issued on BlockID Chain")
            L = self.local
            reg = L.contract("IdentityRegistry", c["local_registry"])
            token = L.contract("BlockIDShareToken", c["local_token"])
            for m in st.offering_mints(oid):
                if m["status"] == "minted":
                    issued.append(m)
                    continue
                claimed = st.claim_mint(m["id"])  # approved -> minting; anything else is not ours to execute
                if not claimed:
                    continue
                self._issue_mint(c, reg, token, claimed)
                issued.append({**claimed, "status": "minted"})
            left = [m for m in st.offering_mints(oid) if m["status"] != "minted"]
            if left:
                raise RuntimeError(f"{len(left)} allocation(s) not issued (status {sorted({m['status'] for m in left})})")
        except Exception as e:  # noqa: BLE001 - recorded on the offering; the admin can approve settlement again
            log.exception("offering %s settlement failed", oid)
            st.fail_offering(oid, _err(e))
            return
        shares = sum(int(m["shares"]) for m in issued)
        st.finish_offering(oid)
        self._event(c["id"], "offering_settled", None, None, offering_id=oid, shares=shares, investors=len(issued),
                    mint_ids=[m["id"] for m in issued], price_aud=str(o["price_aud"]),
                    reserved_aud=str((Decimal(str(o["price_aud"])) * shares).quantize(Decimal("0.01"))),
                    simulated=True)
        self.reanchor(c["id"])  # one mirror + root refresh per chain for the whole offering

    # ================================================================== dividend (BlockID Chain, DemoAUD)
    @staticmethod
    def parse_claims(claims: Any) -> dict[str, dict]:
        """Accepts [{wallet|account|address, amount|units, name?}] or {address: amount | {amount}}."""
        out: dict[str, dict] = {}
        if not claims:
            return out
        if isinstance(claims, dict):
            items = [{"wallet": a, **(v if isinstance(v, dict) else {"amount": v})} for a, v in claims.items()]
        else:
            items = list(claims)
        for it in items:
            w = it.get("wallet") or it.get("account") or it.get("address")
            amt = int(it.get("amount", it.get("units", it.get("amount_units", 0))))
            if not w or amt <= 0:
                continue
            e = out.setdefault(w.lower(), {"wallet": cs(w), "amount": 0, "name": it.get("name")})
            e["amount"] += amt
        return out

    def _plan_pro_rata(self, c: dict, total: int) -> dict[str, dict]:
        _, balances, supply = self.snapshot(c)
        names = {h["wallet"].lower(): h["name"] for h in self.store.holders(c["id"])}
        return {w.lower(): {"wallet": w, "amount": total * b // supply, "name": names.get(w.lower())}
                for w, b in balances.items() if total * b // supply > 0}

    def dividend(self, dividend_id: int) -> None:
        with self._exclusive(f"dividend:{dividend_id}") as ok:
            if ok:
                self._dividend_job(dividend_id)

    def _dividend_job(self, dividend_id: int) -> None:
        st = self.store
        d = st.claim_dividend(dividend_id)  # approved -> paying, atomically
        if not d:
            log.warning("dividend %s is not in status 'approved'; skipped", dividend_id)
            return
        c = st.company(d["company_id"])
        try:
            self._dividend(d, c)
        except Exception as e:
            log.exception("dividend %s failed", dividend_id)
            st.update_dividend(dividend_id, status="failed")
            if c:
                st.update_company(c["id"], error=f"dividend {dividend_id}: {_err(e)}")

    def _dividend(self, d: dict, c: dict | None) -> None:
        st, L, did = self.store, self.local, d["id"]
        if not c or not c.get("local_distributor"):
            raise RuntimeError("company has no DividendDistributor on BlockID Chain")
        if not self.cfg.local_demo_aud:
            raise RuntimeError("LOCAL_DEMO_AUD not configured")
        cid, total = c["id"], int(d["total_units"])
        st.update_dividend(did, status="paying")
        allocs = self.parse_claims(d.get("claims")) or self._plan_pro_rata(c, total)
        if sum(a["amount"] for a in allocs.values()) > total:
            raise RuntimeError("claims exceed total_units")
        tree = build_tree({a["wallet"]: a["amount"] for a in allocs.values()})
        if d.get("merkle_root") and d["merkle_root"].lower() != tree.root:
            log.warning("dividend %s: plan root %s != recomputed OZ root %s; using recomputed",
                        did, d["merkle_root"], tree.root)
        claims = [{"wallet": a["wallet"], "name": a.get("name"), "amount": a["amount"],
                   "proof": tree.proof(a["wallet"]), "claimed": False, "tx_hash": None}
                  for a in sorted(allocs.values(), key=lambda a: -a["amount"])]
        old = {x.get("wallet", "").lower(): x for x in (d.get("claims") or []) if isinstance(x, dict)} \
            if isinstance(d.get("claims"), list) else {}
        for x in claims:  # keep payment state across retries
            if old.get(x["wallet"].lower(), {}).get("tx_hash"):
                x["claimed"], x["tx_hash"] = True, old[x["wallet"].lower()]["tx_hash"]

        dist = L.contract("DividendDistributor", c["local_distributor"])
        round_id = d.get("round_id")
        if round_id is None:  # retry after an ambiguous failure: reuse a round already created for this plan
            for lg in dist.events.RoundCreated().get_logs(from_block=int(c.get("local_block") or 0)):
                if Web3.to_hex(lg["args"]["merkleRoot"]) == tree.root and int(lg["args"]["total"]) == total:
                    round_id = int(lg["args"]["roundId"])
                    st.update_dividend(did, merkle_root=tree.root, round_id=round_id, claims=claims)
                    log.warning("dividend %s: round %s already on chain; not re-created", did, round_id)
        if round_id is None:
            aud = L.contract("DemoAUD", self.cfg.local_demo_aud)
            have = int(aud.functions.balanceOf(L.address).call())
            if have < total:
                L.transact(aud.functions.mint(L.address, total - have))
            if int(aud.functions.allowance(L.address, dist.address).call()) < total:
                L.transact(aud.functions.approve(dist.address, total))
            record_block = L.block_number()
            deadline = self._now(L) + CLAIM_WINDOW
            rec = L.transact(dist.functions.createRound(bytes.fromhex(tree.root[2:]), aud.address, total, record_block,
                                                        deadline, k(f"studio-dividend:{did}")))
            round_id = int(dist.events.RoundCreated().process_receipt(
                {"logs": rec.logs}, errors=_discard())[0]["args"]["roundId"])
            st.update_dividend(did, merkle_root=tree.root, round_id=round_id, tx_hash=rec.tx_hash, claims=claims)
            self._event(cid, "dividend_created", LOCAL, rec, dividend_id=did, round_id=round_id, merkle_root=tree.root,
                        total_units=total, holders=len(claims), pay_token=aud.address, record_block=record_block,
                        deadline=deadline)
        else:
            rnd = dist.functions.getRound(round_id).call()
            if Web3.to_hex(rnd[0]) != tree.root:
                raise RuntimeError(f"round {round_id} root does not match claims")

        # relayer pays gas for claimFor (top up from the issuer if low)
        R = self.relayer
        if R.address != L.address and R.balance(R.address) < self.cfg.relayer_topup_wei // 10:
            r = L.transfer(R.address, self.cfg.relayer_topup_wei)
            self._event(cid, "drip", LOCAL, r, wallet=R.address, amount_wei=str(self.cfg.relayer_topup_wei),
                        purpose="relayer gas")
        dist_r = R.contract("DividendDistributor", c["local_distributor"])
        for x in claims:
            if dist_r.functions.hasClaimed(round_id, x["wallet"]).call():
                x["claimed"] = True
                continue
            rec = R.transact(dist_r.functions.claimFor(round_id, x["wallet"], x["amount"],
                                                       [bytes.fromhex(p[2:]) for p in x["proof"]]))
            x["claimed"], x["tx_hash"] = True, rec.tx_hash
            st.update_dividend(did, claims=claims)
            self._event(cid, "dividend_claimed", LOCAL, rec, dividend_id=did, round_id=round_id, wallet=x["wallet"],
                        name=x.get("name"), amount=x["amount"])
        st.update_dividend(did, status="paid", claims=claims)

    # ================================================================== drip
    DRIP_MAX_WEI = 5 * 10**18  # hard cap of one gas allowance (5 BLKD)

    def drip(self, wallet: str, company_id: int | None = None, amount_wei: int | None = None) -> None:
        """Gas for a wallet on BlockID EVM. Without amount: the classic 0.01 BLKD drip below 0.001 BLKD. With
        amount_wei (API gas allowance, capped at 5 BLKD): top the wallet up to that balance."""
        try:
            if amount_wei is None:
                self._drip_if_needed(wallet, company_id)
                return
            target = min(int(amount_wei), self.DRIP_MAX_WEI)
            have = self.local.balance(wallet)
            if target <= 0 or have >= target:
                log.info("drip %s skipped: balance %s >= allowance %s", wallet, have, target)
                return
            rec = self.local.transfer(cs(wallet), target - have)
            self._event(company_id, "drip", LOCAL, rec, wallet=cs(wallet), amount_wei=str(target - have),
                        allowance_wei=str(target))
            if hasattr(self.store, "record_drip"):
                self.store.record_drip(cs(wallet), rec.tx_hash, target - have)
        except Exception:
            log.exception("drip to %s failed", wallet)

    # ================================================================== health
    def health(self) -> dict:
        def chain_info(ch: Chain | None) -> dict:
            if ch is None:
                return {"configured": False}
            info: dict[str, Any] = {"chain_id": ch.chain_id, "rpc": ch.rpc_url}
            try:
                info["block"] = ch.block_number()
                info["ok"] = True
            except Exception as e:  # noqa: BLE001
                info["ok"], info["error"] = False, _err(e)
            return info

        def bal(ch: Chain | None, addr: str) -> str | None:
            try:
                return str(ch.balance(addr)) if ch else None
            except Exception:  # noqa: BLE001
                return None

        issuer = self.local.address
        relayer = self.relayer.address
        return {
            "ok": True,
            "issuer": {"address": issuer, "local_balance": bal(self.local, issuer), "hoodi_balance": bal(self.hoodi, issuer),
                       "hsk_balance": bal(self.hsk, issuer)},
            "relayer": {"address": relayer, "local_balance": bal(self.local, relayer),
                        "hoodi_balance": bal(self.hoodi, relayer), "hsk_balance": bal(self.hsk, relayer)},
            "local": {**chain_info(self.local), "demo_aud": self.cfg.local_demo_aud or None},
            "hoodi": {**chain_info(self.hoodi), "cap_table_anchor": self.cfg.hoodi_captable_anchor or None},
            "hsk": {**chain_info(self.hsk), "cap_table_anchor": self.cfg.hsk_captable_anchor or None},
            "sync_targets": list(self.targets),
        }


def _discard():
    from web3.logs import DISCARD

    return DISCARD
