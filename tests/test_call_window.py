# SPDX-License-Identifier: GPL-3.0-or-later
"""The call controls on the real GTK window, using no account or microphone."""
import os
import time
from unittest.mock import Mock, patch
from common import load, ok
bm = load()
from fake_link import FakeLink
from fake_hands import FakeHands
from fake_logind import FakeLogind
from gi.repository import GLib, Gio, GdkPixbuf


def wait(check):
    deadline = time.monotonic() + 5
    while not check():
        assert time.monotonic() < deadline
        while GLib.MainContext.default().iteration(False):
            pass
        time.sleep(.01)


fake = FakeLink(can=FakeLink.can | {"calls"})
fake.person(10, "Тестовый собеседник", contact=True)
dialog = fake.dialog(10)
group = fake.group(20, "Тестовая группа")
hands = FakeHands()
app = bm.Max(link=fake, media=bm.Media(hands.spawn, hands.open_uri, hands.fetch, hands.player, hands.download))
app.call_ringer = Mock()  # No real speaker, even on a host with media support.
app.call_awake = Mock()
logind = FakeLogind()
app.call_logind.inhibit = logind.inhibit
app.set_flags(app.get_flags() | bm.Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
# Exercise the real GIO freedesktop backend, including its desktop-entry hint.
notifications, closed = [], []
connection = app.get_dbus_connection()
interface = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
<arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
</interface></node>''').interfaces[0]
def notification_call(_bus, _sender, _path, _iface, method, parameters, invocation):
    if method == "Notify":
        notifications.append(parameters.unpack())
        invocation.return_value(GLib.Variant("(u)", (len(notifications),)))
    else:
        closed.append(parameters.unpack()[0])
        invocation.return_value(None)
registration = connection.register_object("/org/freedesktop/Notifications", interface, notification_call, None, None)
owned = []
bus_owner = Gio.bus_own_name_on_connection(connection, "org.freedesktop.Notifications",
                                         Gio.BusNameOwnerFlags.NONE, lambda *_args: owned.append(True), None)
wait(lambda: owned)
app.do_activate()
assert app.ring_scale.get_value() == 65
app.ring_scale.set_value(40)
assert bm.ring_volume() == .4
wait(lambda: app.backend.accounts["max"].online and dialog in app.chatlist.chats)
app.open(dialog)
assert app.call_button.get_visible()
fake.can = fake.can - {"calls"}
app.page_changed()
assert not app.call_button.get_visible()
app.open(dialog)
assert not app.call_button.get_visible()
fake.can = fake.can | {"calls"}
app.open(group)
assert not app.call_button.get_visible()
app.open(dialog)
# Dialling always asks, including when file/forward confirmations are off.
requests, questions = [], []
async def dial(action, **kwargs):
    requests.append((action, kwargs))
def question(_window, text, yes):
    questions.append((text, yes))
    assert not requests
    app.dial_call()  # reentry while the modal dialog is open cannot ask/dial again
    return False
app.confirm_acts = False
with patch.object(app.backend, "call", side_effect=dial):
    with patch.object(bm.dialogs, "ask", side_effect=question):
        app.dial_call()
    assert not requests and questions == [("Позвонить Тестовый собеседник?", "Позвонить")]
    with patch.object(bm.dialogs, "ask", return_value=True):
        app.dial_call()
    wait(lambda: len(requests) == 1)
    assert requests == [("dial", {"peer": dialog})]
    requests.clear()
    def changed_chat(*_args):
        app.open(group)
        return True
    with patch.object(bm.dialogs, "ask", side_effect=changed_chat):
        app.dial_call()
    assert not requests
    app.open(dialog)
    def incoming_while_asking(*_args):
        app.call_changed({"id": "during-confirm", "name": "Тестовый собеседник", "state": "ringing"})
        return True
    with patch.object(bm.dialogs, "ask", side_effect=incoming_while_asking):
        app.dial_call()
    assert not requests
    app.call_changed({"id": "during-confirm", "name": "Тестовый собеседник", "state": "ended"})
assert app.lookup_action("quit") is not None and app.get_accels_for_action("app.quit")
ok("mandatory dial confirmation, cancellation, reentry, changed chat and incoming-call races")

# Use the real kit dialog and its nested GTK loop. A timeout cancels only
# the broken implementation so this test fails rather than hanging.
responses, timed_out = [], []
def interrupt_confirmation():
    question = next(w for w in bm.Gtk.Window.list_toplevels()
                    if isinstance(w, bm.Gtk.Dialog) and w.get_transient_for() is app.win)
    question.connect("response", lambda _dialog, response: responses.append(response))
    app.call_changed({"id": "interrupt-dialog", "name": "Тестовый собеседник", "state": "ringing"})
    def fallback():
        timed_out.append(True)
        question.response(bm.Gtk.ResponseType.CANCEL)
        return False
    fallback_timer.append(GLib.timeout_add(300, fallback))
    return False
fallback_timer = []
GLib.idle_add(interrupt_confirmation)
app.dial_call()
if not timed_out:
    GLib.source_remove(fallback_timer[0])
assert not timed_out, "incoming call left the dial confirmation blocking Answer"
assert responses == [bm.Gtk.ResponseType.CANCEL]
assert not requests and app.call_answer.is_sensitive()
app.call_changed({"id": "interrupt-dialog", "name": "Тестовый собеседник", "state": "ended"})
ok("incoming call dismisses the real dial confirmation without dialling or answering")

app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "ringing"})
wait(lambda: len(notifications) >= 2)
notification = notifications[-1]
assert notification[6]["urgency"] == 2
assert notification[6]["category"] == "call.incoming"
assert notification[6]["desktop-entry"] == bm.APP_ID
assert "default" in notification[5]
app.activate_action("show-call", None)
assert not requests  # Bringing the call forward is never acceptance.
app.call_awake.hold.assert_called()
assert logind.requests[-1] == ("sleep:idle", "Сообщения", "call", "block")
assert not logind.released()  # A portal cookie is not the tablet's inhibitor.
held_fd, inhibitors = app.call_logind.fd, len(logind.requests)
app.call_ringer.start.assert_called()
assert app.call_box.get_visible() and app.call_answer.get_visible()
assert app.call_pages.get_visible_child_name() == "call"
assert app.call_end.get_label() == "Отклонить"
assert not app.call_button.get_sensitive()
for width, height in ((800, 600), (1280, 800)):
    app.win.resize(width, height)
    until = time.monotonic() + .3
    wait(lambda: time.monotonic() > until)
    app.win.check_resize()
    for control in (app.call_answer, app.call_end):
        allocation = control.get_allocation()
        assert allocation.height >= 80
        assert allocation.y + allocation.height <= app.call_box.get_allocated_height()
    assert app.call_name.is_drawable() and app.call_photo.is_drawable()
    shots = os.environ.get("HALTIA_SHOTS")
    if shots:
        import cairo
        allocation = app.win.get_allocation()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, allocation.width, allocation.height)
        app.win.draw(cairo.Context(surface))
        surface.write_to_png(os.path.join(shots, "incoming-%d.png" % width))
app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "active"})
assert app.call_logind.fd == held_fd and len(logind.requests) == inhibitors
assert not logind.released()
app.call_ringer.stop.assert_called()
wait(lambda: closed)
assert not app.call_answer.get_visible() and app.call_end.get_label() == "Завершить"
assert "микрофон включён" in app.call_label.get_text()
app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "ended"})
assert app.call_logind.fd is None
wait(lambda: logind.released())
assert app.call_end.get_label() == "Закрыть" and app.call_button.get_sensitive()
app.call_end.clicked()
assert not app.call_box.get_visible()
assert app.call_pages.get_visible_child_name() == "messages"
# A late callback for an older call cannot overwrite a new incoming call.
app.call_changed({"id": "replacement", "name": "Другой собеседник", "state": "ringing"})
app.call_changed({"id": "old-call", "name": "Старый собеседник", "state": "failed"})
app.call_result(None, bm.Offline())  # an older request fails after the new invitation
assert "Другой собеседник" in app.call_name.get_text()
app.call_changed({"id": "replacement", "name": "Другой собеседник", "state": "ended"})
# A photo delivered after another invitation must not replace its portrait.
portraits = []
with patch.object(app.media, "photo", side_effect=lambda url, done, **_kw: portraits.append(done)):
    app.call_changed({"id": "portrait-old", "name": "Первый", "state": "ringing", "photo": "https://max.ru/old"})
    app.call_changed({"id": "portrait-old", "name": "Первый", "state": "ended"})
    app.call_changed({"id": "portrait-new", "name": "Второй", "state": "ringing", "photo": "https://max.ru/new"})
    new = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 180, 180)
    old = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 90, 90)
    portraits[-1](new)
    portraits[0](old)
    assert app.call_photo.get_pixbuf() == new
    app.call_changed({"id": "portrait-new", "name": "Второй", "state": "ended"})
app.backend.run(app.backend.stop("max"))
wait(lambda: not app.backend.accounts["max"].online)
app.win.destroy()
assert all(logind.released(n) for n in range(len(logind.readers)))
logind.close()
connection.unregister_object(registration)
Gio.bus_unown_name(bus_owner)
ok("dialog-only Call, incoming Answer/Decline, active End, dismissal and stale events")
ok("critical call.incoming notification, desktop-entry, show-only action, wake, large controls and late portraits")
ok("logind sleep:idle fd is held from ringing through active despite a portal cookie, then closed")
