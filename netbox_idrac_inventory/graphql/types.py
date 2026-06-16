# GraphQL types for netbox_idrac_inventory.
#
# NetBox 4.x uses Strawberry + strawberry-django for its GraphQL layer.
# Confirmed conventions from the NetBox 4.x plugin docs
# (https://netboxlabs.com/docs/netbox/en/stable/plugins/development/graphql-api/):
#
#   - Use @strawberry_django.type(Model, fields="__all__") to declare a type.
#   - Subclass netbox.graphql.types.NetBoxObjectType which extends BaseObjectType
#     and mixes in ChangelogMixin, CustomFieldsMixin, JournalEntriesMixin, TagsMixin.
#   - NetBoxObjectType enforces object-level permissions on the queryset.

import strawberry
import strawberry_django

from netbox.graphql.types import NetBoxObjectType

from netbox_idrac_inventory import models


@strawberry_django.type(
    models.DellServer,
    # All fields except the encrypted password (never expose the secret).
    exclude=["idrac_password"],
)
class DellServerType(NetBoxObjectType):
    """GraphQL type for a Dell server linked to a NetBox Device."""

    pass


@strawberry_django.type(
    models.DellComponent,
    fields="__all__",
)
class DellComponentType(NetBoxObjectType):
    """GraphQL type for a hardware component belonging to a DellServer."""

    pass


@strawberry_django.type(
    models.DellScanRange,
    exclude=["idrac_password"],
)
class DellScanRangeType(NetBoxObjectType):
    """GraphQL type for a Dell discovery scan range."""

    pass
