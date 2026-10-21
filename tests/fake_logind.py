# SPDX-License-Identifier: GPL-3.0-or-later
"""A logind stand-in on the private test bus, returning real Unix fds."""
import os
import queue
import threading
from unittest.mock import patch

from gi.repository import Gio, GLib
from haltia_kit import awake


class FakeLogind:
    def __init__(self):
        self.requests = []
        self.readers = []
        self.ready = queue.Queue()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        result = self.ready.get(timeout=5)
        if isinstance(result, Exception):
            raise result
        self.client = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def _serve(self):
        try:
            context = GLib.MainContext.new()
            context.push_thread_default()
            self.loop = GLib.MainLoop.new(context, False)
            bus = Gio.DBusConnection.new_for_address_sync(
                os.environ["DBUS_SESSION_BUS_ADDRESS"],
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None)
            interface = Gio.DBusNodeInfo.new_for_xml('''<node>
              <interface name="org.freedesktop.login1.Manager"><method name="Inhibit">
              <arg type="s" direction="in"/><arg type="s" direction="in"/>
              <arg type="s" direction="in"/><arg type="s" direction="in"/>
              <arg type="h" direction="out"/>
              </method></interface></node>''').interfaces[0]
            registration = bus.register_object("/org/freedesktop/login1", interface, self._inhibit, None, None)
            bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                          "RequestName", GLib.Variant("(su)", ("org.freedesktop.login1", 0)),
                          GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
            self.ready.put(True)
            self.loop.run()
            bus.unregister_object(registration)
            bus.close_sync(None)
            context.pop_thread_default()
        except Exception as error:
            self.ready.put(error)

    def _inhibit(self, _bus, _sender, _path, _interface, _method, parameters, invocation):
        self.requests.append(parameters.unpack())
        reader, writer = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.readers.append(reader)
        fds = Gio.UnixFDList.new()
        index = fds.append(writer)
        os.close(writer)
        invocation.return_value_with_unix_fd_list(GLib.Variant("(h)", (index,)), fds)

    def inhibit(self, *args):
        # Exercise the kit's real Manager.Inhibit call and fd extraction,
        # redirecting only its system-bus lookup to the private test bus.
        with patch.object(awake.Gio, "bus_get_sync", return_value=self.client):
            return awake.logind_inhibit(*args)

    def released(self, index=-1):
        try:
            return os.read(self.readers[index], 1) == b""
        except BlockingIOError:
            return False

    def close(self):
        self.loop.quit()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        for fd in self.readers:
            os.close(fd)
