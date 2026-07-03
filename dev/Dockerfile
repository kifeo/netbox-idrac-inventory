# Dev image: official NetBox + this plugin installed (editable).
# Build context is the repo root (see docker-compose.yml).
ARG VERSION=v4.6
FROM netboxcommunity/netbox:${VERSION}

# Copy the plugin source and install it editable so a bind-mounted source
# tree (see compose) is picked up on container restart. Pulls deps (sushy).
# Recent NetBox images ship `uv` and a pip-less venv (VIRTUAL_ENV is set to
# /opt/netbox/venv), so install with `uv pip` into that active venv.
COPY . /opt/netbox-idrac-inventory
RUN uv pip install --no-cache -e /opt/netbox-idrac-inventory
