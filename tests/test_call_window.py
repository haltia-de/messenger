# SPDX-License-Identifier: GPL-3.0-or-later
"""The call controls on the real GTK window, using no account or microphone."""
import time
from common import load, ok
bm = load()
from fake_link import FakeLink
from fake_hands import FakeHands
from gi.repository import GLib


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
app.set_flags(app.get_flags() | bm.Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
app.do_activate()
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
app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "ringing"})
assert app.call_box.get_visible() and app.call_answer.get_visible()
assert app.call_end.get_label() == "Отклонить"
assert not app.call_button.get_sensitive()
app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "active"})
assert not app.call_answer.get_visible() and app.call_end.get_label() == "Завершить"
assert "микрофон включён" in app.call_label.get_text()
app.call_changed({"id": "synthetic-invitation", "name": "Тестовый собеседник", "state": "ended"})
assert app.call_end.get_label() == "Закрыть" and app.call_button.get_sensitive()
app.call_end.clicked()
assert not app.call_box.get_visible()
# A late callback for an older call cannot overwrite a new incoming call.
app.call_changed({"id": "replacement", "name": "Другой собеседник", "state": "ringing"})
app.call_changed({"id": "old-call", "name": "Старый собеседник", "state": "failed"})
app.call_result(None, bm.Offline())  # an older request fails after the new invitation
assert "Другой собеседник" in app.call_label.get_text()
app.call_changed({"id": "replacement", "name": "Другой собеседник", "state": "ended"})
app.backend.run(app.backend.stop("max"))
wait(lambda: not app.backend.accounts["max"].online)
app.win.destroy()
ok("dialog-only Call, incoming Answer/Decline, active End, dismissal and stale events")
