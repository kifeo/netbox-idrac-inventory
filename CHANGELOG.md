# Changelog

## 0.3.6 (unreleased)

### Compatibility

- Declared compatibility extended to NetBox 4.7 (`max_version = "4.7.99"`),
  verified by running the full suite on v4.7.1. v4.7.1 added to the CI matrix;
  the dev stack now defaults to NetBox 4.7.

### Features

- **Network adapters go into the Dell model's module bays.** The sync now
  creates the device type's module bays on the device (NetBox only does it at
  device creation), so every slot of the model exists — empty ones included,
  for a card entered by hand. Each adapter is placed in the bay for its slot,
  matched on the bay `position` from the netbox-community devicetype-library
  conventions: `NIC.Slot.N` → `PCIe-N` / `PCIe-GenX-N` / `PCIEN` / `slot-N`,
  `NIC.Integrated.N` → `inic-N`, then `NDC-N`, then `OCP-N`,
  `NIC.Embedded.N` → `enic-N`. No match (or an ambiguous one) keeps the
  previous FQDD-named bay (`NIC.Slot.N`).
- Devices synced by an earlier version are migrated: the module is **moved**
  from its `NIC.*` bay into the model bay, so its interfaces keep their cables
  and IP addresses, and the `NIC.*` bay is removed.
- A hand-entered module already in the model bay is replaced when none of its
  interfaces carries a cable or an IP (its template interfaces, e.g. `eno1`,
  go with it); otherwise it is kept and the adapter stays in an `NIC.*` bay,
  with a warning.
- When an adapter is removed, its module is removed from the model bay but the
  bay itself stays (it belongs to the model). Hand-entered modules are never
  removed.

### Fixes

- **A port or adapter that could not be read is no longer taken for removed
  hardware.** A transient error while reading one port (a DNS hiccup was
  seen) made the sync delete that port's interface, with its cable and IP
  assignments. The client now reports whether each adapter's port list, and
  the adapter list itself, were read completely; the sync only removes
  interfaces, modules or bays after a complete read.
- **A sync that overruns the RQ job timeout is no longer reported as
  "synced"**: RQ enforces its timeout by raising `JobTimeoutException` (an
  `Exception` subclass) wherever the code is, and the iDRAC getters catch
  `Exception` to tolerate partial data — so the timeout was swallowed and the
  server ended up `synced` with some components silently missing (seen on an
  iDRAC8 R630 whose network adapters never made it). The job now marks the
  server `failed` with an explicit message when it hit the timeout.
- **Sync jobs get a longer RQ timeout**, set by the new `sync_job_timeout`
  setting (default 1200s, instead of NetBox's `RQ_DEFAULT_TIMEOUT` of 300s).
  Older iDRACs answer each Redfish call in 2–30s; a full sync of a server
  with three network adapters took 5 to 11 minutes on an iDRAC8. Applies to
  on-demand syncs and to the recurring fleet sync.

## 0.3.5 (unreleased)

### Fixes

- **Sync no longer breaks on devices synced by an earlier version**: 0.3.2
  started matching ports by MAC and renaming the match to the Dell port
  name — but a device synced *before* that already holds both the original
  interface and the duplicate the old code created under that very name.
  Since `(device, name)` is unique, the rename raised `IntegrityError` and
  every subsequent sync of that device failed. The clash is now resolved:
  the empty duplicate is deleted so the cabled original can take the name.
  When *both* interfaces carry a cable or IPs the port is skipped with a
  warning instead, since only a human can decide which to keep.
- **The iDRAC address is no longer recorded twice on a device**: an
  existing copy assigned to another of the device's interfaces is moved
  onto the matched interface rather than a second `IPAddress` being
  created. An "iDRAC" interface left empty by an earlier sync is removed;
  a leftover *copy of the address* is reported in the job log rather than
  deleted, since an `IPAddress` may carry a DNS name or description.
- **The iDRAC address pre-fill added in 0.3.3 never actually worked** in
  the UI: it was written to the form field's `initial`, which `ModelForm`
  overrides from the (empty) instance for model fields, so the rendered
  input stayed blank. It now populates the form's `initial` data, verified
  against the rendered page.

### Corrections

- The 0.3.4 note claimed IP addresses are globally unique in NetBox and
  that a duplicate would fail to save. They are not: NetBox permits
  duplicates by default, so the old behaviour silently recorded the same
  address twice rather than failing.

## 0.3.4

### Fixes

- **Duplicate iDRAC management interface on pre-existing devices**: the
  iDRAC management interface was matched by the literal name "iDRAC" only.
  A device onboarded before this plugin — with its mgmt interface already
  named differently (e.g. "iDRAC9", "iDRAC9 1") and its real IP already
  recorded — got a second interface created on sync, carrying a second
  copy of the same address. Now matched by the interface's
  already-recorded MAC address first (falling back to the "iDRAC" name),
  reusing the existing interface in place without renaming it.

## 0.3.3

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
