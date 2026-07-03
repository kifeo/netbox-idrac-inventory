"""Small helpers for the netbox_idrac_inventory plugin."""

import base64
import hashlib
import ipaddress
import socket


class SecretDecryptionError(Exception):
    """A stored secret exists but cannot be decrypted with the current keys."""


def _derive_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def _fernet():
    """
    Return a MultiFernet keyed on SECRET_KEY plus SECRET_KEY_FALLBACKS, so
    secrets stored before a key rotation (done per Django's documented
    procedure) remain readable. New secrets are encrypted with the primary key.
    """
    from cryptography.fernet import Fernet, MultiFernet
    from django.conf import settings

    secrets = [
        settings.SECRET_KEY,
        *getattr(settings, "SECRET_KEY_FALLBACKS", []),
    ]
    return MultiFernet([Fernet(_derive_key(secret)) for secret in secrets])


def encrypt_secret(plaintext: str) -> str:
    """Encrypt *plaintext* for at-rest storage; "" stays "" (no secret)."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """
    Decrypt a token from :func:`encrypt_secret`; "" for "" (no secret).

    Raises SecretDecryptionError when a stored secret cannot be decrypted
    (e.g. SECRET_KEY rotated without SECRET_KEY_FALLBACKS). Failing loudly
    here prevents a sync from silently falling back to the global default
    password and locking out the iDRAC account with bad login attempts.
    """
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception as exc:
        raise SecretDecryptionError(
            "The stored iDRAC password could not be decrypted (was "
            "SECRET_KEY rotated without SECRET_KEY_FALLBACKS?). Re-enter "
            "the password, or leave it blank to use the plugin default."
        ) from exc


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


def host_part(address: str) -> str:
    """
    Strip an optional port suffix from an address, IPv6-safely.

    ``host:443`` -> ``host``; ``[2001:db8::1]:443`` -> ``2001:db8::1``; a
    bare IPv6 literal (more than one colon, no brackets) is kept whole.
    """
    address = (address or "").strip()
    if address.startswith("["):
        return address[1:].split("]", 1)[0]
    if address.count(":") == 1:
        return address.split(":", 1)[0]
    return address


def check_address_allowed(address: str, networks: list) -> None:
    """
    Raise ValueError if *address* falls outside the *networks* prefixes.

    No-op when *networks* is empty (the feature is opt-in). A hostname is
    resolved and every returned IP must be inside an allowed prefix, so a
    DNS name cannot be used to smuggle an out-of-policy target.
    """
    if not networks:
        return
    prefixes = [ipaddress.ip_network(str(n), strict=False) for n in networks]
    host = host_part(address)
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            info = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise ValueError(
                f"Cannot resolve '{host}' to check it against "
                f"allowed_networks: {exc}"
            ) from exc
        addresses = {ipaddress.ip_address(item[4][0]) for item in info}
    for ip in addresses:
        if not any(ip in prefix for prefix in prefixes):
            raise ValueError(
                f"iDRAC address '{address}' ({ip}) is outside the "
                "configured allowed_networks."
            )


def get_or_create_manufacturer(name: str):
    """Return the NetBox Manufacturer for *name*, creating it if needed."""
    from dcim.models import Manufacturer
    from django.utils.text import slugify

    obj, _ = Manufacturer.objects.get_or_create(
        name=name, defaults={"slug": slugify(name)[:100]}
    )
    return obj


def default_device_name(address: str) -> str:
    """
    Derive a default device name from an iDRAC address.

    For an FQDN, return only the host label (the part before the first dot),
    e.g. ``idrac01.example.com`` -> ``idrac01``. A bare IP address (v4 or
    v6) is returned unchanged; a port suffix is dropped first.
    """
    address = host_part(address)
    if not address:
        return ""
    try:
        ipaddress.ip_address(address)
        return address  # IP literal — keep it whole.
    except ValueError:
        return address.split(".")[0]
