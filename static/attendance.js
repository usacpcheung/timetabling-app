document.addEventListener('DOMContentLoaded', () => {
    new DataTable('#active-table', { searchable: true, sortable: true });
    new DataTable('#deleted-table', { searchable: true, sortable: true });
});
