# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`b8k-max` is a native GTK 3 client for the MAX messenger, written for the tablet shell of
[lenovo-b8000h-linux](https://github.com/trudenboy/lenovo-b8000h-linux) (Lenovo YOGA Tablet 10
B8000-H, Alpine). The whole program is one Python 3 script, `b8k-max` (no `.py` extension). It
was split out of the lenovo-b8000h-linux repo; that repo's image build installs it from here by tag.

There is no build step, test suite or linter config. GPL-2.0; every source file starts with an
`SPDX-License-Identifier: GPL-2.0` line.

## Commands

```sh
sh install.sh            # install into / (root needed)
sh install.sh /mnt/root  # install into another root, e.g. while building an image
b8k-max                  # run with a window
b8k-max --background     # start hidden (what b8k-launcher does at session start)
python3 -m py_compile b8k-max   # quick syntax check
```

Runtime deps (Alpine): `apk add python3 py3-gobject3 gtk+3.0` (optional: `py3-mpv mpv-libs` for voice
messages, `font-noto-emoji` for reactions; the tablet image has them), plus `wget`/`unzip`/`sha256sum`
for `install.sh`. `install.sh` downloads the pinned PyMax wheel (`maxapi_python-2.4.1`), checks
its sha256 and unpacks it into `/usr/local/lib/b8k-max`; the download is cached in `$B8K_CACHE`
(default `.cache/` here, git-ignored). Bumping PyMax means changing both the wheel name and the
sha256 in `install.sh`. The script does `sys.path.insert(0, "/usr/local/lib/b8k-max")`, so running
it from the checkout still needs PyMax installed there.

## Architecture

- **Two threads.** `Backend` runs PyMax's `WebClient` (MAX's web protocol over a WebSocket, no
  web engine) in its own thread with its own asyncio loop. The GTK side calls into it only through
  `Backend.run(coro, done)`; results and events come back to GTK only via `GLib.idle_add`. Keep
  this rule: never touch GTK widgets from the MAX thread, never await PyMax from the GTK thread.
  Some calls reach into PyMax internals (`client._app.api.chats.fetch_chats`, `...users.get_users`),
  so a PyMax upgrade can break them.
- **Login.** `Backend` is PyMax's QR provider (`show_qr`): the first start renders a QR code to
  scan with MAX on a phone. The session lives in `~/.local/share/b8k-max/web.db` (chmod 600).
- **Telemetry.** PyMax's own (a random simulation of browsing) stays off in `ExtraConfig`. The
  `Telemetry` class sends MAX-app-style events built from real UI actions instead: `NAV GO` on
  every screen change (`moved()`, driven by the stack page and window map/unmap), `PERF login`
  after each login, `PERF open_chat_to_render` with measured times. Event shapes and fixed values
  copy PyMax 2.4.1's `pymax/telemetry/payloads.py`; sent in batches via `Opcode.LOG` through
  `Backend.log`. On by default, switched in the settings page (gear), stored in
  `~/.config/b8k/max.conf` (`[max] telemetry`; `buzz` there switches the buzz on new messages,
  not on button taps; `contacts_only` and `invites`, see below). Re-check the shapes when bumping PyMax.
- **Search, join, delete.** The `find` page (magnifier on the list) reads its entry with
  `phone_of` (a person: `users.search_by_phone`, then write or `users.add_contact`), `link_of`
  (a channel or group: `LINK_INFO` invoked directly so public `max.ru/name` links work too, then
  `chats.join_channel`), else filters the own chats by title. A dialog opened from the search
  waits in `Max.pending` (chat id = own id XOR theirs, as PyMax numbers dialogs) until its first
  message. The bin on a chat asks on the page (`confirm` bar), then `Backend.remove`: a dialog
  is deleted, a group or channel left, always `for_all=False` — never for the others in it.
  A message from a chat not in the list fetches it (`Backend.chat`).
- **Contacts only.** MAX has no "who may write to me" setting, so `contacts_only` (on by default)
  is a filter here: summaries carry `peer` and `stranger`, and `Max.hidden()` keeps strangers'
  dialogs off the list, the local search, the badge and the buzz. `Backend.known` (persisted to
  `~/.local/share/b8k-max/known.json`, 600) holds login contacts, contacts added here, people
  written to here (`remember`), and on the very first run every existing dialog's peer — the
  login sends only changed contacts after the first one, and nobody known must go quiet on update.
- **Chat invites.** `invites` (on by default) is MAX's own privacy setting `CHATS_INVITE`, set
  through `account.change_profile_settings`. `Backend.set_invites` sends it when switched, and at
  login only if `~/.local/share/b8k-max/invites.json` (account id -> value last taken) differs —
  so it is not re-sent on every login and a change made on the phone is not overridden.
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
- **Tabs, pins, notifications.** The list's filter func shows one tab (`Max.tab`: chats or
  channels); its sort func puts `pinned` first, in pin order. Notifications (buzz, badge) are per
  chat: `is_muted` is true for channels unless in `unmuted`, for others if in `muted`. All kept in
  `PREFS` (`chats.json`), locally — PyMax has no pin/mute request (`CHAT_PERSONAL_CONFIG` is bare).
  A long press on the list (`row_menu`, one gesture on the ListBox, `get_row_at_y`) opens the menu;
  `held` stops the release from opening the chat. `look()` must include whatever a row shows.
- **Chat view** (`ChatView`, see `CONTEXT.md`). One chat on screen is one deep module: its own
  ScrolledWindow (`.widget`), the bubbles, day labels, reactions and media controls, the build
  queue (`FIRST` at once, then `STEP` per idle, nothing above while the reader scrolled within
  `SETTLE`), older pages (`fetch_older` as the reader nears the top, `PREFETCH` in the background,
  a spinner while one comes), the place (`anchor`; the first `enter()` goes to the bottom, later
  ones stay; the own message scrolls down, another's only if already there), photos loaded only
  near the screen, and `leave()` cutting it to `BUBBLES`. Its interface is `newest(msgs, gap,
  done)`, `add`, `reacted`, `message`, `enter`/`leave`/`destroy`, `empty`; what it needs comes in at
  creation (cached messages and `fetch_older`/`on_hold`/`on_media`/`on_react`). `Max` only keeps
  up to `VIEWS` of them, puts the open one's widget on the chat page and answers the callbacks.
  Keep chat-screen behaviour inside it, and test it through that interface (its widget tree).
  `Backend.history` returns the newest `PAGE` and whether they leave a gap after the cache;
  `older(chat, before)` returns the page before.
- **Media.** `media_of` turns AUDIO/VIDEO/FILE attachments into `media` items. Voice plays in the
  bubble through `Sound` (libmpv, `video=False`; an `end-file` with reason ABORTED is a stop or a
  switch, not an end). Video and files get a link from `Backend.media_url`
  (`get_video_by_id`/`get_file_by_id`), checked by `media_ok` (https on `MEDIA_HOSTS` only: MAX's hosts
  and its CDNs `okcdn.ru`/`mycdn.me`; `photo_ok` is the same check), then `b8k-vplay`/`mpv --fs`
  with `ytdl=no` and `load-unsafe-playlists=no`, or the browser. An `external` video link is never
  followed. This is a security boundary like the photo one: links come inside messages; keep the
  host list tight. Photos, voice and video are asked for as web.max.ru asks (`AGENT`, PyMax's
  browser user agent, set at login; `Referer`/`Origin` `WEB`). What fails goes to
  `~/.cache/b8k-max/player.log` (600, host and path only; the players' own output too). Thumbnails go through `photo_ok` like photos.
  A voice message stops when its button is destroyed (its chat cut or deleted).
- **Reactions.** Message dicts carry `reactions` ([[emoji, count]]) and `yours`; a long press on a
  bubble (`ChatView`'s `on_hold`) opens `Max.pick_reaction`, a popover of `REACTIONS`.
  `Backend.react` uses `messages.add_reaction`/`remove_reaction`; when MAX answers without counts
  the window counts itself. `on_reaction_update` events carry no own reaction, so `reacted(..., ...)`
  (Ellipsis) leaves `yours` alone. Emoji need `font-noto-emoji` (in the tablet image).
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
