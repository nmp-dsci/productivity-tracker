import { useState } from 'react';
import { api } from '../api';
import { RAMP, byMetricOrder, fmt, hours, usd } from '../format';
import { Growth, Head, Sparkline, Status, Strip, Toggle, Tooltip, useFetch, type HoverInfo } from '../ui';

const show = (key: string, v: number) =>
  key === 'cost_usd' ? usd(v) : key === 'screen_hours' ? hours(v) : fmt(v);

export default function Trends({ onPickDay }: { onPickDay: (d: string) => void }) {
  const [grain, setGrain] = useState<'day' | 'week'>('day');
  const window = grain === 'day' ? 180 : 26;
  const { data, error, loading } = useFetch(() => api.trends(grain, window), [grain]);
  const [hover, setHover] = useState<HoverInfo>(null);
  return (
    <section id="trends">
      <Head eyebrow="Over time" title="Trends" lede={grain === 'week'
        ? `Rolling 7-day blocks, every one of them seven whole days, the last ending ${data?.complete_through ?? "…"} — recomputed daily, so no stub week at the start of the week. Colour is volume, red → green, log-scaled per row; ▲▼ is the last block vs the one before, and the last 4 blocks vs the prior 4.`
        : `One strip per metric, in the same order as the tiles above; the number is the all-time total. Colour is volume, red → green, log-scaled per row; the sparkline is the last 26 rolling 7-day blocks. Complete days only, through ${data?.complete_through ?? "…"} — today is drawn as a dashed outline and left out of every total, scale and comparison.`}>
        <Toggle value={grain} options={[['day', 'Day · rolling 180'], ['week', '7-day · rolling 26']]} onChange={setGrain} />
      </Head>
      <Status loading={loading} error={error} />
      {data && (
        <div className="hm-rows">
          {byMetricOrder(data.rows).map((r) => (
            <div className="hm-row" key={r.key} id={'hm-' + r.key}>
              <div className="meta">
                <div className="v">{show(r.key, r.all_time)}</div>
                <div className="l">{r.label}</div>
                <div className="d">all time · {show(r.key, r.total)} over {r.periods} complete {grain === 'day' ? 'days' : '7-day blocks'} · {r.active} active</div>
              </div>
              <div className="sparkcell"><Sparkline values={r.spark} /></div>
              <Growth wow={r.growth.wow} w4={r.growth.w4} />
              <div className="grid"><Strip cells={r.cells} grain={grain} label={r.label} onHover={setHover} onClick={onPickDay} format={(v) => show(r.key, v)} /></div>
            </div>
          ))}
        </div>
      )}
      <div className="hm-legend">low {RAMP.map((c) => <i key={c} style={{ background: c }} />)} high · none = transparent · <i className="partial" /> = in progress, not counted · click a cell to open it in Overview</div>
      <Tooltip info={hover} />
    </section>
  );
}
