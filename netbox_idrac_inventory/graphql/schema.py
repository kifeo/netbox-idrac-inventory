# GraphQL schema for netbox_idrac_inventory.
#
# NetBox will import this module and look for a ``schema`` list containing
# query classes. Confirmed from the NetBox 4.x plugin docs
# (https://netboxlabs.com/docs/netbox/en/stable/plugins/development/graphql-api/):
#
#   "NetBox will attempt to import graphql.schema from the plugin."
#   The module must expose a ``schema`` variable that is a list of
#   @strawberry.type query classes.
#
# Pattern:
#   - list field:   <name>_list uses strawberry_django.field() for queryset-based list.
#   - single field: @strawberry.field decorated method for get-by-id lookup.
#
# Both DellServerType and DellComponentType are registered here.

from typing import List, Optional

import strawberry
import strawberry_django

from .types import DellComponentType, DellScanRangeType, DellServerType


@strawberry.type
class DellInventoryQuery:
    """Root query type for the iDRAC Inventory plugin."""

    # ------------------------------------------------------------------ servers

    @strawberry.field
    def dell_server(self, id: int) -> Optional[DellServerType]:
        """Retrieve a single DellServer by primary key."""
        from netbox_idrac_inventory.models import DellServer

        try:
            return DellServer.objects.get(pk=id)
        except DellServer.DoesNotExist:
            return None

    dell_server_list: List[DellServerType] = strawberry_django.field()

    # --------------------------------------------------------------- components

    @strawberry.field
    def dell_component(self, id: int) -> Optional[DellComponentType]:
        """Retrieve a single DellComponent by primary key."""
        from netbox_idrac_inventory.models import DellComponent

        try:
            return DellComponent.objects.get(pk=id)
        except DellComponent.DoesNotExist:
            return None

    dell_component_list: List[DellComponentType] = strawberry_django.field()

    # ------------------------------------------------------------- scan ranges

    @strawberry.field
    def dell_scan_range(self, id: int) -> Optional[DellScanRangeType]:
        """Retrieve a single DellScanRange by primary key."""
        from netbox_idrac_inventory.models import DellScanRange

        try:
            return DellScanRange.objects.get(pk=id)
        except DellScanRange.DoesNotExist:
            return None

    dell_scan_range_list: List[DellScanRangeType] = strawberry_django.field()


# NetBox reads this list and merges each class into the root Query type.
schema = [DellInventoryQuery]
