// UI component initialisation for Tailwind/Flowbite

document.addEventListener('DOMContentLoaded', function () {
    if (window.initFlowbite) {
        try { initFlowbite(); } catch (e) { /* ignore errors if flowbite unavailable */ }
    }
    if (window.Datepicker) {
        const opts = { autohide: true, format: 'yyyy-mm-dd' };
        const gen = document.getElementById('generate-date');
        if (gen) new Datepicker(gen, opts);
        const view = document.getElementById('view-date');
        if (view) new Datepicker(view, opts);
    }
});
