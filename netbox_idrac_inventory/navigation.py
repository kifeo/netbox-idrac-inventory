"""Navigation menu for the netbox_idrac_inventory plugin.

NetBox 4.x navigation API (confirmed from docs):
  - Import PluginMenu, PluginMenuItem, PluginMenuButton from netbox.plugins
  - Import ButtonColorChoices from netbox.choices
  - Assign a `menu` variable (top-level dedicated menu) or `menu_items`
    (items placed in the shared "Plugins" submenu).
  - PluginMenu(label, groups, icon_class):
      groups is a tuple of (group_label, (items...)) pairs.
  - PluginMenuItem(link, link_text, permissions=[], buttons=[])
  - PluginMenuButton(link, title, icon_class, color=None, permissions=[])
"""

from netbox.choices import ButtonColorChoices
from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem

menu = PluginMenu(
    label="iDRAC Inventory",
    groups=(
        (
            "Servers",
            (
                PluginMenuItem(
                    link="plugins:netbox_idrac_inventory:dellserver_list",
                    link_text="Dell Servers",
                    permissions=["netbox_idrac_inventory.view_dellserver"],
                    buttons=(
                        PluginMenuButton(
                            link="plugins:netbox_idrac_inventory:dellserver_add",
                            title="Add",
                            icon_class="mdi mdi-plus-thick",
                            color=ButtonColorChoices.GREEN,
                            permissions=["netbox_idrac_inventory.add_dellserver"],
                        ),
                    ),
                ),
            ),
        ),
        (
            "Components",
            (
                PluginMenuItem(
                    link="plugins:netbox_idrac_inventory:dellcomponent_list",
                    link_text="Components",
                    permissions=["netbox_idrac_inventory.view_dellcomponent"],
                    buttons=(
                        PluginMenuButton(
                            link="plugins:netbox_idrac_inventory:dellcomponent_add",
                            title="Add",
                            icon_class="mdi mdi-plus-thick",
                            color=ButtonColorChoices.GREEN,
                            permissions=["netbox_idrac_inventory.add_dellcomponent"],
                        ),
                    ),
                ),
            ),
        ),
        (
            "Discovery",
            (
                PluginMenuItem(
                    link="plugins:netbox_idrac_inventory:dellscanrange_list",
                    link_text="Scan Ranges",
                    permissions=["netbox_idrac_inventory.view_dellscanrange"],
                    buttons=(
                        PluginMenuButton(
                            link="plugins:netbox_idrac_inventory:dellscanrange_add",
                            title="Add",
                            icon_class="mdi mdi-plus-thick",
                            color=ButtonColorChoices.GREEN,
                            permissions=[
                                "netbox_idrac_inventory.add_dellscanrange"
                            ],
                        ),
                    ),
                ),
            ),
        ),
    ),
    icon_class="mdi mdi-server",
)
