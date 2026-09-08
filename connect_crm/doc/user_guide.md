# Connect CRM — User Guide

This module ties phone calls to the CRM pipeline. Calls attach themselves to the
lead or opportunity they belong to, and — if your administrator turned it on —
a call from someone you do not know yet can create a lead by itself, so nothing
gets lost between the phone and the pipeline.

It is an add-on to Connect: the phone itself, the call log and the messaging all
work as described in the Connect guide. Only what CRM adds is described here.

## Calls on a lead

Open any lead or opportunity and you get a **Calls** button in the button box at
the top, with the number of calls linked to that lead. Click it for the full
list — who called, when, how long, how it ended, and the recording if there is
one.

This is the quick answer to "has anyone talked to this customer, and what was
said" without leaving the record you are working on.

## Finding a lead by phone number

The lead search now includes **Phone** and **Mobile**. Type a number into the
search box on the leads list and you find the lead by it — useful when someone
calls back and you want their record before you pick up.

Numbers are matched in normalised form, so a lead found this way does not depend
on how the number was typed in.

## Linking a call to the right lead

A call records which lead it belongs to. When Connect can work that out by
itself — the caller's number matches a lead, or the call was started from the
lead — the link is made for you.

When it cannot, the **Lead** field on the call is editable: open the call from
**Connect ▸ Voice ▸ Calls** and pick the right lead. The change is tracked, so
it is visible in the call's history who attached it and when.

## Leads created from calls

If your administrator enabled automatic lead creation, an inbound or outbound
call can create a lead or an opportunity by itself. Which calls do this depends
on configuration — answered ones, missed ones, calls from numbers not yet in the
database — so ask your administrator what is switched on for your company.

Two things worth knowing when it is on:

- the new lead carries the phone number the call came from, so the next search
  by number finds it;
- if the call has no Connect user attached (nobody in your company picked it up,
  for instance), the lead is assigned to the fallback salesperson your
  administrator configured.

You can also create a lead from a call by hand, from the call record, when the
automatic rules did not apply but the conversation turned out to be worth
following up.

## Call source

Calls can carry a **Source** — the UTM source the call is attributed to. When a
marketing campaign publishes a dedicated phone number, calls to that number are
attributed to it, so the pipeline shows which campaign the conversation came
from. Setting the numbers up is administrator work.

## What is administrator territory

- Turning automatic lead creation on or off, and choosing which calls trigger it.
- Choosing whether it creates leads or opportunities.
- The fallback salesperson for calls with no user.
- Attaching phone numbers to campaign sources.

All of that is in the Admin Guide.
