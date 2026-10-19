/* Strongman Coach – Phone-first logging screen controller
 *
 * Responsibilities:
 *  - Fetch today's prescriptions from /api/prescriptions/today
 *  - Render exercise sections with weight, reps, RPE picker, note, pain flag
 *  - Rest timer with vibration alert
 *  - Offline queue via IndexedDB (store sets when offline, sync when online)
 *  - Service worker registration
 */

/* ------------------------------------------------------------------ */
/* IndexedDB helpers                                                    */
/* ------------------------------------------------------------------ */

const DB_NAME = 'strongman-coach-queue';
const DB_VERSION = 1;
const STORE_NAME = 'offline_sets';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
        store.createIndex('synced', 'synced');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function addOfflineSet(setData) {
  return openDB().then((db) => {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const entry = { ...setData, synced: false, queued_at: new Date().toISOString() };
      const req = store.add(entry);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  });
}

function getUnsyncedSets() {
  return openDB().then((db) => {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const index = store.index('synced');
      const req = index.getAll(false);
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  });
}

function markSetSynced(id) {
  return openDB().then((db) => {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const req = store.get(id);
      req.onsuccess = () => {
        const data = req.result;
        if (data) {
          data.synced = true;
          store.put(data);
        }
        resolve();
      };
      req.onerror = () => reject(req.error);
    });
  });
}

function deleteSet(id) {
  return openDB().then((db) => {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      store.delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  });
}

function updateQueueCount() {
  getUnsyncedSets().then((sets) => {
    const el = document.getElementById('queueCount');
    if (el) el.textContent = sets.length;
  });
}

/* ------------------------------------------------------------------ */
/* State                                                                */
/* ------------------------------------------------------------------ */

let currentSessionId = null;
let prescriptions = [];
let exercises = [];

/* ------------------------------------------------------------------ */
/* Service Worker registration                                          */
/* ------------------------------------------------------------------ */

function registerSW() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js')
      .then((reg) => {
        console.log('SW registered', reg.scope);
        // Listen for sync messages from SW
        navigator.serviceWorker.addEventListener('message', (e) => {
          if (e.data && e.data.type === 'SYNC_QUEUE') {
            syncOfflineQueue();
          }
        });
      })
      .catch((err) => console.warn('SW registration failed:', err));
  }
}

/* ------------------------------------------------------------------ */
/* Connection status                                                    */
/* ------------------------------------------------------------------ */

function updateConnectionStatus() {
  const el = document.getElementById('connectionStatus');
  if (!el) return;
  if (navigator.onLine) {
    el.textContent = '● Online';
    el.className = 'status online';
  } else {
    el.textContent = '● Offline';
    el.className = 'status offline';
  }
}

window.addEventListener('online', () => {
  updateConnectionStatus();
  syncOfflineQueue();
});
window.addEventListener('offline', updateConnectionStatus);

/* ------------------------------------------------------------------ */
/* Fetch today's prescriptions                                          */
/* ------------------------------------------------------------------ */

async function loadPrescriptions() {
  try {
    const resp = await fetch('/api/prescriptions/today');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    if (data.session) {
      currentSessionId = data.session.id;
      prescriptions = data.prescriptions || [];
      renderPrescriptionSummary(data.session);
      renderExercises();
    } else {
      renderNoSession();
    }
  } catch (err) {
    console.error('Failed to load prescriptions:', err);
    renderNoSession();
  }
}

function renderPrescriptionSummary(session) {
  const container = document.getElementById('rxSummary');
  if (!container) return;
  container.innerHTML = `
    <div class="rx-chip">
      <span class="label">Day</span>
      <span class="value">${session.day_label || '?'}</span>
    </div>
    <div class="rx-chip">
      <span class="label">Phase</span>
      <span class="value">${session.block_phase || '-'}</span>
    </div>
    <div class="rx-chip">
      <span class="label">Lifts</span>
      <span class="value">${prescriptions.length}</span>
    </div>
  `;
}

function renderNoSession() {
  const container = document.getElementById('rxSummary');
  if (container) {
    container.innerHTML = '<div class="rx-chip"><span class="value">No active session</span></div>';
  }
  const exContainer = document.getElementById('exercisesContainer');
  if (exContainer) exContainer.innerHTML = '';
}

/* ------------------------------------------------------------------ */
/* Render exercises                                                     */
/* ------------------------------------------------------------------ */

function renderExercises() {
  const container = document.getElementById('exercisesContainer');
  if (!container) return;

  // Group prescriptions by exercise name
  const groups = {};
  for (const pres of prescriptions) {
    const key = pres.exercise_name;
    if (!groups[key]) groups[key] = [];
    groups[key].push(pres);
  }

  container.innerHTML = '';
  for (const [name, presList] of Object.entries(groups)) {
    const section = document.createElement('div');
    section.className = 'exercise-section';
    section.innerHTML = `
      <div class="exercise-header">
        <h2>${name}</h2>
        <span class="e1rm-badge" id="e1rm-${name.replace(/\s+/g, '-')}">e1RM: --</span>
      </div>
      <div class="sets-container" id="sets-${name.replace(/\s+/g, '-')}"></div>
    `;
    container.appendChild(section);

    const setsContainer = section.querySelector('.sets-container');
    for (let i = 0; i < presList.length; i++) {
      const pres = presList[i];
      const setRow = createSetRow(name, pres, i + 1);
      setsContainer.appendChild(setRow);
    }

    // Add "Log Set" button
    const logBtn = document.createElement('button');
    logBtn.className = 'btn btn-secondary';
    logBtn.style.marginTop = '8px';
    logBtn.textContent = `+ Log Set (${name})`;
    logBtn.addEventListener('click', () => {
      const nextNum = presList.length + 1;
      const emptyPres = { exercise_name: name, prescribed_load_lb: 0, prescribed_reps: 0, prescribed_rpe: null };
      const setRow = createSetRow(name, emptyPres, nextNum);
      setsContainer.appendChild(setRow);
    });
  }
}

function createSetRow(exerciseName, pres, setNum) {
  const row = document.createElement('div');
  row.className = 'set-row';
  row.dataset.exercise = exerciseName;
  row.dataset.setNum = setNum;

  const safeName = exerciseName.replace(/\s+/g, '-');

  row.innerHTML = `
    <div class="set-num" id="set-num-${safeName}-${setNum}">${setNum}</div>
    <input type="number" inputmode="numeric" placeholder="lbs"
           id="weight-${safeName}-${setNum}"
           value="${pres.prescribed_load_lb || ''}" />
    <input type="number" inputmode="numeric" placeholder="reps"
           id="reps-${safeName}-${setNum}"
           value="${pres.prescribed_reps || ''}" />
    <div class="rpe-picker" id="rpe-${safeName}-${setNum}">
      ${generateRPEButtons(pres.prescribed_rpe)}
    </div>
    <button class="pain-toggle" id="pain-${safeName}-${setNum}" title="Pain flag">⚠</button>
  `;

  // Note input
  const noteRow = document.createElement('div');
  noteRow.style.cssText = 'grid-column: 1 / -1; margin-top: 4px;';
  noteRow.innerHTML = `
    <input type="text" class="note-input" id="note-${safeName}-${setNum}"
           placeholder="Note (optional)" />
  `;
  row.appendChild(noteRow);

  // Log button
  const logBtn = document.createElement('button');
  logBtn.className = 'btn btn-success';
  logBtn.style.marginTop = '8px';
  logBtn.style.width = 'auto';
  logBtn.textContent = '✓ Log';
  logBtn.addEventListener('click', () => logSet(exerciseName, setNum, safeName));
  row.appendChild(logBtn);

  return row;
}

function generateRPEButtons(selectedRPE) {
  let html = '';
  for (let rpe = 6.0; rpe <= 10.0; rpe += 0.5) {
    const sel = (selectedRPE !== null && selectedRPE !== undefined && Math.abs(rpe - selectedRPE) < 0.01)
      ? 'selected' : '';
    html += `<button class="rpe-btn ${sel}" data-rpe="${rpe}">${rpe}</button>`;
  }
  return html;
}

/* RPE picker click handling via event delegation */
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('rpe-btn')) {
    const picker = e.target.closest('.rpe-picker');
    picker.querySelectorAll('.rpe-btn').forEach(b => b.classList.remove('selected'));
    e.target.classList.add('selected');
  }
  if (e.target.classList.contains('pain-toggle')) {
    e.target.classList.toggle('active');
  }
});

/* ------------------------------------------------------------------ */
/* Log a set                                                            */
/* ------------------------------------------------------------------ */

async function logSet(exerciseName, setNum, safeName) {
  const weightInput = document.getElementById(`weight-${safeName}-${setNum}`);
  const repsInput = document.getElementById(`reps-${safeName}-${setNum}`);
  const rpePicker = document.getElementById(`rpe-${safeName}-${setNum}`);
  const painBtn = document.getElementById(`pain-${safeName}-${setNum}`);
  const noteInput = document.getElementById(`note-${safeName}-${setNum}`);

  const weight = parseFloat(weightInput?.value) || 0;
  const reps = parseInt(repsInput?.value) || 0;
  const selectedRpeBtn = rpePicker?.querySelector('.rpe-btn.selected');
  const rpe = selectedRpeBtn ? parseFloat(selectedRpeBtn.dataset.rpe) : null;
  const painFlag = painBtn?.classList.contains('active') || false;
  const note = noteInput?.value || '';

  if (weight <= 0 || reps <= 0) {
    alert('Enter weight and reps');
    return;
  }

  const idempotencyKey = `${exerciseName}-${setNum}-${Date.now()}`;
  const setPayload = {
    exercise_name: exerciseName,
    weight: weight,
    reps: reps,
    rpe: rpe,
    set_type: 'top',
    pain_flag: painFlag,
    note: note,
    idempotency_key: idempotencyKey,
    session_id: currentSessionId,
  };

  try {
    const resp = await fetch('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([setPayload]),
    });

    if (resp.ok) {
      // Mark set number as logged
      const setNumEl = document.getElementById(`set-num-${safeName}-${setNum}`);
      if (setNumEl) setNumEl.classList.add('logged');

      // Update e1RM badge
      const data = await resp.json();
      if (data.results && data.results.length > 0) {
        const result = data.results[0];
        // We don't get e1rm back from sync, but we can estimate
        updateE1RMBadge(exerciseName, weight, reps, rpe);
      }

      // Start rest timer
      startRestTimer(90);
    } else {
      // Store offline
      await addOfflineSet(setPayload);
      updateQueueCount();
      console.warn('Offline: set queued');
    }
  } catch (err) {
    // Store offline on network error
    await addOfflineSet(setPayload);
    updateQueueCount();
    console.warn('Offline: set queued due to error', err);
  }
}

function updateE1RMBadge(exerciseName, weight, reps, rpe) {
  const safeName = exerciseName.replace(/\s+/g, '-');
  const badge = document.getElementById(`e1rm-${safeName}`);
  if (!badge) return;

  let e1rmVal;
  if (rpe !== null && rpe >= 7.0 && reps <= 8) {
    // Approximate e1RM using Epley-like formula for display
    // The server calculates the real value; this is a client-side estimate
    e1rmVal = Math.round(weight * (1 + reps / 30.0));
  } else {
    e1rmVal = Math.round(weight * (1 + reps / 30.0));
  }
  badge.textContent = `e1RM: ${e1rmVal} lb`;
}

/* ------------------------------------------------------------------ */
/* Rest Timer                                                           */
/* ------------------------------------------------------------------ */

let timerInterval = null;
let timerSeconds = 0;

function startRestTimer(seconds) {
  stopRestTimer();
  timerSeconds = seconds;
  updateTimerDisplay();

  timerInterval = setInterval(() => {
    timerSeconds--;
    updateTimerDisplay();
    if (timerSeconds <= 0) {
      stopRestTimer();
      vibrateAlert();
    }
  }, 1000);
}

function stopRestTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

function resetRestTimer() {
  stopRestTimer();
  timerSeconds = 0;
  updateTimerDisplay();
}

function updateTimerDisplay() {
  const el = document.getElementById('timerDisplay');
  if (!el) return;
  const mins = Math.floor(timerSeconds / 60);
  const secs = timerSeconds % 60;
  el.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function vibrateAlert() {
  if ('vibrate' in navigator) {
    navigator.vibrate([200, 100, 200, 100, 200]);
  }
  // Also try AudioContext beep as fallback
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 800;
    gain.gain.value = 0.3;
    osc.start();
    setTimeout(() => { osc.stop(); ctx.close(); }, 300);
  } catch (e) {
    // Audio not available
  }
}

/* Timer button handlers */
document.addEventListener('DOMContentLoaded', () => {
  const startBtn = document.getElementById('timerStart');
  const resetBtn = document.getElementById('timerReset');

  if (startBtn) {
    startBtn.addEventListener('click', () => {
      if (timerSeconds > 0) {
        startRestTimer(timerSeconds);
      } else {
        startRestTimer(90); // default 90 seconds
      }
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', resetRestTimer);
  }

  // Timer presets
  document.querySelectorAll('.timer-preset').forEach((btn) => {
    btn.addEventListener('click', () => {
      const secs = parseInt(btn.dataset.seconds, 10);
      startRestTimer(secs);
    });
  });

  // Sync button
  const syncBtn = document.getElementById('syncBtn');
  if (syncBtn) {
    syncBtn.addEventListener('click', syncOfflineQueue);
  }

  // Complete session button
  const completeBtn = document.getElementById('completeBtn');
  if (completeBtn) {
    completeBtn.addEventListener('click', completeSession);
  }
});

/* ------------------------------------------------------------------ */
/* Sync offline queue                                                   */
/* ------------------------------------------------------------------ */

async function syncOfflineQueue() {
  if (!navigator.onLine) {
    console.log('Offline, cannot sync');
    return;
  }

  try {
    const unsynced = await getUnsyncedSets();
    if (unsynced.length === 0) {
      updateQueueCount();
      return;
    }

    const payloads = unsynced.map((entry) => ({
      exercise_name: entry.exercise_name,
      weight: entry.weight,
      reps: entry.reps,
      rpe: entry.rpe,
      set_type: entry.set_type || 'top',
      pain_flag: entry.pain_flag || false,
      note: entry.note || '',
      idempotency_key: entry.idempotency_key,
      session_id: entry.session_id,
    }));

    const resp = await fetch('/api/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payloads),
    });

    if (resp.ok) {
      // Mark all as synced and delete from queue
      for (const entry of unsynced) {
        await markSetSynced(entry.id);
        await deleteSet(entry.id);
      }
      updateQueueCount();
      console.log(`Synced ${unsynced.length} sets`);
    } else {
      console.warn('Sync failed:', resp.status);
    }
  } catch (err) {
    console.error('Sync error:', err);
  }
}

/* ------------------------------------------------------------------ */
/* Complete session                                                     */
/* ------------------------------------------------------------------ */

async function completeSession() {
  if (!currentSessionId) {
    alert('No active session');
    return;
  }

  try {
    const resp = await fetch(`/api/sessions/${currentSessionId}/complete`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });

    if (resp.ok) {
      alert('Session completed!');
      // Reload prescriptions
      loadPrescriptions();
    } else {
      alert('Failed to complete session');
    }
  } catch (err) {
    console.error('Complete session error:', err);
    alert('Error completing session');
  }
}

/* ------------------------------------------------------------------ */
/* Init                                                                 */
/* ------------------------------------------------------------------ */

document.addEventListener('DOMContentLoaded', () => {
  registerSW();
  updateConnectionStatus();
  updateQueueCount();
  loadPrescriptions();
});
