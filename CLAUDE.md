# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`haltia-messenger` («Сообщения» on the screen) is a native GTK 3 client for the MAX messenger,
a program of the Haltia desktop (github.com/haltia-de), a desktop program of its own:
`io.github.haltia_de.Messenger` (`APP_ID`: the GApplication id, the `.desktop` file, the Wayland
app id via `GLib.set_prgname` before GTK is imported, the icon, AppStream, MPRIS, LauncherEntry).
Made for the tablet of [device-lenovo-b8000h](https://github.com/haltia-de/device-lenovo-b8000h)
(Lenovo YOGA Tablet 10 B8000-H, Alpine), whose image installs it from here by tag, but it depends
on no shell: per that repo's ADR 0001 it meets the shell only through freedesktop standards, and
its shared code is `haltia-kit` 2. The whole program is one Python 3 script, `haltia-messenger`
(no `.py` extension).

Until 2.0 it was `b8k-max`, `io.github.trudenboy.Max` (the rename: ADR 0004 and
`docs/migration-haltia.md` «Правила фазы C» in device-lenovo-b8000h). Till 3.0 these stay: the
`b8k-max` command as a link, the old `.desktop` file with `NoDisplay=true`, `provides`/`replaces`
of `b8k-max` in the APKBUILD, `X-Flatpak-RenamedFrom` and AppStream `<replaces>`, and
`move_old_home()` at the first start: the kit's `paths.migrate_dirs("b8k-max", …)` moves the
folders (leaving links), and `~/.config/b8k/max.conf` `[max]` (`OLD_CONF`) becomes
`~/.config/haltia/messenger.conf` `[messenger]`; so does `~/.config/haltia/max.conf` (`KIT_CONF`),
where the kit's `Settings("max")` in another program (the shell) may have moved it first — that
one is left in place. The name on the screen is by what it is, not the
service: MAX is a trademark (ADR 0004, rule 7); «MAX» stays in `GenericName`/`Keywords`.

There is no build step or linter config; the tests are in `tests/` (see Tests). GPL-2.0; every
source file starts with an `SPDX-License-Identifier: GPL-2.0` line.

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
optionally `py3-mpv mpv-libs` (voice) and `font-noto-emoji`; `wget`/`unzip`/`sha256sum` for
`install.sh`. `install.sh [ROOT] [PREFIX]` installs the script to `PREFIX/bin` (and the `b8k-max`
link), `data/` (the
`.desktop` file with `X-B8K-Home`/`X-B8K-Replaces=max`, the hicolor SVG icon, AppStream metainfo)
to `PREFIX/share` (and the old id's hidden `.desktop`), the XDG autostart file (`--background`, `X-B8K-Autostart`) to
`ROOT/etc/xdg/autostart`, downloads the pinned PyMax wheel (`maxapi_python-2.4.1`, sha256 checked;
cached in `$HALTIA_CACHE`, default `.cache/`) into `PREFIX/lib/haltia-messenger`, and removes
what `b8k-max` put under that prefix and the shell's old `apps.d/max.conf`. The script looks for
PyMax in `/usr/local/lib/haltia-messenger`, `/usr/lib/haltia-messenger` and
`../lib/haltia-messenger` from itself. Bumping PyMax: the wheel name and sha256 in `install.sh` (and the
APKBUILD's `_whl`).

Releases (ADR 0002 in device-lenovo-b8000h): SemVer, always `vX.Y.Z` — X incompatible (commands,
file formats, `X-B8K-…` keys), Y features, Z fixes and packaging-only changes. The tag must equal
`pkgver` in `packaging/alpine/APKBUILD` (`pkgrel=0`) and the newest `<release version>` in
`data/*.metainfo.xml`; CI fails otherwise. From 2.1.2 on every `<release>` has a short Russian
`<description>` (`<p>` or `<ul><li>`) of what the person will notice: the shell's updater shows it
as «Что нового» before installing. Pushing the tag runs `.github/workflows/release.yml`
(haltia-de/ci's `apk.yml`; the APKBUILD's `builddir` is GitHub's tarball folder, named
after the repository): a signed noarch Alpine 3.24 package (`abuild`, `options="net"`
for the PyMax wheel in `source=`) in the GitHub release. Push the commit first and the tag in a
push of its own — a tag pushed with the commit that adds the workflow did not start it. The
tablet's image installs that apk by a lock file; packages install under PREFIX `/usr`, so other
programs are found on `PATH` (`haltia-vplay`, `b8k-vplay` before 2.0: `shutil.which`), never at `/usr/local/bin`.

## Architecture

- **Two threads.** `Backend` runs in its own thread with its own asyncio loop. The GTK side calls
  into it only through `Backend.run(coro, done)`; results and events come back to GTK only via
  `GLib.idle_add`. Keep this rule: never touch GTK widgets from the MAX thread, never await the
  link from the GTK thread.
- **The link to MAX** (`PyMaxLink`, CONTEXT.md «Связь с MAX»). Every request to MAX and every
  event from it goes through one link object: `run(events)`, `chats_page`, `chats`, `users`,
  `history`, `read`, `send`, `find_phone`, `add_contact`, `link_info`, `join`, `leave`, `delete`
  (only for this account: it cannot delete for all), `react`, `media_url`, `invites`, `log`.
  It hands out PyMax's own objects (`Chat`, `Message`, `User`, `ReactionInfo`) and keeps PyMax's
  internals (`client._app`, raw opcodes `LINK_INFO`/`LOG`/`CONFIG`) to itself: Backend never
  touches `client._app` or calls methods on PyMax objects. Events go to `Backend.on_qr`,
  `on_login`, `on_message`, `on_reaction`, `on_delete`. Deletions are read from the frames
  themselves (`_watch_deletions`, set once at the login, wraps PyMax's `dispatcher.dispatch`;
  `_peek`: `NOTIF_MSG_DELETE`, or a `NOTIF_MESSAGE` with status `REMOVED`, which PyMax 2.4.1
  loses); `Backend.on_delete` takes them out of the cache (`cache_forget`) and the window
  (`ChatView.remove`, day labels left empty go too) and renews the chat's last message. Messages
  deleted while away go when a fetched page no longer has them (`history`, `ChatView.newest`). `tests/fake_link.py` is the second link (a small MAX
  in memory); `Max(link=...)`/`Backend(ui, link)` take one. A PyMax upgrade is checked in
  `PyMaxLink` only. Don't name a fake's attributes after link operations (`chats`, `users`).
- **Login.** `PyMaxLink` is PyMax's QR provider; `Backend.on_qr` renders the QR code to scan with
  MAX on a phone. The session lives in `~/.local/share/haltia-messenger/web.db` (chmod 600).
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
  `chats.join_channel`), else filters the own chats by title. A dialog opened from the search
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
  launch just activates the first process over D-Bus. Closing the window hides it. With
  `--background` the window is not shown at start.
- **Caches.** `~/.cache/haltia-messenger/chats/<id>.json` keeps the last `KEEP` messages per chat and
  `list.json` the chat list (all mode 600, written atomically via `.new` + `os.replace`). A chat whose
  `last_message` is already cached and has no unread opens with no history request at all; else
  the last `PAGE` are fetched (see Paging). The last `VIEWS` chat views stay built in memory. The chat list
  keeps one row per chat (`Max.rows`, sorted and filtered by GTK) and `fill_list` redraws only rows
  whose look changed — don't go back to rebuilding it (≈30× slower per message). Photos are cached
  in `~/.cache/haltia-messenger/` by URL hash, touched when shown, pruned after `PHOTO_DAYS` unshown (at
  start and daily). Small state files in `DATA` go through `load_json`/`save_json` (600, atomic).
- **Chat list** (`ChatList`, CONTEXT.md «Список чатов»; no GTK). Owns the summaries, dialogs from
  the search not written to yet (`start_dialog`/`wrote`), pins and per-chat notifications (`PREFS`,
  `chats.json`; local — PyMax has no pin/mute request, `CHAT_PERSONAL_CONFIG` is bare), the
  `contacts_only` value, and the last list (`LIST`, `list.json`, shown at once on the next start).
  It answers `entries(tab)` (ordered `(summary, pinned, quiet)`: pinned first in pin order, then the
  newest; strangers hidden), `counts()` (per tab, and `loud` for the subtitle and the panel's
  button), `loud(chat)` (buzz?), `hidden`, `find`, `get`, `listed`. Channels are quiet unless
  switched on, others loud unless switched off. Keep these rules there; `Max` only draws them: one
  kept row per chat, redrawn when its `look(entry)` changes, ordered and filtered by `positions` from
  `entries(Max.tab)`. A long press on the list (`row_menu`, one gesture on the ListBox,
  `get_row_at_y`) opens the pin/notification menu; `held` stops the release from opening the chat.
- **Chat view** (`ChatView`, see `CONTEXT.md`). One chat on screen is one deep module: its own
  scroll area (`.widget`, an Overlay over the ScrolledWindow with the round «↓» button that shows
  away from the newest message and counts those come meanwhile), the bubbles, day labels, reactions and media controls, the build
  queue (`FIRST` at once, then `STEP` per idle, nothing above while the reader scrolled within
  `SETTLE`), older pages (`fetch_older` as the reader nears the top, `PREFETCH` in the background,
  a spinner while one comes), the place (`anchor`; the first `enter()` goes to the bottom, later
  ones stay; the own message scrolls down, another's only if already there), photos loaded only
  near the screen, and `leave()` cutting it to `BUBBLES`. Its interface is `newest(msgs, gap,
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
  (`PhotoRedirect`). It caches photos (`photo(url, done)`, touched when shown, `prune()` after
  `PHOTO_DAYS` unshown), plays voice through libmpv (`voice`/`toggle`/`stop`, `on_time`/`on_end`;
  an `end-file` with reason ABORTED is a stop or a switch, not an end), starts a video in
  `haltia-vplay` (`b8k-vplay` before 2.0; on `PATH`, Видео's package) or `mpv --fs` with `ytdl=no` and `load-unsafe-playlists=no` (`video(url, title)`), and
  gives a file to the browser (`file(url)`). What fails goes to `~/.cache/haltia-messenger/player.log`
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
  "n"}`); the button is busy till saved (`set_busy`: insensitive, a spinner for its icon); a name
  taken in the folder opens the save dialog (`target` → `ask_save_path`: another name or folder,
  or replace, the dialog asking first; `Gtk.FileChooserNative`, as is «Папка для файлов»
  (`choose_folder`): the portal's dialog inside Flatpak and under KDE, GTK's own elsewhere,
  where `focus_accept` finds it; the focus starts on Сохранить, not the name entry, so the
  on-screen keyboard stays down over the file list till the name is tapped; cancel saves nothing; `Media.save(…, replace=True)` then writes
  over it, and keeps the old one if the download fails); tests stub `ask_save_path`; the
  long-press menu has only the reactions, and a tap on a file opens it (`save_message`: links of videos and
  files asked of MAX first; `Media.save` into `load_text("folder", default_folder())`, set in the
  settings, under `safe_name`, numbered when taken, via `.part`). A forwarded message's text and
  attachments are inside `msg.link.message` (`Backend.carried`); its dict has `forwarded`.
- **Emoji in messages.** The «😊» toggle left of the entry opens a non-modal popover (`EMOJI`
  groups, the recent ones first from `EMOJI_RECENT`, `emoji.json`); a tap inserts at the cursor
  (`put_emoji`). Non-modal on purpose: the entry keeps the focus, so the on-screen keyboard
  stays; every button in it is `can_focus=False`. It closes on send and when the chat is left.
- **Renaming** a dialog's person is local (`ALIASES`, `names.json`): PyMax's contact actions are only
  ADD/REMOVE. `Backend.name()` prefers the alias; don't invent a server request for it.
- **Photo fetch is a security boundary.** Photo URLs arrive inside messages (sender-controlled), so
  `photo_ok` allows only `https` on `oneme.ru`/`max.ru` hosts, and `PhotoRedirect` refuses
  redirects off those hosts. Preserve both checks when touching photo loading.
- **No shell.** Nothing of the Haltia shell is used (ADR 0001 in device-lenovo-b8000h): no
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
  of the shell or of a distribution is needed: PyMax's folders are looked in only if there,
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
pins, and haltia-kit 2.1.0 from GitHub, or `HALTIA_KIT=path/to/checkout`), starts a `broadwayd` of its own and runs four plain scripts with `assert`s, each printing
«… ok» per part: `tests/test_chatlist.py` (the chat list's rules: no MAX, no window),
`tests/test_media.py` (Media with fake hands: hosts, the header, redirects, cache, players),
`tests/test_backend.py` (Backend on the fake link, no window) and `tests/test_window.py` (the real
window and Backend on the fake link). Tests build MAX's state in `FakeLink` (people, dialogs,
groups, channels, messages with attachments and reactions), drive the window as a person would,
and check what it shows (widget trees: rows, `ChatView.widget`) and what was asked of MAX
(`fake.asked(...)`), not private attributes. `HALTIA_SHOTS=dir` saves screenshots. `tests/demo.py`
opens the window on made-up chats.
