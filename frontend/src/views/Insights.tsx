import { api } from '../api';
import { delta, fmt, usd } from '../format';
import { Eyebrow, Head, Status, useFetch } from '../ui';

const money = new Set(['cost_usd']);

/** Rolling last 7 days vs the 7 before: one chip per metric, then the
 *  narrative. Sits above the strips on the home page and introduces them. */
export default function Insights() {
  const { data, error, loading } = useFetch(() => api.insights(), []);
  return (
    <section id="insights" style={{ paddingTop: 40 }}>
      <Head eyebrow={data ? `rolling 7 days · ${data.start} → ${data.end} · vs ${data.prior_start} → ${data.prior_end}` : 'rolling 7 days'} title="This week" lede="Every metric for the last seven days against the seven before. The strips below show the same metrics over time." />
      <Status loading={loading} error={error} />
      {data && (
        <>
          <div className="stats">
            {data.metrics.map((m) => {
              const d = delta(m.value, m.prior);
              return (
                <div key={m.key} title={`${m.note} · prior ${money.has(m.key) ? usd(m.prior) : fmt(m.prior)}`}>
                  <div className="v">{money.has(m.key) ? usd(m.value) : fmt(m.value)}</div>
                  <div className="l">{m.label}</div>
                  <div className={'d ' + d.cls}>{d.text} <span className="muted">vs prior 7</span></div>
                </div>
              );
            })}
          </div>
          <div className="cards c3" style={{ marginTop: 24 }}>
            <div className="card wine" style={{ gridColumn: 'span 2', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
              <Eyebrow>What changed{data.narrative_end ? ` · drafted ${data.narrative_end}` : ''}</Eyebrow>
              {data.narrative ?? <span style={{ opacity: 0.8 }}>No narrative yet — run <code style={{ background: 'rgba(0,0,0,.3)', color: '#fff' }}>pt weekly</code> (the launchd job does this daily).</span>}
            </div>
            <div className="card">
              <Eyebrow>Shipped · last 7 days</Eyebrow>
              <ul className="tl">
                {data.shiplog.slice(0, 12).map((s, i) => (
                  <li key={i} style={{ gridTemplateColumns: '3rem 1fr' }}><span className="when">{s.day.slice(5)}</span><span><span className="tag">{s.kind.replace('_', ' ')}</span> {s.project} · {s.title ?? s.status ?? ''}</span></li>
                ))}
                {data.shiplog.length === 0 && <li style={{ gridTemplateColumns: '1fr' }} className="muted">nothing left the laptop</li>}
              </ul>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
