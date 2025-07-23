document.addEventListener('DOMContentLoaded', () => {
    const options = {
        searchable: true,
        sortable: true,
        perPage: 10,
        perPageSelect: [5, 10, 15, 20],
    };
    new DataTable('#active-table', options);
    new DataTable('#deleted-table', options);
});
