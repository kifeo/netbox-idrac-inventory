# Changelog

## 0.2.0 (unreleased)

### New features

- **Firmware inventory**: each sync reads `UpdateService/FirmwareInventory`
  and writes the installed version onto matching components (by FQDD).
- **Bulk sync**: a *Sync from iDRAC* button on the server list enqueues sync
  jobs for the selected servers.
- **`allowed_networks` setting** (opt-in): restricts which prefixes iDRAC
  addresses and scan targets may point at, so a user with change permission
  cannot direct the iDRAC credentials to an arbitrary host.
- **Per-device password via the REST API**: `idrac_password` is accepted on
  POST/PATCH (write-only, encrypted at rest, never returned).

### Changes

- The recurring fleet sync now fans out one background job per server
  (parallel workers, per-server job history) instead of a serial loop.
- `SECRET_KEY` rotation with `SECRET_KEY_FALLBACKS` keeps stored passwords
  readable; an undecryptable stored password now fails the sync with a clear
  message instead of silently falling back to the global default.
- The `enabled` flag on scan ranges is enforced (UI, API and job).
- Scan-range discovery runs (API) return the job URL under `/api/core/jobs/`
  (the NetBox 4.x location; previously mis-documented as `/api/extras/`).
- Triggering sync/discovery through the API now requires the *change*
  permission on the object, matching the UI.
- A sync that reports no network adapters at all (typically a transient
  Redfish failure) no longer deletes the existing modules and interfaces;
  removals of stale interfaces/bays are logged.
- Declared compatibility extended to NetBox 4.6 (`max_version = "4.6.99"`),
  verified by running the full suite on v4.2 and v4.6.4; the API tests carry
  the query-count baseline NetBox 4.6 requires.

### Bug fixes

- IPv6 iDRAC addresses are no longer mangled when deriving the default
  device name (`2001:db8::10` previously became `2001`).
- Removed an unused bulk-edit form.

## 0.1.0

- Initial release: DellServer/DellComponent/DellScanRange models, iDRAC
  Redfish sync engine (components, network adapters as modules/interfaces,
  LLDP custom fields, OOB IP), discovery scan ranges, REST + GraphQL APIs,
  background jobs and optional scheduled sync.
