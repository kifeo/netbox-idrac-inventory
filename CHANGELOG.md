# Changelog

## 0.3.3 (unreleased)

### New features

- **Auto-detected iDRAC address for pre-existing devices**: when adding a
  Dell server from an existing device's page, if that device already has an
  interface named "iDRAC" with an IP assigned (common for a device
  onboarded before this plugin), the iDRAC address field is pre-filled from
  it instead of requiring it to be retyped.

## 0.3.2

### Fixes

- **Duplicate interfaces on pre-existing devices**: network ports were
  matched by name only (Dell's FQDD, e.g. `NIC.Integrated.1-1`). A device
  onboarded before this plugin — with interfaces already named/cabled under
  a different scheme (e.g. `eth0`) — got a second, duplicate interface
  created alongside the original on every sync, leaving the original (and
  its cable/IP) orphaned. Ports are now matched by their already-recorded
  MAC address first, falling back to name; a matched interface is renamed
  to the Dell port name in place, keeping its cable and IP assignments.

## 0.3.1

### Fixes

- **iDRAC connect timeout**: `idrac_timeout` was only wired to sushy's
  `read_timeout`, never `connect_timeout` (which defaults to unbounded). A
  host that doesn't respond at the TCP level at all (dropped packets, no
  RST/no-route) could hang far past the configured timeout instead of
  failing as "unreachable" — on a subnet with many non-iDRAC or offline
  addresses this made a full scan range extremely slow or effectively
  stuck. Now bounded by the same configured timeout as the read phase.

## 0.3.0

### New features

- **Per-server site confirmation**: a scan range's site is now only a
  best-effort default for newly-discovered devices — each is flagged
  (`site_confirmed=False`) and listed on a new **Site Review** page
  (Plugins → iDRAC Inventory → Dell Servers → Site Review) where a human
  sets or corrects the site individually before it's considered final.
  Useful when one iDRAC management subnet spans multiple NetBox sites.
- The server list gained a "Site confirmed" column/filter, and a discovery
  run's summary now reports how many newly-created devices need review.
- **NUMA node per network adapter**: the NUMA node a Dell NIC's PCIe lanes
  are wired to (read from Redfish `Oem.Dell.CPUAffinity`, converted from
  Dell's 1-indexed CPU socket to a 0-indexed NUMA node) is stored in a new
  `numa_node` custom field on the adapter's `ModuleBay`, created
  automatically on first migrate.

### Fixes

- Background jobs (`DellSyncJob`, `DellSyncAllJob`, `DellDiscoveryJob`) now
  log through the job's own logger, so sync/discovery progress and errors
  show up on the job's **Log** tab instead of going nowhere.
- `DellServer` and `DellScanRange` (both `JobsMixin` models) now register a
  `<model>_jobs` URL, without which NetBox's Job detail page raised
  `NoReverseMatch` for any of their jobs.

## 0.2.0

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
