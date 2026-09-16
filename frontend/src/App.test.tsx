import { render, screen } from '@testing-library/react';
import App from './App';

const trends = { grain: 'day', window: 90, start: '2026-06-19', end: '2026-09-16', rows: [{ key: 'commits', label: 'Commits', note: 'all repos', total: 12, active: 3, spark: [1, 2, 3], growth: { wow: 10, w4: -5 }, cells: [{ d: '2026-09-14', v: 3 }, { d: '2026-09-15', v: 0 }, { d: '2026-09-16', v: 9 }] }] };

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true, status: 200, text: async () => '',
    json: async () => (url.startsWith('/api/health') ? { ok: true, version: '0.1.0', demo: true, rollups_at: '2026-09-16T00:00:00Z' } : trends),
  })));
});

test('renders the Trends landing view from the API and flags demo mode', async () => {
  render(<App />);
  expect(await screen.findByText('Commits')).toBeInTheDocument();
  expect(screen.getByText('public demo · aggregates only')).toBeInTheDocument();
  expect(screen.getByLabelText('Commits')).toBeInTheDocument(); // the strip svg
  expect(screen.getByText('▲ 10%')).toBeInTheDocument();
});
