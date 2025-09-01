// JavaScript helpers for the configuration form.
// Populate drop-downs and handle dynamic slot time fields.

document.addEventListener('DOMContentLoaded', function () {
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
        localStorage.setItem(ACC_KEY, JSON.stringify(open));
    }

    const savedRaw = localStorage.getItem(ACC_KEY);
    if (savedRaw) {
        const savedPanels = JSON.parse(savedRaw);
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

    accordionButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            setTimeout(saveAccordionState, 0);
        });
    });

    const slotTimesDataEl = document.getElementById('slot-times-data');
    const slotTimesContainer = document.getElementById('slot-times');
    const slotsInput = document.querySelector('input[name="slots_per_day"]');
    const slotDurationInput = document.querySelector('input[name="slot_duration"]');

    if (!teacherSelect || !studentSelect || !subjectSelect || !slotSelect) {
        return;
    }

    const teacherData = JSON.parse(document.getElementById('teacher-data').textContent);
    const studentData = JSON.parse(document.getElementById('student-data').textContent);
    const groupData = JSON.parse(document.getElementById('group-data').textContent);
    const unavailData = JSON.parse(document.getElementById('unavail-data').textContent);
    const assignData = JSON.parse(document.getElementById('assign-data').textContent);
    const totalSlots = parseInt(slotSelect.dataset.totalSlots, 10);

    const configForm = document.querySelector('form[method="post"]:not([action])');
    if (configForm) {
        const selects = configForm.querySelectorAll('select:not([multiple])');
        selects.forEach(sel => {
            sel.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    configForm.submit();
                }
            });
        });
    }

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
            opt.textContent = sub;
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
