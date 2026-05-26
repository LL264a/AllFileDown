# First-Run Setup Design

## Goal

Allfiledown should support a clean first-run setup page for new installs. Instead of relying on random installer-generated web credentials, a fresh deployment can start in an uninitialized state and let the operator configure the stable values once from the browser.

## Setup Fields

The setup page collects these values together:

- Web username
- Web password
- Password confirmation
- Download path
- Node ID
- Node name
- Public host / public URL

## Initialization Rules

The app is considered uninitialized when `config["initialized"]` is false, or when either `web_username` or `web_password` is missing. In that state:

- `GET /setup` renders the setup page.
- `POST /api/setup` validates and saves the submitted configuration.
- Browser pages that normally require setup (`/`, `/login`, `/downloads`, `/stations`, `/nodes`) redirect to `/setup`.
- API helpers such as `/health` remain available.

After setup succeeds:

- `initialized` is set to true.
- `web_password` is stored as a password hash.
- The download directory is created if it does not exist.
- `public_base_url` and `file_base_url` are derived from the public host value.
- The browser is redirected to `/login`.
- Visiting `/setup` again redirects to `/`.

## Public Host Normalization

If the public host already starts with `http://` or `https://`, keep it as the base URL without adding the app port. If it is a raw hostname or IP, generate `http://<host>:<port>`. `file_base_url` is always `<public_base_url>/tasks`.

## Installer Compatibility

The installer keeps unattended deployment support. If `--web-password` is provided, it writes an initialized config. If it is omitted on a new install, it writes `initialized: false` and leaves the web password empty so the app opens the setup page.

Existing configs are not overwritten unless `--force-config` is used.
