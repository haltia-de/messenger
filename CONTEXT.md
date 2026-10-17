# b8k-max: the terms

The words this program's code and reviews use for what it deals with. Each
line: the term, its name in the code, what it is.

- **Окно чата** (Chat view, `ChatView`): one chat on screen, with its
  bubbles, day labels, reactions, media controls, older pages and place.
  Built per chat, kept for the last `VIEWS` chats.
- **Список чатов** (Chat list, `Max.summaries` + the ListBox): the chats on
  the first page, in two tabs (chats, channels), pinned first.
- **Сводка чата** (Chat summary, a dict from `Backend.summary`): what the
  list shows of a chat: title, type, last message, time, unread, peer,
  stranger.
- **Кэш сообщений** (Message cache, `cache_*` in `~/.cache/b8k-max/chats`):
  the newest `KEEP` messages of each chat on disk, so a chat opens at once.
- **Свои люди** (Known people, `Backend.known`, `known.json`): contacts,
  people written to here, and those already in a dialog the first time;
  dialogs of others are hidden while «только от контактов» is on.
- **Порция** (Page, `PAGE`): the messages one history request brings; the
  newest when a chat opens, older ones as the reader scrolls up.
