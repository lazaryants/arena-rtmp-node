(() => {
    const STORAGE_KEY = 'arena-ui-theme';
    const THEMES = {
        dark: { icon: '☾', label: 'Dark' },
        ice: { icon: '❄', label: 'Ice' },
        sand: { icon: '◉', label: 'Sand' },
        padel: { icon: '▦', label: 'Padel' },
    };

    function normalizeTheme(value) {
        if (value === 'light') {
            return 'ice';
        }
        return Object.hasOwn(THEMES, value) ? value : 'dark';
    }

    function readTheme() {
        try {
            return normalizeTheme(localStorage.getItem(STORAGE_KEY));
        } catch (_error) {
            // Storage may be unavailable in privacy-restricted browsers.
            return 'dark';
        }
    }

    function applyTheme(theme) {
        const selected = normalizeTheme(theme);
        const metadata = THEMES[selected];
        document.documentElement.dataset.theme = selected;
        document.documentElement.style.colorScheme = (
            selected === 'dark' ? 'dark' : 'light'
        );

        document.querySelectorAll('[data-theme-toggle]').forEach(button => {
            button.textContent = metadata.icon;
            button.setAttribute('aria-label', `Theme: ${metadata.label}`);
            button.title = `Theme: ${metadata.label}`;
        });

        document.querySelectorAll('[data-theme-option]').forEach(option => {
            const active = option.dataset.themeOption === selected;
            option.classList.toggle('active', active);
            option.setAttribute('aria-checked', String(active));
        });
    }

    function saveTheme(theme) {
        try {
            localStorage.setItem(STORAGE_KEY, normalizeTheme(theme));
        } catch (_error) {
            // The visual switch still works for the current page.
        }
    }

    function closePicker(wrapper) {
        const button = wrapper.querySelector('[data-theme-toggle]');
        const menu = wrapper.querySelector('[data-theme-menu]');
        menu.hidden = true;
        button.setAttribute('aria-expanded', 'false');
    }

    function createPicker() {
        const accountSlot = document.querySelector('.account-slot');
        if (!accountSlot || accountSlot.querySelector('[data-theme-picker]')) {
            return null;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'theme-picker';
        wrapper.dataset.themePicker = '';

        const button = document.createElement('button');
        button.className = 'theme-toggle';
        button.type = 'button';
        button.dataset.themeToggle = '';
        button.setAttribute('aria-haspopup', 'menu');
        button.setAttribute('aria-expanded', 'false');

        const menu = document.createElement('div');
        menu.className = 'theme-menu';
        menu.dataset.themeMenu = '';
        menu.setAttribute('role', 'menu');
        menu.hidden = true;

        Object.entries(THEMES).forEach(([value, metadata]) => {
            const option = document.createElement('button');
            option.className = 'theme-option';
            option.type = 'button';
            option.dataset.themeOption = value;
            option.setAttribute('role', 'menuitemradio');
            option.textContent = `${metadata.icon}  ${metadata.label}`;
            menu.append(option);
        });

        wrapper.append(button, menu);
        accountSlot.prepend(wrapper);
        return wrapper;
    }

    function setupThemePicker() {
        const wrapper = createPicker();
        applyTheme(document.documentElement.dataset.theme || readTheme());
        if (!wrapper) {
            return;
        }

        const button = wrapper.querySelector('[data-theme-toggle]');
        const menu = wrapper.querySelector('[data-theme-menu]');

        button.addEventListener('click', event => {
            event.stopPropagation();
            const opening = menu.hidden;
            menu.hidden = !opening;
            button.setAttribute('aria-expanded', String(opening));
        });

        menu.querySelectorAll('[data-theme-option]').forEach(option => {
            option.addEventListener('click', () => {
                const selected = normalizeTheme(option.dataset.themeOption);
                applyTheme(selected);
                saveTheme(selected);
                closePicker(wrapper);
            });
        });

        document.addEventListener('click', event => {
            if (!wrapper.contains(event.target)) {
                closePicker(wrapper);
            }
        });

        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') {
                closePicker(wrapper);
                button.focus();
            }
        });
    }

    applyTheme(readTheme());

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupThemePicker);
    } else {
        setupThemePicker();
    }

    window.addEventListener('storage', event => {
        if (event.key === STORAGE_KEY) {
            applyTheme(event.newValue);
        }
    });
})();
