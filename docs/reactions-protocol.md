# SPDX-License-Identifier: GPL-3.0-or-later
# MAX reactions: snapshots and live chat updates

Investigated on 2026-10-23 against the installed 2.9.4 Flatpak (script SHA256
`f0a5707b48441e755ff0f541d95d3faf78be0d120f8f57de2d56c3f717a4ba10`),
PyMax 2.4.1 and MAX Desktop's local request/response logs. No account ids,
message ids, text, credentials or complete packets are included here.

## What the official client does

- On opening a chat, `MSG_GET_REACTIONS` (`0xb4`) asks about a batch of
  message ids. The response is `messagesReactions`, keyed by message id;
  each value has counters and may have `yourReaction`.
- Independently, `CHAT_SUBSCRIBE` (`0x4b`) sends `{chatId, subscribe: true}`.
  In the 2026-10-23 log the same chat is renewed every 50 seconds, including
  while no messages arrive. The server acknowledges the subscription.
- `MSG_REACTION` (`0xb2`) sends `{chatId, messageId, reaction: {reactionType:
  "EMOJI", id: emoji}}`; its successful response contains `reactionInfo`.
- `NOTIF_MSG_REACTIONS_CHANGED` (`0x9b`) carries `chatId`, `messageId`,
  `counters`, `totalCount` at the top level. It does not identify the
  receiving account's own reaction.
- `NOTIF_MSG_YOU_REACTED` (`0x9c`) carries `chatId`, `messageId` and
  `reactionInfo`. An empty `reactionInfo` clears the counts and own emoji.
  Two events in the 2026-10-22 log, at 15:16:38 and 15:16:45, were followed
  by snapshot/detail responses for the same messages: `yourReaction` agreed
  in the event and the response, without an intervening local reaction.

## Observed failure in 2.9.4

The installed program contained both notification handlers, but never sent
`CHAT_SUBSCRIBE`. After PR #70 it fetched a snapshot once, 1.5 seconds after
opening a chat, then relied entirely on unsolicited events.

On 2026-10-23, MAX Desktop's successful reaction requests at 12:50:45 and
12:51:40/45/48 referred to one message whose cached counters in Messenger
were still empty. Another message's counters did update at 12:51:32.
This is a partial delivery failure, not an omitted release commit.

Replaying all 35 captured `0x9b`/`0x9c` notifications from the two days
through the installed `_peek` delivered the expected counters. The missing
subscription is therefore a concrete protocol difference and the leading
explanation for missing live updates; a fake server cannot establish MAX's
actual delivery policy.

There was also a PyMax `ReactionUpdateEvent` validation error at 12:51:32:
its mapper requires `messageId` as a string, whereas MAX sent an integer.
Messenger had already processed that frame. Passing it into PyMax again
caused noise, without explaining the other message's missing counters.

## Implementation and ownership

`PyMaxLink` alone knows the opcodes. It exposes `subscribe(chat, on)` and
snapshot states `(counts, own emoji)`, and consumes handled notification
frames before PyMax's incompatible mapper. Other frames still pass through.

Each `Account` owns a `ReactionWatch` on the backend's asyncio loop. It
subscribes before fetching the initial snapshot, renews only the lease
every 50 seconds, and cancels/unsubscribes when the chat is left or the
window hidden. Reconnect restores the desired subscription and snapshot.
Only one task per account runs; replacement waits for old cleanup. GTK
only reports which chat is visible. A completed history load updates the
snapshot ids without an arbitrary delay.

Snapshot requests track live changes by message while they are in flight,
so an old reply cannot erase a newer event or a locally sent reaction.
Counts and the own emoji are applied together to cache and UI. A `0x9b`
notification leaves the own emoji unchanged, since it does not supply it.

## Verification and limits

`tests/test_reactions.py` checks subscription frames, lease renewal without
counter polling, duplicate selection, reconnect, cancellation of a slow
snapshot on chat switches, event/snapshot ordering, own-reaction removal,
and bypass of the real PyMax mapper for consumed reaction notifications.
The GTK tests cover snapshots on reopening a chat and visible reaction
buttons. These tests use fake accounts.

A final live acceptance check needs a reaction added, changed and removed
in MAX Desktop while the fixed client keeps the same chat open, followed
by leaving/reopening and a disconnect/reconnect. No automated reactions
were sent to real contacts during this investigation.
