# Connect Helpdesk — User Guide

This module connects the phone to Helpdesk. Calls attach themselves to the
ticket they belong to, so when a customer rings about a problem you already
have their ticket in front of you, and the call becomes part of that ticket's
history.

It is an add-on to Connect: the phone, the call log and messaging work as
described in the Connect guide. Only the ticket side is described here.

## Calls on a ticket

Open a ticket and you get a **Calls** button in the button box at the top, with
the number of calls linked to it. Click it for the list — who called, when, how
long, and the recording if the call was recorded.

This answers "what has already been discussed on the phone about this issue"
without leaving the ticket.

## How a call finds its ticket

When a call ends, Connect looks for a ticket belonging to the number involved —
the caller's number for inbound calls, the number dialled for outbound ones. If
it finds one, the call is linked automatically.

Numbers are matched in normalised form, so the link does not depend on how the
number was typed on the ticket.

If no ticket matches, the call simply stays unlinked. Nothing is created behind
your back.

## Creating or linking a ticket from a call

Open a call and use the ticket action on it:

- if a ticket already exists for that number, the call is linked to it and the
  ticket opens;
- if none exists, a new ticket form opens, pre-filled with the caller's number
  and the contact, and the call is remembered as its origin.

That is the normal path after a customer rings about something new: take the
call, then turn it into a ticket without retyping their details.

The link can also be removed from the call if it was attached to the wrong
ticket.

## Finding a ticket by phone number

Tickets store a normalised phone number, so searching by number finds the
ticket. Useful when someone calls back and you want their ticket open before
you answer.

## What is administrator territory

The module has no user-facing settings. Its behaviour depends on the Connect
configuration — how calls are recorded, which agents see which calls — plus a
valid `connect_helpdesk` license. If the ticket action refuses to work with a
licensing message, that is one for your administrator.
