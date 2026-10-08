import { useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import type { CI } from "../lib/api";

/* ---------- dot + 95% interval rows (one metric, one row per series) ---------- */
export interface IntervalRow {
  key: string;
  label: string;
  color: string;
  stat: CI | undefined;
}

export function IntervalRows({
  title,
  rows,
  format,
  better,
}: {
  title: string;
  rows: IntervalRow[];
  format: (v: number) => string;
  better?: "lower" | "higher";
}) {
  const values = rows.flatMap((r) => [r.stat?.lo, r.stat?.hi, r.stat?.mean]).filter((v): v is number => v !== null && v !== undefined);
  const lo = Math.min(0, ...values);
  const hi = Math.max(...values, lo + 1e-9);
  // Percent positions on an HTML track, so marks keep their shape at any width.
  const x = (v: number) => `${(3 + ((v - lo) / (hi - lo)) * 94).toFixed(2)}%`;
  return (
    <figure style={{ margin: 0 }}>
      <figcaption style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <span style={{ fontWeight: 500 }}>{title}</span>
        {better && <span className="muted" style={{ fontSize: 12 }}>{better} is better</span>}
      </figcaption>
      <div role="list">
        {rows.map((r) => {
          const s = r.stat;
          const ok = s && s.mean !== null;
          const ci = ok && s.lo !== null && s.hi !== null;
          return (
            <div key={r.key} role="listitem" className="interval-row">
              <span className="secondary">{r.label}</span>
              <span className="interval-track" aria-hidden="true">
                {ci && <span className="interval-ci" style={{ left: x(s.lo as number), width: `calc(${x(s.hi as number)} - ${x(s.lo as number)})`, background: r.color }} />}
                {ok && <span className="interval-dot" style={{ left: x(s.mean as number), background: r.color }} />}
              </span>
              <span className="num" style={{ textAlign: "right" }} title={ci ? `95% CI ${format(s.lo as number)} to ${format(s.hi as number)}` : undefined}>
                {ok ? format(s.mean as number) : "n/a"}
              </span>
            </div>
          );
        })}
      </div>
    </figure>
  );
}

/* ---------- line chart with CI wash, labelled extra points, crosshair tooltip ---------- */
export interface Series {
  key: string;
  name: string;
  color: string;
  dashed?: boolean;
  points: { x: number; y: number; lo?: number | null; hi?: number | null }[];
}

export interface Marker {
  key: string;
  name: string;
  x: number;
  y: number;
  color?: string;
}

function niceTicks(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo || 1;
  const step0 = span / (n - 1);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? step0;
  const start = Math.ceil(lo / step) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + step * 1e-6; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

export function LineChart({
  series,
  markers = [],
  xLabel,
  yLabel,
  formatX,
  formatY,
  xDomain,
  yDomain,
  identity = false,
  height = 260,
  ariaLabel,
  footer,
  width = 560,
  legend = true,
}: {
  series: Series[];
  markers?: Marker[];
  xLabel: string;
  yLabel: string;
  formatX: (v: number) => string;
  formatY: (v: number) => string;
  xDomain?: [number, number];
  yDomain?: [number, number];
  identity?: boolean;
  height?: number;
  ariaLabel: string;
  footer?: ReactNode;
  /** viewBox width: smaller values give larger text in small multiples. */
  width?: number;
  legend?: boolean;
}) {
  const m = { l: 60, r: 16, t: 12, b: 40 };
  const all = series.flatMap((s) => s.points);
  const xsAll = all.map((p) => p.x).concat(markers.map((k) => k.x));
  const ysAll = all.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y]).concat(markers.map((k) => k.y));
  const xd: [number, number] = xDomain ?? [Math.min(...xsAll), Math.max(...xsAll)];
  const yPad = (Math.max(...ysAll) - Math.min(...ysAll)) * 0.08 || 1;
  const yd: [number, number] = yDomain ?? [Math.min(...ysAll) - yPad, Math.max(...ysAll) + yPad];
  const sx = (v: number) => m.l + ((v - xd[0]) / (xd[1] - xd[0] || 1)) * (width - m.l - m.r);
  const sy = (v: number) => m.t + (1 - (v - yd[0]) / (yd[1] - yd[0] || 1)) * (height - m.t - m.b);
  const xs = useMemo(() => Array.from(new Set(series.flatMap((s) => s.points.map((p) => p.x)))).sort((a, b) => a - b), [series]);
  const [active, setActive] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  const descId = useId();

  const nearest = (px: number) => {
    let best = 0;
    xs.forEach((x, i) => {
      if (Math.abs(sx(x) - px) < Math.abs(sx(xs[best] ?? 0) - px)) best = i;
    });
    return best;
  };
  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    setActive(nearest(((e.clientX - rect.left) / rect.width) * width));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowRight") setActive((a) => Math.min(xs.length - 1, (a ?? -1) + 1));
    else if (e.key === "ArrowLeft") setActive((a) => Math.max(0, (a ?? 1) - 1));
    else if (e.key === "Escape") setActive(null);
    else return;
    e.preventDefault();
  };
  const ax = active !== null ? xs[active] : undefined;
  const yTicks = niceTicks(yd[0], yd[1]);
  const xTicks = xs.length <= 8 ? xs : niceTicks(xd[0], xd[1]);
  const tipLeft = ax !== undefined ? (sx(ax) / width) * 100 : 0;

  return (
    <div className="chart-box">
      <div className="legend" style={{ marginBottom: 8, display: legend ? undefined : "none" }}>
        {series.map((s) => (
          <span className="key" key={s.key}>
            {s.dashed ? <span className="swatch dash" style={{ borderTopColor: s.color }} /> : <span className="swatch line" style={{ background: s.color }} />}
            {s.name}
          </span>
        ))}
        {markers.map((k) => (
          <span className="key" key={k.key}>
            <span className="swatch" style={{ background: k.color ?? "var(--ink)", borderRadius: 1 }} />
            {k.name}
          </span>
        ))}
        {identity && (
          <span className="key">
            <span className="swatch dash" />
            perfect calibration
          </span>
        )}
      </div>
      <svg
        ref={ref}
        viewBox={`0 0 ${width} ${height}`}
        className="chart"
        role="img"
        aria-label={ariaLabel}
        aria-describedby={descId}
        tabIndex={0}
        onMouseMove={onMove}
        onMouseLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        <desc id={descId}>Use the left and right arrow keys to step through values.</desc>
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={m.l} x2={width - m.r} y1={sy(t)} y2={sy(t)} className="grid-line" />
            <text x={m.l - 8} y={sy(t) + 4} textAnchor="end">
              {formatY(t)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={`x${t}`} x={sx(t)} y={height - m.b + 16} textAnchor="middle">
            {formatX(t)}
          </text>
        ))}
        <line x1={m.l} x2={width - m.r} y1={height - m.b} y2={height - m.b} className="axis-line" />
        <text x={(m.l + width - m.r) / 2} y={height - 6} textAnchor="middle" className="title">
          {xLabel}
        </text>
        <text transform={`translate(12 ${(m.t + height - m.b) / 2}) rotate(-90)`} textAnchor="middle" className="title">
          {yLabel}
        </text>
        {identity && <line x1={sx(Math.max(xd[0], yd[0]))} y1={sy(Math.max(xd[0], yd[0]))} x2={sx(Math.min(xd[1], yd[1]))} y2={sy(Math.min(xd[1], yd[1]))} stroke="var(--ref)" strokeDasharray="4 4" />}
        {series.map((s) => {
          const band = s.points.filter((p) => p.lo !== null && p.lo !== undefined && p.hi !== null && p.hi !== undefined);
          const d = s.points.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
          const area =
            band.length > 1
              ? band.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.hi as number).toFixed(1)}`).join("") +
                [...band].reverse().map((p) => `L${sx(p.x).toFixed(1)},${sy(p.lo as number).toFixed(1)}`).join("") +
                "Z"
              : null;
          return (
            <g key={s.key}>
              {area && <path d={area} fill={s.color} opacity={0.1} />}
              <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? "5 4" : undefined} />
              {s.points.map((p) => (
                <circle key={p.x} cx={sx(p.x)} cy={sy(p.y)} r={3} fill={s.color} stroke="var(--surface)" strokeWidth={1.5} />
              ))}
            </g>
          );
        })}
        {markers.map((k) => (
          <g key={k.key}>
            <rect x={sx(k.x) - 6} y={sy(k.y) - 6} width={12} height={12} fill={k.color ?? "var(--ink)"} stroke="var(--surface)" strokeWidth={2} />
            <text x={sx(k.x) + 10} y={sy(k.y) - 8} style={{ fill: "var(--ink-2)" }}>
              {k.name}
            </text>
          </g>
        ))}
        {ax !== undefined && <line x1={sx(ax)} x2={sx(ax)} y1={m.t} y2={height - m.b} stroke="var(--ink-3)" strokeDasharray="2 3" />}
      </svg>
      {ax !== undefined && (
        <div className="tooltip" style={{ left: `min(calc(${tipLeft}% + 12px), calc(100% - 200px))`, top: 36 }} role="status">
          <div style={{ fontWeight: 500, marginBottom: 4 }}>
            {xLabel}: {formatX(ax)}
          </div>
          {series.map((s) => {
            const p = s.points.find((q) => q.x === ax);
            return (
              <div className="row" key={s.key}>
                <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                  <span className="swatch" style={{ background: s.color }} />
                  {s.name}
                </span>
                <span>{p ? formatY(p.y) : "n/a"}</span>
              </div>
            );
          })}
        </div>
      )}
      {footer}
    </div>
  );
}

/* ---------- table twin for any chart ---------- */
export function TableTwin({ caption, head, rows }: { caption: string; head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="table-twin">
      <summary>Show table</summary>
      <div className="table-wrap" tabIndex={0} style={{ marginTop: 8 }}>
        <table>
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {head.map((h, i) => (
                <th key={h} scope="col" className={i ? "r" : undefined}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((c, j) =>
                  j === 0 ? (
                    <th key={j} scope="row">
                      {c}
                    </th>
                  ) : (
                    <td key={j} className="r">
                      {c}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
