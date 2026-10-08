import type { ReactNode } from "react";
import type { ApiError, Provenance, Status } from "../lib/api";
import { STATUS } from "../lib/format";

/** Status glyph. The half-filled circle is drawn, because fonts render U+25D0 inconsistently. */
export function Glyph({ glyph }: { glyph: string }) {
  if (glyph === "◐")
    return (
      <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden="true" style={{ flex: "none" }}>
        <circle cx="6" cy="6" r="4.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 1.25a4.75 4.75 0 0 1 0 9.5z" fill="currentColor" />
      </svg>
    );
  return (
    <span className="glyph" aria-hidden="true">
      {glyph}
    </span>
  );
}

/** Verification status: always a glyph and a word, never colour alone. */
export function StatusMark({ status, title }: { status: Status; title?: string }) {
  const s = STATUS[status];
  return (
    <span className={`mark ${s.tone}`} title={title ?? s.help}>
      <Glyph glyph={s.glyph} />
      {s.word}
    </span>
  );
}

export function Mark({ tone, glyph, children, title }: { tone: "ok" | "attest" | "bad" | "neutral"; glyph: string; children: ReactNode; title?: string }) {
  return (
    <span className={`mark ${tone}`} title={title}>
      <Glyph glyph={glyph} />
      {children}
    </span>
  );
}

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function Loading({ rows = 5, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="panel" role="status" aria-live="polite">
      <span className="sr-only">{label}…</span>
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Skeleton height={20} width="40%" />
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} height={26} />
        ))}
      </div>
    </div>
  );
}

export function ErrorPanel({ error, retry, what }: { error: ApiError; retry: () => void; what: string }) {
  return (
    <div className="state error" role="alert">
      <h2>Could not load {what}</h2>
      <p className="secondary">
        {error.status ? `HTTP ${error.status}: ` : ""}
        {error.message}
      </p>
      <p className="muted mono">{error.url}</p>
      <button className="btn" type="button" onClick={retry}>
        Retry
      </button>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <h2>{title}</h2>
      {children && <div className="secondary">{children}</div>}
    </div>
  );
}

export function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: T; label: string; title?: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.id)} type="button" aria-pressed={o.id === value} title={o.title} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function ProvenanceLine({ p }: { p: Provenance }) {
  return (
    <p className="muted small" style={{ margin: 0 }}>
      Source <code>results/{p.experiment}/{p.run_id}</code> · commit <code>{p.commit.slice(0, 7)}</code> · {p.seeds} seeds ×{" "}
      {p.n_claims.toLocaleString("en-GB")} claims · {p.runtime_seconds} s
    </p>
  );
}

export function PageHead({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Hash({ value, n = 10 }: { value: string | null | undefined; n?: number }) {
  if (!value) return <span className="hash">–</span>;
  return (
    <span className="hash" title={value}>
      <span aria-hidden="true">{value.slice(0, n)}…</span>
      <span className="sr-only">{value}</span>
    </span>
  );
}

export function Truth({ children }: { children: ReactNode }) {
  return (
    <div className="truth-box">
      <strong>Simulation ground truth.</strong> Not part of the record; an auditor would not see this. {children}
    </div>
  );
}
