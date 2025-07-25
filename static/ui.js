// Initialise Flowbite components used by the templates

document.addEventListener('DOMContentLoaded', function () {
    if (window.initFlowbite) {
        try { initFlowbite(); } catch (e) { /* ignore errors if flowbite unavailable */ }
    }
});
