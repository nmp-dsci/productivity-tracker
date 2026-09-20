import { render, screen } from '@testing-library/react';
import App from './App';

const trends = { grain: 'day', window: 90, start: '2026-06-19', end: '2026-09-16', rows: [{ key: 'commits', label: 'Commits', note: 'all repos', total: 12, active: 3, spark: [1, 2, 3], growth: { wow: 10, w4: -5 }, cells: [{ d: '2026-09-14', v: 3 }, { d: '2026-09-15', v: 0 }, { d: '2026-09-16', v: 9 }] }] };

const insights = { start: '2026-09-10', end: '2026-09-16', prior_start: '2026-09-03', prior_end: '2026-09-09', kpis: {}, prior: {}, metrics: [{ key: 'commits', label: 'Commits', note: 'all repos', value: 12, prior: 10, growth: 20 }], projects: [], split: [], shiplog: [], narrative: 'You shipped things.', narrative_end: '2026-09-16' };

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true, status: 200, text: async () => '',
    json: async () => (url.startsWith('/api/health') ? { ok: true, version: '0.1.0', demo: true, rollups_at: '2026-09-16T00:00:00Z' } : url.startsWith('/api/insights') ? insights : trends),
  })));
});

test('home renders insights above the trends and flags demo mode', async () => {
  render(<App />);
  expect(await screen.findByText('▲ 20%')).toBeInTheDocument();
  expect((await screen.findAllByText('Commits')).length).toBe(2);
  expect(screen.getByText('public demo · aggregates only')).toBeInTheDocument();
  expect(screen.getByLabelText('Commits')).toBeInTheDocument(); // the strip svg
  expect(screen.getByText('▲ 10%')).toBeInTheDocument();
});
