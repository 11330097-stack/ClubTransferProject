(() => {
    document.querySelectorAll('[data-workflow-form]').forEach((form) => {
        form.addEventListener('submit', (event) => {
            if (!form.checkValidity() || form.dataset.submitting === 'true') {
                if (form.dataset.submitting === 'true') event.preventDefault();
                return;
            }

            let confirmMessage = event.submitter?.dataset.confirmMessage || form.dataset.confirmMessage;
            if (form.hasAttribute('data-assignment-form')) {
                const controls = Array.from(form.elements);
                const selected = controls.filter((control) => control.name === 'student_ids' && control.checked).length;
                const clubSelect = controls.find((control) => control.name === 'club_id');
                const clubName = clubSelect?.selectedOptions?.[0]?.textContent?.trim() || '所選社團';
                const subject = form.dataset.assignmentSubject || `${selected} 位學生`;
                const assignmentCount = selected || 1;
                const capacity = clubName.match(/（(\d+)\s*\/\s*(\d+)\s*人）/);
                const remaining = capacity ? Number(capacity[2]) - Number(capacity[1]) - assignmentCount : null;
                const capacityMessage = remaining === null
                    ? '系統會再次檢查社團容量與學生狀態。'
                    : remaining >= 0
                        ? `分配後預估剩餘 ${remaining} 個名額；系統送出時會再次驗證。`
                        : '目前選取人數可能超過社團容量，系統將在送出時拒絕不合法的分配。';
                confirmMessage = `將 ${subject} 分配至「${clubName}」？${capacityMessage}`;
            }
            const selectedCount = Array.from(form.elements).filter((control) => control.type === 'checkbox' && control.checked).length;
            confirmMessage = confirmMessage?.replace('{count}', selectedCount);
            if (confirmMessage && !window.confirm(confirmMessage)) {
                event.preventDefault();
                return;
            }

            form.dataset.submitting = 'true';
            form.setAttribute('aria-busy', 'true');
            const localButtons = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
            const linkedButtons = form.id
                ? Array.from(document.querySelectorAll(`button[form="${form.id}"], input[form="${form.id}"]`))
                : [];
            const submitButtons = Array.from(new Set([...localButtons, ...linkedButtons]));
            const activeButton = event.submitter || submitButtons[0];
            submitButtons.forEach((button) => {
                button.disabled = true;
                if (button === activeButton) {
                    button.style.width = `${Math.ceil(button.getBoundingClientRect().width)}px`;
                    button.classList.add('is-processing');
                }
                if (button === activeButton && button.tagName === 'BUTTON') {
                    button.dataset.originalLabel = button.textContent.trim();
                    button.textContent = button.dataset.submittingLabel || '處理中…';
                }
            });
        });
    });

    document.querySelectorAll('[data-file-feedback]').forEach((input) => {
        const output = document.getElementById(input.dataset.fileFeedback);
        const update = () => {
            if (output) output.textContent = input.files?.[0]?.name || '尚未選擇檔案';
        };
        input.addEventListener('change', update);
        update();
    });

    document.querySelectorAll('.import-dropzone').forEach((dropzone) => {
        const input = dropzone.querySelector('input[type="file"]');
        const output = dropzone.querySelector('[data-file-name]');
        if (!input || !output) return;
        const update = () => output.textContent = input.files?.[0]?.name || '尚未選擇檔案';
        input.addEventListener('change', update);
        update();
    });

    const errorSummary = document.querySelector('.form-error-summary');
    if (errorSummary) errorSummary.focus();

    document.querySelectorAll('[data-auto-dismiss]').forEach((alert) => {
        const delay = Number(alert.dataset.autoDismiss);
        if (!Number.isFinite(delay) || delay <= 0) return;
        window.setTimeout(() => {
            if (window.bootstrap?.Alert) {
                window.bootstrap.Alert.getOrCreateInstance(alert).close();
            } else {
                alert.remove();
            }
        }, delay);
    });
})();
