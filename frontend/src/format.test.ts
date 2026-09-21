import { delta, fmt, growthText, hours, level, usd } from './format';

test('fmt and usd', () => {
  expect(fmt(30608203)).toBe('30.6M');
  expect(fmt(1403)).toBe('1.4k');
  expect(fmt(47)).toBe('47');
  expect(usd(4445)).toBe('$4.4k');
  expect(usd(61.25)).toBe('$61.25');
});

test('delta caps absurd percentages as a multiplier', () => {
  expect(delta(6988, 1205)).toEqual({ cls: 'up', text: '▲ ×5.8' });
  expect(delta(108, 139)).toEqual({ cls: 'down', text: '▼ 22%' });
  expect(delta(5, 0)).toEqual({ cls: 'up', text: 'new' });
  expect(growthText(479.9).text).toBe('▲ ×5.8');
});

test('level is log-scaled with empty at 0', () => {
  expect(level(0, 100)).toBe(0);
  expect(level(100, 100)).toBe(5);
  expect(level(1, 100)).toBe(1);
});

test('hours read like the Screen Time panel', () => {
  expect(hours(8.7)).toBe('8h 42m');
  expect(hours(0.7)).toBe('42m');
  expect(hours(0)).toBe('0m');
  expect(hours(1)).toBe('1h 00m');
});
