// Initialise Flowbite components used by the templates

const renderFlashToasts = () => {
    const payloadNodes = Array.from(document.querySelectorAll('[data-flash-payload]'));
    if (!payloadNodes.length) {
        return;
    }

    const normaliseEntry = entry => {
        const normaliseCategory = value => {
            if (typeof value === 'string') {
                const trimmed = value.trim();
                if (trimmed) {
                    return trimmed;
                }
            }
            return 'info';
        };

        const normaliseText = value => {
            if (typeof value === 'string') {
                const trimmed = value.trim();
                if (trimmed) {
                    return trimmed;
                }
            }
            return '';
        };

        if (Array.isArray(entry)) {
            const [category, message] = entry;
            const text = normaliseText(message);
            if (!text) {
                return null;
            }
            return {
                category: normaliseCategory(category),
                text
            };
        }

        if (entry && typeof entry === 'object') {
            const text = normaliseText(entry.message ?? entry.text ?? '');
            if (!text) {
                return null;
            }
            return {
                category: normaliseCategory(entry.category ?? entry.type ?? entry.level),
                text
            };
        }

        if (typeof entry === 'string') {
            const text = normaliseText(entry);
            if (!text) {
                return null;
            }
            return {
                category: 'info',
                text
            };
        }

        return null;
    };

    const messageGroups = [];

    payloadNodes.forEach(node => {
        const raw = node.textContent ? node.textContent.trim() : '';
        if (!raw) {
            node.remove();
            return;
        }

        let parsed;
        try {
            parsed = JSON.parse(raw);
        } catch (error) {
            console.error('Failed to parse flash payload', error);
            node.remove();
            return;
        }

        const entries = Array.isArray(parsed)
            ? parsed
            : Array.isArray(parsed?.messages)
                ? parsed.messages
                : [];
        const messages = entries
            .map(normaliseEntry)
            .filter(Boolean);

        if (messages.length) {
            messageGroups.push(messages);
        }

        node.remove();
    });

    if (!messageGroups.length) {
        return;
    }

    const categoryStyles = {
        error: 'border-red-500 bg-red-50 text-red-900 dark:border-red-400 dark:bg-red-900 dark:text-red-100',
        warning: 'border-amber-500 bg-amber-50 text-amber-900 dark:border-amber-400 dark:bg-amber-900 dark:text-amber-100',
        success: 'border-emerald-500 bg-emerald-50 text-emerald-900 dark:border-emerald-400 dark:bg-emerald-900 dark:text-emerald-100',
        info: 'border-blue-500 bg-blue-50 text-blue-900 dark:border-blue-400 dark:bg-blue-900 dark:text-blue-100'
    };

    const existingContainer = document.querySelector('[data-flash-toast-container]');
    if (existingContainer) {
        existingContainer.remove();
    }

    const toastContainer = document.createElement('div');
    toastContainer.className = 'fixed top-4 left-4 right-4 z-50 flex max-w-full flex-col gap-3 overflow-y-auto sm:right-auto sm:max-w-sm';
    toastContainer.setAttribute('role', 'alert');
    toastContainer.setAttribute('aria-live', 'assertive');
    toastContainer.setAttribute('data-flash-toast-container', '');

    toastContainer.style.maxHeight = 'calc(100vh - 2rem)';

    const removeToast = toast => {
        if (!toast) {
            return;
        }
        toast.remove();
        if (!toastContainer.childElementCount) {
            toastContainer.remove();
        }
    };

    messageGroups.forEach(messages => {
        const primaryCategory = messages[0]?.category || 'info';
        const style = categoryStyles[primaryCategory] || categoryStyles.info;

        const toast = document.createElement('div');
        toast.className = `flex w-full items-start justify-between gap-3 overflow-hidden rounded-lg border shadow-lg backdrop-blur ${style}`;

        const contentWrapper = document.createElement('div');
        contentWrapper.className = 'flex-1 px-4 py-3 text-sm';

        const heading = document.createElement('div');
        heading.className = 'flex items-baseline justify-between gap-2 text-sm font-semibold';
        const readableCategory = primaryCategory.charAt(0).toUpperCase() + primaryCategory.slice(1);
        heading.textContent = readableCategory;

        const countBadge = document.createElement('span');
        countBadge.className = 'rounded-full bg-black/10 px-2 py-0.5 text-xs font-medium uppercase tracking-wide dark:bg-white/20';
        countBadge.textContent = `${messages.length} ${messages.length === 1 ? 'message' : 'messages'}`;
        heading.appendChild(countBadge);

        const messageList = document.createElement('ul');
        messageList.className = 'mt-2 flex max-h-60 flex-col gap-1 overflow-y-auto pr-1 text-left text-sm font-medium';

        messages.forEach(({ text }) => {
            const listItem = document.createElement('li');
            listItem.className = 'break-words';
            listItem.textContent = text;
            messageList.appendChild(listItem);
        });

        contentWrapper.appendChild(heading);
        contentWrapper.appendChild(messageList);
        toast.appendChild(contentWrapper);

        const dismissButton = document.createElement('button');
        dismissButton.type = 'button';
        dismissButton.className = 'mr-3 mt-3 inline-flex h-8 w-8 flex-none items-center justify-center rounded-full bg-white/80 text-gray-600 transition hover:bg-white hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500 dark:bg-slate-800/80 dark:text-slate-200';
        dismissButton.setAttribute('aria-label', 'Dismiss notification');
        dismissButton.innerHTML = '<span aria-hidden="true" class="text-base font-bold">&times;</span>';
        dismissButton.addEventListener('click', () => removeToast(toast));
        toast.appendChild(dismissButton);

        toastContainer.appendChild(toast);

        const shouldAutoDismiss = !['warning', 'error'].includes(primaryCategory);
        if (shouldAutoDismiss) {
            setTimeout(() => {
                removeToast(toast);
            }, 8000);
        }
    });

    if (!toastContainer.childElementCount) {
        return;
    }

    document.body.appendChild(toastContainer);
};

if (typeof window !== 'undefined') {
    window.renderFlashToasts = renderFlashToasts;
}

document.addEventListener('DOMContentLoaded', function () {
    if (window.initFlowbite) {
        try { initFlowbite(); } catch (e) { /* ignore errors if flowbite unavailable */ }
    }
    renderFlashToasts();
});
