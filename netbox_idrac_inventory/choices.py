from utilities.choices import ChoiceSet


class SyncStatusChoices(ChoiceSet):
    """Result of the last iDRAC synchronization for a Dell server."""

    key = "DellServer.sync_status"

    STATUS_NEW = "new"
    STATUS_SYNCED = "synced"
    STATUS_FAILED = "failed"

    CHOICES = [
        (STATUS_NEW, "Never synced", "gray"),
        (STATUS_SYNCED, "Synced", "green"),
        (STATUS_FAILED, "Failed", "red"),
    ]


class HealthChoices(ChoiceSet):
    """Health rolled up from the Redfish ``Status.Health`` field."""

    key = "DellServer.health"

    HEALTH_OK = "ok"
    HEALTH_WARNING = "warning"
    HEALTH_CRITICAL = "critical"
    HEALTH_UNKNOWN = "unknown"

    CHOICES = [
        (HEALTH_OK, "OK", "green"),
        (HEALTH_WARNING, "Warning", "orange"),
        (HEALTH_CRITICAL, "Critical", "red"),
        (HEALTH_UNKNOWN, "Unknown", "gray"),
    ]

    # Redfish Health value (case-insensitive) -> our value.
    _REDFISH = {
        "ok": HEALTH_OK,
        "warning": HEALTH_WARNING,
        "critical": HEALTH_CRITICAL,
    }

    @classmethod
    def from_redfish(cls, value) -> str:
        """Map a Redfish ``Status.Health`` string to a HealthChoices value."""
        return cls._REDFISH.get(str(value or "").strip().lower(), cls.HEALTH_UNKNOWN)


class ComponentTypeChoices(ChoiceSet):
    """Category of a hardware component reported by iDRAC."""

    key = "DellComponent.type"

    TYPE_CPU = "cpu"
    TYPE_MEMORY = "memory"
    TYPE_DISK = "disk"
    TYPE_CONTROLLER = "controller"
    TYPE_NIC = "nic"
    TYPE_PSU = "psu"
    TYPE_FAN = "fan"
    TYPE_GPU = "gpu"

    CHOICES = [
        (TYPE_CPU, "CPU", "blue"),
        (TYPE_MEMORY, "Memory", "cyan"),
        (TYPE_DISK, "Disk", "indigo"),
        (TYPE_CONTROLLER, "Storage controller", "purple"),
        (TYPE_NIC, "Network interface", "teal"),
        (TYPE_PSU, "Power supply", "orange"),
        (TYPE_FAN, "Fan", "gray"),
        (TYPE_GPU, "GPU", "green"),
    ]
