"""Minimal tray icon via StatusNotifierItem (SNI) using Gio.DBus.

No external Python dependencies — uses gi.repository.Gio/GLib directly.

StatusNotifierItem spec:
    https://www.freedesktop.org/wiki/Specifications/StatusNotifierItem/
DBusMenu spec:
    https://github.com/AyatanaIndicators/libdbusmenu
"""

from __future__ import annotations

import os
from collections.abc import Callable

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gio, GLib  # noqa: E402

# ---------------------------------------------------------------------------
# DBus interface XML
# ---------------------------------------------------------------------------

_SNI_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Id"       type="s" access="read"/>
    <property name="Category" type="s" access="read"/>
    <property name="Status"   type="s" access="read"/>
    <property name="Title"    type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="Menu"     type="o" access="read"/>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta"       type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
  </interface>
</node>"""

_MENU_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version"       type="u"  access="read"/>
    <property name="TextDirection" type="s"  access="read"/>
    <property name="Status"        type="s"  access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId"       type="i"        direction="in"/>
      <arg name="recursionDepth" type="i"        direction="in"/>
      <arg name="propertyNames"  type="as"       direction="in"/>
      <arg name="revision"       type="u"        direction="out"/>
      <arg name="layout"         type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids"           type="ai"      direction="in"/>
      <arg name="propertyNames" type="as"      direction="in"/>
      <arg name="properties"    type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id"    type="i" direction="in"/>
      <arg name="name"  type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id"        type="i"  direction="in"/>
      <arg name="eventId"   type="s"  direction="in"/>
      <arg name="data"      type="v"  direction="in"/>
      <arg name="timestamp" type="u"  direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events"   type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai"      direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id"          type="i" direction="in"/>
      <arg name="needsUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids"          type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors"     type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent"   type="i"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id"        type="i"/>
      <arg name="timestamp" type="u"/>
    </signal>
  </interface>
</node>"""

# Parse interface descriptors once at import time
_SNI_IFACE_INFO = Gio.DBusNodeInfo.new_for_xml(_SNI_XML).interfaces[0]
_MENU_IFACE_INFO = Gio.DBusNodeInfo.new_for_xml(_MENU_XML).interfaces[0]


# ---------------------------------------------------------------------------
# TrayIcon
# ---------------------------------------------------------------------------


class TrayIcon:
    """System tray icon via StatusNotifierItem over session DBus.

    Uses Gio.DBus directly — no AppIndicator3 or other C library needed.
    start() returns True if a StatusNotifierWatcher was found and the item
    was successfully registered.  Returns False (silently) if no watcher
    is present (e.g., plain GNOME without the AppIndicator extension).
    """

    def __init__(
        self,
        icon_name: str,
        title: str,
        on_activate: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._icon_name = icon_name
        self._title = title
        self._on_activate = on_activate
        self._on_quit = on_quit
        self._running = False
        self._conn: Gio.DBusConnection | None = None
        self._bus_name: str = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._sni_reg_id: int = 0
        self._menu_reg_id: int = 0

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Register the tray icon. Returns False if no SNI watcher is present."""
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return False

        # Register StatusNotifierItem object
        self._sni_reg_id = self._conn.register_object(
            "/StatusNotifierItem",
            _SNI_IFACE_INFO,
            self._sni_method_call,
            self._sni_get_property,
            None,
        )

        # Register DBusMenu object
        self._menu_reg_id = self._conn.register_object(
            "/MenuObject",
            _MENU_IFACE_INFO,
            self._menu_method_call,
            self._menu_get_property,
            None,
        )

        # Acquire a well-known bus name so the watcher can address us
        try:
            result = self._conn.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "RequestName",
                GLib.Variant("(su)", (self._bus_name, 0)),
                GLib.VariantType("(u)"),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            # 1 == DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER
            if result.unpack()[0] != 1:
                self._cleanup_registrations()
                return False
        except GLib.Error:
            self._cleanup_registrations()
            return False

        # Register with the StatusNotifierWatcher
        try:
            self._conn.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
        except GLib.Error:
            # No watcher present — clean up and report failure
            self._release_name()
            self._cleanup_registrations()
            return False

        self._running = True
        return True

    def stop(self) -> None:
        """Unregister the tray icon and release the bus name."""
        if not self._running:
            return
        self._running = False
        self._release_name()
        self._cleanup_registrations()

    # ------------------------------------------------------------------
    # StatusNotifierItem interface handlers
    # ------------------------------------------------------------------

    def _sni_method_call(
        self,
        conn: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "Activate":
            self._on_activate()
            invocation.return_value(GLib.Variant("()", ()))
        elif method_name == "SecondaryActivate":
            self._on_quit()
            invocation.return_value(GLib.Variant("()", ()))
        elif method_name == "Scroll":
            invocation.return_value(GLib.Variant("()", ()))
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method: {method_name}",
            )

    def _sni_get_property(
        self,
        conn: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        property_name: str,
    ) -> GLib.Variant | None:
        match property_name:
            case "Id":
                return GLib.Variant("s", self._bus_name)
            case "Category":
                return GLib.Variant("s", "ApplicationStatus")
            case "Status":
                return GLib.Variant("s", "Active")
            case "Title":
                return GLib.Variant("s", self._title)
            case "IconName":
                return GLib.Variant("s", self._icon_name)
            case "Menu":
                return GLib.Variant("o", "/MenuObject")
            case _:
                return None

    # ------------------------------------------------------------------
    # DBusMenu interface handlers
    # ------------------------------------------------------------------

    def _menu_method_call(
        self,
        conn: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "GetLayout":
            # Build (u(ia{sv}av)) in one shot from a plain Python tuple so
            # PyGObject can apply the full type string without needing
            # GLib.Variant.new_tuple (broken as a class-method call in this
            # version of PyGObject).
            layout_tuple = self._build_layout_tuple()
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, layout_tuple)))
        elif method_name == "GetGroupProperties":
            invocation.return_value(GLib.Variant("(a(ia{sv}))", ([],)))
        elif method_name == "GetProperty":
            invocation.return_value(GLib.Variant("(v)", (GLib.Variant("s", ""),)))
        elif method_name == "Event":
            args = parameters.unpack()
            item_id, event_id = args[0], args[1]
            if event_id == "clicked":
                if item_id == 1:
                    self._on_activate()
                elif item_id == 2:
                    self._on_quit()
            invocation.return_value(GLib.Variant("()", ()))
        elif method_name == "EventGroup":
            events = parameters.unpack()[0]
            for item_id, event_id, _data, _ts in events:
                if event_id == "clicked":
                    if item_id == 1:
                        self._on_activate()
                    elif item_id == 2:
                        self._on_quit()
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method_name == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method_name == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method: {method_name}",
            )

    def _menu_get_property(
        self,
        conn: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        property_name: str,
    ) -> GLib.Variant | None:
        match property_name:
            case "Version":
                return GLib.Variant("u", 3)
            case "TextDirection":
                return GLib.Variant("s", "ltr")
            case "Status":
                return GLib.Variant("s", "normal")
            case "IconThemePath":
                return GLib.Variant("as", [])
            case _:
                return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_layout_tuple(self) -> tuple:
        """Return the root menu layout as a plain Python tuple.

        The caller embeds this directly in GLib.Variant("(u(ia{sv}av))", ...)
        so PyGObject can apply the full type string in one pass.  Each child
        item is pre-built as GLib.Variant("v", ...) since the 'av' type
        requires each element to already be a boxed variant.
        """

        def _item(item_id: int, label: str) -> GLib.Variant:
            props: dict[str, GLib.Variant] = {
                "label": GLib.Variant("s", label),
                "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True),
                "type": GLib.Variant("s", "standard"),
            }
            return GLib.Variant("v", GLib.Variant("(ia{sv}av)", (item_id, props, [])))

        return (0, {}, [_item(1, f"Show {self._title}"), _item(2, "Quit")])

    def _cleanup_registrations(self) -> None:
        if self._conn is None:
            return
        if self._sni_reg_id:
            self._conn.unregister_object(self._sni_reg_id)
            self._sni_reg_id = 0
        if self._menu_reg_id:
            self._conn.unregister_object(self._menu_reg_id)
            self._menu_reg_id = 0

    def _release_name(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ReleaseName",
                GLib.Variant("(s)", (self._bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except GLib.Error:
            pass
