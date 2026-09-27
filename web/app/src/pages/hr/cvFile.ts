/* Read a CV file in the browser (the file itself is never uploaded; only its text goes into the report).
   PDF: pdf.js, loaded on first use. DOCX: the zip's word/document.xml, inflated with the browser's
   DecompressionStream. TXT / MD: as text. `onStep` reports progress for the status line. */

export const CV_MAX_BYTES = 10 * 1024 * 1024;
export const CV_MAX_CHARS = 40_000;
export const CV_ACCEPT = ".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown";

export type CvStep = { k: "open" } | { k: "page"; i: number; n: number } | { k: "parse" };
export interface CvRead { text: string; pages: number | null; kind: "pdf" | "docx" | "text"; truncated: boolean; links: string[]; redacted: number }
export class CvError extends Error { constructor(public code: "type" | "size" | "empty" | "scan" | "read") { super(code); } }

const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g;
const PHONE = /(?:\+?\d[\d\s().-]{7,}\d)/g;
const URL_RX = /(?:https?:\/\/|www\.)[^\s<>()"']+|\b(?:linkedin\.com\/in|github\.com)\/[\w\-./]+/gi;

/** Emails and phone numbers out before the text leaves the browser (the server redacts again). */
export function redactContacts(s: string): { text: string; n: number } {
  let n = 0;
  const text = s.replace(EMAIL, () => (n++, "[email]")).replace(PHONE, (m) => {
    const d = m.replace(/\D/g, "");
    if (d.length < 9 || d.length > 15 || /^(19|20)\d\d\s*[-–]\s*(19|20)\d\d$/.test(m.trim())) return m;
    n++;
    return "[phone]";
  });
  return { text, n };
}

export function linksIn(s: string): string[] {
  const out: string[] = [];
  for (const m of s.match(URL_RX) ?? []) {
    let u = m.replace(/[.,;]+$/, "");
    if (!/^https?:/i.test(u)) u = "https://" + u;
    if (!out.includes(u)) out.push(u);
  }
  return out.slice(0, 8);
}

const tidy = (s: string) => s.replace(/\r/g, "").replace(/[ \t ]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();

async function readPdf(buf: ArrayBuffer, onStep: (s: CvStep) => void): Promise<{ text: string; pages: number }> {
  const [pdfjs, worker] = await Promise.all([import("pdfjs-dist/legacy/build/pdf.mjs"), import("pdfjs-dist/legacy/build/pdf.worker.min.mjs?url")]);
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  const doc = await pdfjs.getDocument({ data: new Uint8Array(buf), isEvalSupported: false }).promise;
  const parts: string[] = [];
  const n = Math.min(doc.numPages, 30);
  for (let i = 1; i <= n; i++) {
    onStep({ k: "page", i, n });
    const page = await doc.getPage(i);
    const tc = await page.getTextContent();
    let lastY: number | null = null, line = "";
    const lines: string[] = [];
    for (const it of tc.items as { str?: string; transform?: number[]; hasEOL?: boolean }[]) {
      if (typeof it.str !== "string") continue;
      const y = it.transform ? Math.round(it.transform[5]) : null;
      if (lastY != null && y != null && Math.abs(y - lastY) > 2 && line) { lines.push(line); line = ""; }
      line += (line && !line.endsWith(" ") && it.str && !it.str.startsWith(" ") ? " " : "") + it.str;
      if (it.hasEOL) { lines.push(line); line = ""; }
      lastY = y;
    }
    if (line) lines.push(line);
    parts.push(lines.join("\n"));
    page.cleanup();
  }
  await doc.destroy();
  return { text: parts.join("\n\n"), pages: doc.numPages };
}

async function inflate(data: Uint8Array): Promise<Uint8Array> {
  const ds = new DecompressionStream("deflate-raw");
  const out = await new Response(new Blob([data]).stream().pipeThrough(ds)).arrayBuffer();
  return new Uint8Array(out);
}

/** word/document.xml out of a .docx (zip), then paragraphs -> lines. */
async function readDocx(buf: ArrayBuffer): Promise<string> {
  const b = new Uint8Array(buf), v = new DataView(buf);
  let eocd = -1;
  for (let i = b.length - 22; i >= Math.max(0, b.length - 65_557); i--) if (v.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new CvError("read");
  let p = v.getUint32(eocd + 16, true);
  const count = v.getUint16(eocd + 10, true);
  const dec = new TextDecoder();
  for (let k = 0; k < count && p + 46 <= b.length; k++) {
    if (v.getUint32(p, true) !== 0x02014b50) break;
    const method = v.getUint16(p + 10, true), csize = v.getUint32(p + 20, true);
    const nlen = v.getUint16(p + 28, true), xlen = v.getUint16(p + 30, true), clen = v.getUint16(p + 32, true);
    const local = v.getUint32(p + 42, true);
    const name = dec.decode(b.subarray(p + 46, p + 46 + nlen));
    if (name === "word/document.xml") {
      const start = local + 30 + v.getUint16(local + 26, true) + v.getUint16(local + 28, true);
      const raw = b.subarray(start, start + csize);
      const xml = dec.decode(method === 0 ? raw : await inflate(raw));
      const doc = new DOMParser().parseFromString(xml, "application/xml");
      const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
      const lines: string[] = [];
      for (const para of Array.from(doc.getElementsByTagNameNS(W, "p"))) {
        let s = "";
        const walk = (n: Element) => {
          for (const c of Array.from(n.children)) {
            if (c.namespaceURI === W && c.localName === "t") s += c.textContent ?? "";
            else if (c.namespaceURI === W && c.localName === "tab") s += "\t";
            else if (c.namespaceURI === W && (c.localName === "br" || c.localName === "cr")) s += "\n";
            else if (!(c.namespaceURI === W && c.localName === "p")) walk(c);
          }
        };
        walk(para);
        lines.push(s);
      }
      return lines.join("\n");
    }
    p += 46 + nlen + xlen + clen;
  }
  throw new CvError("read");
}

export async function readCvFile(f: File, onStep: (s: CvStep) => void = () => {}): Promise<CvRead> {
  const ext = (f.name.split(".").pop() || "").toLowerCase();
  const kind = ext === "pdf" || f.type === "application/pdf" ? "pdf" : ext === "docx" ? "docx" : ["txt", "md", "markdown", "text"].includes(ext) || f.type.startsWith("text/") ? "text" : null;
  if (!kind) throw new CvError(ext === "doc" ? "type" : "type");
  if (f.size > CV_MAX_BYTES) throw new CvError("size");
  onStep({ k: "open" });
  let text = "", pages: number | null = null;
  try {
    const buf = await f.arrayBuffer();
    if (kind === "pdf") ({ text, pages } = await readPdf(buf, onStep));
    else if (kind === "docx") { onStep({ k: "parse" }); text = await readDocx(buf); }
    else text = new TextDecoder().decode(buf);
  } catch (e) {
    if (e instanceof CvError) throw e;
    throw new CvError("read");
  }
  text = tidy(text);
  if (text.replace(/\W/g, "").length < 40) throw new CvError(kind === "pdf" ? "scan" : "empty");
  const links = linksIn(text);
  const r = redactContacts(text);
  const truncated = r.text.length > CV_MAX_CHARS;
  return { text: truncated ? r.text.slice(0, CV_MAX_CHARS) : r.text, pages, kind, truncated, links, redacted: r.n };
}
