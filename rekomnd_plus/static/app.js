/* =====================================================
   REKOMND+ — Shared Application JS
   SPA navigation, toast, utils
   ===================================================== */

// ── Navigation ─────────────────────────────────────────
(function initNav() {
  const path = window.location.pathname;
  document.querySelectorAll('.navbar-nav a').forEach(link => {
    const href = link.getAttribute('href');
    if (href === path || (path === '/' && href === '/')) {
      link.classList.add('active');
    } else if (href !== '/' && path.startsWith(href)) {
      link.classList.add('active');
    }
  });
})();

// ── Toast system ───────────────────────────────────────
const Toast = (() => {
  let stack = document.getElementById('toast-stack');

  function ensure() {
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'toast-stack';
      stack.className = 'toast-stack';
      document.body.appendChild(stack);
    }
  }

  function show(msg, type = 'info', duration = 3500) {
    ensure();
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    const icons = { success: '✓', error: '✕', info: 'ℹ' };
    el.innerHTML = `<span>${icons[type] || '•'}</span><span>${msg}</span>`;
    stack.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity 0.3s, transform 0.3s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(10px)';
      setTimeout(() => el.remove(), 300);
    }, duration);
  }

  return { success: m => show(m, 'success'), error: m => show(m, 'error'), info: m => show(m, 'info') };
})();

window.Toast = Toast;

// ── API helpers ────────────────────────────────────────
const API = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`API error ${r.status}`);
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: r.statusText }));
      throw new Error(err.error || r.statusText);
    }
    return r.json();
  },
  async del(url) {
    const r = await fetch(url, { method: 'DELETE' });
    if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
    return r.json();
  },
  async put(url, body) {
    const r = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: r.statusText }));
      throw new Error(err.error || r.statusText);
    }
    return r.json();
  },
};

window.API = API;

// ── Utility: format numbers ────────────────────────────
function fmtNum(n) {
  if (n == null) return '—';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return n.toString();
}
window.fmtNum = fmtNum;

// ── Utility: stars ─────────────────────────────────────
function renderStars(rating) {
  if (!rating) return '—';
  const full = Math.round(rating);
  return '★'.repeat(full) + '☆'.repeat(Math.max(0, 5 - full));
}
window.renderStars = renderStars;

// ── Utility: truncate ──────────────────────────────────
function trunc(str, n = 40) {
  if (!str) return '—';
  return str.length > n ? str.slice(0, n) + '…' : str;
}
window.trunc = trunc;

// ── Table sort helper ──────────────────────────────────
function makeSortable(tableEl) {
  if (!tableEl) return;
  const headers = tableEl.querySelectorAll('thead th[data-col]');
  let sortCol = null, sortDir = 1;

  headers.forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (sortCol === col) { sortDir *= -1; }
      else { sortCol = col; sortDir = 1; }

      headers.forEach(h => h.classList.remove('sorted-asc', 'sorted-desc'));
      th.classList.add(sortDir === 1 ? 'sorted-asc' : 'sorted-desc');

      const tbody = tableEl.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      rows.sort((a, b) => {
        const va = a.dataset[col] || '';
        const vb = b.dataset[col] || '';
        const na = parseFloat(va), nb = parseFloat(vb);
        if (!isNaN(na) && !isNaN(nb)) return (na - nb) * sortDir;
        return va.localeCompare(vb) * sortDir;
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
}
window.makeSortable = makeSortable;
