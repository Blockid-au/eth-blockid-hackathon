import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { isChunkError } from "../lib/chunks";

function Fallback({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useI18n();
  const chunk = isChunkError(error);
  return (
    <div className="wrap page stack" role="alert">
      <p className="banner warn">
        <span>{chunk ? t("err.chunk") : t("err.crash")}</span>
      </p>
      <div className="row">
        <button className="btn" type="button" onClick={() => location.reload()}>{t("err.reload")}</button>
        {!chunk && <button className="btn ghost" type="button" onClick={onRetry}>{t("common.retry")}</button>}
      </div>
    </div>
  );
}

/** Route-level error boundary: a failed lazy chunk or a render crash never leaves a blank or frozen screen. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: unknown }> {
  state = { error: null as unknown };
  static getDerivedStateFromError(error: unknown) {
    return { error };
  }
  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("page error", error, info.componentStack);
  }
  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (this.state.error) return <Fallback error={this.state.error} onRetry={() => this.setState({ error: null })} />;
    return this.props.children;
  }
}

/** Suspense fallback: spinner, then after 8 s a "Still loading… Reload" hint (never an endless spinner). */
export function PageLoading() {
  const { t } = useI18n();
  const [slow, setSlow] = useState(false);
  useEffect(() => { const id = setTimeout(() => setSlow(true), 8000); return () => clearTimeout(id); }, []);
  return (
    <div className="wrap page" aria-busy="true">
      <p className="muted row" role="status"><span className="spinner" aria-hidden="true" />{slow ? t("err.slow") : t("common.loading")}
        {slow && <button className="btn ghost sm" type="button" onClick={() => location.reload()}>{t("err.reload")}</button>}
      </p>
    </div>
  );
}
