"""
Self-contained NetBox configuration for local plugin development.
Mounted over /etc/netbox/config/configuration.py in the container.
Dev only — do not use these credentials/secret in production.
"""
import os

ALLOWED_HOSTS = ["*"]

# NetBox + the netbox-docker entrypoint's DB-wait both require the singular
# `DATABASE` parameter; `DATABASES` alone triggers "Required parameter
# DATABASE is missing from configuration".
DATABASE = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "netbox",
    "USER": "netbox",
    "PASSWORD": "netbox",
    "HOST": "postgres",
    "PORT": "",
    "CONN_MAX_AGE": 300,
}

REDIS = {
    "tasks": {
        "HOST": "redis",
        "PORT": 6379,
        "USERNAME": "",
        "PASSWORD": "",
        "DATABASE": 0,
        "SSL": False,
    },
    "caching": {
        "HOST": "redis",
        "PORT": 6379,
        "USERNAME": "",
        "PASSWORD": "",
        "DATABASE": 1,
        "SSL": False,
    },
}

# Dev-only secret (>= 50 chars). Replace for any real deployment.
SECRET_KEY = "dev-only-secret-key-change-me-0123456789abcdefghijklmnop"

DEBUG = True
# Required so `manage.py makemigrations` is permitted (dev safeguard).
DEVELOPER = True

PLUGINS = ["netbox_idrac_inventory"]

# iDRAC credentials come from the environment so the same values reach the
# RQ worker (which actually runs the sync job). Set them in dev/.env.
PLUGINS_CONFIG = {
    "netbox_idrac_inventory": {
        "idrac_default_username": os.environ.get("IDRAC_USERNAME", "root"),
        "idrac_default_password": os.environ.get("IDRAC_PASSWORD", ""),
        "idrac_verify_ssl": os.environ.get("IDRAC_VERIFY_SSL", "false").lower()
        == "true",
        "idrac_timeout": int(os.environ.get("IDRAC_TIMEOUT", "30")),
        "update_device_serial": True,
    }
}
