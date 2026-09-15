# connect — Module SPEC

Reverse-buildable contract for the module. Rules and shapes, not source.

## Scope and status

This spec covers the **softphone** — the web phone in the systray, the
components it is built from, the ORM methods it calls and the TwiML parameters
it reads — plus the directory lookup that serves it.

The rest of `connect` (call and channel ledger, call flows, TwiML, recordings
and S3, voicemail, transcription, SMS/WhatsApp, webhooks, settings) is **not
yet specced**. Anything outside the sections below still has to be read from
the code. Extend this file as those surfaces are touched; do not assume
silence here means "no behaviour".

## Softphone — composition

One OWL component tree, mounted from a service, registered in
`main_components` as `connectPhone`, plus a systray item `connectPhoneSysTray`.

- The service starts only when `document.location.pathname` contains `/odoo`.
- It calls `connect.user.get_client_token()` and mounts nothing at all when the
  payload has no `token`. A payload with `error` is logged and nothing mounts.

| Component | Template | Role |
|---|---|---|
| `Phone` | `connect.phone` | The panel: owns the call, the device and the screen state |
| `Recents` | `connect.recents` | Recent calls, grouped by day |
| `Contacts` | `connect.contacts` | Search results; doubles as the forward picker |
| `Favorites` | `connect.favorites` | Speed-dial grid |
| `PhoneSysTray` | `connect.menu` | Systray button and detached hang-up button |

`connect.calls` / `connect.call_detail` (the older flat list) still exist and
are unchanged, but the phone no longer renders them.

Icons are QWeb templates named `connect.icon_*` in
`components/phone/icons/icons.xml`, called with `t-call`. Every icon is a
20×20 viewBox inheriting `currentColor`, so one set serves both themes.

## Softphone — screens

`Phone.screen` is a getter returning exactly one of the values below, and the
template renders from it. Order matters: it is a first-match chain.

| Order | Value | Condition |
|---|---|---|
| 1 | `incoming` | `state.inIncoming` |
| 2 | `forward` | `state.isForward` |
| 3 | `dtmf` | `state.inCall and state.isKeypad` |
| 4 | `incall` | `state.inCall` |
| 5 | `recents` | `state.isCalls` |
| 6 | `favorites` | `state.isFavorites` |
| 7 | `contacts` | `state.isContactList` |
| 8 | `keypad` | otherwise |

Derived from it:

- `showDialField` — true on `keypad`, `contacts`, `dtmf`. The dial input is
  **kept mounted** across these three; other code writes into it through a ref,
  so it must never be destroyed by a `t-if`.
- `showContacts` — true on `contacts` and `forward`. The `Contacts` component
  is likewise always mounted: the phone announces its mode over the bus
  *before* the screen changes, so a component created afterwards would miss it.
- `isCallScreen` — true on `incoming`, `forward`, `dtmf`, `incall`. It hides
  the tab bar; during a call there is nowhere else to go.
- `headerTitle` — `Incoming` / `Forward to` / `On a call` / the panel title.
- `headerSub` — `· <duration>` on a call, `· ext <n>` when idle and the user
  has an extension, empty otherwise.
- `headerDotClass` — ringing on `incoming`, solid on any call screen, solid
  when the device is registered, otherwise unset.

Rules that hold across screens:

- Green appears at most once per screen and only ever means "a call can start
  or is running". Red only ever ends something.
- The panel is one light ground; dark is a theme override, not a state.
- A call keeps a strip on screen (`on the line`, peer, timer) whenever it is
  live but not the current screen — that is, on `forward` and `dtmf`.

## Softphone — placing, taking and forwarding

- **Every** dial path converges on `prepareCall({phone})`: keypad, contact
  list, favourites, recent list and click-to-call from a form. It refuses an
  empty or blank number with a user-facing warning and places no call — the
  provider would otherwise accept it, ring nobody and leave a blank ledger row.
- Opening the in-call keypad clears the dial field: what belongs there during a
  call is the tones sent on it, not the number that started it. Pressing a key
  sends the tone and echoes the digit into the field.
- Valid DTMF is `0-9`, `*`, `#`; anything else is dropped.
- **Forward** is a blind transfer through `connect.transfer_wizard`
  `execute_transfer(number, 'blind', call_id, channel_sid)`. Nothing on screen
  changes until that call returns success; on failure the user stays on the
  call and is told why. On success the phone announces the transfer to its
  other browser tabs and then ends its own leg.
- **Live match**: while a number is typed, one colleague and one customer
  lookup run in parallel and the first hit is shown under the field. A result
  that arrives after the query has moved on is discarded.

## Public methods the client calls

| Model | Method | Signature | Returns |
|---|---|---|---|
| `connect.user` | `get_client_token` | `()` | token payload, below |
| `connect.user` | `search_directory` | `(search_query, limit=10)` | list of directory entries, below |
| `connect.user` | `get_user_by_exten_number` | `(search_query)` | one PBX user or `False` |
| `connect.call` | `get_widget_calls` | `(domain, limit, offset, order, fields)` | list of call dicts |
| `connect.transfer_wizard` | `execute_transfer` | `(number, mode, call_id, channel_sid)` | `{success, message \| error}` |
| `res.partner` | `api_get_partner` | `(phone_number)` | partner dict or empty |

### `get_client_token`

Gate: caller must hold `connect.group_connect_user` or
`connect.group_connect_admin`; otherwise `{'token': False}`. Also `False` when
the caller has no `connect.user` record or that record has `client_enabled`
off. Any exception is caught and returned as `{'error': <message>}`.

| Key | Meaning |
|---|---|
| `token` | Provider access token (JWT), TTL 3600 s |
| `edge` | Provider edge for this user, falling back to the global setting |
| `exten` | The user's extension, or `''` — shown in the panel header |
| `outgoing_callerid` | The user's outgoing caller ID number, falling back to the default one, or `''` — shown under the favourites grid |

### `search_directory`

Colleagues a Connect user may dial, by name or extension.

- Gate: `connect.group_connect_user` or `connect.group_connect_admin`;
  otherwise `ValidationError`. An empty or blank query returns `[]` without
  touching the database.
- Runs `sudo()` and returns a **hand-built payload** — never a recordset and
  never a `search_read` the caller can add fields to. `connect.user` is where
  SIP credentials live (`password`, `username`, `sid`), so a field added to the
  model stays invisible here until someone puts it in the dict on purpose.
- Matches `user.name`, `username` or `exten_number`. `name` is computed and
  unstored — it is the Odoo user's name, or the SIP username when there is no
  Odoo user — so neither the domain nor the ordering may reference it.
- Ordered by `username` so the cut at `limit` is deterministic, then sorted by
  `name` for display.
- Entry shape: `{id, name, user_id, exten_number}`. `user_id` is `False` when
  the PBX user has no Odoo user; `exten_number` is `''` when it has no
  extension.
- The caller is **not** filtered out: someone checking their own extension
  should find it.

### `get_user_by_exten_number`

Same gate as `search_directory`. Returns `{id, name, exten_number, user,
partner_id}` for the first PBX user with that exact extension, else `False`.
`partner_id` is the colleague's contact — the person, not the account — and is
`False` when there is no Odoo user behind the record.

## TwiML parameters on a client leg

`render_client` attaches these `<Parameter>` entries to the `<Client>` it
dials. The softphone reads them off the incoming session.

| Parameter | Value | Read as |
|---|---|---|
| `CallerName` | Caller's display name | The name on the incoming screen |
| `Partner` | `res.partner` id, or `False` | Whether the caller is a known contact; drives avatar and *Open contact* |
| `TransferredBy` | Name of the colleague who transferred the call | The *Transferred by* line; absent when the call was not transferred |

Rules:

- On a transferred call the caller ID and `CallerName` keep naming the
  **customer** — the person the agent is about to speak to. The colleague is
  carried by `TransferredBy` instead, so the phone shows both rather than
  choosing. `TransferredBy` is emitted only when the call has
  `transferred_users` and a transferring PBX user can be resolved.
- `Partner` is treated as a known contact only when it parses as an integer.
  Missing, empty, `'false'` and non-numeric values all fall through to a lookup
  by number.
- The SIP path (`render_sip`) has no parameters to carry this and instead
  substitutes the transferring user's extension for the caller ID. The two
  paths therefore differ on purpose: a desk phone shows the colleague, a
  softphone shows the customer plus the handover.

## Component bus

One `EventBus` is created by the service and passed to every component. All
traffic is one-way; there is no reply channel.

| Event | Sent by | Handled by | Payload |
|---|---|---|---|
| `busPhoneMakeCall` | lists, widgets, actions | `Phone` | `{phone}` |
| `busPhoneMakeForward` | `Contacts` | `Phone` | the number, as a bare string |
| `busPhoneToggleDisplay` | systray, actions | `Phone` | — |
| `busPhoneHangUp` | systray | `Phone` | — |
| `busTrayState` / `busTraySetState` | `Phone` | `PhoneSysTray` | `{isDisplay, inCall}` |
| `busTraySetException` | `Phone` | `PhoneSysTray` | `{exception}` |
| `busContactSetState` | `Phone` | `Contacts` | `{isContact, isForward, isContactMode}` |
| `busContactSearchQuery` | `Phone` | `Contacts` | `{searchQuery}` |
| `busCallsGetCalls` | `Phone` | `Recents` | — |
| `busCallsGetFavorites` | `Recents`, `Favorites` | `Recents` | — |

`Recents` is mounted by a `t-if`, so it removes its two bus listeners on
destroy; a listener left behind fires into a dead component the next time the
tab is opened.

## Recent list

- Asks `get_widget_calls` for `create_date desc, id desc` — the list is cut
  into day groups from `create_date`, so that has to be the sort key too;
  ordering by id is only a proxy and drifts whenever rows are backfilled.
- Limit 50, extra fields `status` and `duration_human`.
- A call counts as **not connected** when its status appears in the outcome
  table below; anything else connected and shows its duration. This module
  writes the hyphenated `no-answer`; the other spelling is accepted because it
  is what the rest of the Connect family writes, and matching only one turns
  every missed call into a connected one.

| Status | Shown to the party who was called | Shown to the party who called |
|---|---|---|
| `no-answer` / `noanswer` | Missed | No answer |
| `busy` | Declined | Busy |
| `rejected` | Declined | Declined |
| `canceled` | Missed | Cancelled |
| `failed` | Failed | Failed |

  The same status has to read differently from each side. `busy` is what the
  provider reports when someone presses **Decline** on their softphone, so the
  person who pressed it declined the call and the person who called them
  reached a busy line. One label for every unconnected call — "Missed" one way
  and "Failed" the other — claims the system broke when nobody did anything
  wrong. A connected call reads *Incoming* or *Outgoing*.

- Colour follows the outcome, not the wording: green for a call taken, red for
  one that never connected, plain for one placed.
- Day labels are `Today`, `Yesterday`, then the localised date.
- The peer is the partner, else the colleague on the other leg, else the raw
  number; a partner's display name is cut to its last comma-separated part.
- Clicking the row calls back, the avatar opens the `connect.call` record, the
  star adds or removes a `connect.favorite` for that number.
- A favourite records **who** the row was about, in the same order the list
  resolves it: `partner` when the call has a contact, else `user` when the
  other leg was a colleague, else `name` set to the bare number. Favourites
  read the name and the avatar from those two links, so a favourite made from
  an internal call without the `user` link degrades to an anonymous extension.

## Avatars

There is no default contact image in this module's static files, so a missing
avatar is **not** an `<img>` with a fallback path — it is a coloured tile with
the first letter. The colour is a stable hash of the same text, so one peer is
always the same hue.

## Assets

| Bundle | Contents |
|---|---|
| `web.assets_backend` | The whole module's `static/src`, **minus** `**/*.dark.scss` |
| `web.assets_web_dark` | `**/*.dark.scss` only |

The dark bundle is served instead of the light one when the user's colour
scheme is dark, and includes the light one first, so `.dark.scss` files are
pure overrides. Excluding them from the light bundle is required — the light
globs would otherwise sweep them in and darken the panel for everyone.

## Error handling

`connectAudioGestureHandler` is registered in the `error_handlers` registry at
`sequence: 95`, ahead of the default handler.

- It swallows exactly one failure: a `NotAllowedError` whose message mentions a
  user gesture or `setSinkId`. Safari gates audio-output selection behind a
  user gesture, the provider SDK calls it without handing back the promise, and
  the rejection would otherwise raise a full error dialog over something
  harmless — the default output device is used and playback works once the page
  has been clicked.
- It must **not** swallow a denied microphone, which is also a
  `NotAllowedError`: that is the difference between the ringtone coming out of
  the wrong speaker and nobody being able to hear you.
