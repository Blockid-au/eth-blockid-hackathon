import { lazy, type ComponentType } from "react";

/* A deploy replaces the hashed /assets/*.js files. A tab opened before the deploy then fails to load a lazy chunk
 * (404 / "Failed to fetch dynamically imported module"). Recover by reloading the same URL ONCE (sessionStorage guard);
 * if it fails again the ErrorBoundary shows a friendly message with a Reload button instead of an endless spinner. */
const KEY = "blockid-chunk-reload";

export function isChunkError(e: unknown): boolean {
  const m = String((e as { message?: string })?.message ?? e ?? "");
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported|Loading chunk|preload/i.test(m);
}

/** Reload the page once per URL per 60 s. Returns false when a reload was already tried (caller shows an error). */
export function reloadOnce(): boolean {
  try {
    const raw = sessionStorage.getItem(KEY);
    const prev = raw ? (JSON.parse(raw) as { url: string; at: number }) : null;
    if (prev && prev.url === location.href && Date.now() - prev.at < 60_000) return false;
    sessionStorage.setItem(KEY, JSON.stringify({ url: location.href, at: Date.now() }));
  } catch {
    /* storage blocked: still try one reload */
  }
  location.reload();
  return true;
}

export function installChunkRecovery(): void {
  window.addEventListener("vite:preloadError", (ev) => {
    if (reloadOnce()) ev.preventDefault(); // otherwise let the error reach the ErrorBoundary
  });
}

/** React.lazy that turns a failed chunk load into one page reload (then a real error for the boundary). */
export function lazyPage<T extends ComponentType<any>>(load: () => Promise<{ default: T }>) { // eslint-disable-line @typescript-eslint/no-explicit-any
  return lazy(async () => {
    try {
      return await load();
    } catch (e) {
      if (isChunkError(e) && reloadOnce()) return new Promise<{ default: T }>(() => {}); // page is reloading
      throw e;
    }
  });
}
