/* CV upload for /new/person: drop or pick a PDF / DOCX / TXT, read in the browser with a live status line,
   then a summary card (pages, words, sections, links found, contact details removed). */
import { useRef, useState } from "react";
import { useI18n } from "../../i18n";
import type { DictKey } from "../../dict";
import { CV_ACCEPT, CvError, readCvFile, type CvRead, type CvStep } from "./cvFile";

export interface CvMeta { name: string; kind: CvRead["kind"]; pages: number | null; words: number; truncated: boolean; redacted: number; sections: string[] }

const SECTIONS: [string, RegExp][] = [
  ["experience", /^\s*(?:work |professional )?(?:experience|employment|career history|kinh nghiệm)/im],
  ["education", /^\s*(?:education|academic|qualifications|học vấn)/im],
  ["skills", /^\s*(?:(?:technical |core |key )?skills|competencies|kỹ năng)/im],
  ["projects", /^\s*(?:projects|portfolio|dự án)/im],
  ["certifications", /^\s*(?:certifications?|licen[cs]es|chứng chỉ)/im],
  ["awards", /^\s*(?:awards|honou?rs|achievements|giải thưởng|thành tích)/im],
];
export const cvSections = (text: string) => SECTIONS.filter(([, rx]) => rx.test(text)).map(([k]) => k);

const FileIcon = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h4" /></svg>;
const UpIcon = <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>;

export function CvDrop({ meta, links, onRead, onClear }: { meta: CvMeta | null; links: string[]; onRead: (r: CvRead, meta: CvMeta) => void; onClear: () => void }) {
  const { t, fmt } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [step, setStep] = useState<CvStep | null>(null);
  const [err, setErr] = useState<DictKey | "">("");

  const take = async (f: File | undefined) => {
    if (!f || step) return;
    setErr("");
    setStep({ k: "open" });
    try {
      const r = await readCvFile(f, setStep);
      onRead(r, { name: f.name, kind: r.kind, pages: r.pages, words: (r.text.match(/[\p{L}\p{N}]+/gu) ?? []).length, truncated: r.truncated, redacted: r.redacted, sections: cvSections(r.text) });
    } catch (e) {
      setErr(("hr3.cv.e." + (e instanceof CvError ? e.code : "read")) as DictKey);
    } finally {
      setStep(null);
      if (input.current) input.current.value = "";
    }
  };
  const pct = step?.k === "page" ? Math.round((step.i / step.n) * 100) : step?.k === "parse" ? 60 : 8;
  const stepTxt = !step ? "" : step.k === "page" ? t("hr3.cv.st.page", { i: fmt(step.i), n: fmt(step.n) }) : step.k === "parse" ? t("hr3.cv.st.parse") : t("hr3.cv.st.open");

  if (meta && !step) {
    return (
      <div className="hx-cvcard" role="status">
        <span className="ic ok" aria-hidden="true">{FileIcon}</span>
        <div className="bd">
          <b className="fn">{meta.name}</b>
          <span className="mt">
            {meta.pages != null && <span>{t(meta.pages === 1 ? "hr3.cv.page1" : "hr3.cv.pages", { n: fmt(meta.pages) })}</span>}
            <span>{t("hr3.cv.words", { n: fmt(meta.words) })}</span>
            {meta.sections.length > 0 && <span>{t("hr3.cv.sections", { n: fmt(meta.sections.length) })}</span>}
            {links.length > 0 && <span>{t(links.length === 1 ? "hr3.cv.link1" : "hr3.cv.links", { n: fmt(links.length) })}</span>}
          </span>
          {meta.sections.length > 0 && <span className="chips">{meta.sections.map((s) => <i key={s}>{t(("hr3.cv.sec." + s) as DictKey)}</i>)}</span>}
          <span className="nt">{t("hr3.cv.ready")}{meta.redacted > 0 ? " " + t("hr3.cv.redacted", { n: fmt(meta.redacted) }) : ""}{meta.truncated ? " " + t("hr3.cv.trunc") : ""}</span>
        </div>
        <div className="ac">
          <button type="button" className="btn ghost sm" onClick={() => input.current?.click()}>{t("hr3.cv.replace")}</button>
          <button type="button" className="btn ghost sm" onClick={onClear} aria-label={t("hr3.cv.remove")}>✕</button>
        </div>
        <input ref={input} type="file" accept={CV_ACCEPT} hidden onChange={(e) => take(e.target.files?.[0])} />
      </div>
    );
  }
  return (
    <div className={"hx-drop" + (over ? " over" : "") + (step ? " busy" : "")}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files?.[0]); }}>
      <span className="ic" aria-hidden="true">{UpIcon}</span>
      <div className="bd">
        <b>{t("hr3.cv.h")} <span className="rec">{t("hr3.cv.rec")}</span></b>
        <span>{t("hr3.cv.p")}</span>
        {step ? (
          <span className="prog" role="status" aria-live="polite">
            <span className="bar" aria-hidden="true"><i style={{ width: pct + "%" }} /></span>
            <span className="st"><span className="spinner" aria-hidden="true" />{stepTxt}</span>
          </span>
        ) : <small>{t("hr3.cv.types")}</small>}
        {err && <span className="err" role="alert">{t(err)}</span>}
      </div>
      <button type="button" className="btn sm" disabled={!!step} onClick={() => input.current?.click()}>{t("hr3.cv.pick")}</button>
      <input ref={input} type="file" accept={CV_ACCEPT} hidden onChange={(e) => take(e.target.files?.[0])} aria-label={t("hr3.cv.pick")} />
    </div>
  );
}
