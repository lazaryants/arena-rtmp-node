(() => {
    const STORAGE_KEY = 'arena-ui-theme';
    const THEMES = new Set(['dark', 'light']);

    function readTheme() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (THEMES.has(stored)) {
                return stored;
            }
        } catch (_error) {
            // Storage may be unavailable in privacy-restricted browsers.
        }
        return 'dark';
    }

    function applyTheme(theme) {
        const selected = THEMES.has(theme) ? theme : 'dark';
        document.documentElement.dataset.theme = selected;
        document.documentElement.style.colorScheme = selected;

        document.querySelectorAll('[data-theme-toggle]').forEach(button => {
            const light = selected === 'light';
            button.setAttribute('aria-pressed', String(light));
            button.setAttribute(
                'aria-label',
                light ? 'Use dark theme' : 'Use light theme',
            );
            button.title = light ? 'Dark theme' : 'Light theme';
            button.textContent = light ? '☾' : '☀';
        });
    }

    function saveTheme(theme) {
        try {
            localStorage.setItem(STORAGE_KEY, theme);
        } catch (_error) {
            // The visual switch still works for the current page.
        }
    }

    function createToggle() {
        const accountSlot = document.querySelector('.account-slot');
        if (!accountSlot || accountSlot.querySelector('[data-theme-toggle]')) {
            return;
        }

        const button = document.createElement('button');
        button.className = 'theme-toggle';
        button.type = 'button';
        button.dataset.themeToggle = '';
        accountSlot.prepend(button);
    }

    function setupThemeToggle() {
        createToggle();
        applyTheme(document.documentElement.dataset.theme || readTheme());

        document.querySelectorAll('[data-theme-toggle]').forEach(button => {
            button.addEventListener('click', () => {
                const current = document.documentElement.dataset.theme;
                const next = current === 'light' ? 'dark' : 'light';
                applyTheme(next);
                saveTheme(next);
            });
        });
    }

    applyTheme(readTheme());

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupThemeToggle);
    } else {
        setupThemeToggle();
    }

    window.addEventListener('storage', event => {
        if (event.key === STORAGE_KEY && THEMES.has(event.newValue)) {
            applyTheme(event.newValue);
        }
    });
})();
