import { useState } from 'react';
import { api } from '../api';
import { SERIES, fmt, shortDate } from '../format';
import { Eyebrow, Head, Status, Tag, Toggle, useFetch } from '../ui';

export default function GitHubView() {
  const [days, setDays] = useState<'30' | '90' | '365'>('90');
  const { data, error, loading } = useFetch(() => api.github(+days), [days]);
  const byDay = new Map<string, number>();
  data?.commits.forEach((c) => byDay.set(c.day, (byDay.get(c.day) ?? 0) + c.commits));
  const dayList = [...byDay.entries()].sort();
  const maxC = Math.max(1, ...dayList.map(([, v]) => v));
  const ciPass = data ? data.ci.reduce((a, r) => a + r.passed, 0) : 0;
  const ciRuns = data ? data.ci.reduce((a, r) => a + r.runs, 0) : 0;
  const gates = data ? data.gates.reduce((acc, g) => ({ ...acc, [g.status]: (acc[g.status] ?? 0) + g.n }), {} as Record<string, number>) : {};
  const merged = data?.prs.filter((p) => p.kind === 'pr_merged') ?? [];
  return (
    <section id="github">
      <Head eyebrow="Delivery" title="GitHub & git" lede="Commits from every local repo (including branches only pushed to the no-mistakes gate), merged PRs, CI outcomes and gate runs.">
        <Toggle value={days} options={[['30', '30 days'], ['90', '90 days'], ['365', '365 days']]} onChange={setDays} />
      </Head>
      <Status loading={loading} error={error} />
      {data && (
        <>
          <div className="stats">
            <div><div className="v">{fmt(dayList.reduce((a, [, v]) => a + v, 0))}</div><div className="l">commits</div><div className="d">{dayList.length} active days</div></div>
            <div><div className="v">{merged.length}</div><div className="l">PRs merged</div><div className="d">{data.prs.length - merged.length} opened</div></div>
            <div><div className="v">{ciRuns ? `${Math.round((ciPass / ciRuns) * 100)}%` : '–'}</div><div className="l">CI pass rate</div><div className="d">{ciRuns} runs</div></div>
            <div><div className="v">{fmt(data.commits.reduce((a, c) => a + c.insertions, 0))}</div><div className="l">lines added</div><div className="d">{fmt(data.commits.reduce((a, c) => a + c.deletions, 0))} removed</div></div>
            <div><div className="v">{gates['passed'] ?? 0}/{(gates['passed'] ?? 0) + (gates['failed'] ?? 0)}</div><div className="l">gate runs passed</div><div className="d">no-mistakes</div></div>
          </div>
          <div className="card" style={{ marginTop: 24, border: '1px solid var(--line)' }}>
            <Eyebrow>Commits per day</Eyebrow>
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(dayList.length, 1)}, minmax(0,1fr))`, gap: 2, alignItems: 'end', height: 100 }}>
              {dayList.map(([d, v]) => <div key={d} title={`${d} · ${v} commits`} style={{ height: `${(v / maxC) * 100}%`, background: 'var(--ink)', minHeight: 2 }} />)}
            </div>
          </div>
          <div className="cards c2" style={{ marginTop: 24 }}>
            <div className="card">
              <Eyebrow>Merged PRs</Eyebrow>
              <ul className="tl">
                {merged.slice(0, 30).map((p, i) => <li key={i}><span className="when">{shortDate(p.day)}</span><Tag>{p.project}</Tag><span>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">#{p.number} {p.title}</a> : p.title}</span></li>)}
                {merged.length === 0 && <li style={{ gridTemplateColumns: '1fr' }} className="muted">no merged PRs in range — run <code>pt github backfill</code></li>}
              </ul>
            </div>
            <div className="card">
              <Eyebrow>Branches worked on</Eyebrow>
              <div className="tbl" style={{ borderTop: 0 }}><table><thead><tr><th>project</th><th>branch</th><th className="num">commits</th><th>first</th><th>last</th></tr></thead><tbody>
                {data.branches.slice(0, 30).map((b, i) => <tr key={i}><td>{b.project}</td><td className="mono small">{b.branch ?? '·'}</td><td className="num">{b.commits}</td><td className="small">{shortDate(b.first_day)}</td><td className="small">{shortDate(b.last_day)}</td></tr>)}
              </tbody></table></div>
            </div>
          </div>
          <div className="card" style={{ marginTop: 24, border: '1px solid var(--line)' }}>
            <Eyebrow>CI runs per day</Eyebrow>
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(data.ci.length, 1)}, minmax(0,1fr))`, gap: 2, alignItems: 'end', height: 60 }}>
              {data.ci.map((r) => <div key={r.day} title={`${r.day} · ${r.passed} passed · ${r.failed} failed`} style={{ height: `${(r.runs / Math.max(1, ...data.ci.map((x) => x.runs))) * 100}%`, background: r.failed ? SERIES[0] : SERIES[2], minHeight: 2 }} />)}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
