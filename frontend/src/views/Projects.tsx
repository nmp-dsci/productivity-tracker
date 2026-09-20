import { useState } from 'react';
import { api } from '../api';
import { SERIES, fmt, shortDate, usd } from '../format';
import { Bar, Eyebrow, Head, Status, Tag, useFetch } from '../ui';

export default function Projects() {
  const [open, setOpen] = useState<string | null>(null);
  const { data, error, loading } = useFetch(() => api.projects(90), []);
  const detail = useFetch(() => (open ? api.project(open, 90) : Promise.resolve(null)), [open]);
  return (
    <section id="projects">
      <Head eyebrow="Per repo · last 90 days" title="Projects" lede="Effort beside output for every project: tokens and $ next to commits, PRs, pages, eval runs and deploys. Tokens per commit and $ per merged PR are the honest efficiency numbers." />
      <Status loading={loading} error={error} />
      {data && (
        <div className="tbl"><table><thead><tr>
          <th>project</th><th className="num">out tokens</th><th className="num">agent $</th><th className="num">aws $</th><th className="num">commits</th><th className="num">PRs</th><th className="num">pages</th><th className="num">evals</th><th className="num">deploys</th><th className="num">tok / commit</th><th className="num">$ / PR</th><th>last active</th></tr></thead><tbody>
          {data.map((p) => (
            <tr key={p.project} style={{ cursor: 'pointer', background: open === p.project ? 'var(--bg)' : undefined }} onClick={() => setOpen(open === p.project ? null : p.project)}>
              <td><strong>{p.project}</strong></td><td className="num">{fmt(p.tok_out)}</td><td className="num">{usd(p.agent_usd)}</td><td className="num">{p.aws_usd ? usd(p.aws_usd) : '–'}</td>
              <td className="num">{p.commits}</td><td className="num">{p.prs}</td><td className="num">{p.pages}</td><td className="num">{p.eval_runs}</td><td className="num">{p.deploys}</td>
              <td className="num">{p.commits ? fmt(p.tok_out / p.commits) : '–'}</td><td className="num">{p.prs ? usd(p.agent_usd / p.prs) : '–'}</td><td className="small">{shortDate(p.last_active)}</td>
            </tr>
          ))}
        </tbody></table></div>
      )}
      {open && detail.data && (
        <div className="cards c2" style={{ marginTop: 24 }}>
          <div className="card">
            <Eyebrow>{open} · tokens by class</Eyebrow>
            {detail.data.split.map((s, i) => <Bar key={s.cls} label={s.cls} v={s.tok_out} max={Math.max(1, ...detail.data!.split.map((x) => x.tok_out))} color={SERIES[i % SERIES.length]} />)}
            <Eyebrow>Daily · tokens (bars) and commits (dots)</Eyebrow>
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(detail.data.daily.length, 1)}, minmax(0,1fr))`, gap: 1, alignItems: 'end', height: 80 }}>
              {detail.data.daily.map((d) => <div key={d.day} title={`${d.day} · ${fmt(d.tok_out)} out · ${d.commits} commits`} style={{ height: `${(d.tok_out / Math.max(1, ...detail.data!.daily.map((x) => x.tok_out))) * 100}%`, background: d.commits ? SERIES[2] : 'var(--ink)', minHeight: 2 }} />)}
            </div>
          </div>
          <div className="card">
            <Eyebrow>{open} · ship log</Eyebrow>
            <ul className="tl">
              {detail.data.shiplog.map((s, i) => <li key={i}><span className="when">{shortDate(s.ts)}</span><Tag>{s.kind.replace('_', ' ')}</Tag><span>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : s.title} {s.status && <span className="muted">· {s.status}</span>}</span></li>)}
              {detail.data.shiplog.length === 0 && <li style={{ gridTemplateColumns: '1fr' }} className="muted">nothing shipped in range</li>}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
