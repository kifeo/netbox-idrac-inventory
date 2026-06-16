# REST API URL routing for netbox_idrac_inventory.
#
# NetBox 4.x plugins use NetBoxRouter (confirmed from docs) which extends DRF's
# DefaultRouter and sets up the standard CRUD + bulk endpoints automatically.
# The app_name MUST be set here so that reverse("plugins-api:netbox_idrac_inventory-api:…")
# resolves correctly from within serializers and elsewhere.

from netbox.api.routers import NetBoxRouter

from .views import (
    DellComponentViewSet,
    DellScanRangeViewSet,
    DellServerViewSet,
)

app_name = "netbox_idrac_inventory"

router = NetBoxRouter()
# Registers:
#   GET/POST   /api/plugins/idrac-inventory/servers/
#   GET/PUT/PATCH/DELETE /api/plugins/idrac-inventory/servers/<id>/
#   POST       /api/plugins/idrac-inventory/servers/<id>/sync/
router.register("servers", DellServerViewSet)
# Registers:
#   GET/POST   /api/plugins/idrac-inventory/components/
#   GET/PUT/PATCH/DELETE /api/plugins/idrac-inventory/components/<id>/
router.register("components", DellComponentViewSet)
# Registers /api/plugins/idrac-inventory/scan-ranges/ (+ <id>/run/)
router.register("scan-ranges", DellScanRangeViewSet)

urlpatterns = router.urls
