// Shared UI interactions powered by Alpine.js

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('generate-form');
  if (form) {
    const checkUrl = form.dataset.checkUrl;
    form.addEventListener('submit', async (e) => {
      const dateInput = form.querySelector('input[name="date"]');
      if (!dateInput || !dateInput.value) return;
      e.preventDefault();
      try {
        const resp = await fetch(`${checkUrl}?date=${encodeURIComponent(dateInput.value)}`);
        const data = await resp.json();
        let proceed = true;
        if (data.exists) {
          proceed = confirm('Timetable already exists for this date. Overwrite?');
          if (proceed) {
            let input = form.querySelector('input[name="confirm"]');
            if (!input) {
              input = document.createElement('input');
              input.type = 'hidden';
              input.name = 'confirm';
              input.value = '1';
              form.appendChild(input);
            }
          }
        }
        if (proceed) {
          window.dispatchEvent(new CustomEvent('loading', { detail: true }));
          const result = await fetch(form.action, { method: 'POST', body: new FormData(form) });
          window.dispatchEvent(new CustomEvent('loading', { detail: false }));
          if (result.redirected) {
            window.location.href = result.url;
          } else {
            window.location.reload();
          }
        }
      } catch (err) {
        window.dispatchEvent(new CustomEvent('loading', { detail: false }));
        form.submit();
      }
    });
  }

  document.querySelectorAll('[data-confirm]').forEach((el) => {
    el.addEventListener('submit', (e) => {
      if (!confirm(el.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });
});
