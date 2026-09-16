import { useEffect, useState } from 'react';
import { api } from './api';
import Agents from './views/Agents';
import GitHubView from './views/GitHub';
import Overview from './views/Overview';
import Projects from './views/Projects';
import ShipLog from './views/ShipLog';
import Trends from './views/Trends';
import Insights from './views/Insights';
import { Tag, useFetch } from './ui';

const VIEWS = ['trends', 'overview', 'agents', 'github', 'projects', 'shiplog'] as const;
type View = (typeof VIEWS)[number];

const readPath = (): View => {
  const seg = window.location.pathname.replace(/^\//, '').split('/')[0] as View;
  return VIEWS.includes(seg) ? seg : 'trends';
};

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? 'system');
  const cycle = () => {
    const order = ['system', 'dark', 'light'];
    const next = order[(order.indexOf(theme) + 1) % order.length]!;
    if (next === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    try { next === 'system' ? localStorage.removeItem('pt-theme') : localStorage.setItem('pt-theme', next); } catch { /* private mode */ }
    setTheme(next);
  };
  return [theme, cycle];
}

export default function App() {
  const [view, setView] = useState<View>(readPath);
  const [week, setWeek] = useState<string | undefined>(undefined);
  const [theme, cycleTheme] = useTheme();
  const health = useFetch(() => api.health(), []);
  const go = (v: View) => { window.history.pushState(null, '', '/' + v); setView(v); window.scrollTo(0, 0); };
  useEffect(() => { const onPop = () => setView(readPath()); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop); }, []);
  return (
    <>
      <header className="top">
        <div className="in">
          <nav>{VIEWS.map((v) => <a key={v} href={'/' + v} className={v === view ? 'on' : ''} onClick={(e) => { e.preventDefault(); go(v); }}>{v === 'shiplog' ? 'ship log' : v}</a>)}</nav>
          <a className="brand" href="/trends" onClick={(e) => { e.preventDefault(); go('trends'); }}>productivity<sup>®</sup>tracker</a>
          <div className="right">
            {health.data?.demo && <Tag kind="gold">public demo · aggregates only</Tag>}
            {health.data?.rollups_at && <span className="small muted">rollups {health.data.rollups_at.slice(0, 16).replace('T', ' ')}Z</span>}
            <button className="theme-btn" onClick={cycleTheme} title="system → dark → light">theme: {theme}</button>
          </div>
        </div>
      </header>
      <main>
        {view === 'trends' && <><Insights /><Trends onPickDay={(d) => { setWeek(d); go('overview'); }} /></>}
        {view === 'overview' && <Overview week={week} setWeek={setWeek} />}
        {view === 'agents' && <Agents />}
        {view === 'github' && <GitHubView />}
        {view === 'projects' && <Projects />}
        {view === 'shiplog' && <ShipLog />}
      </main>
      <footer><div className="in"><span>productivity-tracker · events → S3 · DuckDB rollups · FastAPI · React</span><span>github.com/nmp-dsci/productivity-tracker</span><span>aggregates only in demo mode; raw prompts never leave the laptop</span></div></footer>
    </>
  );
}
