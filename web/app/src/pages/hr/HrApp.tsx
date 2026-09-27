/* hr.blockid.au: the "BlockID HR" app. Same SPA build as eth.blockid.au; App.tsx renders this on the hr host. */
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useI18n } from "../../i18n";
import { errText, useAuth } from "../../auth";
import { isMock } from "../../api";
import { BlockIDLogo, FlagEN, FlagVI, ScrollManager } from "../../components/Layout";
import { ErrorBoundary } from "../../components/Boundary";
import { shortAddr } from "../../lib/addr";
import { ethUrl } from "../../lib/hrhost";
import { NotFound } from "../NotFound";
import { HrHome } from "./HrHome";
import { HrNew } from "./HrNew";
import { HrNewPerson } from "./HrNewPerson";
import { HrReport } from "./HrReport";
import { HrPersonPage } from "./HrPerson";
import { HrMine } from "./HrMine";
import { HrMethod } from "./HrMethod";
import "../../components/hr.css";

function HrAccount() {
  const { t } = useI18n();
  const { me, logout, tryDemo, busy } = useAuth();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState("");
  const box = useRef<HTMLSpanElement>(null);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname, me?.address]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => { if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  if (!me) {
    return (
      <span className="menuwrap">
        <button className="btn ghost sm" type="button" disabled={busy} onClick={async () => { setErr(""); try { await tryDemo(); } catch (e) { setErr(errText(e, t)); } }}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}{t("nav.signin")}
        </button>
        {err && <span className="menu" role="alert" style={{ color: "var(--bad)", fontSize: ".82rem", padding: 12 }}>{err}</span>}
      </span>
    );
  }
  const label = me.address ? shortAddr(me.address) : me.username ?? "admin";
  const role = me.role === "admin" ? t("nav.role.admin") : me.auth_method === "demo" ? t("nav.role.demo") : me.auth_method === "guest" ? t("nav.role.guest") : me.auth_method === "google" ? t("nav.role.google") : t("nav.role.user");
  return (
    <span className="menuwrap" ref={box}>
      <button type="button" className={"addrchip" + (me.role === "admin" ? " admin" : "")} aria-haspopup="menu" aria-expanded={open} aria-label={t("nav.account")} onClick={() => setOpen((o) => !o)}>
        <i aria-hidden="true" />{label}<span className="muted" style={{ fontFamily: "var(--body)" }}>· {role}</span>
      </button>
      {open && (
        <span className="menu" role="menu">
          {me.account?.email && <span>{me.account.email}</span>}
          {me.address && <span className="mono">{me.address}</span>}
          <Link role="menuitem" to="/me" onClick={() => setOpen(false)}>{t("hr.nav.me")}</Link>
          <a role="menuitem" href={ethUrl("/i")}>{t("nav.portfolio")}</a>
          <button role="menuitem" type="button" onClick={async () => { setOpen(false); await logout(); }}>{t("nav.signout")}</button>
        </span>
      )}
    </span>
  );
}

function HrNav() {
  const { t, lang, setLang } = useI18n();
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);
  return (
    <header className="nav hr-nav">
      <a className="skip" href="#main">{t("nav.skip")}</a>
      <div className="wrap wide">
        <Link className="brand" to="/" aria-label="BlockID HR">
          <BlockIDLogo size={28} />
          <span className="brand-name">BlockID<span className="brand-tld"> HR</span></span>
        </Link>
        <button className="menubtn" type="button" aria-expanded={open} aria-controls="hr-links" onClick={() => setOpen((o) => !o)}>{open ? "✕" : "☰"}<span className="sr-only">{t("nav.menu")}</span></button>
        <nav id="hr-links" className={"links" + (open ? " open" : "")} aria-label={t("nav.primary")}>
          <NavLink to="/new/person">{t("hr.nav.person")}</NavLink>
          <NavLink to="/new" end>{t("hr.nav.new")}</NavLink>
          <NavLink to="/me">{t("hr.nav.me")}</NavLink>
          <NavLink to="/method">{t("hr.nav.how")}</NavLink>
          <span className="navsep" aria-hidden="true" />
          <a href={ethUrl("/")}>{t("hr.nav.eth")} ↗</a>
        </nav>
        <span className="grow" />
        {isMock && <span className="simbadge" title="?mock=0 to leave">{t("mock.badge")}</span>}
        <span className="langs" role="group" aria-label={t("nav.lang")}>
          <button type="button" aria-pressed={lang === "en"} onClick={() => setLang("en")} lang="en"><FlagEN />EN</button>
          <button type="button" aria-pressed={lang === "vi"} onClick={() => setLang("vi")} lang="vi"><FlagVI />VI</button>
        </span>
        <HrAccount />
      </div>
    </header>
  );
}

function HrFooter() {
  const { t } = useI18n();
  return (
    <footer className="hr-noprint">
      <div className="wrap">
        <span>{t("hr.foot.site")}</span>
        <span><a href={ethUrl("/")}>{t("hr.foot.eth")}</a></span>
        <span>{t("hr.foot.remove")}</span>
        <span>{t("foot.contact")}: <a href="mailto:info@blockid.au">info@blockid.au</a></span>
        <span>{t("foot.legal")}</span>
      </div>
    </footer>
  );
}

export default function HrApp() {
  const { pathname } = useLocation();
  return (
    <>
      <ScrollManager />
      <HrNav />
      <main id="main" tabIndex={-1}>
        <ErrorBoundary resetKey={pathname}>
          <Routes>
            <Route path="/" element={<HrHome />} />
            <Route path="/new" element={<HrNew />} />
            <Route path="/new/person" element={<HrNewPerson />} />
            <Route path="/r/:id/:tab?" element={<HrReport />} />
            <Route path="/r/:id/p/:key/:tab?" element={<HrPersonPage />} />
            <Route path="/p/:id/:tab?" element={<HrPersonPage />} />
            <Route path="/method" element={<HrMethod />} />
            <Route path="/me" element={<HrMine />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </ErrorBoundary>
      </main>
      <HrFooter />
    </>
  );
}
