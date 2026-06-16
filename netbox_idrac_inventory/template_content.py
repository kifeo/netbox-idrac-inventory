"""PluginTemplateExtension for injecting iDRAC Inventory data into the Device detail page.

NetBox 4.x conventions confirmed from source (netbox/plugins/templates.py):
  - Subclass PluginTemplateExtension
  - Set `models = ["app_label.model_name"]` (a list of strings, NetBox 4.x uses
    `models` list rather than the older single `model` string attribute)
  - Implement panel methods: left_page(), right_page(), full_width_page(),
    buttons(), alerts()
  - Call self.render(template_name, extra_context={}) to return rendered HTML
  - The template context already contains 'object' (the current Device instance),
    'request', and 'settings'.
  - Register by exporting `template_extensions = [MyClass]` from this module;
    NetBox discovers it via PluginConfig.template_extensions path.
"""

from netbox.plugins import PluginTemplateExtension


class DeviceDellServerPanel(PluginTemplateExtension):
    """Injects a iDRAC Inventory panel into the Device detail page."""

    # NetBox 4.x: models is a list of "<app_label>.<model_name>" strings
    models = ["dcim.device"]

    def right_page(self):
        device = self.context["object"]
        # Safely retrieve related DellServer without raising an exception
        # when none exists (OneToOne raises RelatedObjectDoesNotExist otherwise)
        try:
            dell_server = device.dell_server
        except Exception:
            dell_server = None

        return self.render(
            "netbox_idrac_inventory/device_extension.html",
            extra_context={
                "dell_server": dell_server,
            },
        )


# NetBox discovers this list via PluginConfig.template_extensions setting
template_extensions = [DeviceDellServerPanel]
