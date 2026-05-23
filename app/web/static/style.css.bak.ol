/*
 * ===== AFD Design System :: OpenList-style =====
 * Modern, clean, cloud-app aesthetic with white surfaces, blue accents, and airy spacing.
 * Inspired by OpenList (a fork of AList) — minimal, soft, utility-focused.
 */

/* ===== CSS Custom Properties (Design Tokens) ===== */
:root {
    /* Backgrounds */
    --bg-page: #f5f6f8;
    --bg-surface: #ffffff;
    --bg-surface-alt: #f0f2f5;
    --bg-surface-hover: #f8f9fb;
    --bg-elevated: #ffffff;
    --bg-elevated-hover: #f3f4f6;
    --bg-input: #ffffff;
    --bg-overlay: rgba(0, 0, 0, 0.5);
    --bg-code: #f6f8fa;
    --bg-success: rgba(34, 197, 94, 0.08);
    --bg-danger: rgba(239, 68, 68, 0.08);
    --bg-warning: rgba(234, 179, 8, 0.08);
    --bg-accent: rgba(24, 144, 255, 0.06);

    /* Borders */
    --border-color: #e8eaed;
    --border-color-hover: #d1d5db;
    --border-color-focus: #1890ff;
    --border-color-success: #22c55e;

    /* Text */
    --text-primary: #202124;
    --text-secondary: #5f6368;
    --text-tertiary: #9aa0a6;
    --text-muted: #dadce0;
    --text-link: #1890ff;
    --text-accent: #1890ff;

    /* Accent / Blue */
    --accent: #1890ff;
    --accent-hover: #40a9ff;
    --accent-dim: rgba(24, 144, 255, 0.08);
    --accent-glow: 0 0 12px rgba(24, 144, 255, 0.15);

    /* Status */
    --green: #22c55e;
    --green-dim: rgba(34, 197, 94, 0.12);
    --red: #ef4444;
    --red-dim: rgba(239, 68, 68, 0.12);
    --yellow: #eab308;
    --yellow-dim: rgba(234, 179, 8, 0.12);
    --orange: #f59e0b;
    --blue: #1890ff;
    --purple: #8b5cf6;

    /* Spacing */
    --space-xs: 4px;
    --space-sm: 8px;
    --space-md: 12px;
    --space-lg: 16px;
    --space-xl: 20px;
    --space-2xl: 24px;
    --space-3xl: 32px;
    --space-4xl: 40px;

    /* Border radius */
    --radius-sm: 6px;
    --radius-md: 8px;
    --radius-lg: 12px;
    --radius-xl: 16px;
    --radius-full: 9999px;

    /* Shadows */
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 2px 8px rgba(0,0,0,0.06);
    --shadow-lg: 0 4px 16px rgba(0,0,0,0.08);
    --shadow-xl: 0 8px 32px rgba(0,0,0,0.1);
    --shadow-glow: 0 0 20px rgba(24, 144, 255, 0.08);

    /* Typography */
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
    --font-mono: "SF Mono", "JetBrains Mono", "Cascadia Code", "Fira Code", "Noto Sans Mono", monospace;

    /* Transitions */
    --transition-fast: 120ms ease;
    --transition-base: 200ms ease;
    --transition-slow: 350ms ease;

    /* Layout */
    --container-max: 1000px;
    --topbar-height: 48px;
}

/* ===== Dark theme ===== */
html[data-theme="dark"]:root,
html[data-theme="dark"] {
    --bg-page: #111318;
    --bg-surface: #1c1e24;
    --bg-surface-alt: #252730;
    --bg-surface-hover: #22242c;
    --bg-elevated: #1c1e24;
    --bg-elevated-hover: #252730;
    --bg-input: #111318;
    --bg-overlay: rgba(0, 0, 0, 0.7);
    --bg-code: #1c1e24;
    --bg-success: rgba(34, 197, 94, 0.12);
    --bg-danger: rgba(239, 68, 68, 0.12);
    --bg-warning: rgba(234, 179, 8, 0.12);
    --bg-accent: rgba(24, 144, 255, 0.12);

    --border-color: #2e3039;
    --border-color-hover: #3a3d48;
    --border-color-focus: #1890ff;
    --border-color-success: #22c55e;

    --text-primary: #e8eaed;
    --text-secondary: #9aa0a6;
    --text-tertiary: #5f6368;
    --text-muted: #3a3d48;
    --text-link: #1890ff;
    --text-accent: #1890ff;

    --accent: #1890ff;
    --accent-hover: #40a9ff;
    --accent-dim: rgba(24, 144, 255, 0.12);
    --accent-glow: 0 0 12px rgba(24, 144, 255, 0.15);

    --green: #22c55e;
    --red: #ef4444;
    --yellow: #eab308;
    --blue: #1890ff;

    --shadow-sm: 0 1px 2px rgba(0,0,0,0.2);
    --shadow-md: 0 2px 8px rgba(0,0,0,0.3);
    --shadow-lg: 0 4px 16px rgba(0,0,0,0.4);
    --shadow-xl: 0 8px 32px rgba(0,0,0,0.4);
    --shadow-glow: 0 0 20px rgba(24, 144, 255, 0.1);
}

/* ===== Reset ===== */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { font-size: 14px; }
body {
    font-family: var(--font-sans);
    background: var(--bg-page);
    color: var(--text-primary);
    line-height: 1.5;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ===== Topbar (OpenList-style minimal header) ===== */
.topbar {
    height: var(--topbar-height);
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--space-xl);
    position: sticky;
    top: 0;
    z-index: 100;
}

.topbar-left {
    display: flex;
    align-items: center;
    gap: var(--space-xl);
}

.topbar-logo {
    font-weight: 600;
    font-size: 1rem;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 6px;
}
.topbar-logo span { color: var(--text-tertiary); font-weight: 400; }

.topbar-nav {
    display: flex;
    align-items: center;
    gap: 2px;
}

.topbar-nav a {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--text-secondary);
    border-radius: var(--radius-sm);
    transition: all var(--transition-fast);
    text-decoration: none;
}
.topbar-nav a:hover {
    background: var(--bg-surface-hover);
    color: var(--text-primary);
    text-decoration: none;
}
.topbar-nav a.active {
    color: var(--accent);
    background: var(--bg-accent);
}

.topbar-nav a .nav-label { display: inline; }

.topbar-right {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
}

.node-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    font-size: 0.78rem;
    color: var(--text-secondary);
    background: var(--bg-surface-alt);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-full);
}

/* ===== Container (centered card layout) ===== */
.container {
    max-width: var(--container-max);
    margin: 0 auto;
    padding: var(--space-xl);
}

/* ===== Card ===== */
.card {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
}

/* ===== Search ===== */
.search-wrap {
    position: relative;
    margin-bottom: var(--space-lg);
}
.search-wrap .search-icon {
    position: absolute;
    left: 12px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 0.85rem;
    opacity: 0.4;
    pointer-events: none;
}
.search-wrap input[type="search"] {
    width: 100%;
    padding: 8px 12px 8px 36px;
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-size: 0.88rem;
    font-family: var(--font-sans);
    outline: none;
    transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.search-wrap input[type="search"]:focus {
    border-color: var(--border-color-focus);
    box-shadow: 0 0 0 2px var(--accent-dim);
}
.search-wrap input[type="search"]::placeholder { color: var(--text-tertiary); }

/* ===== Filter pills ===== */
.filter-pills {
    display: flex;
    gap: 4px;
    margin-bottom: var(--space-lg);
    flex-wrap: wrap;
}
.filter-pill {
    padding: 4px 12px;
    font-size: 0.78rem;
    border-radius: var(--radius-full);
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-tertiary);
    cursor: pointer;
    transition: all var(--transition-fast);
    user-select: none;
    line-height: 1.4;
}
.filter-pill:hover {
    border-color: var(--border-color-hover);
    color: var(--text-secondary);
}
.filter-pill.active {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
}

/* ===== File List (OpenList-style card) ===== */
.file-list {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow-sm);
}

.file-list-header {
    display: flex;
    align-items: center;
    padding: 12px 16px;
    background: var(--bg-surface-alt);
    border-bottom: 1px solid var(--border-color);
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.3px;
}

.file-list-header .header-name { flex: 1; display: flex; align-items: center; gap: 8px; }
.file-list-header .header-size {
    width: 80px;
    text-align: right;
    flex-shrink: 0;
}
.file-list-header .header-time {
    width: 140px;
    text-align: right;
    flex-shrink: 0;
}
.file-list-header .header-actions {
    width: 130px;
    text-align: right;
    flex-shrink: 0;
}

.file-row {
    display: flex;
    align-items: center;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border-color);
    transition: background var(--transition-fast);
    gap: 12px;
}
.file-row:last-child { border-bottom: none; }
.file-row:hover { background: var(--bg-surface-hover); }

.file-row .row-check {
    flex-shrink: 0;
    width: 16px;
}
.file-row .row-check input[type="checkbox"] {
    accent-color: var(--accent);
    width: 14px;
    height: 14px;
    cursor: pointer;
    vertical-align: middle;
}

.file-row .row-icon {
    flex-shrink: 0;
    width: 20px;
    text-align: center;
    font-size: 1rem;
    line-height: 1;
}

.file-row .row-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.88rem;
    color: var(--accent);
    cursor: pointer;
}
.file-row .row-name:hover { text-decoration: underline; color: var(--accent-hover); }

.file-row .row-size {
    width: 80px;
    text-align: right;
    flex-shrink: 0;
    font-size: 0.82rem;
    color: var(--text-secondary);
    font-family: var(--font-mono);
}

.file-row .row-time {
    width: 140px;
    text-align: right;
    flex-shrink: 0;
    font-size: 0.8rem;
    color: var(--text-tertiary);
}

.file-row .row-actions {
    width: 130px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 4px;
}

/* Row action buttons */
.btn-row {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    color: var(--text-tertiary);
    cursor: pointer;
    font-size: 0.8rem;
    transition: all var(--transition-fast);
    opacity: 0.3;
}
.file-row:hover .btn-row { opacity: 0.5; }
.btn-row:hover { opacity: 1 !important; background: var(--bg-surface-alt); border-color: var(--border-color); color: var(--text-secondary); }
.btn-row.btn-dl-row { opacity: 0.6; }
.btn-row.btn-dl-row:hover { background: var(--bg-accent); border-color: var(--accent); color: var(--accent); }
.btn-row.btn-del-row:hover { background: var(--bg-danger); border-color: var(--red); color: var(--red); }

/* Multi-source tag */
.multi-source-tag {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 1px 7px;
    font-size: 0.65rem;
    color: var(--accent);
    background: var(--bg-accent);
    border: 1px solid rgba(24, 144, 255, 0.2);
    border-radius: var(--radius-sm);
    font-weight: 500;
    white-space: nowrap;
    flex-shrink: 0;
}

/* ===== Stats bar ===== */
.stats-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-md) var(--space-sm);
    font-size: 0.82rem;
    color: var(--text-tertiary);
}
.stats-bar .count { color: var(--text-secondary); }
.stats-bar .total-size { font-family: var(--font-mono); }

/* ===== Empty state ===== */
.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 60px 20px;
    text-align: center;
}
.empty-state .emoji { font-size: 3rem; margin-bottom: var(--space-md); opacity: 0.5; }
.empty-state h3 { font-size: 1.1rem; margin-bottom: var(--space-sm); color: var(--text-primary); }
.empty-state p { font-size: 0.88rem; color: var(--text-tertiary); }

/* ===== Loading ===== */
.loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 80px 20px;
    gap: var(--space-md);
    color: var(--text-tertiary);
}
.spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--border-color);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ===== Buttons ===== */
.btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    font-size: 0.85rem;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border-color);
    background: var(--bg-surface);
    color: var(--text-secondary);
    cursor: pointer;
    transition: all var(--transition-fast);
    font-family: var(--font-sans);
    font-weight: 500;
    text-decoration: none;
    line-height: 1.4;
}
.btn:hover {
    background: var(--bg-surface-hover);
    border-color: var(--border-color-hover);
    text-decoration: none;
}
.btn-primary {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
}
.btn-primary:hover {
    background: var(--accent-hover);
    border-color: var(--accent-hover);
}
.btn-success {
    background: var(--green);
    border-color: var(--green);
    color: #fff;
}
.btn-sm {
    padding: 4px 10px;
    font-size: 0.78rem;
}

/* ===== Batch bar ===== */
.batch-bar {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
    padding: 8px 0;
    font-size: 0.82rem;
    color: var(--text-tertiary);
}
.batch-bar .batch-count { color: var(--text-secondary); font-weight: 500; }
.batch-bar .btn-batch-del {
    padding: 4px 12px;
    background: var(--bg-danger);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: var(--radius-sm);
    color: var(--red);
    cursor: pointer;
    font-size: 0.78rem;
    opacity: 0.4;
    pointer-events: none;
    transition: all var(--transition-fast);
    font-family: var(--font-sans);
}
.batch-bar .btn-batch-del.active { opacity: 1; pointer-events: auto; }
.batch-bar .btn-batch-del:hover { background: rgba(239, 68, 68, 0.15); }

/* ===== Source Popup ===== */
.source-popup {
    position: fixed;
    inset: 0;
    background: var(--bg-overlay);
    display: flex;
    align-items: flex-end;
    justify-content: center;
    z-index: 999;
    opacity: 0;
    pointer-events: none;
    transition: opacity var(--transition-base);
}
.source-popup.show { opacity: 1; pointer-events: auto; }
.source-sheet {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    width: min(480px, 100%);
    max-height: 60vh;
    overflow-y: auto;
    transform: translateY(100%);
    transition: transform var(--transition-base);
}
.source-popup.show .source-sheet { transform: translateY(0); }
.source-sheet-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-lg) var(--space-xl);
    border-bottom: 1px solid var(--border-color);
}
.source-sheet-header h3 {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.source-sheet-header .close-btn {
    background: transparent;
    border: none;
    color: var(--text-tertiary);
    font-size: 1.2rem;
    cursor: pointer;
    padding: 4px;
    line-height: 1;
}
.source-sheet-header .close-btn:hover { color: var(--text-primary); }
#sourceList { padding: var(--space-sm); }
.source-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-md) var(--space-lg);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--transition-fast);
}
.source-option:hover { background: var(--bg-surface-hover); }
.source-option .node-name { font-weight: 500; color: var(--text-primary); }
.source-option .btn-dl {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    background: var(--bg-accent);
    color: var(--accent);
    border: 1px solid rgba(24, 144, 255, 0.2);
    border-radius: var(--radius-sm);
    font-size: 0.78rem;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    transition: all var(--transition-fast);
}
.source-option .btn-dl:hover { background: rgba(24, 144, 255, 0.12); border-color: rgba(24, 144, 255, 0.4); }

/* ===== Toast ===== */
.copy-toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    padding: 8px 18px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    color: var(--green);
    font-size: 0.82rem;
    opacity: 0;
    transition: opacity var(--transition-base);
    z-index: 300;
    pointer-events: none;
    box-shadow: var(--shadow-lg);
}
.copy-toast.show { opacity: 1; }

/* ===== Preview Modal ===== */
.preview-overlay {
    position: fixed;
    inset: 0;
    background: var(--bg-overlay);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 999;
    backdrop-filter: blur(4px);
    animation: fadeIn 0.15s ease;
}
.preview-modal {
    background: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    width: min(700px, 94vw);
    max-height: 85vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    animation: sheetUp 0.2s ease;
}
.preview-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px var(--space-xl);
    border-bottom: 1px solid var(--border-color);
}
.preview-head h3 { font-size: 0.9rem; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-close { background: transparent; border: none; color: var(--text-tertiary); font-size: 1.2rem; cursor: pointer; padding: 4px; line-height: 1; }
.preview-close:hover { color: var(--text-primary); }
.preview-body { padding: var(--space-xl); display: flex; align-items: center; justify-content: center; min-height: 100px; overflow: auto; flex: 1; }
.preview-body img { max-width: 100%; max-height: 70vh; border-radius: var(--radius-sm); }
.preview-body pre { width: 100%; max-height: 60vh; overflow: auto; font: 13px/1.5 var(--font-mono); color: var(--text-primary); white-space: pre-wrap; word-break: break-all; background: var(--bg-code); padding: var(--space-lg); border-radius: var(--radius-sm); margin: 0; }
.preview-body .preview-fail { color: var(--text-tertiary); font-size: 0.85rem; }

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes sheetUp { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

/* ===== Form inputs ===== */
.input {
    width: 100%;
    padding: 8px 12px;
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-size: 0.88rem;
    font-family: var(--font-sans);
    outline: none;
    transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.input:focus { border-color: var(--border-color-focus); box-shadow: 0 0 0 2px var(--accent-dim); }
.input::placeholder { color: var(--text-muted); }

/* ===== Download form ===== */
.form-inline { display: flex; gap: 8px; flex-wrap: wrap; }
.form-inline .input-url { flex: 1; min-width: 200px; }
@media (max-width: 640px) { .form-inline { flex-direction: column; } }

/* ===== Task items ===== */
.task-section { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-sm); }
.task-section .task-head { padding: 14px var(--space-xl); display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-color); }
.task-section .task-head h2 { font-size: 0.88rem; font-weight: 600; color: var(--text-secondary); display: flex; align-items: center; gap: 8px; }
.task-section .task-head h2 .count-badge { font-size: 0.7rem; font-weight: 500; color: var(--text-tertiary); background: var(--bg-surface-alt); padding: 1px 8px; border-radius: var(--radius-full); }
.task-item { padding: 14px var(--space-xl); border-bottom: 1px solid var(--border-color); transition: background var(--transition-fast); cursor: pointer; }
.task-item:last-child { border-bottom: none; }
.task-item:hover { background: var(--bg-surface-hover); }
.task-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.task-info { flex: 1; min-width: 0; }
.task-info .name { font-weight: 600; color: var(--text-primary); word-break: break-all; font-size: 0.9rem; }
.task-info .url { font-size: 0.75rem; color: var(--text-tertiary); margin-top: 2px; word-break: break-all; }
.task-status-col { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex-shrink: 0; }
.task-actions { display: flex; gap: 4px; }
.task-action-btn { background: transparent; border: 1px solid var(--border-color); border-radius: var(--radius-sm); width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; font-size: 0.72rem; transition: all var(--transition-fast); opacity: 0.5; color: var(--text-tertiary); }
.task-action-btn:hover { opacity: 1; }
.task-action-btn.resume:hover { color: var(--green); border-color: var(--green); }
.task-action-btn.pause:hover { color: var(--yellow); border-color: var(--yellow); }
.task-action-btn.cancel:hover { color: var(--yellow); border-color: var(--yellow); }
.task-action-btn.retry:hover { color: var(--accent); border-color: var(--accent); }
.task-action-btn.delete:hover { color: var(--red); border-color: var(--red); }
.task-meta-bar { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.meta-chip { display: inline-flex; align-items: center; gap: 3px; padding: 2px 8px; font-size: 0.72rem; color: var(--text-tertiary); background: var(--bg-surface-alt); border-radius: var(--radius-sm); }

.progress-bar-wrap { height: 8px; background: var(--bg-surface-alt); border-radius: 4px; overflow: hidden; max-width: 200px; }
.progress-bar { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
.progress-bar-accent { background: var(--accent); }
.progress-bar-green { background: var(--green); }
.progress-bar-red { background: var(--red); }
.progress-bar-yellow { background: var(--yellow); }

.badge { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: var(--radius-full); font-size: 0.72rem; font-weight: 600; }
.badge-downloading { background: var(--bg-accent); color: var(--accent); border: 1px solid rgba(24, 144, 255, 0.2); }
.badge-paused { background: rgba(234, 179, 8, 0.08); color: var(--yellow); border: 1px solid rgba(234, 179, 8, 0.2); }
.badge-completed { background: rgba(34, 197, 94, 0.08); color: var(--green); border: 1px solid rgba(34, 197, 94, 0.2); }
.badge-failed { background: rgba(239, 68, 68, 0.08); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.2); }
.badge-pending { background: rgba(139,92,246,0.08); color: #a78bfa; border: 1px solid rgba(139,92,246,0.2); }
.badge-seeding { background: rgba(34,197,94,0.06); color: var(--green); border: 1px solid rgba(34,197,94,0.12); }

.node-progress { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
.node-progress .node-label { width: 60px; font-size: 0.78rem; color: var(--text-tertiary); flex-shrink: 0; font-weight: 500; }
.node-progress .node-label.offline { color: var(--red); opacity: 0.7; }
.node-progress .pct { width: 36px; text-align: right; color: var(--text-tertiary); font-size: 0.76rem; font-family: var(--font-mono); }

/* ===== Station / Node cards ===== */
.station-card, .section-card { background: var(--bg-surface); border: 1px solid var(--border-color); border-radius: var(--radius-lg); margin-bottom: 16px; overflow: hidden; box-shadow: var(--shadow-sm); }
.station-head, .section-card .section-head { display: flex; align-items: center; justify-content: space-between; padding: var(--space-md) var(--space-lg); border-bottom: 1px solid var(--border-color); }
.station-head-left { display: flex; align-items: center; gap: 10px; }
.station-name { font-weight: 600; font-size: 0.95rem; color: var(--text-primary); }
.station-host { font-size: 0.72rem; color: var(--text-tertiary); font-family: var(--font-mono); }
.station-body { padding: var(--space-md) var(--space-lg); }
.speed-row { display: flex; gap: var(--space-md); margin-bottom: var(--space-md); }
.speed-gauge { flex: 1; background: var(--bg-surface-alt); border-radius: var(--radius-md); padding: 10px 14px; text-align: center; border: 1px solid var(--border-color); }
.speed-gauge .speed-label { font-size: 0.7rem; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.speed-gauge .speed-value { font-size: 1.2rem; font-weight: 700; font-family: var(--font-mono); }
.speed-gauge .speed-value.down { color: var(--accent); }
.speed-gauge .speed-value.up { color: var(--green); }
.stat-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: var(--space-md); }
.stat-chip { padding: 4px 12px; border-radius: var(--radius-sm); font-size: 0.76rem; font-weight: 500; display: flex; align-items: center; gap: 4px; }
.stat-chip.downloading { background: var(--bg-accent); color: var(--accent); border: 1px solid rgba(24,144,255,0.15); }
.stat-chip.paused { background: rgba(234
