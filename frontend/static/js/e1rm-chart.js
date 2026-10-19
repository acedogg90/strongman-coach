/* Strongman Coach - E1RMChart (vanilla JS, no build step, no libraries).
 * Works as a classic <script> in the PWA and as require() in Node tests. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.E1RMChart = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  const W = 600, H = 300, PAD = { top: 20, right: 20, bottom: 40, left: 50 };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /** points: oldest-first [{date, e1rm, is_pr}] from /api/e1rm-history. Returns an SVG string. */
  function buildSvg(points) {
    const innerW = W - PAD.left - PAD.right, innerH = H - PAD.top - PAD.bottom;
    const vals = points.map((p) => p.e1rm);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
    const yMin = lo - span * 0.1, yMax = hi + span * 0.1;
    const x = (i) => PAD.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
    const y = (v) => PAD.top + innerH * (1 - (v - yMin) / (yMax - yMin));
    const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.e1rm).toFixed(1)}`).join('');
    const dots = points.map((p, i) =>
      `<circle class="e1rm-dot" cx="${x(i).toFixed(1)}" cy="${y(p.e1rm).toFixed(1)}" r="3"/>`).join('');
    const badges = points.map((p, i) => !p.is_pr ? '' :
      `<g class="e1rm-pr-badge" data-testid="pr-badge"><title>PR ${esc(p.e1rm)} lb on ${esc(p.date)}</title>` +
      `<circle cx="${x(i).toFixed(1)}" cy="${y(p.e1rm).toFixed(1)}" r="6"/>` +
      `<text x="${x(i).toFixed(1)}" y="${(y(p.e1rm) - 10).toFixed(1)}" text-anchor="middle">PR</text></g>`).join('');
    return `<svg class="e1rm-svg" data-testid="chart-svg" viewBox="0 0 ${W} ${H}" role="img" ` +
      `aria-label="e1RM history"><path class="e1rm-line" d="${path}" fill="none"/>${dots}${badges}</svg>`;
  }

  /** state: {status: 'loading'|'error'|'ready', points?, title?, message?} */
  function render(container, state) {
    const title = `<h3 class="e1rm-title">${esc(state.title || 'e1RM history')}</h3>`;
    let body;
    if (state.status === 'loading') {
      body = '<div class="e1rm-loading" data-testid="loading-indicator" role="status">Loading e1RM history…</div>';
    } else if (state.status === 'error') {
      body = `<div class="e1rm-error" data-testid="error-message" role="alert">${esc(state.message || 'Could not load e1RM history.')}</div>`;
    } else if (!state.points || state.points.length === 0) {
      body = '<div class="e1rm-empty" data-testid="empty-state">No e1RM history yet for this exercise.</div>';
    } else {
      body = buildSvg(state.points);
    }
    container.innerHTML = title + body;
  }

  /** Fetch + render. fetchFn is injectable so tests need no network. */
  async function load(container, exerciseId, opts) {
    const o = Object.assign({ fetchFn: (typeof fetch === 'function' ? fetch : null), title: 'e1RM history', limit: 30 }, opts);
    render(container, { status: 'loading', title: o.title });
    try {
      const res = await o.fetchFn(`/api/e1rm-history/${encodeURIComponent(exerciseId)}?limit=${o.limit}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      render(container, { status: 'ready', points: data.points || [], title: o.title });
    } catch (err) {
      render(container, { status: 'error', message: 'Could not load e1RM history.', title: o.title });
    }
  }

  return { buildSvg, render, load };
});
