import { api } from '../api';
import { Head, Status, useFetch } from '../ui';

export default function Weekly({ week }: { week: string | undefined }) {
  const { data, error, loading } = useFetch(() => api.weekly(week), [week]);
  return (
    <section id="weekly">
      <Head eyebrow="Narrative" title="Weekly review" lede="Drafted from the rollups, never from prompts: what shipped, where effort went, and anything odd — a project that ate tokens with no commits." />
      <Status loading={loading} error={error} />
      {data && (
        data.narrative ? (
          <div className="card" style={{ border: '1px solid var(--line)', maxWidth: '52rem', margin: '0 auto', whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
            <div className="eyebrow">week of {data.week_start}</div>
            {data.narrative}
          </div>
        ) : (
          <div className="empty">No narrative for the week of {data.week_start} yet — run <code>pt weekly --week {data.week_start}</code>.</div>
        )
      )}
    </section>
  );
}
