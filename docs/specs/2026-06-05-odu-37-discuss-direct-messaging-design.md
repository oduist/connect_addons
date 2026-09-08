# Discuss-based direct messaging (SMS / MMS / WhatsApp) — design (ODU-37)

- **Ticket:** ODU-37 / GitHub oduist/connect_addons#118
- **Module:** `connect`
- **Status:** approved design, ready for implementation plan
- **Date:** 2026-06-05

## Problem

Today SMS/MMS (Twilio) and WhatsApp messages are stored in `connect.message` and surfaced
two ways: a flat list under *Messaging → Messages*, and as posts in the **chatter** of a
linked record (the partner, or a configured destination model). Sending is done from
one-off wizards (`sms.composer`, `connect.whatsapp_composer`) launched from a record.

There is **no conversational surface**. ODU-37 wants a real two-way messaging experience
inside the **Discuss** app: a new **"Messages"** sidebar group where each customer is a
thread you can read and reply to with SMS / MMS / WhatsApp directly.

## Research conclusions (must respect)

- **This is the Enterprise WhatsApp pattern.** Odoo EE `whatsapp` already implements
  exactly this: `whatsapp.message` ⇄ `discuss.channel` (type `whatsapp`) with a
  `message_post` override that routes outgoing through the provider, and a client-side
  sidebar category + composer patch set. Our `connect.message` is the direct analog of
  `whatsapp.message`. We follow this blueprint. Reference files (read-only, in
  `/Users/poligon/Workspace/odoo19/odoo_enterprise/whatsapp/`):
  - `models/discuss_channel.py` — `channel_type` `selection_add`, find-or-create
    (`_get_whatsapp_channel`), `message_post` override (outbound → create provider message
    → send), `_notify_thread` (inbound), `_to_store`, autovacuum membership.
  - `models/discuss_channel_member.py` — `_gc_unpin_whatsapp_channels` autovacuum that
    unpins idle/read channels to keep operator sidebars clean.
  - `models/mail_message.py` — `message_type` `selection_add`, reverse o2m, `_to_store`
    pushing provider status to the bubble.
  - `static/src/core/public_web/discuss_app_model_patch.js` — adds the sidebar category.
  - `static/src/core/web/discuss_app_category_model_patch.js` — category thread sorting.
  - `static/src/core/common/composer_patch.js` — composer gating (24h window).
- **Core `discuss.channel.channel_type`** is only `('chat','channel','group')`; special
  types are added via `selection_add` (`mail/models/discuss/discuss_channel.py:69`).
- **We deliberately diverge from WhatsApp in two places** (flagged ⚠️ below): one channel
  per **partner** (mixing all three providers) instead of one per provider-number, and a
  **shared inbox** (all agents) instead of assigned-responsible membership.

## Scope

In scope:
1. `discuss.channel` of type `connect_messages`, one per partner, in a "Messages" sidebar group.
2. Inbound SMS/MMS/WhatsApp mirrored into the partner's channel in real time (**and** still
   posted to record chatter — no regression).
3. Outbound from the Discuss composer → `connect.message` → Twilio (SMS/MMS) or
   `connect.whatsapp_sender` (WhatsApp), with a per-message **channel + sender selector**.
4. Delivery/failed status propagated onto the Discuss message bubble.
5. Shared-inbox visibility for all Connect agents, with auto-unpin of idle conversations.

Out of scope (YAGNI / follow-ups):
- Per-agent assignment / routing rules.
- "Discuss + link" chatter mode (replacing full chatter posts with a pointer). We keep
  full chatter posting as today.
- Group MMS, reactions/typing indicators beyond what core Discuss already provides.
- Messaging analytics / reporting.

## Architecture

Two layers with clear ownership:

- **Transport / system-of-record:** `connect.message` — Twilio send/receive, SID, status,
  media, direction. Existing logic unchanged.
- **Presentation / interaction:** `discuss.channel` (type `connect_messages`) + `mail.message`.
  Each `connect.message` is mirrored to one `mail.message` in the partner's channel.

Data flow: `Twilio ⇄ connect.message ⇄ mail.message (in discuss.channel) ⇄ Discuss UI`.
Status propagates `connect.message → mail.message → store` (live badge on the bubble).

### 1. Data model

**`discuss.channel`** (`_inherit`):
- `channel_type`: `selection_add=[('connect_messages', 'Customer Messages')]`,
  `ondelete={'connect_messages': 'cascade'}`.
- `connect_partner_id` (m2o `res.partner`) — the customer; the channel key (one per partner).
- WhatsApp 24h-window helpers (the Twilio/Meta session rule, WhatsApp only):
  `last_inbound_whatsapp_message_id` (m2o `mail.message`) + computed
  `whatsapp_valid_until` (Datetime) and `whatsapp_window_open` (Boolean).
- `_to_store` adds `connect_partner_id`, `whatsapp_valid_until`, `whatsapp_window_open` so
  the composer can react client-side.
- Relax the `group_public_id`/`group_ids` constraints for this type the same way WhatsApp
  does (it allows group auto-subscription for its type).

**`mail.message`** (`_inherit`):
- `message_type`: `selection_add=[('connect_message', 'Connect Message')]`,
  `ondelete` → rewrite to `comment`.
- `connect_message_ids` (o2m `connect.message`).
- `_to_store` pushes `connectStatus` (sent/delivered/read/failed) + `connectMessageType`
  (sms/mms/whatsapp), like WhatsApp's `whatsappStatus`.

**`connect.message`** (existing model):
- Add `mail_message_id` (m2o `mail.message`, index) and `channel_id` (m2o `discuss.channel`,
  stored, set at mirror time). No change to existing Twilio send/receive logic.

### 2. Channel lifecycle — `_get_connect_channel(partner)`

`discuss.channel._get_connect_channel(partner, create_if_not_found=False)`:
- Search `channel_type='connect_messages'`, `connect_partner_id=partner`.
- On create: `name = partner.display_name`, `connect_partner_id = partner`, add the
  **customer partner** as a member (so inbound messages attribute author + avatar to them).
- Idempotent; safe to call from both inbound paths and from a "Message in Discuss" action
  on the partner form.

⚠️ **Divergence 1 — shared-inbox membership.** WhatsApp assigns channels to *responsible*
users. We want **all Connect agents** to see every conversation. Plan:
- Set `group_public_id` to the Connect agents group (auto-subscription, as WhatsApp does
  for its type) so any agent may see/open the channel.
- **Pin-on-activity:** when a new (esp. inbound) message arrives, broadcast/pin the channel
  for agents so it surfaces in their Discuss sidebar with an unread badge.
- **Auto-unpin idle/read:** reuse WhatsApp's `_gc_unpin_*` autovacuum
  (`discuss.channel.member`) to unpin read conversations with no recent activity, keeping
  sidebars clean.
- *Trade-off:* "everyone sees everything" yields large sidebars on big deployments;
  auto-unpin mitigates it, and per-agent assignment (out of scope) is the future scale path.

### 3. Inbound flow

Extend `connect.message.receive()` (Twilio SMS/MMS) and the WhatsApp inbound path so that,
**in addition to today's chatter post (kept)**, they:
1. Resolve the partner (existing `get_partner_by_number` / auto-create via
   `connect.message_configuration` destination — every inbound already maps to a partner).
2. `channel = discuss.channel._get_connect_channel(partner, create_if_not_found=True)`.
3. `channel.message_post(author_id=partner, message_type='connect_message', body=…,
   attachment_ids=[…media…])`. Tag the post (context flag) as a **mirror** so the outbound
   `message_post` override does not re-send it to Twilio.
4. Link the resulting `mail.message` to the `connect.message` (`mail_message_id`).
Real-time delivery to agents is automatic via `bus`.

### 4. Outbound flow — `discuss.channel.message_post` override

Modeled on `whatsapp/models/discuss_channel.py::message_post`:
- If `channel_type != 'connect_messages'` or the post is a tagged inbound mirror →
  `super()` only (normal behavior / no send).
- Otherwise: `msg = super().message_post(...)` creates the `mail.message`; then create an
  outbound `connect.message` and call the existing transport:
  - **SMS/MMS:** `connect.message.send(recipient, body, …, outgoing_callerid=<chosen>)`
    (attachments → Twilio `MediaUrl` for MMS).
  - **WhatsApp:** `connect.whatsapp_sender.send_whatsapp(recipient, body, …)` (+ template
    when required, see §5).
- Link `connect.message.mail_message_id = msg`. Guard against double-send (inbound mirrors
  tagged; outbound creates exactly one `connect.message`).
- Status callbacks update `connect.message.status`, which pushes `connectStatus` onto the
  bubble via `mail.message._to_store` + a `_bus_send_store`.

### 5. Composer UX ⚠️ Divergence 2

Because one channel mixes providers (unlike WhatsApp's one-provider channel), the composer
needs two small controls (OWL `Composer` patch + `discuss.channel` store data):
- **Channel selector** (SMS / WhatsApp) — default "same as last inbound message" in the thread.
- **Sender selector** — SMS: outgoing number (default user's `connect_user.outgoing_callerid`,
  choices from `connect.number`); WhatsApp: `connect.whatsapp_sender` (default
  `get_default_sender`).
- **WhatsApp 24h gate:** only when WhatsApp is selected **and** `whatsapp_window_open` is
  false, require an approved template (reuse `connect.message_content_template` +
  `connect.whatsapp_composer` template/variables rendering). **SMS is always allowed**, so —
  unlike WhatsApp — we do **not** disable the whole composer; we gate only the WhatsApp path.
- **MMS:** attachments with SMS selected send as MMS (Twilio `MediaUrl`); keep WhatsApp's
  one-attachment-per-message rule for the WhatsApp path.

### 6. Discuss sidebar — the "Messages" group

Client patches mirroring WhatsApp's:
- `DiscussApp.new` adds a `connect_messages` category: `icon` (comments/chat icon),
  `name: _t("Messages")`, `hideWhenEmpty: true`, `canAdd: true`
  (search/start a conversation), `serverStateKey` for open/closed persistence, a `sequence`.
- `DiscussAppCategory.sortThreads` sorts `connect_messages` threads by `lastInterestDt`.
- Server `discuss.channel` provides these channels to the sidebar for members (per §2).

### 7. Keep-both chatter

`receive()` / `send()` continue posting to the linked record's chatter exactly as today,
**in addition** to the channel mirror. No regression to the partner-form history. (A future
"Discuss + link" mode could replace full chatter posts with a pointer — out of scope.)

### 8. Security

- `connect_messages` channels visible to the Connect agents group via `group_public_id`.
- The customer partner is a member but a portal-less external contact (no portal access).
- Webhook-created records run `sudo` as today.
- `ir.rule` ensures non-Connect users don't see these channels; existing
  `security/user_record_rules.xml` / `admin_record_rules.xml` patterns extended as needed.

## Testing

Per repo memory: the `run_odoo_tests` runner has a port-8069 conflict with the running
server, so run plain `unittest` `TransactionCase`s via `run_odoo_shell`.

- `_get_connect_channel` idempotency (one channel per partner; concurrent calls).
- Inbound: SMS/MMS/WhatsApp each mirror to the channel **and** still post to chatter;
  `mail_message_id` linked; author = partner.
- Outbound: posting in a `connect_messages` channel creates exactly one `connect.message`
  and calls the Twilio client (mocked) / `whatsapp_sender.send_whatsapp` (mocked); inbound
  mirror tag prevents re-send.
- WhatsApp window: `whatsapp_window_open` compute; template required when closed; SMS path
  unaffected.
- Status propagation: status callback updates `connect.message` and emits `connectStatus`.
- Sender defaults: SMS uses `outgoing_callerid`; WhatsApp uses default sender.

## Open items

- **Exact membership mechanism for "shared inbox"** (group auto-subscription + pin-on-activity
  vs. explicitly adding every agent as a member) to be finalized in the implementation plan;
  both are viable, auto-subscription scales better.
- **`message_type` granularity:** single `connect_message` type (provider carried on
  `connect.message`) vs. separate sms/whatsapp types — start with single; revisit if the UI
  needs per-type rendering hooks.
- **WhatsApp send via Twilio vs. Meta Cloud API:** this design reuses the existing
  `connect.whatsapp_sender.send_whatsapp` path; confirm it covers the 24h-window/template
  semantics the composer gate assumes.
