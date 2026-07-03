"""NetBox configuration used by the GitHub Actions test run (CI only)."""

ALLOWED_HOSTS = ["*"]

DATABASE = {
    "NAME": "netbox",
    "USER": "netbox",
    "PASSWORD": "netbox",
    "HOST": "localhost",
    "PORT": "",
}

REDIS = {
    "tasks": {
        "HOST": "localhost",
        "PORT": 6379,
        "DATABASE": 0,
        "SSL": False,
    },
    "caching": {
        "HOST": "localhost",
        "PORT": 6379,
        "DATABASE": 1,
        "SSL": False,
    },
}

PLUGINS = ["netbox_idrac_inventory"]

SECRET_KEY = "ci-only-secret-key-0123456789abcdefghijklmnopqrstuvwxyz"

# Required by NetBox 4.6+ (v2 API tokens); ignored by older versions.
# Integer keys, values >= 50 chars.
API_TOKEN_PEPPERS = {1: "ci-only-pepper-0123456789abcdefghijklmnopqrstuvwxyz"}
