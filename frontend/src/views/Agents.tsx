import { useState } from 'react';
import { api } from '../api';
import { SERIES, dur, fmt, shortDate, usd } from '../format';
import { Bar, Eyebrow, Head, Status, Tag, Toggle, useFetch } from '../ui';

export default function Agents() {
  const [days, setDays] = useState<'7' | '30' | '90'>('30');
  const { data, error, loading } = useFetch(() => api.agents(+days), [days]);
  const models = [...new Set(data?.by_day_model.map((r) => r.model) ?? [])];
  const byModel = models.map((m) => ({ model: m, tok_out: data!.by_day_model.filter((r) => r.model === m).reduce((a, r) => a + r.tok_out, 0), cost: data!.by_day_model.filter((r) => r.model === m).reduce((a, r) => a + r.cost_usd, 0), msgs: data!.by_day_model.filter((r) => r.model === m).reduce((a, r) => a + r.msgs, 0) })).sort((a, b) => b.cost - a.cost);
  const days_ = [...new Set(data?.by_day_model.map((r) => r.day) ?? [])].sort();
  const dayTotals = days_.map((d) => ({ d, v: data!.by_day_model.filter((r) => r.day === d).reduce((a, r) => a + r.cost_usd, 0) }));
  const maxDay = Math.max(1, ...dayTotals.map((x) => x.v));
  const cache = data?.cache;
  const hit = cache && cache.cache_read + cache.uncached > 0 ? cache.cache_read / (cache.cache_read + cache.uncached) : null;
  const top = (data?.sessions ?? []).filter((s) => s.prompts > 0).slice(0, 40);
  const dayStart = (iso: string) => new Date(iso.slice(0, 10) + 'T00:00:00');
  return (
    <section id="agents">
      <Head eyebrow="Effort" title="Agents" lede="Tokens and list-price cost by model, class and project; cache economics; one bar per session.">
        <Toggle value={days} options={[['7', '7 days'], ['30', '30 days'], ['90', '90 days']]} onChange={setDays} />
      </Head>
      <Status loading={loading} error={error} />
      {data && (
        <>
          <div className="cards c3">
            <div className="card">
              <Eyebrow>By model · list price</Eyebrow>
              {byModel.map((m, i) => <Bar key={m.model} label={m.model.replace('claude-', '').replace(/-\d{8}$/, '')} v={m.cost} max={Math.max(1, ...byModel.map((x) => x.cost))} color={SERIES[i % SERIES.length]} n={`${usd(m.cost)} · ${fmt(m.tok_out)} out`} />)}
            </div>
            <div className="card">
              <Eyebrow>By class</Eyebrow>
              {data.by_class.map((c, i) => <Bar key={c.cls} label={c.cls} v={c.tok_out} max={Math.max(1, ...data.by_class.map((x) => x.tok_out))} color={SERIES[i % SERIES.length]} n={`${fmt(c.tok_out)} · ${usd(c.cost_usd)}`} />)}
            </div>
            <div className="card dark">
              <Eyebrow>Cache economics · Claude Code</Eyebrow>
              <div style={{ fontFamily: 'var(--cond)', fontWeight: 700, fontSize: 40, lineHeight: 1 }}>{hit === null ? '–' : `${(hit * 100).toFixed(2)}%`}</div>
              <div className="small">of input tokens served from cache</div>
              <div className="small muted">{fmt(cache?.cache_read)} read · {fmt(cache?.cache_write)} written · {fmt(cache?.uncached)} uncached</div>
              <div className="small muted" style={{ marginTop: 8 }}>Tools by session: {data.tools.slice(0, 8).map((t) => `${t.tool} ${t.sessions}`).join(' · ')}</div>
            </div>
          </div>
          <div className="card" style={{ marginTop: 24, border: '1px solid var(--line)' }}>
            <Eyebrow>Cost per day</Eyebrow>
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${dayTotals.length}, minmax(0,1fr))`, gap: 2, alignItems: 'end', height: 120 }}>
              {dayTotals.map((d) => <div key={d.d} title={`${d.d} · ${usd(d.v)}`} style={{ height: `${(d.v / maxDay) * 100}%`, background: 'var(--ink)', minHeight: d.v ? 2 : 0 }} />)}
            </div>
            <div className="small muted" style={{ display: 'flex', justifyContent: 'space-between' }}><span>{dayTotals[0]?.d}</span><span>{dayTotals[dayTotals.length - 1]?.d}</span></div>
          </div>
          <div className="card" style={{ marginTop: 24, border: '1px solid var(--line)' }}>
            <Eyebrow>Sessions · most recent interactive {top.length}</Eyebrow>
            <div className="gantt">
              {top.map((s, i) => {
                const start = dayStart(s.first_ts);
                const a = (new Date(s.first_ts).getTime() - start.getTime()) / 864e5;
                const w = Math.max(0.004, s.seconds / 86400);
                return (
                  <div className="row" key={s.session_id ?? i}>
                    <span title={s.first_ts}>{shortDate(s.first_ts)} · {s.project ?? '—'}</span>
                    <div className="track" title={`${s.cls} · ${s.messages} msgs · ${fmt(s.tok_out)} out · ${usd(s.cost_usd)} · ${dur(s.seconds)}${s.branch ? ' · ' + s.branch : ''}`}>
                      <div className="seg" style={{ left: `${a * 100}%`, width: `${w * 100}%`, background: SERIES[['building', 'evals', 'writing', 'review', 'infra', 'unknown'].indexOf(s.cls) % SERIES.length] }} />
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="small muted">bar = position and length within its day · colour = class {['building', 'evals', 'writing', 'review', 'infra', 'unknown'].map((c, i) => <Tag key={c}><i style={{ display: 'inline-block', width: 8, height: 8, background: SERIES[i], marginRight: 4 }} />{c}</Tag>)}</div>
          </div>
          <div className="cards c2" style={{ marginTop: 24 }}>
            <div className="card">
              <Eyebrow>By project × class</Eyebrow>
              <div className="tbl" style={{ borderTop: 0 }}><table><thead><tr><th>project</th><th>class</th><th className="num">out tokens</th><th className="num">$</th></tr></thead><tbody>
                {data.by_project.slice(0, 24).map((r, i) => <tr key={i}><td>{r.project}</td><td>{r.cls}</td><td className="num">{fmt(r.tok_out)}</td><td className="num">{usd(r.cost_usd)}</td></tr>)}
              </tbody></table></div>
            </div>
            <div className="card">
              <Eyebrow>Models · messages</Eyebrow>
              {byModel.map((m, i) => <Bar key={m.model} label={m.model.replace('claude-', '')} v={m.msgs} max={Math.max(1, ...byModel.map((x) => x.msgs))} color={SERIES[i % SERIES.length]} />)}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
