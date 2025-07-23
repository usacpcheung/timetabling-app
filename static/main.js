// Site-wide JavaScript helpers

document.addEventListener('DOMContentLoaded', function () {
    // Timetable overwrite check on the index page
    const generateForm = document.getElementById('generate-form');
    if (generateForm) {
        const checkUrl = generateForm.dataset.checkUrl;
        generateForm.addEventListener('submit', async function (e) {
            const dateInput = generateForm.querySelector('input[name="date"]');
            if (!dateInput || !dateInput.value || !checkUrl) return;
            e.preventDefault();
            try {
                const resp = await fetch(checkUrl + '?date=' + encodeURIComponent(dateInput.value));
                const data = await resp.json();
                let proceed = true;
                if (data.exists) {
                    proceed = confirm('Timetable already exists for this date. Overwrite?');
                }
                if (proceed) {
                    if (data.exists) {
                        let input = generateForm.querySelector('input[name="confirm"]');
                        if (!input) {
                            input = document.createElement('input');
                            input.type = 'hidden';
                            input.name = 'confirm';
                            input.value = '1';
                            generateForm.appendChild(input);
                        }
                    }
                    generateForm.submit();
                }
            } catch (err) {
                generateForm.submit();
            }
        });
    }

    // Confirmation prompts for destructive actions
    const resetForm = document.getElementById('reset-db-form');
    if (resetForm) {
        resetForm.addEventListener('submit', function (e) {
            if (!confirm('This will erase all data and reset to defaults. Continue?')) {
                e.preventDefault();
            }
        });
    }

    const deleteForm = document.getElementById('delete-form');
    if (deleteForm) {
        deleteForm.addEventListener('submit', function (e) {
            if (!confirm('Delete selected timetables?')) {
                e.preventDefault();
            }
        });
    }

    const clearAllForm = document.getElementById('clear-all-form');
    if (clearAllForm) {
        clearAllForm.addEventListener('submit', function (e) {
            if (!confirm('Delete all timetables?')) {
                e.preventDefault();
            }
        });
    }

    function setupTableSearch(tableId, searchId) {
        const input = document.getElementById(searchId);
        const table = document.getElementById(tableId);
        if (!input || !table) return;
        input.addEventListener('input', function () {
            const filter = input.value.toLowerCase();
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => {
                row.style.display = row.textContent.toLowerCase().includes(filter) ? '' : 'none';
            });
        });
    }

    function setupSortableTable(tableId) {
        const table = document.getElementById(tableId);
        if (!table) return;
        table.querySelectorAll('th[data-sort]').forEach((header, idx) => {
            header.classList.add('cursor-pointer');
            header.addEventListener('click', () => {
                const tbody = table.querySelector('tbody');
                const rows = Array.from(tbody.querySelectorAll('tr'));
                const asc = header.dataset.asc !== 'true';
                header.dataset.asc = asc;
                rows.sort((a, b) => {
                    const aText = a.children[idx].textContent.trim();
                    const bText = b.children[idx].textContent.trim();
                    return asc ? aText.localeCompare(bText) : bText.localeCompare(aText);
                });
                tbody.innerHTML = '';
                rows.forEach(r => tbody.appendChild(r));
            });
        });
    }

    setupTableSearch('timetables-table', 'timetables-search');
    setupSortableTable('timetables-table');
    setupTableSearch('attendance-active-table', 'attendance-active-search');
    setupSortableTable('attendance-active-table');
    setupTableSearch('attendance-deleted-table', 'attendance-deleted-search');
    setupSortableTable('attendance-deleted-table');
});
