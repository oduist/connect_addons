# Connect BYOC — Admin Guide

Routing Connect calls through your own carrier instead of Twilio's network:
the BYOC trunk, its SIP credentials, the numbers that use it, and the rules that
reshape dialled numbers to match what the carrier expects.

Requires the Connect **Admin** group. The module adds two menus under
**Connect ▸ Voice**: **BYOC** and **Outgoing Rules**.

## The BYOC record

**Connect ▸ Voice ▸ BYOC** holds one record per carrier trunk. Creating it in
Odoo also provisions the matching objects on the Twilio side, so treat this form
as the source of truth rather than editing things in the Twilio Console.

| Field | Meaning |
| --- | --- |
| **Name** | How the trunk is identified in Odoo. |
| **Origination URIs** | Where Twilio sends calls destined for your carrier — one or more SIP targets such as `sip:your.siptrunk.com:5060`, each with a **priority** and a **weight**. |
| **SIP Username** / **SIP password** | The credentials your carrier authenticates with. |
| **Default CallerID** | The caller ID presented when nothing more specific applies. |
| **App** | The TwiML application handling calls on this trunk. |
| **Domain** | The Connect SIP domain the trunk is attached to; computed, not typed. |
| **Voice URL** / **Fallback URL** / **Status URL** | The callback URLs, computed from your Odoo URL. Give these to your carrier or check them when calls arrive but nothing happens in Odoo. |

**Priority and weight** work the way SIP practitioners expect: priority orders
the targets (lower is tried first), weight distributes load between targets of
equal priority. A single carrier with one endpoint needs one URI and no thought;
two endpoints for redundancy is the common reason to add a second.

The **Sync** action pushes the configuration to Twilio. Run it after changing
URIs or credentials — Odoo and Twilio must agree, and until they do, calls fail
at the carrier, not in Odoo.

## Caller IDs

The module extends outgoing caller IDs with a **BYOC** type and a link to the
BYOC record. Setting the BYOC field flips the type to BYOC automatically;
clearing it returns the caller ID to a normal one.

Use this to present numbers that belong to your carrier rather than numbers
bought from Twilio. Users then select these caller IDs on their Connect user
record exactly as they would any other.

## Numbers

Numbers gain a **BYOC** field. Set it, and inbound calls to that number arrive
through your carrier trunk rather than through Twilio's network.

## Outgoing rules

**Connect ▸ Voice ▸ Outgoing Rules** decides how a dialled number is transformed
before it reaches the carrier.

| Field | Meaning |
| --- | --- |
| **Name** | Free-text label. |
| **Pattern** | The destination prefix this rule applies to, e.g. `+44` for the UK. |
| **BYOC** | Which trunk the matching calls leave through. |
| **Enabled** | Whether the rule is considered at all. |
| **Add Prefix** | Digits prepended to the number before dialling. |
| **Trim Leading Digits** | How many digits to strip from the front before dialling. |

**Matching is longest-prefix-wins.** Every enabled rule whose pattern matches the
start of the number is collected, and the most specific one is used. So a
general `+` rule can catch everything while `+4420` handles London differently,
without the two fighting.

The module ships one rule out of the box — **All destinations**, matching
everything — so a fresh install routes somewhere rather than nowhere. Add more
specific rules above it as your carrier requires.

Two failure modes are worth recognising:

- **No rule matches** — the call is not routed and the reason is logged. If a
  particular country stops working, this is the first thing to check.
- **A rule matches but the carrier rejects the number** — the prefix/trim
  combination does not match what the carrier expects. Carriers differ: some
  want strict E.164, others a national format with a trunk prefix. Ask the
  carrier for their expected format rather than guessing digit by digit.

## Setup order

1. Get from your carrier: the SIP endpoint(s), the credentials, and the number
   format they expect.
2. Create the BYOC record with the origination URIs and SIP credentials, and
   **Sync**.
3. Point your numbers at the BYOC record.
4. Create the outgoing rules for the destinations you call, from general to
   specific.
5. Create BYOC caller IDs, and assign them to users.

## Health check

1. An outbound call to a national number connects, and the carrier's logs show
   it in the format they expect.
2. An outbound call to an international number connects — this is where a
   missing prefix rule usually surfaces.
3. An inbound call to a BYOC number rings in Odoo, and appears in
   **Connect ▸ Voice ▸ Calls**.
4. The recipient of an outbound call sees the caller ID you intended.
