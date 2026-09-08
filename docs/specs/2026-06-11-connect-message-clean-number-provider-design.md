# Clean numbers + explicit provider for connect.message

- Date: 2026-06-11
- Branch: `19.0-discuss-on-direct-sms-messages`
- Status: Approved (design)

## Problem

WhatsApp inbound messages are stored on `connect.message` with the Twilio
scheme prefix baked into the phone number, e.g. `from_number =
'whatsapp:+37367597308'`. The rest of the system reasons about *clean* E.164
numbers (the Discuss channel already stores `connect_number` clean +
`connect_channel_provider`). This mismatch has produced a string of bugs, all
the same root cause — a clean-number lookup never matches a prefixed stored
value:

1. WhatsApp 24h-window check failed (replies wrongly rejected as "window
   expired"). Patched at the boundary, but the patch is a workaround.
2. Inbound partner lookup (`get_partner_by_number('whatsapp:+…')`) never matches
   the contact's `phone_sanitized`, so after the agent creates a contact a new
   inbound spawns a **duplicate** number-only channel instead of reusing the
   partner's channel ("as if the contact doesn't exist").
3. `_connect_link_partner` back-fill matches `from_number == connect_number`
   (clean) and so never relinks the prefixed WhatsApp rows.

## Goal / principle

A phone number is **always stored and passed clean** (E.164, no `whatsapp:`).
The messaging provider is a **separate value**, never encoded into the number.
The `whatsapp:` scheme exists **only at the Twilio boundary** and nowhere
internal.

Provider is represented by the existing `connect.message.message_type` field
(no new field), normalized to lowercase values `'whatsapp' | 'sms' | 'mms'`.
Wherever code needs the channel "provider" (`'whatsapp' | 'sms'`) it derives it
explicitly and passes it alongside the clean number.

## Scope

- **In scope:** the messaging path — `connect.message` and its mirror into
  Discuss.
- **Out of scope (unchanged):**
  - WhatsApp *voice calling* paths (`domain.py`, `call.py`, `settings.py`,
    `channel.py`, `phone.js`) — these already keep numbers clean internally and
    add `whatsapp:` only at the TwiML boundary, which is the target pattern.
  - `mail.message.message_type` (a *different* field, value `'WhatsApp'`, added
    via `mail.py` selection_add and used by chatter `whatsapp_sender.chatter_post`).
    Left as-is.
  - Data migration. Project is pre-prod; existing prefixed rows and the existing
    duplicate channel (49) are not cleaned up. New traffic behaves correctly.

## Design

### Provider representation

`connect.message.message_type` carries the provider. Inbound sets it from the
Twilio webhook; values are lowercase `'whatsapp' | 'sms' | 'mms'`. A small
helper maps message_type to the channel provider (collapsing the media-type
`'mms'` onto `'sms'`):

```python
def _provider(self):
    self.ensure_one()
    return 'whatsapp' if self.message_type == 'whatsapp' else 'sms'
```

### Twilio boundary (the only place `whatsapp:` lives)

- **Inbound** `connect.message.get_receive_message_values`: detect WhatsApp from
  the `From` prefix to set `message_type='whatsapp'`, then **strip the prefix**
  and store clean `from_number` / `to_number`. `receive()` uses the clean
  numbers (from the computed values) for partner lookup and thread matching.
- **Outbound** `whatsapp_sender.send_whatsapp` → `client.messages.create`:
  continues to format `to=f'whatsapp:{recipient}'`, `from_=f'whatsapp:{number}'`.
  Unchanged — single outbound boundary.
- **Sender sync** `whatsapp_sender._prepare_vals_from_api`: continues to strip
  `whatsapp:` from Twilio's `sender_id` when storing the sender `number`.
  Unchanged.

### Internal flow (clean numbers + explicit provider)

- `discuss.channel._get_connect_channel(partner=False, number=False,
  provider='sms', create_if_not_found=False)` — gains an explicit `provider`
  argument. It no longer parses the provider out of a prefixed number; `number`
  is expected clean.
- Inbound mirror `connect.message.receive` (~line 373):
  `_get_connect_channel(partner, number=<clean from_number>,
  provider=message._provider(), create_if_not_found=True)`.
- Inbound partner lookup uses the clean number → `get_partner_by_number` matches
  the contact → channel resolved by partner → **no duplicate channel**.
- Revert the earlier window-check workaround
  (`whatsapp_sender.send_whatsapp`): search by clean `from_number == recipient`
  with `message_type == 'whatsapp'`.
- `discuss_channel._connect_send_outbound` (~line 245): drop the
  `.replace('whatsapp:', '')` on `last_inbound.to_number` (now clean).
- View filter `views/message.xml`: `[('message_type','=','whatsapp')]`.

### Touch-point summary

| Place | Change |
|---|---|
| `message.py` `get_receive_message_values` | store clean numbers; `message_type='whatsapp'` |
| `message.py` `receive` | use clean numbers for partner/thread; pass `provider` to channel |
| `message.py` `_provider()` | new helper |
| `discuss_channel.py` `_get_connect_channel` | new `provider` arg; stop parsing provider from number |
| `discuss_channel.py` `_connect_send_outbound` | remove `.replace('whatsapp:','')` |
| `discuss_channel.py:190` | compare `message_type == 'whatsapp'` |
| `whatsapp_sender.py` window check | revert workaround; clean `from_number`, `'whatsapp'` |
| `whatsapp_sender.py:313` | outbound record `message_type='whatsapp'` |
| `views/message.xml:34` | filter domain `'whatsapp'` |

## Testing

- Inbound WhatsApp stores a **clean** `from_number` and `message_type='whatsapp'`.
- Inbound WhatsApp with an already-linked contact **reuses** the partner's
  channel (no duplicate) — reproduces the reported bug, green after fix.
- Outbound: `whatsapp:` appears **only** in the Twilio `to`/`from_`; the created
  `connect.message` stores clean numbers.
- `_provider()` returns `'whatsapp'` for `'whatsapp'`, `'sms'` for `'sms'` and
  `'mms'`.
- 24h window: a recent clean inbound lets a reply send (no false "expired").

## Risks / notes

- `mail.message.message_type` keeps the capitalized `'WhatsApp'`; the lowercase
  normalization is intentionally limited to `connect.message`.
- No migration: existing prefixed `connect.message` rows and channel 49 remain
  inconsistent but harmless in this pre-prod environment.
