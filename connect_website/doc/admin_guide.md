# Connect Website — Admin Guide

Enabling the "Let's Talk" call button on the public website and choosing where
those calls land.

Requires the Connect **Admin** group. The module depends on `website` and
`connect`.

## Settings

**Connect ▸ Settings ▸ General**, tab **Website**:

| Setting | What it controls |
| --- | --- |
| **Talk Button Enable** | Master switch. The two fields below appear — and are required — only when it is on. |
| **Extension** | The Connect extension website calls are routed to. This is the destination that rings when a visitor clicks the button. |
| **Domain** | The Connect SIP domain used for these calls. |

Both fields are mandatory once the feature is enabled, deliberately: a button
with no destination is worse than no button, because the visitor gets silence
instead of an obvious absence.

Point the extension at whatever should answer public enquiries — a PBX group so
several people ring at once, a call flow with a menu, or an AI agent if
`connect_elevenlabs` is installed.

## Placing the button

The module ships a website snippet, **Connect Button**. Edit a page in the
website editor and drag it in. It renders as a card with a **Let's Talk** label,
which turns into accept/reject controls while a call is in progress.

The frontend assets (JS, XML template, SCSS) are registered automatically in the
website asset bundle — nothing to configure.

## How a website call is routed

Calls originating from the site are marked as coming from the website, and the
routing takes a different path from ordinary telephony:

- the caller is a browser client rather than a phone number;
- a call record is created the usual way, so the call appears in
  **Connect ▸ Voice ▸ Calls** with the same lifecycle as any other;
- if the caller's identity can be matched to a partner, it is used.

Two things follow from this that matter operationally:

1. **Anonymous by default.** There is no caller number to identify a website
   visitor with, so agents see an enquiry rather than a known customer. If your
   process depends on knowing who is calling, make identifying the visitor part
   of the conversation.
2. **The webhook path is the same one telephony uses.** Website routing is
   guarded by the Connect webhook group, exactly like normal inbound calls, so
   if inbound telephony is broken, the button is broken too — fix that first.

## Requirements and constraints

- **HTTPS is mandatory.** Browsers refuse microphone access on insecure origins,
  so the button cannot work on a plain-HTTP site. This is a browser rule, not an
  Odoo setting.
- **A valid `connect_website` license.** Without it, callers hear a message
  saying the trial period is over instead of reaching your team. The button will
  look like it works, which makes this an easy failure to misdiagnose — check
  the license before debugging the snippet.
- **A reachable Odoo URL**, as with all Connect callbacks.

## Health check

1. Enable the feature, set extension and domain, save.
2. Drop the snippet on a test page and publish it.
3. Open that page over HTTPS in a normal browser, click the button, and grant
   microphone access.
4. The configured destination rings; answer it.
5. The call appears in **Connect ▸ Voice ▸ Calls** with the website as its
   origin, and its recording plays back if recording is enabled.
