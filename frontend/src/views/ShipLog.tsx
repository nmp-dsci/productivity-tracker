import { api } from '../api';
import { shortDate } from '../format';
import { Head, Status, Tag, useFetch } from '../ui';

const KIND_TAG: Record<string, 'yes' | 'gold' | 'wine' | undefined> = { pr_merged: 'yes', apprunner_deploy: 'wine', deployment_status: 'wine', release: 'wine', page_created: 'gold' };

export default function ShipLog() {
  const { data, error, loading } = useFetch(() => api.shiplog(300), []);
  return (
    <section id="shiplog">
      <Head eyebrow="What left the laptop" title="Ship log" lede="Merged PRs, deployments, releases, review pages, eval runs and gate runs — in order. Commits are effort, so they are not here." />
      <Status loading={loading} error={error} />
      {data && (
        <div className="tbl"><table><thead><tr><th>when</th><th>kind</th><th>project</th><th>what</th><th>status</th></tr></thead><tbody>
          {data.map((s, i) => (
            <tr key={i}>
              <td className="mono small">{s.ts.slice(0, 16).replace('T', ' ')}</td>
              <td><Tag kind={KIND_TAG[s.kind]}>{s.kind.replace('_', ' ')}</Tag></td>
              <td>{s.project ?? '—'}</td>
              <td>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.number ? `#${s.number} ` : ''}{s.title}</a> : s.title}{s.branch && s.branch !== 'main' ? <span className="muted small"> · {s.branch}</span> : null}</td>
              <td className="small">{s.status ?? ''} <span className="muted">{shortDate(s.day)}</span></td>
            </tr>
          ))}
        </tbody></table></div>
      )}
    </section>
  );
}
