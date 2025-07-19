document.addEventListener('DOMContentLoaded', function () {
    const teacherSelect = document.getElementById('new_assign_teacher');
    const studentSelect = document.getElementById('new_assign_student');
    const subjectSelect = document.getElementById('new_assign_subject');
    const slotSelect = document.getElementById('new_assign_slot');

    if (!teacherSelect || !studentSelect || !subjectSelect || !slotSelect) {
        return;
    }

    const teacherData = JSON.parse(document.getElementById('teacher-data').textContent);
    const studentData = JSON.parse(document.getElementById('student-data').textContent);
    const unavailData = JSON.parse(document.getElementById('unavail-data').textContent);
    const totalSlots = parseInt(slotSelect.dataset.totalSlots, 10);

    function updateOptions() {
        const tid = teacherSelect.value;
        const sid = studentSelect.value;
        const teacherSubs = teacherData[tid] || [];
        const studentSubs = studentData[sid] || [];
        const common = studentSubs.filter(s => teacherSubs.includes(s));

        subjectSelect.innerHTML = '';
        common.forEach(sub => {
            const opt = document.createElement('option');
            opt.value = sub;
            opt.textContent = sub;
            subjectSelect.appendChild(opt);
        });

        const unavailable = unavailData[tid] || [];
        slotSelect.innerHTML = '';
        for (let i = 1; i <= totalSlots; i++) {
            if (!unavailable.includes(i - 1)) {
                const opt = document.createElement('option');
                opt.value = i;
                opt.textContent = i;
                slotSelect.appendChild(opt);
            }
        }
    }

    teacherSelect.addEventListener('change', updateOptions);
    studentSelect.addEventListener('change', updateOptions);

    updateOptions();
});
