export const fmt = (n: number | null | undefined, digits = 1): string => {
  if (n == null || Number.isNaN(n)) return '–';
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(digits) + 'B';
  if (a >= 1e6) return (n / 1e6).toFixed(digits) + 'M';
  if (a >= 1e3) return (n / 1e3).toFixed(digits) + 'k';
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
};
export const usd = (n: number | null | undefined): string => (n == null ? '–' : '$' + (n >= 1000 ? fmt(n, 1) : n.toFixed(n >= 100 ? 0 : 2)));
export const pct = (a: number, b: number): number | null => (b > 0 ? Math.round(((a - b) / b) * 100) : a > 0 ? null : 0);
export const delta = (a: number, b: number): { cls: 'up' | 'down' | 'flat'; text: string } => {
  const g = pct(a, b);
  if (g === null) return { cls: 'up', text: 'new' };
  if (Math.abs(g) >= 300) return { cls: g > 0 ? 'up' : 'down', text: (g > 0 ? '▲ ×' : '▼ ×') + (a / b).toFixed(1) };
  return { cls: g > 0 ? 'up' : g < 0 ? 'down' : 'flat', text: (g > 0 ? '▲ ' : g < 0 ? '▼ ' : '– ') + Math.abs(g) + '%' };
};
export const growthText = (g: number | null): { cls: 'up' | 'down' | 'flat'; text: string } => {
  if (g === null) return { cls: 'flat', text: '–' };
  if (Math.abs(g) >= 300) return { cls: g > 0 ? 'up' : 'down', text: (g > 0 ? '▲ ×' : '▼ ×') + (1 + g / 100).toFixed(1) };
  return { cls: g > 0 ? 'up' : g < 0 ? 'down' : 'flat', text: (g > 0 ? '▲ ' : g < 0 ? '▼ ' : '– ') + Math.abs(g).toFixed(0) + '%' };
};
export const shortDate = (iso: string): string => iso.slice(5, 10);
export const dur = (s: number): string => (s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`);
// Red → green by log-scaled volume; index 0 is "empty".
export const RAMP = ['#B4382E', '#C9633A', '#C9A24A', '#8F9A3C', '#6E8A2E'];
export const level = (v: number, max: number): number => {
  if (!v) return 0;
  const r = Math.log1p(v) / Math.log1p(Math.max(max, 1));
  return r < 0.2 ? 1 : r < 0.4 ? 2 : r < 0.6 ? 3 : r < 0.8 ? 4 : 5;
};
export const SERIES = ['#B4386E', '#C9A24A', '#6E8A2E', '#4A2C22', '#6E2A2A', '#3E3E3E'];
