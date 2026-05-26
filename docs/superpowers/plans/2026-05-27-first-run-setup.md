# First-Run Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-run setup page that configures Allfiledown username, password, download path, node identity, and public URL.

**Architecture:** Add small setup helper functions in `app.web.routes`, a `setup.html` template, and installer changes that write either initialized or uninitialized config depending on whether `--web-password` is supplied. Keep old configs compatible.

**Tech Stack:** FastAPI, Jinja templates, pytest, Bash installer.

---

### Task 1: Setup state and validation

**Files:**
- Modify: `app/web/routes.py`
- Test: `tests/test_web_setup.py`

- [ ] Add tests for uninitialized detection, public URL normalization, setup validation, hashed password save, and redirect behavior.
- [ ] Implement `_is_initialized`, `_setup_redirect_if_needed`, `_normalize_public_base`, and `api_setup`.
- [ ] Verify with `pytest tests/test_web_setup.py -q`.

### Task 2: Setup page

**Files:**
- Create: `app/web/templates/setup.html`
- Modify: `app/web/routes.py`

- [ ] Add `GET /setup` route.
- [ ] Add a compact form posting JSON to `/api/setup`.
- [ ] Verify with template rendering test/client smoke check.

### Task 3: Installer uninitialized mode

**Files:**
- Modify: `/data/tools/install_allfiledown.sh`

- [ ] Change config writer so missing `--web-password` writes `initialized: false` and empty web password.
- [ ] Keep explicit `--web-password` path initialized.
- [ ] Update summary text to say setup is required instead of printing a random password.
- [ ] Syntax-check with `bash -n /data/tools/install_allfiledown.sh`.

### Task 4: Full verification

- [ ] Run focused pytest for config/web auth/setup.
- [ ] Run full pytest if practical.
- [ ] Report changed files and exact verification result.
