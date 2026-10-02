"""SwitchMap: synthetic SwitchDraw logs and VLAN color persistence."""

from nccm.switchmap.log_builder import SwitchdrawLogResult, build_switchdraw_log
from nccm.switchmap.vlan_colors import assign_vlan_colors, get_vlan_colors_for_site

__all__ = [
    "SwitchdrawLogResult",
    "build_switchdraw_log",
    "assign_vlan_colors",
    "get_vlan_colors_for_site",
]
