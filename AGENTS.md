# AGENTS.md

This file provides guidance to coding agents (Claude Code, Codex and others) when working with code in this repository.

## What this is

`haltia-messenger` («Сообщения» on the screen) is a native GTK 3 client for the MAX messenger (and Telegram),
a program of the Haltia desktop (github.com/haltia-de), a desktop program of its own:
`io.github.haltia_de.Messenger` (`APP_ID`: the GApplication id, the `.desktop` file, the Wayland
app id via `GLib.set_prgname` before GTK is imported, the icon, AppStream, MPRIS, LauncherEntry).
Made for the tablet of [device-lenovo-b8000h](https://github.com/haltia-de/device-lenovo-b8000h)
(Lenovo YOGA Tablet 10 B8000-H, Alpine), whose image installs it from here by tag, but it depends
on no shell: per ADR 0001 in haltia-de/haltia it meets the shell only through freedesktop standards, and
its shared code is `haltia-kit` 2. The whole program is one Python 3 script, `haltia-messenger`
(no `.py` extension).

Until 2.0 it was `b8k-max`, `io.github.trudenboy.Max` (the rename: ADR 0004 and
`docs/plans/migration-haltia.md` in haltia-de/haltia). Till 3.0 these stay: the
`b8k-max` command as a link, the old `.desktop` file with `NoDisplay=true`, `provides`/`replaces`
of `b8k-max` in the APKBUILD, `X-Flatpak-RenamedFrom` and AppStream `<replaces>`, and
`move_old_home()` at the first start: the kit's `paths.migrate_dirs("b8k-max", …)` moves the
folders (leaving links), and `~/.config/b8k/max.conf` `[max]` (`OLD_CONF`) becomes
`~/.config/haltia/messenger.conf` `[messenger]`; so does `~/.config/haltia/max.conf` (`KIT_CONF`),
where the kit's `Settings("max")` in another program (the shell) may have moved it first — that
one is left in place. The name on the screen is by what it is, not the
service: MAX is a trademark (ADR 0004, rule 7); «MAX» stays in `GenericName`/`Keywords`.

There is no build step or linter config; the tests are in `tests/` (see Tests). GPL-3.0-or-later;
every source file starts with an `SPDX-License-Identifier: GPL-3.0-or-later` line.

## Commands

```sh
sh install.sh                # install into / under /usr/local (root needed)
sh install.sh /mnt/root /usr # into another root and prefix (packaging/alpine/APKBUILD does this)
haltia-messenger                # run with a window
haltia-messenger --background   # start hidden (the XDG autostart file does this)
python3 -m py_compile haltia-messenger   # quick syntax check
sh tests/run.sh                 # all tests (needs broadwayd and network once, for the venv)
sh tests/run.sh test_backend.py # one of them
.cache/venv/bin/python tests/demo.py   # the window on made-up chats, no account
```

Runtime deps: Python 3, PyGObject/GTK 3, `haltia-kit` 2 (github.com/haltia-de/kit, module
`haltia_kit`; Alpine `py3-haltia-kit`), PyMax's own packages (the list is `depends` in `packaging/alpine/APKBUILD`),
Telethon 1.43.2 for Telegram (Alpine `py3-telethon`; trixie's 1.40 is enough, noble's 1.25 is not:
`debian/vendor.list` puts the wheel there; the Flatpak builds pyaes from its sources, PyPI has no wheel),
optionally `py3-mpv mpv-libs` (voice) and `font-noto-emoji`; `wget`/`unzip`/`sha256sum` for
`install.sh`. `install.sh [ROOT] [PREFIX]` installs the script as the module
`PREFIX/lib/haltia-messenger/haltia_messenger_main.py` and writes `PREFIX/bin/haltia-messenger` (and the
`b8k-max` link) as a stub that runs it with `runpy.run_module(..., run_name="__main__",
alter_sys=False)`: Python keeps no bytecode of the script it is started with, so the 450 KB script was
compiled at every start, while a module loads from its `__pycache__` (the package compiles it).
`sys.argv` and the command line (`python3 PREFIX/bin/haltia-messenger`, which the shell matches; the
stub keeps the script's `#!/usr/bin/env python3`) stay
as they were; `__file__` is the module's, so paths from it go up two levels to `PREFIX` (`ringtone_file`).
It installs `data/` (the
`.desktop` file with `X-B8K-Home`/`X-B8K-Replaces=max`, the hicolor SVG icon, AppStream metainfo)
to `PREFIX/share` (and the old id's hidden `.desktop`), the XDG autostart file (`--background`, `X-B8K-Autostart`) to
`ROOT/etc/xdg/autostart`, downloads the pinned PyMax wheel (`maxapi_python-2.4.1`, sha256 checked;
cached in `$HALTIA_CACHE`, default `.cache/`) into `PREFIX/lib/haltia-messenger`, and removes
what `b8k-max` put under that prefix and the shell's old `apps.d/max.conf`. The program looks for
PyMax in `/usr/local/lib/haltia-messenger`, `/usr/lib/haltia-messenger` and
`../lib/haltia-messenger` from its command (`sys.argv[0]`). Bumping PyMax: the wheel name and sha256 in `install.sh` (and the
APKBUILD's `_whl`).

Other packages (haltia-de/haltia's `docs/plans/desktop-packages.md`), published only in Haltia's own
repositories, never on Flathub (an unofficial client):
- **Flatpak**, `packaging/flatpak/io.github.haltia_de.Messenger.yml` on `org.gnome.Platform` 51:
  `haltia-kit.yml` (a copy of the kit's module), libass, libplacebo and mpv (libmpv for voice and
  the `mpv` that opens videos; flathub/shared-modules has no libmpv), then PyMax and its packages
  as PyPI wheels by sha256: pure ones where PyPI has them, cp314 for x86_64 and aarch64
  (`only-arches`) otherwise; their versions are `requirements.txt`'s. The program's module writes
  the same stub as `install.sh` and compiles `/app/lib/haltia-messenger` (checked-hash: `/app` is
  read-only and OSTree drops mtimes). Build from the checkout
  (Flatpak's builder cannot see `/tmp`): `flatpak run org.flatpak.Builder --user --install
  --force-clean build packaging/flatpak/io.github.haltia_de.Messenger.yml`. A `flatpak run` left
  over keeps the single instance: `flatpak kill io.github.haltia_de.Messenger` before another.
- **deb**, `debian/` (native), built in `ubuntu:noble` and `debian:trixie`: `install.sh` into
  the package without the old names, `Architecture: any` because noble's pydantic is 1 —
  `debian/vendor.list` puts pydantic 2 (with pydantic-core's wheel for the architecture),
  websockets and their packages next to PyMax in `/usr/lib/haltia-messenger` there; trixie's
  own are new enough (`haltia:Depends`). The build fetches the wheels (network, sha256). The
  tests run on an installed package's Python with `HALTIA_PYTHON=/usr/bin/python3
  dbus-run-session -- sh tests/run.sh`.
- The login's QR code is drawn by `qr_png` from qrcode's matrix: qrcode's images need Pillow,
  which neither has.

Releases (ADR 0002 in haltia-de/haltia): SemVer, always `vX.Y.Z` — X incompatible (commands,
file formats, `X-B8K-…` keys), Y features, Z fixes and packaging-only changes. The tag must equal
`pkgver` in `packaging/alpine/APKBUILD` (`pkgrel=0`), the newest `<release version>` in
`data/*.metainfo.xml` and the version in `debian/changelog`; CI fails otherwise. The notes are written in `NEWS.md` (`## X.Y.Z (YYYY-MM-DD)`, then `### Русский` and
`### English`: what the person will notice), both languages, before tagging; haltia-de/ci's
`news.py metainfo NEWS.md data/*.metainfo.xml` writes them into the metainfo's `<releases>`
(English the text, Russian `xml:lang="ru"`), and `apk.yml` checks they match (`--check`). The
shell's updater shows the Russian as «Что нового» before installing. Pushing the tag runs `.github/workflows/release.yml`
(haltia-de/ci's `apk.yml`; the APKBUILD's `builddir` is GitHub's tarball folder, named
after the repository): a signed noarch Alpine 3.24 package (`abuild`, `options="net"`
for the PyMax wheel in `source=`) in the GitHub release. Push the commit first and the tag in a
push of its own — a tag pushed with the commit that adds the workflow did not start it. The
tablet's image installs that apk by a lock file; packages install under PREFIX `/usr`, so other
programs are found on `PATH` (`haltia-vplay`, `b8k-vplay` before 2.0: `shutil.which`), never at `/usr/local/bin`.

## Architecture

- **Two threads.** `Backend` runs in its own thread with its own asyncio loop. The GTK side calls
  into it only through `Backend.run(coro, done)`; results and events come back to GTK only via
  `GLib.idle_add`. Keep this rule: never touch GTK widgets from the messengers' thread, never
  await a link from the GTK thread. `run(coro, done, owner)` always answers: with `Offline` when
  the account has no connection (`Account.online`: set by `on_login`, cleared by the link's
  `on_disconnect`; requests that need the messenger call `ask()` first), there is no such
  account, or no loop, and never to an `owner` that is `gone` (a destroyed `ChatView`). The loop
  is made in `start()`.
- **Accounts** (CONTEXT.md «Аккаунт»). `Backend` holds one `Account` per link
  (`Backend.accounts`, by the link's `account`: `"max"`; `Backend(ui, link_or_links)`, else a
  `PyMaxLink` at the start; `add(link)` starts one later). An account keeps its own me, names,
  chats, known people and aliases; its files are in `DATA` for MAX (as before there were
  others) and `DATA/<account>/` for the others; the message cache is shared, another
  messenger's chats under `chats/<prefix>/`. A request about a chat or a person goes to the
  account whose id it is (`Backend.of`, `Account.owns`: MAX's ids are numbers, another's
  strings with its `prefix`, like `"tg:…"`), a channel's link to the one whose `hosts` it is on,
  a phone to each that `can` it in turn; telemetry only to those that can. A link says what it
  is: `account`, `label` (on the screen), `prefix`, `hosts`, `can` (`phone`, `links`, `react`,
  `forward`, `telemetry`, `invites`) and `dialog_of(me, user)` (MAX: own id XOR theirs). Summaries
  carry `account`, and `ChatList.replace(summaries, account)` replaces only that account's chats.
  The window is told which account: `ui.failed(account, why, pause)`, `ui.connected(account,
  on)` (the «Нет связи» bar, naming the messenger when only one of several is off; the person
  stays on their page, the wait page only before any list), `show_qr`, `logged_in`,
  `show_chats`. When a link's `run` ends or raises (PyMax gave up), `Account.live` starts it
  again after `RETRY`'s pauses (`retry()`, the wait page's «Повторить», cuts one short). A new QR
  (MAX ended the login) shows the QR page from anywhere.
- **The link to MAX** (`PyMaxLink`, CONTEXT.md «Связь с MAX»). Every request to MAX and every
  event from it goes through one link object: `run(events)`, `chats_page`, `chats`, `users`,
  `history`, `read`, `send`, `find_phone`, `add_contact`, `link_info`, `join`, `leave`, `delete`
  (only for this account: it cannot delete for all), `react`, `media_url`, `invites`, `log`.
  It hands out the link's own entities, plain dataclasses of the script — `Person` (id, name),
  `Chat` (id, kind, title, members, count, unread, last, time) and `Message` (as shown: text in
  words, photos, media items, notes of what is not shown, parts for a preview, reactions, yours,
  fwd) — never PyMax's: `max_person`/`max_chat`/`max_message` make them (MAX's service keys put
  in words, a forward's original carried, attachments sorted). PyMax and its internals
  (`client._app`, raw opcodes `LINK_INFO`/`LOG`/`CONFIG`) stay inside the link; nothing above
  it imports PyMax. Events go to `Backend.on_qr`,
  `on_login`, `on_message`, `on_reaction`, `on_delete`. Deletions are read from the frames
  themselves (`_watch_deletions`, set once at the login, wraps PyMax's `dispatcher.dispatch`;
  `_peek`: `NOTIF_MSG_DELETE`, or a `NOTIF_MESSAGE` with status `REMOVED`, which PyMax 2.4.1
  loses); `Backend.on_delete` takes them out of the cache (`cache_forget`) and the window
  (`ChatView.remove`, day labels left empty go too) and renews the chat's last message. Messages
  deleted while away go when a fetched page no longer has them (`history`, `ChatView.newest`). `tests/fake_link.py` is the second link (a small MAX
  in memory, on the same entities: `common.load()` registers the script as `haltia_messenger`); `Max(link=...)`/`Backend(ui, link)` take one. A PyMax upgrade is checked in
  `PyMaxLink` only. Don't name a fake's attributes after link operations (`chats`, `users`).
- **The link to Telegram** (`TelethonLink`, CONTEXT.md «Связь с Telegram»). The same operations
  and events as `PyMaxLink`, through Telethon (in the same asyncio loop), on the same entities:
  `tg_person`/`tg_chat`/`tg_message` make them, and nothing else imports Telethon. Its ids are
  strings: `"tg:"` and Telethon's marked peer id (a person's and their dialog's are the same,
  `dialog_of` gives the user; groups negative, channels `-100…`); message ids are Telegram's
  ints. What a message carries is a ref `"tg:<chat>/<msg>"` (`/thumb` for a video's preview)
  that `download` fetches; `media_url` gives the ref back. An outgoing message's sender is the
  account's own id (Telegram leaves it out in dialogs, `tg_message(msg, me)`). `REACTIONS`
  are mapped to Telegram's (`TG_REACTION`: it has no 😂/😮, its ❤ has no variation selector).
  `send` with files sends each as a message of its own (the text under the first) and returns
  the list (`Account.send` and the window take a list); deletions come without a chat except
  in channels (`Account.on_delete(None, ids)` looks the ids up in the account's chats).
  Senders and dialogs met are kept (`people`), so `users()` asks only for strangers. The
  login: `qr_login()` (a new code when one expires), `SessionPasswordNeededError` →
  `events.on_password(wrong)` (`Account.on_password`: the card asks, `Backend.password(name,
  text)` answers), then the `StringSession` into the Vault (`telegram`). The application's
  keys: `TG_API_ID`/`TG_API_HASH`, or `[telegram] api_id`/`api_hash` in `messenger.conf`
  (`telegram_keys()`); without keys or Telethon `Backend.missing(name)` says why, and the
  card shows it with its switch off and greyed. Telemetry and invites stay MAX's (`can`).
  Telegram is experimental (`EXPERIMENTAL`: its card says so) and off until switched on.
- **Login.** `PyMaxLink` is PyMax's QR provider; `Backend.on_qr` renders the QR code to scan with
  MAX on a phone. The session lives in the keyring: `secrets()` is haltia-kit's `Vault`
  (`app=APP_ID`, `account=max`; libsecret, the Secret portal in Flatpak; `DATA/max-session.json`,
  600, only where no Secret Service answers — never as a fallback of a refused unlock, which
  raises `Locked`), reached by PyMax through `VaultStore` (its `ExtraConfig.store`; blocking
  calls in a thread). 2.4's `web.db` moves in once (`take_old`) and is removed. Tests put a
  `FakeKeyring` in `KEYRING` (`common.load`). The sign-in is drawn as one card per messenger
  (`MESSENGERS`; `account_card`, the same in the settings' «Мессенджеры» and on the `login`
  page, which the first start and a login ended show): a switch (`messenger_on`, setting
  `account_<name>`: MAX on until switched off, others off until switched on; off disconnects,
  keeps the login, takes its chats off the list) and the state Backend tells
  (`ui.signin(account, state)`: `off`, `out` — «Войти по QR-коду» → `Backend.begin(name)` —,
  `getting`, `waiting` with its QR code, `in` with the name — «Выйти», asked first:
  `Backend.logout`, the link's `logout()` forgets the login, the account's cache goes —,
  `locked` — «Открыть»: `retry(name)` asks the keyring again —, `password` — the cloud password's
entry, `wrong` after a wrong one —, `failed` with the pause). With more than one messenger switched
on (`Max.retag`, `tagged`) each chat row says whose before its time and the phone search's
cards say it too; the phone is asked of every messenger online (`Backend.find_phone` gives a
list), a link goes by its host (`link_of`: `max.ru`, `t.me`). The forward page lists only the
chats of the message's messenger (between messengers: step 4). At the
  start (`_main`) a messenger switched on starts only if its link has a login kept
  (`link.signed_in()`); `Account.stop()` cancels its task.
- **Telemetry.** PyMax's own (a random simulation of browsing) stays off in `ExtraConfig`. The
  `Telemetry` class sends MAX-app-style events built from real UI actions instead: `NAV GO` on
  every screen change (`moved()`, driven by the stack page and window map/unmap), `PERF login`
  after each login, `PERF open_chat_to_render` with measured times. Event shapes and fixed values
  copy PyMax 2.4.1's `pymax/telemetry/payloads.py`; sent in batches via `Opcode.LOG` through
  `Backend.log` and the link. On by default, switched in the settings page (gear), stored in
  `~/.config/haltia/messenger.conf` (`[messenger] telemetry`; `buzz` there switches the desktop
  notifications of new messages; `contacts_only`, see below). Re-check the shapes when bumping PyMax.
- **Search, join, delete.** The `find` page (magnifier on the list) reads its entry with
  `phone_of` (a person: `users.search_by_phone`, then write or `users.add_contact`), `link_of`
  (a channel or group: `LINK_INFO` invoked directly so public `max.ru/name` links work too, then
  `chats.join_channel`), else filters the own chats by title and asks MAX's own search of
  public channels and groups (`Backend.search` → the link's `search`: `PUBLIC_SEARCH`
  `{query, count, type: "ALL"}`, as web.max.ru and the official app send it — PyMax has no call;
  `result[].chat` with `link`, people left out; Telegram's `contacts.search`), shown under
  «Каналы и группы» with «Подписаться» by the result's link; those already listed left out. A dialog opened from the search
  waits in `Max.pending` (chat id = own id XOR theirs, as PyMax numbers dialogs) until its first
  message. The chat menu's delete (the edit button in the header, `chat_menu`; it also renames, pins
  and switches notifications) asks on the page (`confirm` bar), then `Backend.remove`: a dialog
  is deleted, a group or channel left, always `for_all=False` — never for the others in it.
  A message from a chat not in the list fetches it (`Backend.chat`).
- **Contacts only.** MAX has no "who may write to me" setting, so `contacts_only` (on by default)
  is a filter here: summaries carry `peer` and `stranger`, and `ChatList.hidden()` keeps strangers'
  dialogs off the list, the local search, the badge and the buzz. `Backend.known` (persisted to
  `~/.local/share/haltia-messenger/known.json`, 600) holds login contacts, contacts added here, people
  written to here (`remember`), and on the very first run every existing dialog's peer — the
  login sends only changed contacts after the first one, and nobody known must go quiet on update.
- **Chat invites.** MAX's own privacy setting `CHATS_INVITE` is shown, not changed: MAX answers
  `account.change_profile_settings` from a web client with `errors.safe.mode.protected.change.disabled`
  ("update the app"; the account has `SAFE_MODE`). PyMax keeps only the hash of the login answer's
  `config`, so `PyMaxLink._watch_login` wraps `app.invoke` and keeps `config.user` of each
  `Opcode.LOGIN` answer; `link.invites()` gives `CHATS_INVITE`, and the settings card shows it on a
  greyed switch with a hint that only MAX's official app changes it.
- **Single instance, background life.** `Max` is a `Gtk.Application` with id `APP_ID`; a second
  launch just activates the first process over D-Bus. Closing the window hides it. The header
  has the desktop's window buttons (`set_show_close_button`) except under the Haltia shell
  (`ON_HALTIA`: `Haltia` in `XDG_CURRENT_DESKTOP`), whose own ✕ closes windows. With
  `--background` the window is not shown at start.
- **Caches.** `~/.cache/haltia-messenger/chats/<id>.json` keeps the last `KEEP` messages per chat and
  `list.json` the chat list (all mode 600, written atomically via `.new` + `os.replace`).
  Chat *files* themselves are not bounded (MSG2-14); `docs/cache-retention.md` is the proposed
  access-stamp retention policy and is not applied — no production pass deletes them. The
  messages go through `MessageCache` (`Backend.cache`): read from disk once and kept in memory,
  written by a timer thread 2 s after the last change and at `do_shutdown` (`flush`); both
  threads use it, `read` gives copies — never touch the files themselves. A chat whose
  `last_message` is already cached and has no unread opens with no history request at all; else
  the last `PAGE` are fetched (see Paging). The last `VIEWS` chat views stay built in memory. The chat list
  keeps one row per chat (`Max.rows`, sorted and filtered by GTK) and `fill_list` redraws only rows
  whose look changed — don't go back to rebuilding it (≈30× slower per message). A full fill with many new rows (the first login's) builds the
  shown tab's top `ROWS_FIRST` at once and the rest `ROWS_STEP` per idle (`_more_rows`). A message, a read
  or a delete calls `fill_list(only={chat})`: that row alone is redrawn and re-placed
  (`row.changed()`); `invalidate_sort`/`invalidate_filter` only for a full refresh (a tab, a pin,
  `contacts_only`), and the login's list redraws only the chats that differ (`show_chats`).
  `show_counts` touches the tabs, the subtitle and the badge only when a count changed (a tab's
  text through its label child: `set_label` builds a new one, ms on the tablet). The tablet's
  numbers come from `tests/bench.py`. Photos are cached
  in `~/.cache/haltia-messenger/` by URL hash, touched when shown, pruned after `PHOTO_DAYS` unshown (at
  start and daily). Small state files in `DATA` go through `load_json`/`save_json`/`save_text` (600,
  atomic, from any thread). The MAX thread starts after the window's first frame (`after_first_frame`;
  at once with `--background`), so PyMax's import does not share the GIL with the first drawing. `asyncio`, `concurrent.futures` and
  `urllib.request` are `lazy()` modules for the same reason (loaded at first use, after it); keep
  them off the path to the first frame, and the photo opener is made by `photo_opener()` at first use.
- **Chat list** (`ChatList`, CONTEXT.md «Список чатов»; no GTK). Owns the summaries, dialogs from
  the search not written to yet (`start_dialog`/`wrote`), pins and per-chat notifications (`PREFS`,
  `chats.json`; local — PyMax has no pin/mute request, `CHAT_PERSONAL_CONFIG` is bare), the
  `contacts_only` value, and the last list (`LIST`, `list.json`, shown at once on the next start).
  It answers `entries(tab)` (ordered `(summary, pinned, quiet)`: pinned first in pin order, then the
  newest; strangers hidden), `counts()` (per tab, and `loud` for the subtitle and the panel's
  button), `loud(chat)` (buzz?), `hidden`, `find`, `get`, `listed`. Channels are quiet unless
  switched on, others loud unless switched off. Keep these rules there; `Max` only draws them: one
  kept row per chat, redrawn when its `look(entry)` changes, ordered by `order(chat)` and filtered
  by `shown(chat, Max.tab)` (`entry(chat)` per row; `entries(tab)` is the same answer for a whole
  tab). `list.json` is written only when it changed, by a thread (`saving`). A long press on the list (`row_menu`, one gesture on the ListBox,
  `get_row_at_y`) opens the pin/notification menu; `held` stops the release from opening the chat.
- **Chat view** (`ChatView`, see `CONTEXT.md`). One chat on screen is one deep module: its own
  scroll area (`.widget`, an Overlay over the ScrolledWindow with the round «↓» button that shows
  away from the newest message and counts those come meanwhile), the bubbles, day labels, reactions and media controls, the build
  queue (`FIRST` at once, then `STEP` per idle, nothing above while the reader scrolled within
  `SETTLE`), older pages (`fetch_older` as the reader nears the top, `PREFETCH` in the background,
  a spinner while one comes), the place (`anchor`; the first `enter()` goes to the bottom, later
  ones stay; the own message scrolls down, another's only if already there), photos loaded only
  near the screen, and `leave()` cutting it to `BUBBLES` (also when the reader comes back down to
  the newest from far above). Every reason to look at the place (a scroll, a size change, bubbles
  built) goes through `_soon()`: one idle `_pass` decides the down button, the spinner, an older
  page (on a scroll only, and only after `newest()` came: `fresh`), the photos and the cut; one
  `anchor_timer` drops the anchor 400 ms after the last chunk above. Its interface is `newest(msgs, gap,
  done)`, `add`, `reacted`, `message`, `enter`/`leave`/`destroy`, `empty`; what it needs comes in at
  creation (cached messages and `fetch_older`/`on_hold`/`on_media`/`on_react`). `Max` only keeps
  up to `VIEWS` of them, puts the open one's widget on the chat page and answers the callbacks.
  Keep chat-screen behaviour inside it, and test it through that interface (its widget tree).
  `Backend.history` returns the newest `PAGE` and whether they leave a gap after the cache
  (no request at all when the cache holds a full page ending at the chat's last message);
  `older(chat, before)` returns the page before.
- **Media** (`Media`, CONTEXT.md «Медиа»). The one place that decides how to reach MAX's CDNs:
  `media_ok` (https on `MEDIA_HOSTS` only: MAX's hosts and its CDNs `okcdn.ru`/`mycdn.me`;
  `photo_ok` is the same) for photos, previews, voice, video and files; one header, the
  `agent` (PyMax's browser user agent, set by `Max.logged_in`), and no `Referer`/`Origin` — the
  video CDN answers 400 to those; photos never follow a redirect off those hosts
  (`PhotoRedirect`, made by `photo_redirect()` at first use). Photos come through its queue (`PHOTO_WORKERS` at a time, the last asked
  first, one fetch per link, none for an `owner` that is `gone` — ChatView's images are `watched`),
  saves through a worker of their own, one at a time. It caches photos (`photo(url, done, size,
  owner)`, touched when shown, `prune()` after
  `PHOTO_DAYS` unshown), plays voice through libmpv (`voice`/`toggle`/`stop`, `on_time`/`on_end`;
  an `end-file` with reason ABORTED is a stop or a switch, not an end), starts a video in
  `haltia-vplay` (`b8k-vplay` before 2.0; on `PATH`, Видео's package) or `mpv --fs` with `ytdl=no` and `load-unsafe-playlists=no` (`video(url, title)`), and
  opens a file by the desktop's program for its type (`file(url, name, done)`: fetched under its name into a folder of its link's own (a hash) in `DOCS`, the cache's `documents/` — two messages' files of one name never write over each other — then a `file://` URI — a PDF opens in «Документы» on the tablet). What fails goes to `~/.cache/haltia-messenger/haltia-messenger.log` (`LOG`; the link's
  losses and restarts too; `player.log` before 2.4, removed by `prune`)
  (600, host and path only; the players' own output too). Its hands come in at creation —
  `spawn`, `open_uri`, `fetch`, `player` — real by default, `tests/fake_hands.py` in tests.
  `media_of` turns AUDIO/VIDEO/FILE attachments into `media` items; a FILE named like audio
  (`AUDIO_FILES`: .mp3, .m4a, .ogg…) becomes an `audio` item with `url` None and its `file` id:
  `Max.media_tapped` asks its link of MAX on ▶, then plays it like a voice message (its length
  comes from libmpv: `on_time(sec, total)`); the link for a video or a
  file comes from `Backend.media_url` (never an `external` one). This is a security boundary:
  links come inside messages; keep the host list tight. What plays and where its button is stays
  with `Max` (`playing`, `playing_chat`); a voice message stops when its button is destroyed.
  By default it plays only while its chat is in front (`chat`, `photo`, `forward` pages):
  `stop_sound` on leaving it, opening another chat or the window's unmap. With `keep_sound`
  (setting, off by default) it plays on, and `show_nowplay` shows the bar above the stack from the
  moment it starts, in its chat too (so it is plain it plays on): the chat (a tap, `go_to_playing`, opens it at the message playing:
  `ChatView.show_message` scrolls there and lights the bubble, class `found`), the time, pause
  (`toggle_sound`), stop. What plays is told to the desktop by MPRIS (`Mpris`:
  `org.mpris.MediaPlayer2.` + `APP_ID` at `/org/mpris/MediaPlayer2`, `DesktopEntry`
  the app id; status, metadata — title, the chat as artist, length — position; PlayPause, Play,
  Pause, Stop, Raise → `go_to_playing`); `mpris.changed()` after every change of what plays. The
  shell shows it on the program's button; the LauncherEntry count has no "playing". Play buttons use theme icons through `set_play(button, "play"|"pause"|"fail")`, whose
  `state` the tests read (⏸ is tiny in most fonts).
  What another messenger carries has no link: its link gives a ref (`is_ref`: `"tg:…"`, never a
  scheme of the web or of files), `Media.how(ref)` says `"own"`, and it is fetched through
  `Media.own` — the window sets it to `Backend.download(ref, path)`, a blocking call from
  Media's worker threads into the account's link (`link.download`) — into the photo cache;
  voice, video and files are played or opened from there once fetched (a voice stopped or
  switched meanwhile does not start late; one that cannot be fetched is told as `on_end`).
- **Files from other programs** (haltia-de/haltia's `docs/plans/share-and-documents.md`;
  haltia_kit.share is the sender). The `.desktop` file has `X-Haltia-Share=true`, the
  `MimeType=` of what MAX takes (concrete types, not `image/*`: validators refuse wildcards)
  and `Exec=haltia-messenger %U`; `Max` is `HANDLES_OPEN` (a second launch hands the files to
  the running one; `--background` is a main option now that `run(sys.argv)` parses them).
  `do_open` → `show_share(paths)`: the `forward` page as «Кому отправить?» (the files named
  above the search, «Отмена» drops them; chats of every messenger, no channels); a chat chosen
  opens with the files as a draft (`attached`), sent by the usual «Отправить». A file is taken
  as the real file it is (`share_ok`: `realpath`, a regular file, never under `DATA`, `CONFIG`,
  the cache, `/proc`, `/sys`, `/dev`) and copied when the chat is chosen into `SHARED` (a
  folder per share, gone after a day), so what is sent is what was chosen. Documents in
  messages are opened only when `openable` (`OPENABLE`: PDF, office, pictures, text — never a
  `.desktop` file or a script; others are saved), and `DOCS` keeps the last `DOCS_KEPT`.
- **Reactions.** Message dicts carry `reactions` ([[emoji, count]]) and `yours`; a long press on a
  bubble (`ChatView`'s `on_hold`) opens `Max.pick_reaction`, a popover of `REACTIONS`.
  `Backend.react` uses `messages.add_reaction`/`remove_reaction`; when MAX answers without counts
  the window counts itself. `on_reaction_update` events carry no own reaction, so `reacted(..., ...)`
  (Ellipsis) leaves `yours` alone. Emoji need `font-noto-emoji` (in the tablet image).
- **A photo, large.** A tap on a photo in a bubble (`GestureMultiPress` on its frame; a
  scroll cancels it, and a release within a second of a long press is ignored, `held_at`) calls
  `ChatView`'s `on_photo(url)` → `Max.show_photo`: the `photo` page, black, within the window —
  not full screen, where the shell's ✕ covered the corner; the header stays with back, «Фото»
  and the save button (`viewer_save`, shown on that page only). `Media.photo(url, done,
  size=2048)` loads it, `fit_photo` scales it to the page on every size. A tap, back or Esc
  (`close_photo`) returns to the chat.
- **Confirmations.** `Max.ask(question, yes)` is the kit's `dialogs.ask` while the setting
  `confirm` (default on, the settings page) is on, else True: saving to a free name (`target`;
  a taken one has the save dialog) and forwarding, after the chat is chosen (a «no» stays on
  the `forward` page). Tests answer it by replacing `bm.dialogs.ask`.
- **Forwarding and saving.** Beside every bubble, at its foot on the side with room (right of
  another's, left of the own, as Telegram has it), a round `mail-forward-symbolic` button
  (`ChatView`'s `on_forward(msg_id)`) opens the `forward` page: chats but no channels,
  searchable; after it the chat forwarded into opens; `Backend.forward` → the link's `forward` (MSG_SEND built by `forward_payload`:
  PyMax 2.4.1's `forward_message` sends the message id as a string, which MAX refuses),
  attachments go with it. Saving is per item: every photo
  (in its corner, and in the viewer's), voice, audio file, video and file has its own
  `document-save-symbolic` button (`ChatView._save_button`, `on_save(msg, item)` →
  `save_message(chat_id, m, [item], button)`; a photo is the item `{"kind": "photo", "url",
  "n"}`); the button is busy till saved (`set_busy`: insensitive, a spinner for its icon); for a
  name taken in the folder the person is asked plainly (`target` → `ask_taken`, the kit's
  `dialogs.choose`: replace it, a numbered copy beside it, or the save dialog); the save dialog
  (`ask_save_path`: another name or folder,
  or replace, the dialog asking first; `Gtk.FileChooserNative`, as is «Папка для файлов»
  (`choose_folder`): the portal's dialog inside Flatpak and under KDE, GTK's own elsewhere,
  where `focus_accept` finds it; the focus starts on Сохранить, not the name entry, so the
  on-screen keyboard stays down over the file list till the name is tapped; cancel saves nothing; `Media.save(…, replace=True)` then writes
  over it, and keeps the old one if the download fails); tests stub `ask_save_path` and `ask_taken`; the
  long-press menu has only the reactions, and a tap on a file opens it (`save_message`: links of videos and
  files asked of MAX first; `Media.save` into `load_text("folder", default_folder())`, set in the
  settings, under `safe_name`, numbered when taken, via `.part`). A forwarded message's text and
  attachments are inside `msg.link.message` (`Backend.carried`); its dict has `forwarded`.
- **Sending attachments.** The paperclip (`clip`, left of the entry) picks files
  (`choose_files`: `FileChooserNative`, several; tests replace it); `attachment(path)` makes
  them what links take — `{"kind": "photo"|"file", "path", "name"}`, a photo by its name
  (`PHOTO_FILES`, what MAX takes as photos), video goes as a file — and they wait in
  `attached`, drawn above the entry (`show_attached`: a small photo or the name, each with its
  ✕). `send()` sends the text with them (`Backend.send(chat, text, files)` → the link's
  `send(chat, text, files)`; PyMaxLink makes PyMax's `Photo`/`File`/`Voice`); what could not be
  sent stays. PyMax 2.4.1's photo and voice uploads fail on today's MAX (its issues #108, #103):
  `PyMaxLink._fix_uploads` puts its own on the client — a photo's token from the answer's one
  entry (`photo_token`: MAX's upload link has no `photoIds` since autumn 2026), a voice as a
  multipart form (`audio/ogg`, no user agent) sent at once by its upload token with a real
  waveform (`voice_wave`: 80 levels 0…127 by ffmpeg as bytes, a string of exactly 80 characters in the frame — MAX answers «Invalid media wave length» else; flat without ffmpeg), and an upload's
  error read from a 200's body. Both checked against the official Linux app's own log
  (`~/.local/share/ONEME/logs`: it logs every request and answer, tokens masked); `send` sends again, uploaded anew, while MAX answers
  `…not.ready` (`VOICE_TRIES`, `VOICE_PAUSE`). Recorders make Opus 48 kHz mono, which MAX checks.
  Drop these when a PyMax release fixes them. The microphone shows only with `voice` on (the setting «Голосовые сообщения», on by
  default; `voice_on`). A voice message: the microphone button held (`GestureMultiPress` pressed /
  released; `record_start`/`record_stop`) records by `Recorder` — `RECORDERS`' first on `PATH`:
  ffmpeg from pulse to Ogg/Opus (in the tablet's image), gst-launch, parecord's Ogg/Vorbis;
  stopped by SIGINT so the file is finished, in a thread — into `PHOTOS/voice-*.ogg`, sent as
  `{"kind": "voice", "duration": ms}` and removed; shorter than `SHORTEST` is not sent.
  `Max(recorder=…)` takes a recorder with fake hands (`popen`, `which`) in tests.
- **No keyboard on entering a chat.** `open()` focuses nothing (`win.set_focus(None)`): the
  on-screen keyboard comes when the entry is tapped, never over a channel (no entry there).
- **Emoji in messages.** The «😊» toggle left of the entry opens a non-modal popover (`EMOJI`
  groups, the recent ones first from `EMOJI_RECENT`, `emoji.json`); a tap inserts at the cursor
  (`put_emoji`). Non-modal on purpose: the entry keeps the focus, so the on-screen keyboard
  stays; every button in it is `can_focus=False`. It closes on send and when the chat is left.
- **Renaming** a dialog's person is local (`ALIASES`, `names.json`): PyMax's contact actions are only
  ADD/REMOVE. `Backend.name()` prefers the alias; don't invent a server request for it.
- **Photo fetch is a security boundary.** Photo URLs arrive inside messages (sender-controlled), so
  `photo_ok` allows only `https` on `oneme.ru`/`max.ru` hosts, and `PhotoRedirect` refuses
  redirects off those hosts. Preserve both checks when touching photo loading.
- **No shell.** Nothing of the Haltia shell is used (ADR 0001 in haltia-de/haltia): no
  `b8k_ui`, no `apps.d`, no buzzing (the shell's touch guard buzzes every touch), no header
  CSS (the desktop's GTK theme, the shell's on the tablet, gives the header and the large buttons; `CSS`
  styles only the program's own content). The desktop is met through standards: the unread count
  (loud chats) as `com.canonical.Unity.LauncherEntry` `Update` on the session bus (`Max.badge`);
  a new message in a loud chat as a desktop notification (`Max.notify`, `Gio.Notification`, its
  tap the `app.open-chat` action; the desktop buzzes or sounds for it — the `buzz` setting
  switches these); the start with the session as XDG autostart (`--background`; with no
  graphical session the program exits at once and quietly), inside Flatpak (`FLATPAK`:
  `/.flatpak-info`) the Background portal instead (`ask_background` at every start:
  `RequestBackground` with `autostart` and that command line; the portal asks once). No path
  of the shell or of a distribution is needed: `DATA`, `PHOTOS`, `CONFIG` and `BASES` come
  from GLib's XDG dirs, never `~` (inside Flatpak they are `~/.var/app/APP_ID/…`; tests set
  `XDG_*_HOME` in their temporary home), PyMax's folders are looked in only if there,
  else site-packages (`requirements.txt`, exact versions, for a Flatpak), and the video
  player is `haltia-vplay` if on `PATH`, else `mpv`. Shared code is `haltia-kit`:
  `Settings("messenger", CONFIG)` (an ini, yes/no), `awake.Awake` while a voice plays, `photos.pixbuf_of`
  (size checked before decoding) for photos. Voice keeps its own libmpv (`Libmpv`): the kit's
  `Player` takes no user agent, which MAX's CDN wants.

## Conventions

- Domain terms (chat view, chat list, chat summary, message cache, known people) are in
  `CONTEXT.md`; name new modules after them.
- UI text is Russian; code comments, docstrings and commit messages are English. The README is
  Russian.
- Large, calm type for an older person is the point (no «крупно» in names, ADR 0004): font and
  widget sizes live in the `CSS` block at the top of `haltia-messenger`.
- Commit subjects are full sentences ending with a period (older ones carry a `b8k-max:` prefix
  from the monorepo days).
- `.gitattributes` forces LF for `*.sh`, `*.py` and `haltia-*`.
- This is an unofficial client (see the README's disclaimer): call it "a client for MAX", keep the
  icon free of MAX's logo or wordmark, and don't add bulk-sending, scraping or other automation
  features — MAX's terms (legal.max.ru/ps, 4.3.7, 4.3.10) forbid them and it blocks such clients.

## Tests

`sh tests/run.sh` makes `.cache/venv` once (system PyGObject plus the PyMax wheel `install.sh`
pins, haltia-kit 2.2.0 from GitHub, or `HALTIA_KIT=path/to/checkout`, and Telethon 1.43.2), starts a `broadwayd` of its own for each script (one takes no second program) and runs plain scripts with `assert`s, each printing
«… ok» per part: `tests/test_chatlist.py` (the chat list's rules: no MAX, no window),
`tests/test_media.py` (Media with fake hands: hosts, the header, redirects, cache, players),
`tests/test_backend.py` (Backend on the fake link, no window), `tests/test_cache_retention.py`
(proposed message-cache retention on a scratch tree, issue #86), `tests/test_window.py` (the real
window and Backend on the fake link) and `tests/test_login.py` (the sign-in: the first start,
the cards, switching off, the logout, a closed keyring, a second fake as Telegram with its cloud
password; the fake's `kept`, `scan()`, `refuse`, `password`, `split`). `test_backend.py` checks
`tg_message`/`tg_chat` on Telethon's own types and `TelethonLink` on a stand-in client (no
Telegram). Tests build MAX's state in `FakeLink` (people, dialogs,
groups, channels, messages with attachments and reactions), drive the window as a person would,
and check what it shows (widget trees: rows, `ChatView.widget`) and what was asked of MAX
(`fake.asked(...)`), not private attributes. `HALTIA_SHOTS=dir` saves screenshots. `tests/demo.py`
opens the window on made-up chats.
