document.addEventListener('DOMContentLoaded', function () {
    const teacherSelect = document.getElementById('new_assign_teacher');
    const studentSelect = document.getElementById('new_assign_student');
    const groupSelect = document.getElementById('new_assign_group');
    const subjectSelect = document.getElementById('new_assign_subject');
    const slotSelect = document.getElementById('new_assign_slot');

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

    function parseTime(str) {
        const parts = str.split(':');
        return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    }

    function formatTime(mins) {
        mins = mins % (24 * 60);
        const h = String(Math.floor(mins / 60)).padStart(2, '0');
        const m = String(mins % 60).padStart(2, '0');
        return h + ':' + m;
    }

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
            input.value = times[i] || '08:30';
            label.appendChild(input);
            slotTimesContainer.appendChild(label);
            slotTimesContainer.appendChild(document.createElement('br'));
        }
    }

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
    function warnUnavail() {
        const tid = unavailTeacher.value;
        const slotVal = unavailSlot.value;
        const slot = parseInt(slotVal, 10) - 1;
        if (!tid || isNaN(slot)) return;
        const fixed = assignData[tid] || [];
        const unav = unavailData[tid] || [];
        const flashes = document.getElementById('flash-messages');
        if (!flashes) return;
        const li = document.createElement('li');
        li.className = 'error';
        if (fixed.includes(slot)) {
            li.textContent = 'Warning: fixed assignment exists in this slot.';
        } else if (unav.includes(slot)) {
            li.textContent = 'Slot already marked unavailable.';
        } else {
            return;
        }
        flashes.appendChild(li);
    }
    if (unavailTeacher && unavailSlot) {
        unavailTeacher.addEventListener('change', warnUnavail);
        unavailSlot.addEventListener('input', warnUnavail);
    }

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
