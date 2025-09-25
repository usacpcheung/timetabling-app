// JavaScript helpers for the configuration form.
// Populate drop-downs and handle dynamic slot time fields.

document.addEventListener('DOMContentLoaded', function () {
    const loadForm = document.getElementById('load-form');
    const overwriteInput = document.getElementById('overwrite');
    const presetSectionsInput = document.getElementById('selected-sections-input');
    const loadPresetModal = document.getElementById('load-preset-modal');
    const loadPresetButton = document.querySelector('[data-preset-load]');
    const loadPresetCancel = loadPresetModal ? loadPresetModal.querySelector('[data-preset-load-cancel]') : null;
    const loadPresetConfirm = document.getElementById('confirm-load-preset');

    function getModalInstance(modalId) {
        if (!modalId) {
            return null;
        }
        if (!window.FlowbiteInstances || typeof window.FlowbiteInstances.getInstance !== 'function') {
            return null;
        }
        try {
            return window.FlowbiteInstances.getInstance('Modal', modalId);
        } catch (err) {
            return null;
        }
    }

    function ensureModal(modal) {
        if (!modal) {
            return null;
        }
        const existing = getModalInstance(modal.id);
        if (existing) {
            return existing;
        }
        if (typeof window.Modal === 'function') {
            try {
                return new window.Modal(modal, { closable: false }, { id: modal.id, override: true });
            } catch (err) {
                return null;
            }
        }
        return null;
    }

    function showModal(modal) {
        if (!modal) {
            return;
        }
        const instance = ensureModal(modal);
        if (instance && typeof instance.show === 'function') {
            instance.show();
        } else {
            modal.classList.remove('hidden');
        }
    }

    function hideModal(modal) {
        if (!modal) {
            return;
        }
        const instance = getModalInstance(modal.id);
        if (instance && typeof instance.hide === 'function') {
            instance.hide();
        } else {
            modal.classList.add('hidden');
        }
    }

    if (loadForm && overwriteInput && presetSectionsInput && loadPresetModal && loadPresetButton) {
        const sectionCheckboxes = Array.from(loadPresetModal.querySelectorAll('[data-preset-section]'));
        loadPresetButton.addEventListener('click', event => {
            event.preventDefault();
            sectionCheckboxes.forEach(cb => {
                cb.checked = true;
            });
            showModal(loadPresetModal);
        });

        if (loadPresetCancel) {
            loadPresetCancel.addEventListener('click', event => {
                event.preventDefault();
                hideModal(loadPresetModal);
            });
        }

        if (loadPresetConfirm) {
            loadPresetConfirm.addEventListener('click', () => {
                const selected = sectionCheckboxes.filter(cb => cb.checked).map(cb => cb.value);
                if (!selected.length) {
                    alert('Select at least one section to load.');
                    return;
                }
                presetSectionsInput.value = JSON.stringify(selected);
                overwriteInput.value = '1';
                hideModal(loadPresetModal);
                if (typeof loadForm.requestSubmit === 'function') {
                    loadForm.requestSubmit();
                } else {
                    loadForm.submit();
                }
            });
        }
    }

    const teacherSelect = document.getElementById('new_assign_teacher');
    const studentSelect = document.getElementById('new_assign_student');
    const groupSelect = document.getElementById('new_assign_group');
    const subjectSelect = document.getElementById('new_assign_subject');
    const slotSelect = document.getElementById('new_assign_slot');

    const accordionButtons = document.querySelectorAll('#config-accordion button[data-accordion-target]');
    const ACC_KEY = 'config_open_panels';

    function saveAccordionState() {
        const open = Array.from(accordionButtons)
            .map(btn => btn.getAttribute('data-accordion-target'))
            .filter(id => {
                const panel = document.querySelector(id);
                return panel && !panel.classList.contains('hidden');
            });
        try {
            localStorage.setItem(ACC_KEY, JSON.stringify(open));
        } catch (err) {
            return;
        }
    }

    function restoreAccordionState() {
        let savedRaw;
        try {
            savedRaw = localStorage.getItem(ACC_KEY);
        } catch (err) {
            return;
        }
        if (!savedRaw) {
            return;
        }

        let savedPanels = [];
        try {
            const parsed = JSON.parse(savedRaw);
            if (Array.isArray(parsed)) {
                savedPanels = parsed;
            } else {
                // Fall back to an empty array so invalid storage entries don't break the accordion state.
            }
        } catch (err) {
            // Keep the default [] when JSON parsing fails.
        }

        accordionButtons.forEach(btn => {
            const id = btn.getAttribute('data-accordion-target');
            const panel = document.querySelector(id);
            if (panel) {
                panel.classList.add('hidden');
                btn.setAttribute('aria-expanded', 'false');
                const icon = btn.querySelector('[data-accordion-icon]');
                if (icon) icon.classList.remove('rotate-180');
            }
        });
        savedPanels.forEach(id => {
            const panel = document.querySelector(id);
            const btn = document.querySelector(`#config-accordion button[data-accordion-target="${id}"]`);
            if (panel && btn) {
                panel.classList.remove('hidden');
                btn.setAttribute('aria-expanded', 'true');
                const icon = btn.querySelector('[data-accordion-icon]');
                if (icon) icon.classList.add('rotate-180');
            }
        });
    }

    restoreAccordionState();

    accordionButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            setTimeout(saveAccordionState, 0);
        });
    });

    const slotTimesDataEl = document.getElementById('slot-times-data');
    const slotTimesContainer = document.getElementById('slot-times');
    const slotsInput = document.querySelector('input[name="slots_per_day"]');
    const slotDurationInput = document.querySelector('input[name="slot_duration"]');
    const configForm = document.getElementById('config-form');
    const saveButton = configForm ? configForm.querySelector('[data-config-save]') : null;
    let allowSubmit = false;

    const allowNextSubmit = () => {
        allowSubmit = true;
        setTimeout(() => {
            allowSubmit = false;
        }, 0);
    };

    const triggerConfigSubmit = () => {
        if (!configForm) {
            return;
        }
        allowNextSubmit();
        if (typeof configForm.requestSubmit === 'function') {
            configForm.requestSubmit();
        } else {
            configForm.submit();
        }
    };

    if (configForm) {
        configForm.addEventListener('submit', event => {
            if (!allowSubmit) {
                event.preventDefault();
            }
        });

        configForm.addEventListener('keydown', event => {
            if (event.key !== 'Enter') {
                return;
            }

            const target = event.target;
            const isShortcut = event.ctrlKey || event.metaKey;

            if (isShortcut) {
                event.preventDefault();
                triggerConfigSubmit();
                return;
            }

            if (target && target.tagName === 'TEXTAREA') {
                return;
            }

            if (target instanceof HTMLButtonElement && target.type === 'submit') {
                allowNextSubmit();
                return;
            }

            event.preventDefault();
        });
    }

    if (saveButton) {
        saveButton.addEventListener('click', allowNextSubmit);
        saveButton.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                allowNextSubmit();
            }
        });
    }

    const modalOriginalValues = new Map();

    function captureModalState(modal) {
        return Array.from(modal.querySelectorAll('input, select, textarea')).map(field => {
            if (field.tagName === 'SELECT' && field.multiple) {
                return {
                    field,
                    type: 'multiple',
                    values: Array.from(field.options).filter(opt => opt.selected).map(opt => opt.value)
                };
            }
            if (field.type === 'checkbox' || field.type === 'radio') {
                return { field, type: 'checked', checked: field.checked };
            }
            return { field, type: 'value', value: field.value };
        });
    }

    function restoreModalState(state) {
        state.forEach(item => {
            if (!item || !item.field) return;
            if (item.type === 'multiple') {
                const values = new Set(item.values || []);
                Array.from(item.field.options).forEach(opt => {
                    opt.selected = values.has(opt.value);
                });
            } else if (item.type === 'checked') {
                item.field.checked = !!item.checked;
            } else {
                item.field.value = item.value;
            }
        });
    }

    const modalToggles = document.querySelectorAll('[data-modal-toggle]');
    modalToggles.forEach(btn => {
        btn.addEventListener('click', event => {
            const targetId = btn.getAttribute('data-modal-target');
            if (!targetId) return;
            const modal = document.getElementById(targetId);
            if (!modal) return;
            if (modal.classList.contains('hidden')) {
                modalOriginalValues.set(targetId, captureModalState(modal));
            }
            event.preventDefault();
            event.stopPropagation();
            const existingInstance = window.FlowbiteInstances && typeof window.FlowbiteInstances.getInstance === 'function'
                ? window.FlowbiteInstances.getInstance('Modal', targetId)
                : null;
            const instance = existingInstance || (typeof window.Modal === 'function'
                ? new window.Modal(modal, { closable: false }, { id: modal.id, override: true })
                : null);
            if (instance && typeof instance.show === 'function') {
                instance.show();
            }
        });
    });

    const modalElements = document.querySelectorAll('[data-config-modal]');
    const ensureModalInstances = () => {
        if (typeof window === 'undefined' || typeof window.Modal !== 'function') {
            return;
        }
        modalElements.forEach(modalEl => {
            if (!modalEl || !modalEl.id) {
                return;
            }
            new window.Modal(
                modalEl,
                { closable: false },
                { id: modalEl.id, override: true }
            );
        });
    };
    if (modalElements.length) {
        setTimeout(ensureModalInstances, 0);
    }

    const modalCancelButtons = document.querySelectorAll('[data-modal-cancel]');
    modalCancelButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-modal-hide');
            const modal = targetId ? document.getElementById(targetId) : btn.closest('[data-config-modal]');
            if (!modal) return;
            const state = modalOriginalValues.get(modal.id);
            if (state) {
                restoreModalState(state);
                modalOriginalValues.delete(modal.id);
            }
            const instance = window.FlowbiteInstances && typeof window.FlowbiteInstances.getInstance === 'function'
                ? window.FlowbiteInstances.getInstance('Modal', modal.id)
                : null;
            if (instance && typeof instance.hide === 'function') {
                instance.hide();
            }
        });
    });

    const modalSaveButtons = document.querySelectorAll('[data-modal-save]');
    modalSaveButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            if (!configForm) {
                return;
            }
            const modal = btn.closest('[data-config-modal]');
            if (modal) {
                modalOriginalValues.delete(modal.id);
                const instance = window.FlowbiteInstances && typeof window.FlowbiteInstances.getInstance === 'function'
                    ? window.FlowbiteInstances.getInstance('Modal', modal.id)
                    : null;
                if (instance && typeof instance.hide === 'function') {
                    instance.hide();
                }
            }
            triggerConfigSubmit();
        });
    });

    if (!teacherSelect || !studentSelect || !subjectSelect || !slotSelect) {
        return;
    }

    const teacherData = JSON.parse(document.getElementById('teacher-data').textContent);
    const studentData = JSON.parse(document.getElementById('student-data').textContent);
    const groupData = JSON.parse(document.getElementById('group-data').textContent);
    const unavailData = JSON.parse(document.getElementById('unavail-data').textContent);
    const assignData = JSON.parse(document.getElementById('assign-data').textContent);
    const subjectMap = JSON.parse(document.getElementById('subject-map').textContent);
    const totalSlots = parseInt(slotSelect.dataset.totalSlots, 10);

    // Convert "HH:MM" to minutes.
    function parseTime(str) {
        const parts = str.split(':');
        return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    }

    // Convert minutes back to "HH:MM".
    function formatTime(mins) {
        mins = mins % (24 * 60);
        const h = String(Math.floor(mins / 60)).padStart(2, '0');
        const m = String(mins % 60).padStart(2, '0');
        return h + ':' + m;
    }

    // Build time input fields whenever the slot count or duration changes.
    function updateSlotTimeFields() {
        if (!slotTimesContainer || !slotTimesDataEl) return;
        const count = parseInt(slotsInput.value, 10) || 0;
        const duration = parseInt(slotDurationInput.value, 10) || 0;
        let times = [];
        try {
            times = JSON.parse(slotTimesDataEl.textContent);
        } catch (e) {}
        while (times.length < count) {
            if (times.length === 0) {
                times.push('08:30');
            } else {
                const last = parseTime(times[times.length - 1]);
                times.push(formatTime(last + duration));
            }
        }
        if (times.length > count) {
            times = times.slice(0, count);
        }
        slotTimesContainer.innerHTML = '';
        for (let i = 0; i < count; i++) {
            const label = document.createElement('label');
            label.textContent = 'Slot ' + (i + 1) + ' start: ';
            const input = document.createElement('input');
            input.type = 'time';
            input.name = 'slot_start_' + (i + 1);
            input.value = times[i] || '00:00';

            // fix the flowbite class not apply correctly issue
            input.className = 'border border-emerald-300 rounded-lg p-2.5 w-full';

            label.appendChild(input);
            slotTimesContainer.appendChild(label);
            slotTimesContainer.appendChild(document.createElement('br'));
        }
    }

    // Update subject and slot dropdowns based on the chosen teacher and student.
    function updateOptions() {
        const tid = teacherSelect.value;
        const sid = studentSelect.value;
        const gid = groupSelect ? groupSelect.value : '';
        const teacherSubs = teacherData[tid] || [];
        const baseSubs = gid ? (groupData[gid] || []) : (studentData[sid] || []);
        const common = baseSubs.filter(s => teacherSubs.includes(s));

        subjectSelect.innerHTML = '';
        const subPlaceholder = document.createElement('option');
        subPlaceholder.value = '';
        subPlaceholder.textContent = '-- Select --';
        subjectSelect.appendChild(subPlaceholder);
        common.forEach(sub => {
            const opt = document.createElement('option');
            opt.value = sub;
            opt.textContent = subjectMap[sub] || sub;
            subjectSelect.appendChild(opt);
        });

        const unavailable = unavailData[tid] || [];
        slotSelect.innerHTML = '';
        const slotPlaceholder = document.createElement('option');
        slotPlaceholder.value = '';
        slotPlaceholder.textContent = '-- Select --';
        slotSelect.appendChild(slotPlaceholder);
        for (let i = 1; i <= totalSlots; i++) {
            if (!unavailable.includes(i - 1)) {
                const opt = document.createElement('option');
                opt.value = i;
                opt.textContent = i;
                slotSelect.appendChild(opt);
            }
        }
    }

    const unavailTeacher = document.getElementById('new_unavail_teacher');
    const unavailSlot = document.getElementById('new_unavail_slot');
    // Display a warning when marking slots unavailable would conflict.
    function warnUnavail() {
        if (!unavailTeacher || !unavailSlot) return;
        const tids = Array.from(unavailTeacher.selectedOptions).map(o => o.value);
        const slots = Array.from(unavailSlot.selectedOptions).map(o => parseInt(o.value, 10) - 1);
        if (!tids.length || !slots.length) return;
        const flashes = document.getElementById('flash-messages');
        if (!flashes) return;
        tids.forEach(tid => {
            const fixed = assignData[tid] || [];
            const unav = unavailData[tid] || [];
            slots.forEach(slot => {
                let msg = '';
                if (fixed.includes(slot)) {
                    msg = 'Warning: fixed assignment exists in this slot.';
                } else if (unav.includes(slot)) {
                    msg = 'Slot already marked unavailable.';
                }
                if (msg) {
                    const li = document.createElement('li');
                    li.className = 'error';
                    li.textContent = msg;
                    flashes.appendChild(li);
                }
            });
        });
    }
    if (unavailTeacher && unavailSlot) {
        unavailTeacher.addEventListener('change', warnUnavail);
        unavailSlot.addEventListener('change', warnUnavail);
    }

    
    // Hook up event listeners so dropdowns stay in sync.
    teacherSelect.addEventListener('change', updateOptions);
    studentSelect.addEventListener('change', updateOptions);
    if (groupSelect) groupSelect.addEventListener('change', updateOptions);

    if (slotsInput && slotDurationInput) {
        slotsInput.addEventListener('input', updateSlotTimeFields);
        slotDurationInput.addEventListener('input', updateSlotTimeFields);
    }

    updateSlotTimeFields();
    updateOptions();
});
