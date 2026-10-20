# Сообщения (haltia-messenger): the terms

The words this program's code and reviews use for what it deals with. Each
line: the term, its name in the code, what it is.

- **Связь с MAX** (MAX link, `PyMaxLink`; `FakeLink` in tests): every request
  to MAX and every event from it, in the link's own Person, Chat and Message;
  nothing above it knows PyMax.
- **Связь с Telegram** (Telegram link, `TelethonLink`): the same for
  Telegram through Telethon; its ids are `"tg:…"` strings, and what its
  messages carry it fetches itself (refs, not links).
- **Аккаунт** (Account, `Account`; all of them in `Backend.accounts`): the
  person's account in one messenger (MAX, Telegram) on top of its
  link: its chats, names, known people and names given here; requests go to
  it by the ids it owns.
- **Медиа** (Media, `Media`): fetching and playing what messages carry —
  photos, previews, voice, video, files — and how MAX's CDNs are reached.
- **Окно чата** (Chat view, `ChatView`): one chat on screen, with its
  bubbles, day labels, reactions, media controls, older pages and place.
  Built per chat, kept for the last `VIEWS` chats.
- **Список чатов** (Chat list, `ChatList`; drawn by `Max` in a ListBox): the
  chats on the first page, in two tabs (chats, channels), pinned first, with
  the rules of who is shown, who buzzes and what is counted.
- **Сводка чата** (Chat summary, a dict from `Backend.summary`): what the
  list shows of a chat: title, type, last message, time, unread, peer,
  stranger.
- **Кэш сообщений** (Message cache, `MessageCache`, `Backend.cache`; files in `~/.cache/haltia-messenger/chats`):
  the newest `KEEP` messages of each chat on disk, so a chat opens at once.
- **Свои люди** (Known people, `Backend.known`, `known.json`): contacts,
  people written to here, and those already in a dialog the first time;
  dialogs of others are hidden while «только от контактов» is on.
- **Порция** (Page, `PAGE`): the messages one history request brings; the
  newest when a chat opens, older ones as the reader scrolls up.
