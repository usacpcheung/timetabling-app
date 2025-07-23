document.addEventListener('DOMContentLoaded', () => {
    const options = {
        searchable: true,
        sortable: true,
        perPage: 10,
        perPageSelect: [5, 10, 15, 20],
        classes: {
            table: "w-full text-sm text-left text-emerald-700"
        }
    };
    new DataTable('#active-table', options);
    new DataTable('#deleted-table', options);
});
