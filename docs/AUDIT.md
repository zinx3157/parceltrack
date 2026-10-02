# Audit and fixes — 2 October 2026

Reviewed the repository and the published GitHub Pages page. The published page is the README rendered by Pages, not a running ParcelDesk installation. A persistent Python host is required for production; no backend has been deployed by this change.

## Fixed

- Restrict the SPA file handler to its static directory after resolving paths; return real 404s for missing API/static assets.
- Reject weak/default JWT signing keys outside demo mode. Invalidate staff sessions after password changes, require token expiry/subject claims, and handle malformed stored password hashes safely.
- Match login identifiers literally, case-insensitively, instead of treating `%` and `_` as SQL wildcards.
- Fix the duplicate `name` argument that crashed client creation.
- Fetch label pages and exports with bearer authentication, without placing tokens in URLs. Handle unavailable clipboard access.
- Retry reads only: repeating a failed receiving POST could otherwise add a second carton after the first request committed.
- Resolve barcodes by normalized exact match or an unambiguous literal partial match. Ambiguous scans cannot receive a parcel.
- Block direct receiving/receipt clearing after release, repeated release, and release before all cartons arrive. Age partial receipts from their first receipt timestamp.
- Neutralize formula-like strings in CSV, parcel Excel, and warehouse Excel exports.
- Avoid constructing real carrier HTTP clients in demo diagnostics; include SOCKS support for environments using a SOCKS proxy.
- Add regression checks and GitHub Actions validation; refresh frontend asset versions.

## Validation

- `python tests/test_all_features.py`: 62/62 checks.
- `python tests/test_audit_regressions.py`: isolated security and operational regression checks.
- `python tests/test_messaging_webhook.py`: local stand-in messaging gateway end-to-end.
- `node tests/ui_smoke.js`: every view in normal and restricted stub browser environments.

These UI checks use a stub DOM, not a real-browser layout/accessibility test. Live carrier requests, actual SMTP/WhatsApp delivery, load testing, and production hosting were not verified. Configure first-run admin credentials, HTTPS, backups, and carrier access before using real shipments. Existing staff tokens will require a fresh login.
