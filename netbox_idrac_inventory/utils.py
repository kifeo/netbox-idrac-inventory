"""Small helpers for the netbox_idrac_inventory plugin."""

import base64
import hashlib
import ipaddress


def _fernet():
    """Return a Fernet built from the NetBox SECRET_KEY (derived 32-byte key)."""
    from cryptography.fernet import Fernet
    from django.conf import settings

    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* for at-rest storage; "" stays "" (no secret)."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a token from :func:`encrypt_secret`; "" on empty/failure."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:
        # e.g. SECRET_KEY rotated since encryption — treat as no secret.
        return ""

# Safety cap so a careless CIDR can't expand into a huge scan.
MAX_SCAN_TARGETS = 4096


def expand_targets(text: str, *, limit: int = MAX_SCAN_TARGETS) -> list[str]:
    """
    Expand a scan-range specification into a de-duplicated list of host IPs.

    Accepts, separated by commas/whitespace/newlines:
      - a CIDR:        ``10.0.0.0/24``  (network/broadcast excluded)
      - a dashed range ``10.0.0.10-20`` (last octet) or
                       ``10.0.0.10-10.0.0.20`` (full address)
      - a single host: ``10.0.0.5`` or a hostname (returned as-is)

    Raises ValueError if the total exceeds *limit*.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            out.append(value)

    for token in text.replace(",", " ").split():
        if "/" in token:
            for ip in ipaddress.ip_network(token, strict=False).hosts():
                _add(str(ip))
        elif "-" in token:
            start, end = (p.strip() for p in token.split("-", 1))
            start_ip = ipaddress.ip_address(start)
            # "10.0.0.10-20" -> reuse the start's leading octets for the end.
            if "." not in end and ":" not in end:
                prefix = start.rsplit(".", 1)[0]
                end = f"{prefix}.{end}"
            end_ip = ipaddress.ip_address(end)
            for value in range(int(start_ip), int(end_ip) + 1):
                _add(str(ipaddress.ip_address(value)))
        else:
            _add(token)
        if len(out) > limit:
            raise ValueError(
                f"Scan range expands to more than {limit} targets."
            )
    return out


def get_or_create_manufacturer(name: str):
    """Return the NetBox Manufacturer for *name*, creating it if needed."""
    from django.utils.text import slugify

    from dcim.models import Manufacturer

    obj, _ = Manufacturer.objects.get_or_create(
        name=name, defaults={"slug": slugify(name)[:100]}
    )
    return obj


def default_device_name(address: str) -> str:
    """
    Derive a default device name from an iDRAC address.

    For an FQDN, return only the host label (the part before the first dot),
    e.g. ``idrac01.example.com`` -> ``idrac01``. For a bare IPv4
    address, return it unchanged (splitting on dots would be meaningless).
    """
    address = (address or "").strip()
    if not address:
        return ""
    # Drop a port suffix if present (host:port).
    address = address.split(":")[0]
    parts = address.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        # Looks like an IPv4 literal — keep it whole.
        return address
    return parts[0]
