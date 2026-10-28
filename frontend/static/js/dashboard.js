/**
 * Strongman Coach — Dashboard
 *
 * Fetches data from /api/dashboard and renders all sections:
 *   - Current cycle & block phase
 *   - Next scheduled workout
 *   - e1RM trend charts (Chart.js)
 *   - Recent sessions
 *   - Pain flags
 *   - Deload warnings
 */

(function () {
  'use strict';

  const API_BASE = '/api';

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  async function fetchDashboardData() {
    const res = await fetch(`${API_BASE}/dashboard`);
    if (!res.ok) {
      throw new Error(`Dashboard fetch failed: ${res.status}`);
    }
    return res.json();
  }

  // ---------------------------------------------------------------------------
  // Rendering helpers
  // ---------------------------------------------------------------------------

  function capitalize(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  }

  // ---------------------------------------------------------------------------
  // Cycle / Block
  // ---------------------------------------------------------------------------

  function renderCycleInfo(data) {
    document.getElementById('cycle-number').textContent = data.current_cycle;
    document.getElementById('block-phase').textContent = capitalize(data.block_phase);
  }

  // ---------------------------------------------------------------------------
  // Next Workout
  // ---------------------------------------------------------------------------

  function renderNextWorkout(data) {
    const dayEl = document.getElementById('next-day-label');
    const dateEl = document.getElementById('next-date');
    if (data.next_workout) {
      dayEl.textContent = `Day ${data.next_workout.day_label}`;
      dateEl.textContent = formatDate(data.next_workout.scheduled_date);
    } else {
      dayEl.textContent = 'No upcoming sessions';
      dateEl.textContent = '';
    }
  }

  // ---------------------------------------------------------------------------
  // e1RM Trend Charts (Chart.js)
  // ---------------------------------------------------------------------------

  const chartInstances = {};

  function renderE1RMChart(canvasId, trend) {
    // Destroy previous chart if exists
    if (chartInstances[canvasId]) {
      chartInstances[canvasId].destroy();
    }

    const ctx = document.getElementById(canvasId).getContext('2d');
    const labels = trend.history.map(h => h.date);
    const values = trend.history.map(h => h.e1rm);

    chartInstances[canvasId] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: `${trend.exercise} e1RM (lb)`,
          data: values,
          borderColor: '#e94560',
          backgroundColor: 'rgba(233, 69, 96, 0.1)',
          fill: true,
          tension: 0.3,
          pointRadius: 4,
          pointBackgroundColor: '#e94560',
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: '#e0e0e0' },
          },
          title: {
            display: true,
            text: `${trend.exercise} — Trend: ${trend.trend_e1rm ? trend.trend_e1rm + ' lb' : 'N/A'}`,
            color: '#e0e0e0',
          },
        },
        scales: {
          x: {
            ticks: { color: '#aaa' },
            grid: { color: 'rgba(255,255,255,0.05)' },
          },
          y: {
            ticks: { color: '#aaa' },
            grid: { color: 'rgba(255,255,255,0.05)' },
          },
        },
      },
    });
  }

  function renderE1RMTrends(data) {
    const chartMap = {
      'Deadlift': 'deadlift-chart',
      'Overhead Press': 'ohp-chart',
      'Squat': 'squat-chart',
    };
    for (const trend of data.e1rm_trends) {
      const canvasId = chartMap[trend.exercise];
      if (canvasId) {
        renderE1RMChart(canvasId, trend);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Recent Sessions
  // ---------------------------------------------------------------------------

  function renderRecentSessions(data) {
    const list = document.getElementById('sessions-list');
    list.innerHTML = '';
    if (!data.recent_sessions || data.recent_sessions.length === 0) {
      const li = document.createElement('li');
      li.textContent = 'No completed sessions yet.';
      list.appendChild(li);
      return;
    }
    for (const sess of data.recent_sessions) {
      const li = document.createElement('li');
      li.innerHTML =
        `<span class="session-day">Day ${sess.day_label}</span>` +
        `<span class="session-date">${formatDate(sess.date)}</span>` +
        `<br><span>${sess.summary}</span>`;
      list.appendChild(li);
    }
  }

  // ---------------------------------------------------------------------------
  // Pain Flags
  // ---------------------------------------------------------------------------

  function renderPainFlags(data) {
    const list = document.getElementById('pain-flags-list');
    const noFlags = document.getElementById('no-pain-flags');
    list.innerHTML = '';
    if (!data.pain_flags || data.pain_flags.length === 0) {
      noFlags.classList.remove('hidden');
      return;
    }
    noFlags.classList.add('hidden');
    for (const flag of data.pain_flags) {
      const li = document.createElement('li');
      li.textContent = `${flag.exercise} — ${formatDate(flag.session_date)}${flag.note ? ': ' + flag.note : ''}`;
      list.appendChild(li);
    }
  }

  // ---------------------------------------------------------------------------
  // Deload Warning
  // ---------------------------------------------------------------------------

  function renderDeloadWarning(data) {
    const section = document.getElementById('deload-warning');
    const msg = document.getElementById('deload-message');
    if (data.deload_warning && data.deload_warning.triggered) {
      msg.textContent = data.deload_warning.message;
      section.classList.remove('hidden');
    } else {
      section.classList.add('hidden');
    }
  }

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  async function renderDashboard() {
    try {
      const data = await fetchDashboardData();
      renderCycleInfo(data);
      renderNextWorkout(data);
      renderE1RMTrends(data);
      renderRecentSessions(data);
      renderPainFlags(data);
      renderDeloadWarning(data);
    } catch (err) {
      console.error('Dashboard render error:', err);
    }
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  // Expose for testing / external refresh triggers
  window.dashboard = {
    renderDashboard,
    fetchDashboardData,
  };
  window.loadDashboard = renderDashboard;

  document.addEventListener('DOMContentLoaded', function () {
    // Only render if dashboard sections are visible
    const dashboardPage = document.getElementById('dashboard-page');
    if (dashboardPage && dashboardPage.style.display !== 'none') {
      renderDashboard();
    }
  });

  var refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', renderDashboard);
  }
})();
