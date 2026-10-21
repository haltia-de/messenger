# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""haltia-messenger on the fake link, with made-up chats: to look at the window
without an account. Nothing goes anywhere; what is sent, joined or deleted
stays in this process. Run with the tests' Python:

    .cache/venv/bin/python tests/demo.py      (after sh tests/run.sh once)
"""
from common import load

bm = load()
from fake_link import FakeLink, audio, file, now_ms, video  # noqa: E402
from gi.repository import GLib  # noqa: E402

MIN, DAY = 60000, 86400000
NOW = now_ms()
fake = FakeLink()
MAMA, SERGEY, PETYA, OLGA = 10, 20, 30, 40
fake.person(MAMA, "Мама", contact=True)
fake.person(SERGEY, "Сергей Иванов", contact=True)
fake.person(PETYA, "Петя", contact=True)
fake.person(OLGA, "Ольга", phone="+79001234567")

mama = fake.dialog(MAMA, unread=2)
fake.say(mama, "Привет! Как дела?", MAMA, t=NOW - DAY - 30 * MIN, reactions=[("❤️", 1)], yours="❤️")
fake.say(mama, "Хорошо, работаю", t=NOW - DAY - 20 * MIN)
fake.say(mama, "", MAMA, t=NOW - 30 * MIN, attaches=[audio("https://vd.okcdn.ru/voice.ogg", 14)])
fake.say(mama, "", MAMA, t=NOW - 20 * MIN, attaches=[video(5, "", 42)])
fake.say(mama, "Вот рецепт", MAMA, t=NOW - 10 * MIN, attaches=[file(6, "Пирог с яблоками.pdf", 1840000)])
fake.say(mama, "Позвони вечером", MAMA, t=NOW - 5 * MIN, reactions=[("👍", 1)])
sergey = fake.dialog(SERGEY)
fake.say(sergey, "Договорились", t=NOW - DAY)
dacha = fake.group(-21, "Дача", members=[PETYA], unread=5)
fake.say(dacha, "фото с участка", PETYA, t=NOW - 40 * MIN)
school = fake.group(-22, "Школа, 5 «Б»", members=[PETYA])
fake.say(school, "Собрание в четверг", PETYA, t=NOW - 3 * DAY)
news = fake.group(-31, "Новости города", kind="CHANNEL", unread=12)
for i in range(200):  # a long channel: older pages as it scrolls up
    fake.say(news, "Новость №%d. Короткий текст о жизни города." % (i + 1), 99,
             t=NOW - (200 - i) * 47 * MIN)
weather = fake.group(-32, "Погода", kind="CHANNEL", unread=3)
fake.say(weather, "Завтра +12, дождь", 98, t=NOW - 2 * 3600000)
fake.group(-70, "Афиша", kind="CHANNEL", joined=False, link="https://max.ru/afisha")

bm.save_json(bm.KNOWN, [MAMA, SERGEY, PETYA])  # not the first run
app = bm.Max(link=fake)
app.pinned = [mama]
# Every minute a new message from Мама, to see one come in.
GLib.timeout_add_seconds(60, lambda: fake.incoming(mama, "Ты где?", MAMA) and True)
app.run(None)
