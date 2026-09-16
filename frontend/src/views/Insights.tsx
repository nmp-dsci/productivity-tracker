import { api } from '../api';
import { fmt, usd } from '../format';
import { Eyebrow, Head, Status, useFetch } from '../ui';

const money = new Set(['cost_usd']);
const show = (key: string, v: number) => (money.has(key) ? usd(v) : fmt(v));

/** Rolling last 7 days vs the 7 before. Left: every metric as a row with
 *  both numbers and a coloured change. Right: projects with activity, by commits. */
export default function Insights() {
  const { data, error, loading } = useFetch(() => api.insights(), []);
  return (
    <section id="insights" style={{ paddingTop: 40 }}>
      <Head eyebrow="rolling 7 days" title="This week" lede={data ? `${data.start} → ${data.end}, against ${data.prior_start} → ${data.prior_end}. The strips below show the same metrics over time.` : undefined} />
      <Status loading={loading} error={error} />
      {data && (
        <div className="cards c2">
          <div className="card" style={{ padding: 0 }}>
            <div className="tbl" style={{ borderTop: 0 }}>
              <table>
                <thead><tr><th>metric</th><th className="num">last 7</th><th className="num">prior 7</th><th className="num">change</th></tr></thead>
                <tbody>
                  {data.metrics.map((m) => {
                    const diff = m.value - m.prior;
                    const cls = diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat';
                    const sign = diff > 0 ? '+' : diff < 0 ? '−' : '';
                    const pct = m.prior > 0 ? ` (${diff > 0 ? '+' : diff < 0 ? '−' : ''}${Math.abs(Math.round((diff / m.prior) * 100))}%)` : m.value > 0 ? ' (new)' : '';
                    return (
                      <tr key={m.key} title={m.note}>
                        <td><strong>{m.label}</strong><div className="small muted">{m.note}</div></td>
                        <td className="num" style={{ fontFamily: 'var(--cond)', fontSize: 20, fontWeight: 700 }}>{show(m.key, m.value)}</td>
                        <td className="num muted">{show(m.key, m.prior)}</td>
                        <td className={'num ' + cls} style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{sign}{show(m.key, Math.abs(diff))}{pct}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="card" style={{ padding: 0 }}>
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
        </div>
      )}
    </section>
  );
}
