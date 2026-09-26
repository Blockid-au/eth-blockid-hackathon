"""Issuer operations. Each public method processes ONE admin-approved DB row and records every tx in studio.events.

Chains: `local` = BlockID Chain (262626, events.chain='blockid'), `hoodi` = Ethereum Hoodi (560048, 'hoodi').
All operations are idempotent enough to be retried after a failure (contracts already deployed are reused,
shares already issued are not issued twice, claims already paid are skipped).
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from web3 import Web3

from .chain import Chain, Receipt
from .config import IssuerConfig
from .merkle import build_tree

log = logging.getLogger(__name__)

LOCAL, HOODI = "blockid", "hoodi"
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
                 relayer: Chain | None = None):
        self.cfg, self.store, self.local, self.hoodi = cfg, store, local, hoodi
        self.relayer = relayer or local  # relayer signer on the local chain (claimFor)
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
        try:
            relayer = local.with_account(load_account(cfg.relayer_account, cfg.keystore_dir, pw_dir))
        except FileNotFoundError:
            log.warning("relayer keystore missing; deployer will submit claimFor")
            relayer = None
        return cls(cfg, Store(cfg.database_url), local, hoodi, relayer)

    # ================================================================== helpers
    def _event(self, company_id, kind, chain=None, rec: Receipt | None = None, **data) -> None:
        self.store.add_event(company_id, kind, chain, rec.tx_hash if rec else None, rec.block if rec else None, data)

    def _now(self, chain: Chain) -> int:
        try:
            return max(int(time.time()), int(chain.w3.eth.get_block("latest")["timestamp"]))
        except Exception:  # noqa: BLE001
            return int(time.time())

    def _ensure_registry(self, ch: Chain, addr: str | None, save) -> Any:
        if addr:
            reg = ch.contract("IdentityRegistry", addr)
        else:
            reg, _ = ch.deploy("IdentityRegistry", ch.address)
            save(reg.address)
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
        return token, rec

    def _kyc(self, ch: Chain, reg, wallet: str, name: str, company_id: int | None, record: bool = True) -> Receipt | None:
        if reg.functions.isVerified(cs(wallet)).call():
            return None
        exp = self._now(ch) + YEAR
        rec = ch.transact(reg.functions.registerInvestor(cs(wallet), self.cfg.kyc_country, exp, k(name)))
        if record:
            self._event(company_id, "kyc", LOCAL if ch is self.local else HOODI, rec, wallet=cs(wallet), name=name,
                        registry=reg.address)
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

    # ================================================================== issue (BlockID Chain)
    def issue(self, company_id: int) -> None:
        with self._exclusive(f"company:{company_id}") as ok:
            if not ok:
                return
            c = self.store.company(company_id)  # re-read inside the lock: status is the source of truth
            if not c:
                raise LookupError(f"company {company_id} not found")
            if c["status"] != "issuing":
                log.warning("issue: company %s is %s, expected issuing; skipped", company_id, c["status"])
                return
            try:
                self._issue(c)
            except Exception as e:  # noqa: BLE001
                self._fail_company(company_id, e)

    def _issue(self, c: dict) -> None:
        cid, L, st = c["id"], self.local, self.store
        reg = self._ensure_registry(L, c.get("local_registry"), lambda a: st.update_company(cid, local_registry=a))
        token, _ = self._ensure_token(L, c, reg, c.get("local_token"), lambda a: st.update_company(cid, local_token=a))
        if not c.get("local_distributor"):
            dist, _ = L.deploy("DividendDistributor", token.address, L.address)
            st.update_company(cid, local_distributor=dist.address)

        last: Receipt | None = None
        ref = k(f"studio-issue:{cid}")
        for h in self._targets(st.holders(cid)).values():
            self._kyc(L, reg, h["wallet"], h["name"], cid)
            self._drip_if_needed(h["wallet"], cid)
            have = token.functions.balanceOf(h["wallet"]).call()
            if have < h["shares"]:
                last = L.transact(token.functions.issue(h["wallet"], h["shares"] - have, ref))
                self._event(cid, "issued", LOCAL, last, wallet=h["wallet"], name=h["name"],
                            shares=h["shares"] - have, token=token.address)

        mark = Decimal(str(c.get("share_price_aud") or 1))
        cents = _cents(mark)
        rec = L.transact(token.functions.anchorValuation(k(str(c.get("valuation_id") or "")), cents))
        self._event(cid, "valuation_anchored", LOCAL, rec, mark_aud=str(mark), per_share_cents=cents,
                    valuation_aud=str(c["valuation_aud"]), valuation_id=c.get("valuation_id"))
        lm = st.latest_mark(cid)
        if not lm or lm.get("source") != "issuance":
            st.add_mark(cid, c["valuation_aud"], mark, "issuance", c.get("valuation_id"))
        st.update_company(cid, local_block=(last or rec).block, status="issued", error=None)

    # ================================================================== anchor (Hoodi mirror + CapTableAnchor)
    def anchor(self, company_id: int) -> None:
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
        try:
            self._sync_and_anchor(c)
        except Exception as e:  # noqa: BLE001
            self._fail_company(company_id, e)

    def reanchor(self, company_id: int) -> None:
        """After a mint / revaluation: refresh the Hoodi mirror + anchor a new root. Only for anchored companies."""
        c = self.store.company(company_id)
        if not c or c["status"] != "anchored" or not c.get("hoodi_token"):
            return
        try:
            self._sync_and_anchor(c)
        except Exception as e:  # noqa: BLE001  keep status 'anchored' (the previous anchor stays valid)
            self._fail_company(company_id, e, set_status=False)

    def snapshot(self, c: dict) -> tuple[int, dict[str, int], int]:
        """(local block, {wallet: balance>0}, totalSupply) of the BlockID Chain share token."""
        L = self.local
        token = L.contract("BlockIDShareToken", c["local_token"])
        blk = L.block_number()
        wallets = {h["wallet"].lower(): cs(h["wallet"]) for h in self.store.holders(c["id"])}
        try:  # also pick up wallets that received shares outside the studio (transfers)
            for ev in token.events.Transfer().get_logs(from_block=0, to_block=blk):
                to = ev["args"]["to"]
                if int(to, 16):
                    wallets.setdefault(to.lower(), cs(to))
        except Exception as e:  # noqa: BLE001
            log.warning("Transfer log scan failed (%s); using studio.holders only", e)

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
        return blk, balances, supply

    def _sync_and_anchor(self, c: dict) -> None:
        if self.hoodi is None or not self.cfg.hoodi_captable_anchor:
            raise RuntimeError("Hoodi chain / HOODI_CAPTABLE_ANCHOR not configured")
        if not c.get("local_token"):
            raise RuntimeError("company has no BlockID Chain token (not issued)")
        cid, H, st = c["id"], self.hoodi, self.store
        blk, balances, supply = self.snapshot(c)
        names = {h["wallet"].lower(): h["name"] for h in st.holders(cid)}

        # ---- mirror register on Hoodi (paused: display/verification copy, not tradable)
        reg = self._ensure_registry(H, c.get("hoodi_registry"), lambda a: st.update_company(cid, hoodi_registry=a))
        token, deploy_rec = self._ensure_token(H, c, reg, c.get("hoodi_token"),
                                               lambda a: st.update_company(cid, hoodi_token=a))
        mirror_txs: list[Receipt] = [deploy_rec] if deploy_rec else []
        ref = k(f"studio-mirror:{cid}:{blk}")
        wallets = {w.lower(): w for w in balances}
        for w in wallets.values():
            want = balances.get(w, 0)
            have = int(token.functions.balanceOf(w).call())
            if want > have:
                r = self._kyc(H, reg, w, names.get(w.lower(), w), cid, record=False)
                if r:
                    mirror_txs.append(r)
                mirror_txs.append(H.transact(token.functions.issue(w, want - have, ref)))
        # holders that no longer hold shares locally
        hoodi_supply = int(token.functions.totalSupply().call())
        if hoodi_supply != supply:
            for h in st.holders(cid):
                w = cs(h["wallet"])
                if w.lower() in wallets:
                    continue
                have = int(token.functions.balanceOf(w).call())
                if have:
                    mirror_txs.append(H.transact(token.functions.cancel(w, have, ref)))
        local_tok = self.local.contract("BlockIDShareToken", c["local_token"])
        cents = int(local_tok.functions.valuationPerShareCents().call())
        if int(token.functions.valuationPerShareCents().call()) != cents:
            vh = local_tok.functions.valuationReportHash().call()
            mirror_txs.append(H.transact(token.functions.anchorValuation(vh, cents)))
        if not token.functions.paused().call():
            mirror_txs.append(H.transact(token.functions.pause()))
        if mirror_txs:
            self._event(cid, "hoodi_mirrored", HOODI, mirror_txs[-1], registry=reg.address, token=token.address,
                        holders=len(balances), total_supply=supply, local_block=blk, txs=len(mirror_txs),
                        deploy_tx=deploy_rec.tx_hash if deploy_rec else None)

        # ---- CapTableAnchor.anchor(ticker, localToken, 262626, localBlock, root, totalSupply, uri)
        tree = build_tree(balances)
        anchor = H.contract("CapTableAnchor", self.cfg.hoodi_captable_anchor)
        uri = f"{self.cfg.public_base_url.rstrip('/')}/c/{c['ticker']}"
        rec = H.transact(anchor.functions.anchor(c["ticker"], cs(c["local_token"]), self.cfg.local_chain_id, blk,
                                                 bytes.fromhex(tree.root[2:]), supply, uri))
        idx = None
        try:
            idx = int(anchor.events.Anchored().process_receipt({"logs": rec.logs}, errors=_discard())[0]["args"]["anchorIndex"])
        except Exception:  # noqa: BLE001
            idx = int(anchor.functions.anchorCount(c["ticker"]).call()) - 1
        self._event(cid, "anchored", HOODI, rec, merkle_root=tree.root, local_block=blk, local_chain_id=self.cfg.local_chain_id,
                    total_supply=supply, holders=len(balances), anchor_index=idx, contract=anchor.address, uri=uri)
        st.update_company(cid, merkle_root=tree.root, hoodi_anchor_tx=rec.tx_hash, anchored_block=rec.block,
                          anchored_at=datetime.now(UTC), status="anchored", error=None)

    # ================================================================== revalue
    def revalue(self, company_id: int) -> None:
        """Anchor the latest mark on the BlockID token, then re-anchor the cap table on Hoodi (if anchored)."""
        c = self.store.company(company_id)
        if not c or not c.get("local_token"):
            log.warning("revalue: company %s not issued; skipped", company_id)
            return
        try:
            m = self.store.latest_mark(company_id)
            if m:
                cents = _cents(m["mark_aud"])
                token = self.local.contract("BlockIDShareToken", c["local_token"])
                rec = self.local.transact(token.functions.anchorValuation(k(f"studio-mark:{m['id']}:{m.get('ref') or ''}"), cents))
                self._event(company_id, "valuation_anchored", LOCAL, rec, mark_aud=str(m["mark_aud"]),
                            per_share_cents=cents, valuation_aud=str(m["valuation_aud"]), mark_id=m["id"])
        except Exception as e:  # noqa: BLE001
            self._fail_company(company_id, e, set_status=False)
            return
        self.reanchor(company_id)

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
            L, cid = self.local, c["id"]
            reg = L.contract("IdentityRegistry", c["local_registry"])
            token = L.contract("BlockIDShareToken", c["local_token"])
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
            self._event(cid, "minted", LOCAL, rec, mint_id=mint_id, wallet=to, name=m["holder_name"],
                        shares=int(m["shares"]), reason=m.get("reason"))
        except Exception as e:
            log.exception("mint %s failed", mint_id)
            st.update_mint(mint_id, status="failed")
            if c:
                st.update_company(c["id"], error=f"mint {mint_id}: {_err(e)}")
            return
        self.reanchor(c["id"])

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
    def drip(self, wallet: str, company_id: int | None = None) -> None:
        try:
            self._drip_if_needed(wallet, company_id)
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
            "issuer": {"address": issuer, "local_balance": bal(self.local, issuer), "hoodi_balance": bal(self.hoodi, issuer)},
            "relayer": {"address": relayer, "local_balance": bal(self.local, relayer),
                        "hoodi_balance": bal(self.hoodi, relayer)},
            "local": {**chain_info(self.local), "demo_aud": self.cfg.local_demo_aud or None},
            "hoodi": {**chain_info(self.hoodi), "cap_table_anchor": self.cfg.hoodi_captable_anchor or None},
        }


def _discard():
    from web3.logs import DISCARD

    return DISCARD
