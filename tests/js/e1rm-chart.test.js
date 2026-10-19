const test = require('node:test');
const assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');
const C = require('../../frontend/static/js/e1rm-chart.js');

const mk = (n) => Array.from({ length: n }, (_, i) => ({
  date: `2026-01-${String((i % 28) + 1).padStart(2, '0')}`, e1rm: 200 + i * 2, is_pr: i > 0 && i % 5 === 0 }));
const box = () => ({ innerHTML: '' });
const count = (s, re) => (s.match(re) || []).length;

test('loading state shows the indicator and no chart', () => {
  const el = box(); C.render(el, { status: 'loading' });
  assert.match(el.innerHTML, /data-testid="loading-indicator"/);
  assert.doesNotMatch(el.innerHTML, /<svg/);
});
test('empty state when there is no history', () => {
  const el = box(); C.render(el, { status: 'ready', points: [] });
  assert.match(el.innerHTML, /data-testid="empty-state"/);
  assert.doesNotMatch(el.innerHTML, /<svg/);
});
test('chart renders an SVG element with line path and dots', () => {
  const el = box(); C.render(el, { status: 'ready', points: mk(8) });
  // Directly verify the SVG element is rendered with correct attributes
  assert.match(el.innerHTML, /<svg class="e1rm-svg" data-testid="chart-svg" viewBox="0 0 600 300"/);
  assert.equal(count(el.innerHTML, /<path class="e1rm-line" d="M/g), 1);
  assert.equal(count(el.innerHTML, /class="e1rm-dot"/g), 8);
  // Verify the SVG contains actual coordinate data (not empty)
  assert.match(el.innerHTML, /<path class="e1rm-line" d="M\d+\.\d+,\d+\.\d+/);
});
test('PR badges appear only on is_pr points', () => {
  const pts = mk(12), prs = pts.filter((p) => p.is_pr).length;
  const el = box(); C.render(el, { status: 'ready', points: pts });
  assert.equal(count(el.innerHTML, /data-testid="pr-badge"/g), prs);
  const none = box(); C.render(none, { status: 'ready', points: mk(6).map((p) => ({ ...p, is_pr: false })) });
  assert.equal(count(none.innerHTML, /data-testid="pr-badge"/g), 0);
});
test('single point does not crash (no divide by zero / NaN)', () => {
  const el = box(); C.render(el, { status: 'ready', points: mk(1) });
  assert.doesNotMatch(el.innerHTML, /NaN|Infinity/);
});
test('dates are escaped', () => {
  const el = box(); C.render(el, { status: 'ready', points: [{ date: '<img onerror=x>', e1rm: 300, is_pr: true }] });
  assert.doesNotMatch(el.innerHTML, /<img/);
});
test('load(): loading first, then chart, using the endpoint', async () => {
  const el = box(); const seen = []; let url;
  const fetchFn = async (u) => { url = u; seen.push(el.innerHTML); return { ok: true, json: async () => ({ points: mk(5) }) }; };
  await C.load(el, 7, { fetchFn });
  assert.match(seen[0], /loading-indicator/);
  assert.equal(url, '/api/e1rm-history/7?limit=30');
  assert.match(el.innerHTML, /<svg/);
});
test('load(): HTTP failure shows an error, not a blank card', async () => {
  const el = box(); await C.load(el, 1, { fetchFn: async () => ({ ok: false, status: 500 }) });
  assert.match(el.innerHTML, /data-testid="error-message"/);
});
test('50 sessions (150 sets worth of data) render well under 2 seconds', () => {
  const el = box(); const t0 = performance.now();
  C.render(el, { status: 'ready', points: mk(50) });
  assert.ok(performance.now() - t0 < 2000);
});
