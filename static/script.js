// script.js — Shared frontend behavior for AI Study Assistant
// Handles: mobile sidebar toggle, AI (Gemini) status indicator, logout action.
// Page-specific logic (chat, study, dashboard, history) lives in each template's <script> block.

document.addEventListener('DOMContentLoaded', () => {
  setupMobileMenu();
  setupLogout();
  pollAiStatus();
});

/**
 * Toggle the sidebar open/closed on mobile via the hamburger button.
 */
function setupMobileMenu() {
  const toggle = document.getElementById('menuToggle');
  const sidebar = document.getElementById('sidebar');
  if (!toggle || !sidebar) return;

  toggle.addEventListener('click', () => {
    sidebar.classList.toggle('open');
  });

  // Close sidebar when a nav link is tapped (mobile UX)
  sidebar.querySelectorAll('.nav-item').forEach((link) => {
    link.addEventListener('click', () => sidebar.classList.remove('open'));
  });
}

/**
 * Wire up the "Sign out" button in the sidebar footer.
 */
function setupLogout() {
  const btn = document.getElementById('logoutBtn');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    await fetch('/api/users/logout', { method: 'POST' });
    window.location.href = '/';
  });
}

/**
 * Check Gemini API connectivity and update the status dot in the sidebar.
 * Re-checks every 60 seconds so the indicator stays accurate without
 * burning extra API quota too aggressively.
 */
async function pollAiStatus() {
  const dot = document.getElementById('aiStatus');
  if (!dot) return;

  const check = async () => {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (data.running && data.model_available) {
        dot.className = 'status-dot status-ok';
        dot.title = data.message || 'Gemini API connected';
      } else {
        dot.className = 'status-dot status-error';
        dot.title = data.message || 'Gemini API unavailable';
      }
    } catch (e) {
      dot.className = 'status-dot status-error';
      dot.title = 'Cannot reach the server.';
    }
  };

  check();
  setInterval(check, 60000);
}
