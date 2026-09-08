# Connect — User Guide

Connect turns Odoo into your phone and messaging desk. You place and take calls
from the browser, see who is calling before you pick up, and keep the whole
conversation history — calls, recordings, SMS and WhatsApp — attached to the
contact it belongs to.

This guide is for the person using Connect day to day. Everything that requires
administrator rights — accounts, numbers, call routing, storage, transcription —
lives in the Admin Guide instead.

## Where things are

Everything sits under the **Connect** app in the main menu:

| Menu | What you find there |
| --- | --- |
| **Voice ▸ Calls** | The call log: every inbound and outbound call. |
| **Voice ▸ Recordings** | Call recordings you are allowed to hear. |
| **Voice ▸ Users** | Phone settings, including your own. |
| **Messaging ▸ Messages** | SMS and WhatsApp messages. |
| **Documentation** | This book. |

Some menus are visible only to administrators, so your list may be shorter.

## The phone panel

Connect adds a phone button to the Odoo system tray, at the top right of the
screen next to the clock and your avatar. Click it to open the panel; click
again to hide it. The button changes appearance while you are on a call, and
when the panel is hidden a hang-up button appears next to it so you can end a
call without reopening the panel.

The panel has three tabs:

- **Keypad** — type a name or a number in the input field and press the call
  button. Searching by name looks the contact up in Odoo, so you rarely need to
  know the number.
- **Favorites** — the numbers you call often.
- **History** — your recent calls, so you can call someone back with one click.

## Making a call

There are three ways to start a call, and they all end up in the same place:

1. **From the phone panel** — open the keypad, type the name or number, press
   call.
2. **From a phone number anywhere in Odoo** — phone and mobile fields on
   contacts, leads and other records are clickable. One click dials.
3. **From the contact form** — open a contact and use the phone action there.

While a call is up, the panel gives you:

- **Mute microphone** — the other side stops hearing you.
- **DTMF keypad** — send tones, for navigating voice menus ("press 1 for…").
- **Forward** — hand the call over to a colleague or another number. Start the
  forward, and if you change your mind, cancel it before it completes.
- **End call** — hang up.

Before a call is answered you can also mute the ringing sound.

## Receiving calls

When a call comes in for you, Connect shows a notification with the caller. If
the caller matches a contact in Odoo, you see who it is before you answer, and
can open their record while you talk.

You can change how these notifications behave in your own settings (see below):
turn them off entirely, or make them sticky so they stay on screen until you
dismiss them by hand.

If you do not pick up, what happens next — voicemail, a colleague, your mobile —
depends on how your administrator set up your fallback. You can ask to be
notified about calls you missed.

## Your personal phone settings

Open **Connect ▸ Voice ▸ Users** and find your own record. Depending on your
rights you may only see yourself, and some fields may be read-only — those
belong to the administrator.

Things you may want to change:

- **Web Phone enabled** — whether calls ring in this browser at all.
- **Ring timeout** — how many seconds your web phone rings before the call moves
  on.
- **Voicemail** — turn it on and write the greeting callers hear. The greeting
  can use your name automatically.
- **Call notifications** — enable them, and choose whether they stay until you
  dismiss them.
- **Missed-call notification** — get told about calls you did not answer.
- **Outgoing caller ID** — which of your company's numbers people see when you
  call them.

If the setting you need is missing or greyed out, it is administrator territory.

## Call history and recordings

**Voice ▸ Calls** is the full log: who called whom, when, how long, and how the
call ended. Open a call to see its details.

**Voice ▸ Recordings** holds the audio. You play a recording straight in Odoo —
no download needed. Whether a given call is recorded at all is a configuration
decision, and users can be excluded from recording entirely, so do not assume
every call has audio.

If your administrator enabled transcription, a recording can also carry a
written transcript and a short summary of what was said. When summaries are
turned on, the summary is posted to the contact's chatter, so the next person
who opens that contact sees what the call was about without listening to it.

## Messages

**Messaging ▸ Messages** lists SMS and WhatsApp traffic — direction, status,
the text, and the contact it belongs to. Failed messages are marked, with the
error the provider returned.

You send messages the same way you send anything else in Odoo:

- from a contact or record, using the SMS or WhatsApp composer;
- from Discuss, where a conversation with a customer appears as a normal chat
  thread — you type, they receive it on their phone, and their reply comes back
  into the same thread.

WhatsApp has a rule that is not Odoo's doing: outside a 24-hour window after the
customer's last message, WhatsApp only accepts pre-approved template messages.
If your administrator has set templates up, pick one; if the composer refuses a
free-text message, this is usually why.

## What you see on a contact

Open any contact and Connect adds:

- a **Calls** button showing how many calls you have had with them — click it
  for the list;
- a **Messages** button, the same for SMS and WhatsApp;
- a **Recorded Calls** tab where you can play the audio without leaving the
  contact form.

## When something does not work

- **The phone button is missing.** You are probably not in a Connect group yet,
  or the browser tab was open before Connect was installed — reload first, then
  ask your administrator.
- **The web phone does not ring.** Check that Web Phone is enabled on your user
  record, and that your browser is allowed to use the microphone.
- **A number will not dial.** Numbers must be in international format. If a
  contact's number was entered in local format, correct it on the contact.
- **A message failed.** Open it in **Messaging ▸ Messages** — the error from the
  provider is on the record, and it usually says exactly what is wrong (invalid
  number, missing template, insufficient balance).

Anything involving credentials, numbers, routing or storage needs an
administrator — those are in the Admin Guide.
