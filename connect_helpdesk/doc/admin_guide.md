# Connect Helpdesk — Admin Guide

What an administrator needs to know about the Helpdesk integration: what it adds,
what it decides automatically, and the two things that make it stop working.

Requires the Connect **Admin** group. The module depends on `helpdesk` and
`connect`.

## It has no settings

Unlike the CRM integration, this module exposes **no configuration**. There is
nothing to switch on, no automatic ticket creation to tune. It extends existing
records and adds behaviour that is always on:

| Object | What is added |
| --- | --- |
| `helpdesk.ticket` | A **Calls** stat button, the linked calls, and a stored normalised phone number so tickets can be found by number. |
| `connect.call` | A **Ticket** link, tracked, plus actions to create/link and to unlink a ticket. |

Configuration that affects it lives in the base Connect module — recording,
access groups, number formatting — not here.

## Automatic linking

When a call reaches a final status, the module looks for a ticket matching the
number: the caller for inbound calls, the number dialled for outbound ones. A
match links the call to the ticket. No match leaves the call unlinked.

Two properties are worth knowing when users report "the call did not attach":

- **The match is on the normalised number.** A ticket whose phone was entered in
  a local format still matches, but a ticket with no phone at all never does.
- **An existing link is never overwritten.** If the call already has a ticket,
  the automatic step does nothing — a manual correction stays corrected.

The module deliberately does **not** create tickets by itself. Ticket creation
is a human decision here, taken from the call with the ticket action.

## Licensing

Both the automatic linking and the create/link action check the
`connect_helpdesk` license:

- without a valid license, `on_call_status` falls through to the base Connect
  behaviour — calls are logged, but never linked to tickets;
- the ticket action raises a validation error naming the missing license.

That is the first thing to check when the integration seems to do nothing on an
otherwise healthy system: the symptom of an unlicensed module is silence on the
automatic path, not an error.

## Health check

1. Create a ticket with a customer's phone number.
2. Place a call from that number; when it ends, the call carries the ticket, and
   the ticket's **Calls** count goes up by one.
3. Place a call from a number no ticket has; the call stays unlinked.
4. From that unlinked call, use the ticket action — a new ticket form opens with
   the number and contact pre-filled.
5. Unlink a ticket from a call and confirm the call's tracked history records it.
