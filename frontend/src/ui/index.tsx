import { useEffect, useState, type ReactNode } from 'react';
import { RAMP, fmt, growthText, level } from '../format';

export const Eyebrow = ({ children, pill }: { children: ReactNode; pill?: boolean }) => (
  <div className={'eyebrow' + (pill ? ' pill' : '')}>{children}</div>
);

export const Head = ({ eyebrow, title, lede, children }: { eyebrow: string; title: string; lede?: ReactNode; children?: ReactNode }) => (
  <div className="head">
    <Eyebrow>{eyebrow}</Eyebrow>
    <h2>{title}</h2>
    {lede && <p className="lede">{lede}</p>}
    {children}
  </div>
);

export const Tag = ({ children, kind }: { children: ReactNode; kind?: 'yes' | 'gold' | 'wine' }) => (
  <span className={'tag' + (kind ? ' ' + kind : '')}>{children}</span>
);

export const Toggle = <T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) => (
  <div className="toggle" role="tablist">
    {options.map(([v, label]) => (
      <button key={v} type="button" role="tab" className={v === value ? 'on' : ''} onClick={() => onChange(v)}>
        {label}
      </button>
    ))}
  </div>
);

export const Stats = ({ items }: { items: { v: string; l: string; d?: ReactNode }[] }) => (
  <div className="stats">
    {items.map((it) => (
      <div key={it.l}>
        <div className="v">{it.v}</div>
        <div className="l">{it.l}</div>
        {it.d && <div className="d">{it.d}</div>}
      </div>
    ))}
  </div>
);

export const Bar = ({ label, v, max, color, n }: { label: ReactNode; v: number; max: number; color?: string; n?: string }) => (
  <div className="bar">
    <span>{label}</span>
    <i style={{ width: `${max > 0 ? (v / max) * 100 : 0}%`, background: color ?? 'var(--ink)' }} />
    <span className="n">{n ?? fmt(v)}</span>
  </div>
);

export const Sparkline = ({ values, height = 40 }: { values: number[]; height?: number | string }) => {
  const W = 200, H = 80, n = values.length, max = Math.max(1, ...values);
  const pts = values.map((v, i) => [(i / Math.max(n - 1, 1)) * W, H - (v / max) * H * 0.9] as const);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ height }} aria-label="sparkline">
      <path d={`${line} L${W} ${H} L0 ${H} Z`} fill="var(--ink)" fillOpacity=".1" />
      <path d={line} fill="none" stroke="var(--ink)" strokeOpacity=".7" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
};

export const Growth = ({ wow, w4 }: { wow: number | null; w4: number | null }) => (
  <div className="growth">
    {[
      [wow, 'wow', 'this week vs last'],
      [w4, '4w', 'last 4 weeks vs prior 4'],
    ].map(([g, lab, title]) => {
      const t = growthText(g as number | null);
      return (
        <span key={lab as string} className={'g ' + t.cls} title={title as string}>
          {t.text}
          <small>{lab as string}</small>
        </span>
      );
    })}
  </div>
);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export type HoverInfo = { x: number; y: number; body: ReactNode } | null;

/** One strip per metric: rolling days (thin cells) or weeks (wide cells). */
export const Strip = ({ cells, grain, label, onHover, onClick, format = fmt }: {
  cells: { d: string; end?: string; v: number; done: boolean }[]; grain: 'day' | 'week'; label: string;
  onHover: (h: HoverInfo) => void; onClick?: (d: string) => void; format?: (v: number) => string;
}) => {
  const C = grain === 'day' ? 5 : 36, G = grain === 'day' ? 1 : 4, Hc = 26, top = 13;
  const W = cells.length * (C + G), H = top + Hc;
  // The period in progress is excluded from the scale as well as the totals.
  const max = Math.max(1, ...cells.filter((c) => c.done).map((c) => c.v));
  let lastM = -1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label={label}>
      <rect x="0" y={top} width={W - G} height={Hc} fill="var(--ink)" fillOpacity=".04" />
      {cells.map((c, i) => {
        const m = +c.d.slice(5, 7) - 1;
        const showMonth = m !== lastM;
        lastM = m;
        const l = level(c.v, max);
        const tip = (
          <>
            <b>{grain === 'week' ? `7 days to ${c.end ?? c.d}` : c.d}</b>
            <br />{label}: {format(c.v)}
            {!c.done && <><br /><i>{grain === 'week' ? 'week' : 'day'} still in progress — not counted</i></>}
          </>
        );
        return (
          <g key={c.d}>
            {showMonth && <text x={i * (C + G)} y="10">{MONTHS[m]}</text>}
            <rect
              x={i * (C + G)} y={top} width={C} height={Hc}
              fill={c.done ? (l ? RAMP[l - 1] : 'transparent') : 'transparent'}
              fillOpacity={c.done ? 1 : 0}
              stroke={c.done ? 'none' : 'var(--muted)'} strokeWidth={c.done ? 0 : 1} strokeDasharray="2 2"
              style={{ cursor: onClick ? 'pointer' : 'default' }}
              onMouseEnter={(e) => onHover({ x: e.clientX, y: e.clientY, body: tip })}
              onMouseMove={(e) => onHover({ x: e.clientX, y: e.clientY, body: tip })}
              onMouseLeave={() => onHover(null)}
              onClick={() => onClick?.(c.d)}
            />
          </g>
        );
      })}
    </svg>
  );
};

export const Tooltip = ({ info }: { info: HoverInfo }) =>
  info ? <div className="tip" style={{ left: info.x + 12, top: info.y + 12 }}>{info.body}</div> : null;

export function useFetch<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean } {
  const [state, set] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    set((s) => ({ ...s, loading: true }));
    fn().then((data) => live && set({ data, error: null, loading: false })).catch((e: Error) => live && set({ data: null, error: e.message, loading: false }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export const Status = ({ loading, error }: { loading: boolean; error: string | null }) =>
  error ? <div className="note err">{error}</div> : loading ? <div className="empty">loading…</div> : null;
