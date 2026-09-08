# Connect BYOC — User Guide

BYOC stands for "Bring Your Own Carrier". It lets your company route calls
through its own telecom operator instead of buying minutes from Twilio, while
everything else in Connect — the phone panel, the call log, recordings —
stays exactly the same.

For you as a user this module is almost invisible: you dial the way you always
did, and the call quietly leaves through your company's carrier. This guide
covers the two places where you might notice it.

## Which number the other side sees

Outgoing caller IDs can be of type **BYOC**, meaning the number is presented by
your own carrier rather than by Twilio.

If you can choose your outgoing caller ID on your Connect user record, a BYOC
caller ID behaves like any other — pick it and calls go out showing that number.
Which caller IDs exist, and which carrier each belongs to, is set by your
administrator.

## Why a number sometimes dials differently

Your administrator can define **outgoing rules**: per-destination instructions
that adjust the number before it is dialled — adding a prefix, or trimming
leading digits.

This is normal for carrier setups. A carrier may require a `0` in front of
national numbers, or expect the number without a country code. The rule does it
for you, so you keep entering numbers the usual international way and the
carrier still receives what it expects.

If a destination fails to dial while others work, that is worth reporting: it is
usually a missing or wrong rule, and it is fixed centrally rather than by
changing how you type the number.

## What stays the same

Everything else. The phone panel, click-to-call from contacts, transfers, call
history, recordings and messaging are unchanged — BYOC only changes the path the
audio takes to leave your company.

## Administrator territory

Carriers, SIP credentials, origination URIs, the rules above and which numbers
route through which carrier are all configured by an administrator. See the
Admin Guide.
