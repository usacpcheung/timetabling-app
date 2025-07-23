// UI component initialisation for Tailwind/Flowbite

document.addEventListener('DOMContentLoaded', function () {
    if (window.initFlowbite) {
        try { initFlowbite(); } catch (e) { /* ignore errors if flowbite unavailable */ }
    }
});
