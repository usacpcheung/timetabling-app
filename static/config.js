document.addEventListener('DOMContentLoaded', function () {
    const teacherSelect = document.getElementById('new_assign_teacher');
    const studentSelect = document.getElementById('new_assign_student');
    const groupSelect = document.getElementById('new_assign_group');
    const subjectSelect = document.getElementById('new_assign_subject');
    const slotSelect = document.getElementById('new_assign_slot');

    if (!teacherSelect || !studentSelect || !subjectSelect || !slotSelect) {
        return;
    }

    const teacherData = JSON.parse(document.getElementById('teacher-data').textContent);
    const studentData = JSON.parse(document.getElementById('student-data').textContent);
    const groupData = JSON.parse(document.getElementById('group-data').textContent);
    const unavailData = JSON.parse(document.getElementById('unavail-data').textContent);
    const assignData = JSON.parse(document.getElementById('assign-data').textContent);
    const totalSlots = parseInt(slotSelect.dataset.totalSlots, 10);

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

    updateOptions();
});
