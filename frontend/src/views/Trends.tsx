import { useState } from 'react';
import { api } from '../api';
import { RAMP, fmt, usd } from '../format';
import { Growth, Head, Sparkline, Status, Strip, Toggle, Tooltip, useFetch, type HoverInfo } from '../ui';

export default function Trends({ onPickDay }: { onPickDay: (d: string) => void }) {
  const [grain, setGrain] = useState<'day' | 'week'>('day');
  const window = grain === 'day' ? 180 : 26;
  const { data, error, loading } = useFetch(() => api.trends(grain, window), [grain]);
  const [hover, setHover] = useState<HoverInfo>(null);
  return (
    <section id="trends">
      <Head eyebrow="Landing view" title="Trends" lede="One strip per metric. Colour is volume, red → green, log-scaled per row; the sparkline is the last 26 weeks; ▲▼ is week-on-week and last-4-weeks vs prior-4.">
        <Toggle value={grain} options={[['day', 'Day · rolling 180'], ['week', 'Week · rolling 26']]} onChange={setGrain} />
      </Head>
      <Status loading={loading} error={error} />
      {data && (
        <div className="hm-rows">
          {data.rows.map((r) => (
            <div className="hm-row" key={r.key} id={'hm-' + r.key}>
              <div className="meta">
                <div className="v">{r.key === 'cost_usd' ? usd(r.total) : fmt(r.total)}</div>
                <div className="l">{r.label}</div>
                <div className="d">{r.note} · {r.active} active {grain}s</div>
              </div>
              <div className="sparkcell"><Sparkline values={r.spark} /></div>
              <Growth wow={r.growth.wow} w4={r.growth.w4} />
              <div className="grid"><Strip cells={r.cells} grain={grain} label={r.label} onHover={setHover} onClick={onPickDay} /></div>
            </div>
          ))}
        </div>
      )}
      <div className="hm-legend">low {RAMP.map((c) => <i key={c} style={{ background: c }} />)} high · none = transparent · click a cell to open that week in Overview</div>
      <Tooltip info={hover} />
    </section>
  );
}
