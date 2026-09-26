import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useI18n } from "../i18n";
import { errText, useAuth } from "../auth";
import { isMock } from "../api";
import { shortAddr } from "../lib/addr";
import { useMyCompanies, type MyCompany } from "../lib/companyAdmins";

export function FlagEN() {
  return (
    <svg className="flag" viewBox="0 0 60 40" aria-hidden="true"><rect width="60" height="40" fill="#012169" /><path d="M0 0l60 40M60 0L0 40" stroke="#fff" strokeWidth="8" /><path d="M0 0l60 40M60 0L0 40" stroke="#C8102E" strokeWidth="3" /><path d="M30 0v40M0 20h60" stroke="#fff" strokeWidth="12" /><path d="M30 0v40M0 20h60" stroke="#C8102E" strokeWidth="7" /></svg>
  );
}
export function FlagVI() {
  return (
    <svg className="flag" viewBox="0 0 60 40" aria-hidden="true"><rect width="60" height="40" fill="#DA251D" /><path fill="#FFCD00" d="M30 9.5l2.6 8h8.4l-6.8 4.9 2.6 8-6.8-4.9-6.8 4.9 2.6-8-6.8-4.9h8.4z" /></svg>
  );
}

/** "My companies": companies the signed-in wallet administers (GET /v1/me/companies). */
function MyCompaniesNav({ list }: { list: MyCompany[] }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  if (!list.length) return null;
  if (list.length === 1) return <NavLink to={`/c/${list[0].ticker}`}>{t("nav.mycos")}</NavLink>;
  return (
    <span className="menuwrap" ref={box}>
      <a href="#" role="button" aria-haspopup="menu" aria-expanded={open} onClick={(e) => { e.preventDefault(); setOpen((o) => !o); }}>{t("nav.mycos")} ▾</a>
      {open && (
        <span className="menu" role="menu" style={{ left: 0, right: "auto" }}>
          {list.map((c) => <Link key={c.id} role="menuitem" to={`/c/${c.ticker}`} onClick={() => setOpen(false)}><b className="mono">{c.ticker}</b> · {c.name} <span className="muted">· {t(("ca.role." + c.role) as "ca.role.owner")}</span></Link>)}
        </span>
      )}
    </span>
  );
}

function Account({ mine }: { mine: MyCompany[] }) {
  const { t } = useI18n();
  const { me, busy, connect, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState("");
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  useEffect(() => { if (!err) return; const id = setTimeout(() => setErr(""), 6000); return () => clearTimeout(id); }, [err]);

  if (!me) {
    return (
      <span className="menuwrap">
        <button className="btn ghost sm" type="button" disabled={busy} onClick={async () => { setErr(""); try { await connect(); } catch (e) { setErr(errText(e, t)); } }}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}{busy ? t("nav.connecting") : t("nav.connect")}
        </button>
        {err && <span className="menu" role="alert" style={{ color: "var(--bad)", fontSize: ".82rem", padding: 12 }}>{err}</span>}
      </span>
    );
  }
  const label = me.address ? shortAddr(me.address) : me.username ?? "admin";
  return (
    <span className="menuwrap" ref={box}>
      <button type="button" className={"addrchip" + (me.role === "admin" ? " admin" : "")} aria-haspopup="menu" aria-expanded={open} aria-label={t("nav.account")} onClick={() => setOpen((o) => !o)}>
        <i aria-hidden="true" />{label}<span className="muted" style={{ fontFamily: "var(--body)" }}>· {me.role === "admin" ? t("nav.role.admin") : t("nav.role.user")}</span>
      </button>
      {open && (
        <span className="menu" role="menu">
          {me.address && <span className="mono">{me.address}</span>}
          {me.role === "admin" && <Link role="menuitem" to="/admin" onClick={() => setOpen(false)}>{t("nav.adminlink")}</Link>}
          {mine.length > 0 && <span className="mono">{t("nav.mycos")}</span>}
          {mine.map((c) => <Link key={c.id} role="menuitem" to={`/c/${c.ticker}`} onClick={() => setOpen(false)}><b className="mono">{c.ticker}</b> · {c.name}</Link>)}
          <button role="menuitem" type="button" onClick={async () => { setOpen(false); await logout(); }}>{t("nav.signout")}</button>
        </span>
      )}
    </span>
  );
}

export function Nav() {
  const { t, lang, setLang } = useI18n();
  const mine = useMyCompanies().list;
  return (
    <header className="nav">
      <a className="skip" href="#main">{t("nav.skip")}</a>
      <div className="wrap">
        <Link className="brand" to="/"><span className="mark" aria-hidden="true" />BlockID</Link>
        <nav className="links" aria-label={t("nav.primary")}>
          <Link to="/#how">{t("nav.how")}</Link>
          <NavLink to="/companies">{t("nav.companies")}</NavLink>
          <NavLink to="/hsk">{t("nav.hsk")}</NavLink>
          <NavLink to="/verify">{t("nav.verify")}</NavLink>
          <NavLink to="/admin">{t("nav.admin")}</NavLink>
          <MyCompaniesNav list={mine} />
        </nav>
        <span className="grow" />
        {isMock && <span className="simbadge" title="?mock=0 to leave">{t("mock.badge")}</span>}
        <span className="netchip"><i />{t("nav.net")}</span>
        <span className="langs" role="group" aria-label={t("nav.lang")}>
          <button type="button" aria-pressed={lang === "en"} onClick={() => setLang("en")} lang="en"><FlagEN />EN</button>
          <button type="button" aria-pressed={lang === "vi"} onClick={() => setLang("vi")} lang="vi"><FlagVI />VI</button>
        </span>
        <Account mine={mine} />
        <Link className="btn sm" to="/new">{t("cta.primary")}</Link>
      </div>
    </header>
  );
}

export function Footer() {
  const { t } = useI18n();
  return (
    <footer>
      <div className="wrap">
        <span>BlockID · eth.blockid.au</span>
        <span>
          {t("foot.deck")}:{" "}
          <a href="/deck/BlockID-Startup-Passport-3min.pdf" download>PDF</a>{" · "}
          <a href="/deck/BlockID-Startup-Passport-3min.pptx" download>PPTX</a>{" · "}
          <a href="/deck/BlockID-Startup-Passport-pitch.pdf" download>{t("foot.deckFull")}</a>
        </span>
        <span>{t("foot.legal")}</span>
      </div>
    </footer>
  );
}

/** Scroll to #hash after navigation, else to top. */
export function ScrollManager() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (hash) {
      const id = hash.slice(1);
      const tryScroll = (n: number) => {
        const el = document.getElementById(id);
        if (el) el.scrollIntoView({ block: "start" });
        else if (n > 0) setTimeout(() => tryScroll(n - 1), 60);
      };
      tryScroll(10);
    } else window.scrollTo(0, 0);
  }, [pathname, hash]);
  return null;
}

export function Loading() {
  const { t } = useI18n();
  return <div className="wrap page" aria-busy="true"><p className="muted row"><span className="spinner" aria-hidden="true" />{t("common.loading")}</p></div>;
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="banner bad" role="alert">
      <span>{t("common.error")} {errText(error, t)}</span>
      {retry && <button className="btn ghost sm" type="button" onClick={retry}>{t("common.retry")}</button>}
    </div>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return <div className="wrap page">{children}</div>;
}
