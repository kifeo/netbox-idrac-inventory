"""
Redfish/iDRAC client wrapper built on top of the ``sushy`` library.

This module purposely returns plain Python dicts and lists so that the sync
layer (``sync.py``) and unit tests remain decoupled from sushy object types.

Confirmed API details (verified via sushy source on opendev.org, 2026-06):
  - sushy.Sushy(base_url, username, password, verify, read_timeout, connect_timeout)
  - system = conn.get_system()  # retrieves the single available system
  - system attributes: sku, model, manufacturer, bios_version, power_state, hostname
  - system.processors.get_members() -> list[Processor]
  - Processor attrs: identity, model, manufacturer, max_speed_mhz, total_cores, total_threads
  - memory: not modeled by this sushy release; we GET the Redfish Memory
    collection via system._conn and parse raw JSON members.
  - system.storage.get_members() -> list[Storage]
  - Storage.storage_controllers -> list[StorageControllersListField] (member_id, name)
  - Storage.drives -> list[Drive]
  - Drive attrs: identity, name, model, manufacturer, serial_number, capacity_bytes,
                 media_type, protocol, part_number, revision (firmware)
  - Network adapters live under the Chassis (NetworkAdapters/<id>); ports come
    from the modern /Ports resource, which also carries the LLDP neighbour in
    Ethernet.LLDPReceive. The reusable card model is read from the Dell NIC
    NetworkDeviceFunction OEM (ProductName) when Model is just the FQDD.
  - Power supplies live on the Chassis resource; accessed via conn.get_chassis_collection()
    or the system's managers.  As iDRAC may not expose this cleanly through sushy, we
    fall back to raw JSON from the ``/redfish/v1/Chassis/System.Embedded.1/Power`` endpoint.

Auth/connection errors map to sushy.exceptions.AccessError and
sushy.exceptions.ConnectionError, which we re-raise as IdracConnectionError.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

log = logging.getLogger(__name__)


class IdracConnectionError(Exception):
    """Raised when the client cannot authenticate or connect to the iDRAC."""


def _netmask_to_prefix(netmask) -> int | None:
    """Convert a dotted netmask (255.255.255.128) to a prefix length (25)."""
    if not netmask:
        return None
    try:
        return sum(bin(int(octet)).count("1") for octet in str(netmask).split("."))
    except (ValueError, TypeError):
        return None


class IdracClient:
    """
    Thin wrapper around ``sushy`` that speaks to a single iDRAC endpoint and
    returns plain Python primitives.

    Usage::

        with IdracClient("192.168.1.10", "root", "password") as c:
            info = c.get_system_info()
            cpus = c.get_processors()

    Parameters
    ----------
    address:
        Hostname or IP of the iDRAC management interface.
    username:
        iDRAC user account (e.g. "root").
    password:
        iDRAC password.
    verify_ssl:
        Passed to sushy as ``verify``; set False for self-signed certs.
    timeout:
        HTTP read timeout in seconds (sushy ``read_timeout``).
    """

    def __init__(
        self,
        address: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: int = 30,
    ) -> None:
        self._address = address
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._conn = None  # lazy – opened on first use or __enter__

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> IdracClient:
        self._ensure_connected()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        """Release the underlying sushy session."""
        if self._conn is not None:
            with suppress(Exception):
                self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """Open the sushy connection if not already open."""
        if self._conn is not None:
            return
        try:
            import sushy  # imported lazily so tests can mock it

            base_url = self._address
            # Normalise: sushy expects a scheme.
            if not base_url.startswith(("http://", "https://")):
                base_url = f"https://{base_url}"

            self._conn = sushy.Sushy(
                base_url,
                username=self._username,
                password=self._password,
                verify=self._verify_ssl,
                read_timeout=self._timeout,
            )
        except Exception as exc:
            # Map sushy auth/connection errors to our own type.
            _classify_and_raise(exc)

    def _get_system(self):
        """Return the (single) System resource."""
        self._ensure_connected()
        try:
            return self._conn.get_system()
        except Exception as exc:
            _classify_and_raise(exc)

    @staticmethod
    def _safe(obj: Any, attr: str, default: Any = "") -> Any:
        """
        Return ``getattr(obj, attr)`` or ``default`` without raising.

        Also handles the case where the attribute exists but is ``None``.
        """
        try:
            val = getattr(obj, attr)
            return val if val is not None else default
        except Exception:
            return default

    @staticmethod
    def _safe_json(obj: Any, key: str, default: Any = "") -> Any:
        """
        Read a key from ``obj.json`` (the raw Redfish payload dict).

        Falls back to ``default`` if the attribute or key is missing.
        """
        try:
            return obj.json.get(key) or default
        except Exception:
            return default

    @staticmethod
    def _health_from(status: Any) -> str:
        """
        Extract the raw Redfish health string from a ``Status`` dict.

        Prefers ``HealthRollup`` (present on aggregates like the system) and
        falls back to ``Health`` (per-component). Returns "" if unavailable;
        callers map the string to a NetBox value via HealthChoices.
        """
        if not isinstance(status, dict):
            return ""
        return status.get("HealthRollup") or status.get("Health") or ""

    # ------------------------------------------------------------------
    # Public API – system-level info
    # ------------------------------------------------------------------

    def get_system_info(self) -> dict:
        """
        Return top-level system identity fields.

        Keys
        ----
        service_tag : str
            The Dell service tag (maps to Redfish ``SKU``).
        model : str
        manufacturer : str
        bios_version : str
        power_state : str
        host_name : str
        """
        system = self._get_system()
        return {
            "service_tag": self._safe(system, "sku") or self._safe_json(system, "SKU"),
            "model": self._safe(system, "model"),
            "manufacturer": self._safe(system, "manufacturer"),
            "bios_version": self._safe(system, "bios_version"),
            "power_state": str(self._safe(system, "power_state")),
            "host_name": self._safe(system, "hostname"),
            "health": self._health_from(self._safe_json(system, "Status")),
        }

    def get_idrac_firmware(self) -> str:
        """
        Best-effort retrieval of the iDRAC firmware version string.

        Attempts to walk the Manager resources; returns "" if unavailable.
        iDRAC typically appears as a Manager of type ``BMC``.
        """
        try:
            self._ensure_connected()
            managers = self._conn.get_manager_collection().get_members()
            for mgr in managers:
                fw = self._safe(mgr, "firmware_version")
                if fw:
                    return str(fw)
        except Exception as exc:
            log.debug("get_idrac_firmware: %s", exc)
        return ""

    def get_idrac_network(self) -> dict:
        """
        Return the iDRAC's own management NIC details (authoritative source
        for the OOB management IP, better than DNS-resolving the FQDN).

        Keys (empty dict if unavailable): ipv4, prefix_length, gateway,
        mac_address, hostname, fqdn, speed_mbps. Read from the Manager's
        EthernetInterfaces -> IPv4Addresses.
        """
        try:
            self._ensure_connected()
            conn = self._get_system()._conn
            managers = self._conn.get_manager_collection().get_members()
        except Exception as exc:
            log.info("get_idrac_network: no managers: %s", exc)
            return {}

        for manager in managers:
            eth_link = (
                self._safe_json(manager, "EthernetInterfaces") or {}
            ).get("@odata.id")
            if not eth_link:
                continue
            try:
                members = conn.get(path=eth_link).json().get("Members", [])
            except Exception as exc:
                log.info("get_idrac_network: eth list failed: %s", exc)
                continue
            for ref in members:
                p_path = ref.get("@odata.id")
                if not p_path:
                    continue
                try:
                    nic = conn.get(path=p_path).json()
                except Exception:
                    continue
                ipv4 = (nic.get("IPv4Addresses") or [{}])[0]
                address = ipv4.get("Address")
                if not address:
                    continue
                return {
                    "ipv4": address,
                    "prefix_length": _netmask_to_prefix(ipv4.get("SubnetMask")),
                    "gateway": ipv4.get("Gateway") or "",
                    "mac_address": (
                        nic.get("MACAddress")
                        or nic.get("PermanentMACAddress")
                        or ""
                    ).upper(),
                    "hostname": nic.get("HostName") or "",
                    "fqdn": nic.get("FQDN") or "",
                    "speed_mbps": nic.get("SpeedMbps"),
                }
        return {}

    # ------------------------------------------------------------------
    # Processors
    # ------------------------------------------------------------------

    def get_processors(self) -> list[dict]:
        """
        Return one dict per CPU socket reported by iDRAC.

        Keys: name, model, manufacturer, total_cores, total_threads,
              max_speed_mhz, serial.
        """
        system = self._get_system()
        results: list[dict] = []
        try:
            members = system.processors.get_members()
        except Exception as exc:
            log.warning("get_processors: could not retrieve collection: %s", exc)
            return results

        for proc in members:
            try:
                # serial_number is not a sushy-defined field on Processor; fall
                # back to raw JSON (iDRAC often includes it in the payload).
                serial = (
                    self._safe_json(proc, "SerialNumber")
                    or self._safe_json(proc, "Id")
                )
                results.append(
                    {
                        "name": self._safe(proc, "identity"),
                        "model": self._safe(proc, "model"),
                        "manufacturer": self._safe(proc, "manufacturer"),
                        "total_cores": self._safe(proc, "total_cores", 0),
                        "total_threads": self._safe(proc, "total_threads", 0),
                        "max_speed_mhz": self._safe(proc, "max_speed_mhz", 0),
                        "serial": str(serial),
                        "health": self._health_from(
                            self._safe_json(proc, "Status")
                        ),
                    }
                )
            except Exception as exc:
                log.warning("get_processors: skipping member due to error: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def get_memory(self) -> list[dict]:
        """
        Return one dict per DIMM reported by iDRAC.

        Keys: name, manufacturer, model, capacity_bytes, speed_mhz, serial,
              part_number.

        Notes
        -----
        Redfish reports capacity in MiB (``CapacityMiB``); this method
        converts to bytes for storage in ``DellComponent.capacity_bytes``.
        Sushy's Memory resource uses the attribute ``memory_device_type``
        for the device-type string (e.g. "DDR4"); ``part_number`` maps to
        the Redfish ``PartNumber`` field and is used as the ``model`` key.
        """
        system = self._get_system()
        results: list[dict] = []
        # This sushy release does not model `system.memory`, so walk the
        # Redfish Memory collection by hand using the system connector and
        # parse each member's raw JSON. Confirmed against an iDRAC 9
        # (PowerEdge R450) where DIMMs are absent from the sushy System object.
        try:
            mem_link = system.json.get("Memory", {}).get("@odata.id")
            if not mem_link:
                return results
            collection = system._conn.get(path=mem_link).json()
            member_links = [
                m["@odata.id"]
                for m in collection.get("Members", [])
                if m.get("@odata.id")
            ]
        except Exception as exc:
            log.warning("get_memory: could not retrieve collection: %s", exc)
            return results

        for link in member_links:
            try:
                dimm = system._conn.get(path=link).json()
                cap_mib = dimm.get("CapacityMiB")
                capacity_bytes = (
                    int(cap_mib) * 1024 * 1024 if cap_mib else None
                )
                part_number = dimm.get("PartNumber", "")
                results.append(
                    {
                        # DeviceLocator (e.g. "DIMM A2") is friendlier than Id.
                        "name": dimm.get("DeviceLocator") or dimm.get("Id"),
                        "manufacturer": dimm.get("Manufacturer", ""),
                        # Use part_number as the "model" column; device type
                        # (e.g. DDR4) kept in data by the sync layer.
                        "model": part_number,
                        "capacity_bytes": capacity_bytes,
                        "speed_mhz": dimm.get("OperatingSpeedMhz", 0),
                        "serial": dimm.get("SerialNumber", ""),
                        "part_number": part_number,
                        "memory_device_type": dimm.get("MemoryDeviceType", ""),
                        "health": self._health_from(dimm.get("Status")),
                    }
                )
            except Exception as exc:
                log.warning("get_memory: skipping member due to error: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Storage controllers
    # ------------------------------------------------------------------

    def get_storage_controllers(self) -> list[dict]:
        """
        Return one dict per storage controller reported by iDRAC.

        Keys: name, model, manufacturer, firmware, serial.

        Notes
        -----
        Sushy's Storage resource wraps controllers as
        ``StorageControllersListField`` items (not independent resources),
        so detailed attributes (model, manufacturer, firmware) may only
        be present in the raw JSON.  We try sushy attributes first and
        fall back to ``storage.json["StorageControllers"][i]``.
        """
        system = self._get_system()
        results: list[dict] = []
        try:
            storages = system.storage.get_members()
        except Exception as exc:
            log.warning("get_storage_controllers: could not retrieve collection: %s", exc)
            return results

        for storage in storages:
            try:
                controllers = self._safe(storage, "storage_controllers", []) or []
                raw_list = []
                with suppress(Exception):
                    raw_list = storage.json.get("StorageControllers", []) or []

                for idx, ctrl in enumerate(controllers):
                    try:
                        raw = raw_list[idx] if idx < len(raw_list) else {}
                        results.append(
                            {
                                "name": (
                                    self._safe(ctrl, "name")
                                    or raw.get("Name", "")
                                    or self._safe(ctrl, "member_id")
                                    or raw.get("MemberId", "")
                                ),
                                "model": raw.get("Model", ""),
                                "manufacturer": raw.get("Manufacturer", ""),
                                "firmware": raw.get("FirmwareVersion", ""),
                                "serial": raw.get("SerialNumber", ""),
                                "health": self._health_from(raw.get("Status")),
                            }
                        )
                    except Exception as exc:
                        log.warning(
                            "get_storage_controllers: skipping controller: %s", exc
                        )
            except Exception as exc:
                log.warning(
                    "get_storage_controllers: skipping storage member: %s", exc
                )

        return results

    # ------------------------------------------------------------------
    # Drives
    # ------------------------------------------------------------------

    def get_drives(self) -> list[dict]:
        """
        Return one dict per physical drive reported by iDRAC.

        Keys: name, model, manufacturer, serial, capacity_bytes, media_type,
              protocol.

        Notes
        -----
        Drives are accessed via each ``Storage`` member's ``.drives``
        property.  Sushy's ``Drive.revision`` holds the firmware version.
        """
        system = self._get_system()
        results: list[dict] = []
        try:
            storages = system.storage.get_members()
        except Exception as exc:
            log.warning("get_drives: could not retrieve storage collection: %s", exc)
            return results

        for storage in storages:
            try:
                drives = self._safe(storage, "drives", []) or []
            except Exception as exc:
                log.warning("get_drives: could not get drives for storage: %s", exc)
                continue

            for drive in drives:
                try:
                    results.append(
                        {
                            "name": (
                                self._safe(drive, "identity")
                                or self._safe(drive, "name")
                            ),
                            "model": self._safe(drive, "model"),
                            "manufacturer": self._safe(drive, "manufacturer"),
                            "serial": self._safe(drive, "serial_number"),
                            "capacity_bytes": self._safe(drive, "capacity_bytes", None),
                            "media_type": str(self._safe(drive, "media_type")),
                            "protocol": str(self._safe(drive, "protocol")),
                            "part_number": self._safe(drive, "part_number"),
                            "firmware": self._safe(drive, "revision"),
                            "health": self._health_from(
                                self._safe_json(drive, "Status")
                            ),
                        }
                    )
                except Exception as exc:
                    log.warning("get_drives: skipping drive due to error: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Network adapters / ports
    # ------------------------------------------------------------------

    def get_network_adapters(self) -> list[dict]:
        """
        Return the physical network adapters (cards) and their ports.

        Each adapter dict has keys:
          name, manufacturer, model, part_number, serial, firmware, ports
        where ``ports`` is a list of dicts:
          name, mac_address, link_status, speed_mbps,
          lldp_remote_chassis, lldp_remote_port

        Notes
        -----
        Network adapters live under the Chassis, not the System:
          GET /redfish/v1/Chassis/<id>/NetworkAdapters
          GET .../NetworkAdapters/<id>/NetworkPorts/<port>
        Sushy does not model these cleanly across releases, so we walk the
        tree via the connector and parse raw JSON.

        LLDP neighbour data is exposed by Dell as the per-port OEM object
        ``Oem.Dell.DellSwitchConnection`` (``SwitchConnectionID`` = remote
        chassis, ``SwitchPortConnectionID`` = remote port). It is populated
        only when the port has an active link; otherwise it is empty and the
        LLDP fields come back as "".
        """
        results: list[dict] = []
        try:
            # The raw JSON connector lives on a resource, not on the Sushy
            # root object (which has no .get); reuse the System's connector.
            conn = self._get_system()._conn
            chassis_list = self._conn.get_chassis_collection().get_members()
        except Exception as exc:
            log.warning("get_network_adapters: no chassis collection: %s", exc)
            return results

        for chassis in chassis_list:
            na_link = self._safe_json(chassis, "NetworkAdapters")
            na_link = na_link.get("@odata.id") if isinstance(na_link, dict) else None
            if not na_link:
                continue
            try:
                adapters = conn.get(path=na_link).json().get("Members", [])
            except Exception as exc:
                log.warning("get_network_adapters: list failed: %s", exc)
                continue

            for ref in adapters:
                a_path = ref.get("@odata.id")
                if not a_path:
                    continue
                try:
                    adapter = conn.get(path=a_path).json()
                except Exception as exc:
                    log.warning("get_network_adapters: %s failed: %s", a_path, exc)
                    continue

                # Firmware lives on the first controller, when present.
                firmware = ""
                controllers = adapter.get("Controllers") or []
                if controllers:
                    firmware = (
                        controllers[0].get("FirmwarePackageVersion") or ""
                    ).strip()

                results.append(
                    {
                        "name": adapter.get("Id", ""),
                        "manufacturer": (adapter.get("Manufacturer") or "").strip(),
                        # A reusable hardware model (not the per-slot FQDD).
                        "model": self._resolve_adapter_model(conn, adapter),
                        "part_number": (adapter.get("PartNumber") or "").strip(),
                        "serial": (adapter.get("SerialNumber") or "").strip(),
                        "firmware": firmware,
                        "ports": self._get_adapter_ports(conn, adapter),
                    }
                )

        return results

    def _get_adapter_ports(self, conn, adapter: dict) -> list[dict]:
        """Return the physical port dicts for one network adapter."""
        ports: list[dict] = []
        ports_link = adapter.get("NetworkPorts") or adapter.get("Ports") or {}
        ports_link = ports_link.get("@odata.id") if isinstance(ports_link, dict) else None
        if not ports_link:
            return ports
        try:
            members = conn.get(path=ports_link).json().get("Members", [])
        except Exception as exc:
            log.warning("_get_adapter_ports: list failed: %s", exc)
            return ports

        # The modern Redfish /Ports resource carries the LLDP neighbour under
        # Ethernet.LLDPReceive. Build the map once per adapter; empty when no
        # link / no /Ports support.
        a_path = adapter.get("@odata.id", "")
        lldp_map = (
            self._get_lldp_map_from_ports(conn, f"{a_path}/Ports")
            if a_path else {}
        )

        for ref in members:
            p_path = ref.get("@odata.id")
            if not p_path:
                continue
            try:
                port = conn.get(path=p_path).json()
            except Exception as exc:
                log.warning("_get_adapter_ports: %s failed: %s", p_path, exc)
                continue

            macs = port.get("AssociatedNetworkAddresses") or []
            speed = port.get("CurrentLinkSpeedMbps")
            if not speed:
                caps = port.get("SupportedLinkCapabilities") or []
                if caps:
                    speed = caps[0].get("LinkSpeedMbps")

            port_id = port.get("Id", "")
            chassis, rport = lldp_map.get(port_id, ("", ""))
            # Legacy fallback: older OEM location on the NetworkPort itself.
            if not chassis and not rport:
                sc = (port.get("Oem", {}).get("Dell", {})
                      .get("DellSwitchConnection", {}) or {})
                chassis = self._clean_lldp(sc.get("SwitchConnectionID"))
                rport = self._clean_lldp(sc.get("SwitchPortConnectionID"))

            ports.append(
                {
                    "name": port_id,
                    "mac_address": (macs[0] if macs else "").strip(),
                    "link_status": port.get("LinkStatus") or "",
                    "speed_mbps": speed,
                    "lldp_remote_chassis": chassis,
                    "lldp_remote_port": rport,
                }
            )
        return ports

    def _get_lldp_map_from_ports(self, conn, ports_link: str) -> dict:
        """
        Map physical port id -> (remote_chassis, remote_port) read from the
        DMTF ``Port`` resource: ``<adapter>/Ports/<port>`` exposes the LLDP
        neighbour as ``Ethernet.LLDPReceive`` (ChassisId/PortId with their
        subtypes). Returns an empty map when /Ports is absent or no link.
        """
        lldp: dict[str, tuple[str, str]] = {}
        try:
            members = conn.get(path=ports_link).json().get("Members", [])
        except Exception as exc:
            log.info("_get_lldp_map_from_ports: %s unavailable: %s", ports_link, exc)
            return lldp

        for ref in members:
            p_path = ref.get("@odata.id")
            if not p_path:
                continue
            try:
                port = conn.get(path=p_path).json()
            except Exception:
                continue
            recv = (port.get("Ethernet") or {}).get("LLDPReceive") or {}
            chassis = self._decode_lldp_id(
                recv.get("ChassisId"), recv.get("ChassisIdSubtype")
            )
            rport = self._decode_lldp_id(
                recv.get("PortId"), recv.get("PortIdSubtype")
            )
            if not chassis and not rport:
                continue
            lldp[port.get("Id", "")] = (chassis, rport)
        return lldp

    def _resolve_adapter_model(self, conn, adapter: dict) -> str:
        """
        Return a reusable hardware model string for the adapter.

        Redfish ``Model`` is preferred, but embedded/slot NICs often report
        only their FQDD there; in that case fall back to the Dell NIC
        ``ProductName`` (e.g. "Broadcom NetXtreme Gigabit Ethernet (BCM5720)")
        so the same card produces the same ModuleType across machines.
        """
        model = (adapter.get("Model") or "").strip()
        adapter_id = (adapter.get("Id") or "").strip()
        if model and model != adapter_id:
            return model

        pname = self._get_adapter_product_name(conn, adapter)
        if pname:
            return pname

        mfr = (adapter.get("Manufacturer") or "").strip()
        return f"{mfr} NIC".strip() if mfr else adapter_id

    def _get_adapter_product_name(self, conn, adapter: dict) -> str:
        """Read DellNIC.ProductName from the adapter's first device function."""
        ndf = adapter.get("NetworkDeviceFunctions") or {}
        ndf_link = ndf.get("@odata.id") if isinstance(ndf, dict) else None
        if not ndf_link:
            return ""
        try:
            members = conn.get(path=ndf_link).json().get("Members", [])
        except Exception as exc:
            log.info("_get_adapter_product_name: %s unavailable: %s", ndf_link, exc)
            return ""
        for ref in members:
            f_path = ref.get("@odata.id")
            if not f_path:
                continue
            try:
                fn = conn.get(path=f_path).json()
            except Exception:
                continue
            pname = (
                fn.get("Oem", {}).get("Dell", {}).get("DellNIC", {}) or {}
            ).get("ProductName")
            if pname:
                # Strip the trailing " - <MAC>" identifier Dell appends.
                return pname.split(" - ")[0].strip()
        return ""

    @staticmethod
    def _clean_lldp(value: Any) -> str:
        """Normalise an LLDP value, treating placeholders as empty."""
        if not value:
            return ""
        text = str(value).strip()
        if text.lower() in ("not available", "no link", "n/a", "none"):
            return ""
        return text

    @staticmethod
    def _decode_lldp_id(value: Any, subtype: Any) -> str:
        """
        Normalise an LLDP ChassisId/PortId. MAC/network-address subtypes are
        already readable; name subtypes (IfName, etc.) are often hex-encoded
        ASCII (e.g. '70:6F:72:74:32:37' -> 'port27'), so decode those.
        """
        text = IdracClient._clean_lldp(value)
        if not text:
            return ""
        if subtype in ("MacAddr", "NetworkAddress", "ChassisComponent"):
            return text
        hexstr = text.replace(":", "").replace("-", "").replace(" ", "")
        if len(hexstr) >= 2 and len(hexstr) % 2 == 0:
            try:
                raw = bytes.fromhex(hexstr)
            except ValueError:
                return text
            if all(32 <= b < 127 for b in raw):
                return raw.decode("ascii")
        return text

    # ------------------------------------------------------------------
    # Firmware inventory
    # ------------------------------------------------------------------

    def get_firmware_inventory(self) -> list[dict]:
        """
        Return the installed firmware entries from
        ``/redfish/v1/UpdateService/FirmwareInventory``.

        Keys: name, version, fqdd.

        Dell encodes the component FQDD in the member Id after a double
        underscore (e.g. ``Installed-25227-4.40.00.00__NIC.Slot.1-1-1`` ->
        ``NIC.Slot.1-1-1``), which matches the component names reported
        elsewhere, so the sync layer can enrich matching components. Only
        ``Installed-*`` entries are returned (``Previous-``/``Available-``
        versions are skipped).
        """
        results: list[dict] = []
        try:
            conn = self._get_system()._conn
            members = (
                conn.get(path="/redfish/v1/UpdateService/FirmwareInventory")
                .json()
                .get("Members", [])
            )
        except Exception as exc:
            log.warning("get_firmware_inventory: unavailable: %s", exc)
            return results

        for ref in members:
            path = ref.get("@odata.id") or ""
            entry_id = path.rsplit("/", 1)[-1]
            if not entry_id.startswith("Installed-"):
                continue
            try:
                entry = conn.get(path=path).json()
            except Exception as exc:
                log.debug("get_firmware_inventory: %s failed: %s", path, exc)
                continue
            results.append(
                {
                    "name": entry.get("Name", ""),
                    "version": (entry.get("Version") or "").strip(),
                    "fqdd": (
                        entry_id.split("__", 1)[1] if "__" in entry_id else ""
                    ),
                }
            )
        return results

    # ------------------------------------------------------------------
    # Power supplies
    # ------------------------------------------------------------------

    def get_power_supplies(self) -> list[dict]:
        """
        Return one dict per power supply reported by iDRAC.

        Keys: name, model, manufacturer, serial, part_number,
              power_capacity_watts, firmware.

        Notes
        -----
        Power supplies in Redfish live under the Chassis ``Power`` resource,
        not under the System.  We retrieve the chassis collection and look
        for a power resource on each chassis.  Sushy does not model
        PowerSupply as an independent resource class, so we parse raw JSON.

        The Redfish path is typically:
          GET /redfish/v1/Chassis/<id>/Power  -> PowerSupplies[]
        """
        self._ensure_connected()
        results: list[dict] = []
        try:
            chassis_list = self._conn.get_chassis_collection().get_members()
        except Exception as exc:
            log.warning("get_power_supplies: could not get chassis collection: %s", exc)
            return results

        for chassis in chassis_list:
            try:
                # Try the sushy power accessor first; fall back to raw JSON.
                power_data = None
                with suppress(Exception):
                    power_data = chassis.power.json

                if power_data is None:
                    with suppress(Exception):
                        power_data = chassis.json.get("Power") or {}

                if not power_data:
                    continue

                for psu in power_data.get("PowerSupplies", []):
                    try:
                        results.append(
                            {
                                "name": psu.get("Name") or psu.get("MemberId", ""),
                                "model": psu.get("Model", ""),
                                "manufacturer": psu.get("Manufacturer", ""),
                                "serial": psu.get("SerialNumber", ""),
                                "part_number": psu.get("PartNumber", ""),
                                "power_capacity_watts": psu.get(
                                    "PowerCapacityWatts", None
                                ),
                                "firmware": psu.get("FirmwareVersion", ""),
                                "health": self._health_from(psu.get("Status")),
                            }
                        )
                    except Exception as exc:
                        log.warning(
                            "get_power_supplies: skipping PSU entry: %s", exc
                        )
            except Exception as exc:
                log.warning(
                    "get_power_supplies: skipping chassis member: %s", exc
                )

        return results


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _classify_and_raise(exc: Exception) -> None:
    """
    Convert a sushy connection/auth exception into ``IdracConnectionError``.

    Any other exception is re-raised as-is so callers can decide whether
    to treat it as a transient error or a hard failure.
    """
    try:
        import sushy.exceptions as sushy_exc

        if isinstance(exc, (sushy_exc.ConnectionError, sushy_exc.AccessError)):
            raise IdracConnectionError(str(exc)) from exc
    except ImportError:
        pass
    raise exc
