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

    const backupForm = document.getElementById('backup-form');
    if (backupForm) {
        backupForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            try {
                const resp = await fetch(backupForm.action, {
                    method: 'POST',
                    credentials: 'same-origin'
                });
                const blob = await resp.blob();
                let filename = 'backup.zip';
                const disposition = resp.headers.get('Content-Disposition');
                if (disposition && disposition.includes('filename=')) {
                    filename = disposition.split('filename=')[1].split(';')[0].trim().replace(/"/g, '');
                }
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                setTimeout(function () {
                    window.URL.revokeObjectURL(url);
                    a.remove();
                    window.location.reload();
                }, 100);
            } catch (err) {
                window.location.reload();
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
    const slotInput = document.getElementById('slot-input');
    const teacherInput = document.getElementById('teacher-input');
    const modalEl = document.getElementById('add-modal');
    const addForm = document.getElementById('add-form');
    let modal = null;
    if (modalEl && typeof Modal !== 'undefined') {
        modal = new Modal(modalEl);
    }
    addButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (slotInput) slotInput.value = btn.dataset.slot;
            if (teacherInput) teacherInput.value = btn.dataset.teacher;
            if (modal) modal.show();
        });
    });

    const editButtons = document.querySelectorAll('.edit-lesson-btn');
    const entryInput = document.getElementById('entry-id-input');
    const editStudentSelect = document.getElementById('edit-student-group');
    const editSubjectSelect = document.getElementById('edit-subject');
    const editLocationSelect = document.getElementById('edit-location');
    const editModalEl = document.getElementById('edit-modal');
    let editModal = null;
    if (editModalEl && typeof Modal !== 'undefined') {
        editModal = new Modal(editModalEl);
    }
    editButtons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (entryInput) entryInput.value = btn.dataset.entry;
            if (editStudentSelect) {
                if (btn.dataset.student) {
                    editStudentSelect.value = 's' + btn.dataset.student;
                } else if (btn.dataset.group) {
                    editStudentSelect.value = 'g' + btn.dataset.group;
                }
            }
            if (editSubjectSelect && btn.dataset.subject) {
                editSubjectSelect.value = btn.dataset.subject;
            }
            if (editLocationSelect) {
                editLocationSelect.value = btn.dataset.location || '';
            }
            if (editModal) editModal.show();
        });
    });

    const worksheetForms = document.querySelectorAll('.worksheet-form');
    worksheetForms.forEach(function (form) {
        const cb = form.querySelector('input[type="checkbox"]');
        const hidden = form.querySelector('input[name="assign"]');
        if (cb && hidden) {
            cb.addEventListener('change', function () {
                hidden.value = cb.checked ? '1' : '0';
                form.submit();
            });
        }
    });
});
