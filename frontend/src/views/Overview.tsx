import { api } from '../api';
import { SERIES, delta, fmt, shortDate, usd } from '../format';
import { Bar, Eyebrow, Head, Status, useFetch } from '../ui';

const KPIS: [string, string, (n: number) => string][] = [
  ['cost_usd', 'agent $', usd], ['tokens_out', 'out tokens', fmt], ['claude_sessions', 'sessions', fmt], ['automated_sessions', 'automated', fmt], ['prompts', 'prompts', fmt],
  ['commits', 'commits', fmt], ['prs', 'PRs merged', fmt], ['deploys', 'deploys', fmt], ['lavish', 'lavish pages', fmt], ['projects', 'projects', fmt],
];

export default function Overview({ week, setWeek }: { week: string | undefined; setWeek: (w: string | undefined) => void }) {
  const { data, error, loading } = useFetch(() => api.overview(week), [week]);
  const shift = (days: number) => {
    const base = new Date((data?.week_start ?? new Date().toISOString().slice(0, 10)) + 'T00:00:00');
    base.setDate(base.getDate() + days);
    setWeek(base.toISOString().slice(0, 10));
  };
  const maxTok = Math.max(1, ...(data?.projects.map((p) => p.tok_out) ?? [0]));
  const build = data?.split.find((s) => s.cls === 'building')?.tok_out ?? 0;
  const evals = data?.split.find((s) => s.cls === 'evals')?.tok_out ?? 0;
  return (
    <section id="overview">
      <Head eyebrow="Monday summary" title="Overview" lede={data ? `Week of ${data.week_start} → ${data.week_end}, each number against the prior week.` : undefined}>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn ghost" onClick={() => shift(-7)}>← prev</button>
          <button className="btn ghost" onClick={() => setWeek(undefined)}>this week</button>
          <button className="btn ghost" onClick={() => shift(7)}>next →</button>
        </div>
      </Head>
      <Status loading={loading} error={error} />
      {data && (
        <>
          <div className="stats">
            {KPIS.map(([k, l, f]) => {
              const d = delta(data.kpis[k] ?? 0, data.prior[k] ?? 0);
              return (
                <div key={k}><div className="v">{f(data.kpis[k] ?? 0)}</div><div className="l">{l}</div><div className={'d ' + d.cls}>{d.text} <span className="muted">vs prior</span></div></div>
              );
            })}
            <div><div className="v">{build + evals > 0 ? `${Math.round((build / (build + evals)) * 100)}:${Math.round((evals / (build + evals)) * 100)}` : '–'}</div><div className="l">build : eval</div><div className="d">by output tokens</div></div>
          </div>
          <div className="cards c2" style={{ marginTop: 24 }}>
            <div className="card">
              <Eyebrow>Effort → output · by project</Eyebrow>
              <div className="bar muted" style={{ fontFamily: 'var(--cond)', letterSpacing: '.1em', textTransform: 'uppercase', fontSize: 11, gridTemplateColumns: '11rem minmax(0,1fr) 4rem 4rem 4rem' }}><span>project</span><span>agent tokens (out)</span><span className="n">commits</span><span className="n">PRs</span><span className="n">pages</span></div>
              {data.projects.map((p, i) => (
                <div className="bar" key={p.project} style={{ gridTemplateColumns: '11rem minmax(0,1fr) 4rem 4rem 4rem' }}>
                  <span>{p.project}</span>
                  <i style={{ width: `${(p.tok_out / maxTok) * 100}%`, background: SERIES[i % SERIES.length] }} />
                  <span className="n">{p.commits}</span><span className="n">{p.prs}</span><span className="n">{p.pages}</span>
                </div>
              ))}
              {data.projects.length === 0 && <div className="empty">no activity this week</div>}
            </div>
            <div className="card wine">
              <Eyebrow>Ship log · this week</Eyebrow>
              <ul className="tl">
                {data.shiplog.map((s, i) => (
                  <li key={i}><span className="when">{shortDate(s.day)}</span><span className="tag" style={{ borderColor: 'rgba(255,255,255,.4)', color: '#fff' }}>{s.kind.replace('_', ' ')}</span><span>{s.project} · {s.title ?? s.status ?? ''}</span></li>
                ))}
                {data.shiplog.length === 0 && <li style={{ gridTemplateColumns: '1fr', opacity: 0.8 }}>nothing left the laptop this week</li>}
              </ul>
            </div>
          </div>
          <div className="card" style={{ marginTop: 24, border: '1px solid var(--line)' }}>
            <Eyebrow>Where the tokens went · by class</Eyebrow>
            {data.split.map((s, i) => <Bar key={s.cls} label={s.cls} v={s.tok_out} max={Math.max(1, ...data.split.map((x) => x.tok_out))} color={SERIES[i % SERIES.length]} n={`${fmt(s.tok_out)} · ${usd(s.cost_usd)}`} />)}
          </div>
        </>
      )}
    </section>
  );
}
