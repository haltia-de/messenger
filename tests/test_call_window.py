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
from haltia_kit import awake
from gi.repository import GLib, Gio, GdkPixbuf


def wait(check):
    deadline = time.monotonic() + 5
    while not check():
        assert time.monotonic() < deadline
        while GLib.MainContext.default().iteration(False):
            pass
        time.sleep(.01)


def shot(name):
    folder = os.environ.get("HALTIA_SHOTS")
    if not folder:
        return
    import cairo
    app.win.check_resize()
    allocation = app.win.get_allocation()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, allocation.width, allocation.height)
    app.win.draw(cairo.Context(surface))
    surface.write_to_png(os.path.join(folder, name))


fake = FakeLink(can=FakeLink.can | {"calls"})
fake.person(10, "Тестовый собеседник", contact=True)
dialog = fake.dialog(10)
group = fake.group(20, "Тестовая группа")
hands = FakeHands()
app = bm.Max(link=fake, media=bm.Media(hands.spawn, hands.open_uri, hands.fetch, hands.player, hands.download))
app.call_ringer = Mock()  # No real speaker, even on a host with media support.
portal_awake = app.call_awake
app.call_awake = Mock()
logind = FakeLogind()
app.call_logind.inhibit = logind.inhibit
app.set_flags(app.get_flags() | bm.Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
# Exercise the real GIO freedesktop backend, including its desktop-entry hint.
notifications, closed = [], []
reply_delay = [0]  # ms before Notify answers: GIO knows no server id meanwhile
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
        answer = GLib.Variant("(u)", (len(notifications),))
        if reply_delay[0]:
            GLib.timeout_add(reply_delay[0], lambda: invocation.return_value(answer) and False)
        else:
            invocation.return_value(answer)
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
app.ring_scale.set_value(0)
assert app.ring_scale.get_value() == 20 and bm.ring_volume() == .2
bm.save_setting("ring_volume", "0")
assert bm.ring_volume() == .2  # Old saved settings cannot silence calls either.
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
    shot("incoming-%d.png" % width)
app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "active"})
assert app.call_logind.fd == held_fd and len(logind.requests) == inhibitors
assert not logind.released()
app.call_ringer.stop.assert_called()
wait(lambda: closed)
assert not app.call_answer.get_visible() and app.call_end.get_label() == "Завершить"
assert app.call_label.get_text() == "Разговор" and app.call_mute.get_visible()  # its time once it is known
# The talk's time goes on; the microphone switched off is said
app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "active",
                  "since": time.time() - 65, "muted": True})
assert app.call_label.get_text() == "Разговор 1:05 · микрофон выключен"
assert app.call_mute.get_label() == "Включить микрофон"
requests.clear()
with patch.object(app.backend, "call", side_effect=dial):
    app.call_mute.clicked()
    wait(lambda: len(requests) == 1)
assert requests[0] == ("mute", {"conversation": "synthetic-invitation"})
shot("talk.png")
requests.clear()
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
# A pre-call error clears the previous caller and invalidates its late photo.
app.call_result(None, bm.Offline())
assert app.call_name.get_text() == "" and app.call_portrait is None
portraits[-1](new)
assert app.call_photo.get_storage_type() == bm.Gtk.ImageType.ICON_NAME
assert not app.call_hint.get_visible() and app.call_end.get_label() == "Закрыть"
app.call_end.clicked()

# A refused logind is tried once per call, not once per state/name update.
logind.refuse = True
attempts = len(logind.requests)
portal = Mock()
portal.inhibit.return_value = 0
with patch.object(app, "call_awake", portal_awake), patch.object(portal_awake, "app", portal):
    with patch.object(awake.Gio, "bus_get_sync", return_value=logind.client):
        for count, call_id in enumerate(("refused-first", "refused-next"), 1):
            for state in ("ringing", "ringing", "connecting", "active"):
                app.call_changed({"id": call_id, "name": "Тестовый собеседник", "state": state})
            assert len(logind.requests) == attempts + count and portal.inhibit.call_count == count
            app.call_changed({"id": call_id, "name": "Тестовый собеседник", "state": "ended"})
logind.refuse = False

async def unanswered():
    call = app.backend.accounts["max"].new_call("missed-local", 10, True)
    await call.end()  # Signalling ended without opening a socket or microphone.
app.backend.run(unanswered())
wait(lambda: app.missed_calls.get(str(dialog), {}).get("id") == "missed-local")
notice = app.missed_calls[str(dialog)]
wait(lambda: any(n[6].get("category") == "call.missed" for n in notifications))
missed = [n for n in notifications if n[6].get("category") == "call.missed"]
assert missed[-1][3] == "Пропущенный звонок от Тестовый собеседник"
assert "default" in missed[-1][5] and missed[-1][6]["urgency"] == 1
app.missed_call(notice)
app.open(group)
assert not app.view.call_note.get_visible()
app.activate_action("open-chat", GLib.Variant("s", bm.json.dumps(dialog)))
assert app.open_chat == dialog and app.view.call_note.is_visible()
assert app.call_pages.get_visible_child_name() == "messages"
assert "пропущенный" in app.view.call_note.get_text().lower()
assert app.view.message(notice["id"]) is None and not requests
until = time.monotonic() + .3
wait(lambda: time.monotonic() > until)
shot("missed-call.png")
saved = bm.load_json(app.missed_path, {})
assert saved[str(dialog)] == notice
assert os.stat(app.missed_path).st_mode & 0o777 == 0o600
# Restoring an app and its view keeps the dated mark, with no server message.
restored = bm.Max(link=FakeLink())
assert restored.missed_calls == saved
restored_view = restored.view_for(dialog)
assert restored_view.call_note.get_visible()
restored_view.destroy()
ok("missed notification opens the chat; its dated local mark survives a restart without a fake message")
ok("ringtone floor, clean error identity and one failed inhibitor attempt per call")

# Video invitations never open a camera by presenting or drawing frames.
video_probe = patch.object(bm, "video_supported", return_value=True)
video_probe.start()
app.open(dialog)
assert app.video_button.get_visible()
app.stack.set_visible_child_name("chats")
assert not app.video_button.get_visible()
app.open(group)
assert not app.video_button.get_visible()
app.open(dialog)
video_call = {"id": "video-ui", "name": "Тестовый собеседник", "state": "ringing",
              "video_invitation": True, "video": False}
app.call_changed(video_call)
assert "Видеозвонок" in app.call_label.get_text()
# Two buttons, as on a phone: red «Отклонить» left of green «Ответить»; the
# camera is switched in the talk (no third «Ответить без видео»).
assert app.call_answer.get_visible() and app.call_end.get_visible()
assert app.call_end.get_parent() is app.call_answer.get_parent()
assert app.call_end.get_parent().get_children() == [app.call_end, app.call_answer]
assert app.call_answer.get_style_context().has_class("call-answer")
assert not app.call_mute.get_visible()
shot("video-ringing.png")
requests.clear()
with patch.object(app.backend, "call", side_effect=dial):
    app.call_answer.clicked()
    wait(lambda: len(requests) == 1)
assert requests[0] == ("answer", {"conversation": "video-ui", "video": True})
# A tap: the button says what was asked at once, and waits for the camera.
app.call_changed(dict(video_call, state="active", video=False, video_wanted=True))
assert app.call_camera.get_label() == "Выключить камеру" and not app.call_camera.get_sensitive()
app.call_changed(dict(video_call, state="active", video=True))
assert app.call_camera.get_sensitive()
# Feed the mailbox from a worker just like Gst: GTK drawing happens later.
import threading
frame = (32, 24, bytes([80, 130, 180, 255]) * (32 * 24))
worker = threading.Thread(target=lambda: [app.call_frame("video-ui", own, frame)
                                        for _n in range(100) for own in (True, False)])
worker.start()
worker.join()
assert len(app.call_frames) == 2 and app.call_frame_pending
wait(lambda: app.call_remote.surface is not None and app.call_own.surface is not None)
assert app.call_own_box.get_visible() and app.call_video_area.get_visible()
assert app.call_end.get_visible() and app.call_camera.get_visible()
for width, height in ((1280, 800), (800, 1280)):
    app.win.resize(width, height)
    until = time.monotonic() + .2
    wait(lambda: time.monotonic() > until)
    assert app.call_end.get_mapped() and app.call_camera.get_mapped()
    assert app.call_end.get_allocation().height >= 80
    assert app.call_camera.get_allocation().height >= 80
    shot("video-call-%dx%d.png" % (width, height))
shot("video-call.png")
app.call_changed(dict(video_call, state="active", video=False, remote_video=False))
assert app.call_own.surface is None and not app.call_video_area.get_visible()
app.call_frame("old-video", True, frame)
wait(lambda: not app.call_frame_pending)
assert app.call_own.surface is None
# The peer's picture goes when its frames stop, though it never said so.
with patch.object(bm, "REMOTE_STALE", .3):
    app.call_changed(dict(video_call, state="active", video=False))
    app.call_frame("video-ui", False, (24, 32, bytes(4 * 24 * 32)))
    wait(lambda: app.call_remote.surface is not None)
    assert app.call_video_area.get_visible() and not app.call_identity.get_visible()
    # Upright, as sent: no bands of its own (CallPicture fits it).
    assert (app.call_remote.surface.get_width(), app.call_remote.surface.get_height()) == (24, 32)
    wait(lambda: app.call_remote.surface is None)
    assert not app.call_video_area.get_visible() and app.call_identity.get_visible()
app.call_changed(dict(video_call, state="ended"))
assert not app.call_mute.get_visible() and not app.call_camera.get_visible()
video_probe.stop()
requests.clear()
ok("video invitation, audio-only answer, bounded frame mailbox, own preview and stale-frame rejection")

# The incoming call's notification leaves the server on every way the
# ringing ends (critical ones stay in mako till closed): answered, with or
# without video (connecting), declined, cancelled, missed, answered
# elsewhere (ended), failed; also when the server has not answered yet.
for video in (False, True):
    for outcome in ("connecting", "ended", "failed"):
        for delay in (0, 300):
            reply_delay[0] = delay
            conversation = "notice-%s-%s-%d" % (video, outcome, delay)
            invitation = {"id": conversation, "name": "Тестовый собеседник", "state": "ringing",
                          "video_invitation": video}
            sent = len(notifications)
            app.call_changed(invitation)
            wait(lambda: len(notifications) == sent + 1)
            server_id = len(notifications)
            assert notifications[-1][1] == 0  # a new notification, not an earlier call's replaced
            assert notifications[-1][3] == ("Видеозвонок" if video else "Входящий звонок")
            if not delay:
                settled = time.monotonic() + .2
                wait(lambda: time.monotonic() > settled)  # the server's id is known to GIO
            app.call_changed(dict(invitation, state=outcome))
            wait(lambda: server_id in closed)
            if outcome == "connecting":
                app.call_changed(dict(invitation, state="ended"))
            app.call_end.clicked()
            assert app.call_id is None
reply_delay[0] = 0
# None of the window's incoming-call notifications stays on the server
# (the earlier parts end calls at once after ringing, before Notify answers).
ringing = {n + 1 for n, note in enumerate(notifications) if note[3] in ("Входящий звонок", "Видеозвонок")}
replaced = {note[1] for note in notifications}
wait(lambda: not ringing - replaced - set(closed))
ok("the incoming call's notification is closed on the server however the ringing ends")

app.backend.run(app.backend.stop("max"))
wait(lambda: not app.backend.accounts["max"].online)
app.signin("max", {"kind": "out"})
assert not bm.load_json(app.missed_path, {}) and not app.view.call_note.get_visible()
app.win.destroy()
assert all(logind.released(n) for n in range(len(logind.readers)))
logind.close()
connection.unregister_object(registration)
Gio.bus_unown_name(bus_owner)
ok("dialog-only Call, incoming Answer/Decline, active End, dismissal and stale events")
ok("critical call.incoming notification, desktop-entry, show-only action, wake, large controls and late portraits")
ok("logind sleep:idle fd is held from ringing through active despite a portal cookie, then closed")
