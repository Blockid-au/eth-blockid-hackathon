/* /terms and /privacy on both hosts (eth.blockid.au and hr.blockid.au). Text: ./copy.ts (EN + VI). */
import { Fragment, useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import { HR_HOST } from "../../lib/hrhost";
import { legalEn, legalVi, LEGAL_UPDATED_ISO, type Block } from "./copy";
import "./legal.css";

export type LegalKind = "terms" | "privacy";

// **bold**, emails, https links, and the in-app paths /terms and /privacy
const INLINE = /(\*\*[^*]+\*\*|[\w.+-]+@blockid\.au|https:\/\/[^\s),]+|\/(?:terms|privacy)\b)/g;

function inline(s: string): ReactNode[] {
  return s.split(INLINE).map((part, i) => {
    if (i % 2 === 0) return part ? <Fragment key={i}>{part}</Fragment> : null;
    if (part.startsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.includes("@")) return <a key={i} href={`mailto:${part}`}>{part}</a>;
    if (part.startsWith("https://")) return <a key={i} href={part} target="_blank" rel="noopener noreferrer">{part.replace(/^https:\/\//, "")}</a>;
    return <Link key={i} to={part}>{part}</Link>;
  });
}

function BlockView({ b }: { b: Block }) {
  if (Array.isArray(b)) return <ul>{b.map((li) => <li key={li}>{inline(li)}</li>)}</ul>;
  return <p>{inline(b)}</p>;
}

export default function LegalPage({ kind }: { kind: LegalKind }) {
  const { lang } = useI18n();
  const c = lang === "vi" ? legalVi : legalEn;
  const d = c[kind];
  const other: LegalKind = kind === "terms" ? "privacy" : "terms";
  useEffect(() => {
    document.title = `${d.title} · ${HR_HOST ? "BlockID HR" : "BlockID"}`;
  }, [d.title]);
  return (
    <div className="wrap page legal">
      <div className="head">
        <span className="eyebrow">{d.eyebrow}</span>
        <h1>{d.title}</h1>
        <p>{inline(d.lede)}</p>
        <p className="legal-meta">
          <time dateTime={LEGAL_UPDATED_ISO}>{c.updated}</time>
          <span aria-hidden="true"> · </span>
          <Link to={`/${other}`}>{c.other[other]}</Link>
        </p>
        <p className="legal-review" role="note">{c.review}</p>
      </div>
      <div className="legal-grid">
        <nav className="legal-toc" aria-label={c.toc}>
          <span className="eyebrow">{c.toc}</span>
          <ol>{d.sections.map((s) => <li key={s.id}><a href={`#${s.id}`}>{s.h.replace(/^\d+\.\s*/, "")}</a></li>)}</ol>
        </nav>
        <article className="legal-body">
          {d.sections.map((s) => (
            <section key={s.id} id={s.id}>
              <h2>{s.h}</h2>
              {s.body.map((b, i) => <BlockView key={i} b={b} />)}
            </section>
          ))}
          <section className="legal-contact card solid">
            <h2>{c.contactH}</h2>
            <p>{inline(c.contact)}</p>
            <p className="muted-sm">BlockID™ · © 2026 Auschain Pty Ltd</p>
          </section>
        </article>
      </div>
    </div>
  );
}

export function TermsPage() {
  return <LegalPage kind="terms" />;
}
export function PrivacyPage() {
  return <LegalPage kind="privacy" />;
}
