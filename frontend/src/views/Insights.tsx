import { api } from '../api';
import { delta, fmt, usd } from '../format';
import { Eyebrow, Head, Status, useFetch } from '../ui';

const money = new Set(['cost_usd']);
// Session counts stay in the strips below; the top line is about work and output.
const HIDE = new Set(['claude_sessions', 'automated_sessions', 'codex_sessions']);
const show = (key: string, v: number) => (money.has(key) ? usd(v) : fmt(v));

/** Rolling last 7 days vs the 7 before: the stat strip of every metric with a
 *  coloured change, then projects with activity by commits. */
export default function Insights() {
  const { data, error, loading } = useFetch(() => api.insights(), []);
  return (
    <section id="insights" style={{ paddingTop: 40 }}>
      <Head eyebrow="rolling 7 days" title="This week" lede={data ? `${data.start} → ${data.end}, against ${data.prior_start} → ${data.prior_end}. The strips below show the same metrics over time.` : undefined} />
      <Status loading={loading} error={error} />
      {data && (
        <>
          <div className="stats">
            {data.metrics.filter((m) => !HIDE.has(m.key)).map((m) => {
              const d = delta(m.value, m.prior);
              return (
                <div key={m.key} title={m.note}>
                  <div className="v">{show(m.key, m.value)}</div>
                  <div className="l">{m.label}</div>
                  <div className={'d ' + d.cls}>{d.text} <span className="muted">· prior {show(m.key, m.prior)}</span></div>
                </div>
              );
            })}
          </div>
          <div className="card" style={{ marginTop: 24, padding: 0, border: '1px solid var(--line)' }}>
            <div style={{ padding: '14px 16px 0' }}><Eyebrow>Projects with activity · by commits · last 7 days</Eyebrow></div>
            <div className="tbl compact" style={{ borderTop: 0 }}>
              <table>
                <thead><tr><th>project</th><th className="num">commits</th><th className="num">PRs</th><th className="num">pages</th><th className="num">deploys</th><th className="num">out tokens</th><th className="num">$</th></tr></thead>
                <tbody>
                  {data.projects.map((p) => (
                    <tr key={p.project}>
                      <td><strong>{p.project}</strong></td>
                      <td className="num" style={{ fontWeight: 600 }}>{p.commits}</td>
                      <td className="num">{p.prs}</td><td className="num">{p.pages}</td><td className="num">{p.deploys}</td>
                      <td className="num">{fmt(p.tok_out)}</td><td className="num">{usd(p.cost_usd)}</td>
                    </tr>
                  ))}
                  {data.projects.length === 0 && <tr><td colSpan={7} className="muted">no activity in the last 7 days</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
