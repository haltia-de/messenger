# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`b8k-max` is a native GTK 3 client for the MAX messenger, written for the tablet shell of
[lenovo-b8000h-linux](https://github.com/trudenboy/lenovo-b8000h-linux) (Lenovo YOGA Tablet 10
B8000-H, Alpine). The whole program is one Python 3 script, `b8k-max` (no `.py` extension). It
was split out of the lenovo-b8000h-linux repo; that repo's image build installs it from here by tag.

There is no build step or linter config; the tests are in `tests/` (see Tests). GPL-2.0; every
source file starts with an `SPDX-License-Identifier: GPL-2.0` line.

## Commands

```sh
sh install.sh            # install into / (root needed)
sh install.sh /mnt/root  # install into another root, e.g. while building an image
b8k-max                  # run with a window
b8k-max --background     # start hidden (what b8k-launcher does at session start)
python3 -m py_compile b8k-max   # quick syntax check
sh tests/run.sh                 # all tests (needs broadwayd and network once, for the venv)
sh tests/run.sh test_backend.py # one of them
.cache/venv/bin/python tests/demo.py   # the window on made-up chats, no account
```

Runtime deps (Alpine): `apk add python3 py3-gobject3 gtk+3.0` (optional: `py3-mpv mpv-libs` for voice
messages, `font-noto-emoji` for reactions; the tablet image has them), plus `wget`/`unzip`/`sha256sum`
for `install.sh`. `install.sh` downloads the pinned PyMax wheel (`maxapi_python-2.4.1`), checks
its sha256 and unpacks it into `/usr/local/lib/b8k-max`; the download is cached in `$B8K_CACHE`
(default `.cache/` here, git-ignored). Bumping PyMax means changing both the wheel name and the
sha256 in `install.sh`. The script does `sys.path.insert(0, "/usr/local/lib/b8k-max")`, so running
it from the checkout still needs PyMax installed there.

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
  `on_login`, `on_message`, `on_reaction`. `tests/fake_link.py` is the second link (a small MAX
  in memory); `Max(link=...)`/`Backend(ui, link)` take one. A PyMax upgrade is checked in
  `PyMaxLink` only. Don't name a fake's attributes after link operations (`chats`, `users`).
- **Login.** `PyMaxLink` is PyMax's QR provider; `Backend.on_qr` renders the QR code to scan with
  MAX on a phone. The session lives in `~/.local/share/b8k-max/web.db` (chmod 600).
- **Telemetry.** PyMax's own (a random simulation of browsing) stays off in `ExtraConfig`. The
  `Telemetry` class sends MAX-app-style events built from real UI actions instead: `NAV GO` on
  every screen change (`moved()`, driven by the stack page and window map/unmap), `PERF login`
  after each login, `PERF open_chat_to_render` with measured times. Event shapes and fixed values
  copy PyMax 2.4.1's `pymax/telemetry/payloads.py`; sent in batches via `Opcode.LOG` through
  `Backend.log` and the link. On by default, switched in the settings page (gear), stored in
  `~/.config/b8k/max.conf` (`[max] telemetry`; `buzz` there switches the buzz on new messages,
  not on button taps; `contacts_only`, see below). Re-check the shapes when bumping PyMax.
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
  `~/.local/share/b8k-max/known.json`, 600) holds login contacts, contacts added here, people
  written to here (`remember`), and on the very first run every existing dialog's peer — the
  login sends only changed contacts after the first one, and nobody known must go quiet on update.
- **Chat invites.** MAX's own privacy setting `CHATS_INVITE` is shown, not changed: MAX answers
  `account.change_profile_settings` from a web client with `errors.safe.mode.protected.change.disabled`
  ("update the app"; the account has `SAFE_MODE`). PyMax keeps only the hash of the login answer's
  `config`, so `PyMaxLink._watch_login` wraps `app.invoke` and keeps `config.user` of each
  `Opcode.LOGIN` answer; `link.invites()` gives `CHATS_INVITE`, and the settings card shows it on a
  greyed switch with a hint that only MAX's official app changes it.
- **Single instance, background life.** `Max` is a `Gtk.Application` with id `b8k.Max`; a second
  launch just activates the first process over D-Bus. Closing the window hides it. With
  `--background` the window is not shown at start.
- **Caches.** `~/.cache/b8k-max/chats/<id>.json` keeps the last `KEEP` messages per chat and
  `list.json` the chat list (all mode 600, written atomically via `.new` + `os.replace`). A chat whose
  `last_message` is already cached and has no unread opens with no history request at all; else
  the last `PAGE` are fetched (see Paging). The last `VIEWS` chat views stay built in memory. The chat list
  keeps one row per chat (`Max.rows`, sorted and filtered by GTK) and `fill_list` redraws only rows
  whose look changed — don't go back to rebuilding it (≈30× slower per message). Photos are cached
  in `~/.cache/b8k-max/` by URL hash, touched when shown, pruned after `PHOTO_DAYS` unshown (at
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
  `b8k-vplay`/`mpv --fs` with `ytdl=no` and `load-unsafe-playlists=no` (`video(url, title)`), and
  gives a file to the browser (`file(url)`). What fails goes to `~/.cache/b8k-max/player.log`
  (600, host and path only; the players' own output too). Its hands come in at creation —
  `spawn`, `open_uri`, `fetch`, `player` — real by default, `tests/fake_hands.py` in tests.
  `media_of` turns AUDIO/VIDEO/FILE attachments into `media` items; a FILE named like audio
  (`AUDIO_FILES`: .mp3, .m4a, .ogg…) becomes an `audio` item with `url` None and its `file` id:
  `Max.media_tapped` asks its link of MAX on ▶, then plays it like a voice message (its length
  comes from libmpv: `on_time(sec, total)`); the link for a video or a
  file comes from `Backend.media_url` (never an `external` one). This is a security boundary:
  links come inside messages; keep the host list tight. What plays and where its button is stays
  with `Max` (`playing`); a voice message stops when its button is destroyed.
- **Reactions.** Message dicts carry `reactions` ([[emoji, count]]) and `yours`; a long press on a
  bubble (`ChatView`'s `on_hold`) opens `Max.pick_reaction`, a popover of `REACTIONS`.
  `Backend.react` uses `messages.add_reaction`/`remove_reaction`; when MAX answers without counts
  the window counts itself. `on_reaction_update` events carry no own reaction, so `reacted(..., ...)`
  (Ellipsis) leaves `yours` alone. Emoji need `font-noto-emoji` (in the tablet image).
- **Forwarding and saving.** A long press on a message (`pick_reaction`) offers, under the
  reactions, «↪ Переслать» (the `forward` page: chats but no channels, searchable; then
  `Backend.forward` → the link's `forward`, MAX's own `forward_message`, attachments go with it)
  and «💾 Сохранить на планшет» (`save_message`: every photo and media item, files of any
  type; a tap on a file offers «Открыть»/«Сохранить» for it alone, `save_message(…, [item])`; links of videos and
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
- **Optional shell module.** If `/usr/local/share/b8k/python/b8k_ui.py` exists, the program uses
  `b8k_ui.Buzz` (haptic buzz on every `Gtk.Button` "pressed"), `b8k_ui.HEADER_CSS` and
  `b8k_ui.badge("max", n)` (unread count of dialogs and groups, channels excluded, on the panel
  button). Without it (`b8k_ui = None`) the program must still run on any GTK 3 desktop — guard
  every `b8k_ui` use.
- **Shell integration files.** `max.conf` is installed to `/usr/local/share/b8k/apps.d/max.conf`
  and registers the panel button (`signal = 7`, `app_ids` must match the application id);
  `max.png` is its icon.

## Conventions

- Domain terms (chat view, chat list, chat summary, message cache, known people) are in
  `CONTEXT.md`; name new modules after them.
- UI text is Russian; code comments, docstrings and commit messages are English. The README is
  Russian.
- Large type is the point ("MAX in large type"): font and widget sizes live in the `CSS` block at
  the top of `b8k-max`.
- Commit subjects are full sentences ending with a period (older ones carry a `b8k-max:` prefix
  from the monorepo days).
- `.gitattributes` forces LF for `*.sh`, `*.py` and `b8k-*`.
- This is an unofficial client (see the README's disclaimer): call it "a client for MAX", keep the
  icon free of MAX's logo or wordmark, and don't add bulk-sending, scraping or other automation
  features — MAX's terms (legal.max.ru/ps, 4.3.7, 4.3.10) forbid them and it blocks such clients.

## Tests

`sh tests/run.sh` makes `.cache/venv` once (system PyGObject plus the PyMax wheel `install.sh`
pins), starts a `broadwayd` of its own and runs four plain scripts with `assert`s, each printing
«… ok» per part: `tests/test_chatlist.py` (the chat list's rules: no MAX, no window),
`tests/test_media.py` (Media with fake hands: hosts, the header, redirects, cache, players),
`tests/test_backend.py` (Backend on the fake link, no window) and `tests/test_window.py` (the real
window and Backend on the fake link). Tests build MAX's state in `FakeLink` (people, dialogs,
groups, channels, messages with attachments and reactions), drive the window as a person would,
and check what it shows (widget trees: rows, `ChatView.widget`) and what was asked of MAX
(`fake.asked(...)`), not private attributes. `B8K_SHOTS=dir` saves screenshots. `tests/demo.py`
opens the window on made-up chats.
