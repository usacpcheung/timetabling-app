// Site-wide JavaScript helpers for prompts and timetable checks

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

    const lessonDeleteForms = document.querySelectorAll('.delete-lesson-form');
    lessonDeleteForms.forEach(function (form) {
        form.addEventListener('submit', function (e) {
            if (!confirm('Delete this lesson?')) {
                e.preventDefault();
            }
        });
    });

    const addButtons = document.querySelectorAll('.add-lesson-btn');
    const slotSelect = document.getElementById('slot-select');
    const teacherSelect = document.getElementById('teacher-select');
    const addForm = document.getElementById('add-form');
    addButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (slotSelect) slotSelect.value = btn.dataset.slot;
            if (teacherSelect) teacherSelect.value = btn.dataset.teacher;
            if (addForm) addForm.scrollIntoView({ behavior: 'smooth' });
        });
    });
});
