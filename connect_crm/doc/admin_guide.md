# Connect CRM — Admin Guide

Configuration for the CRM side of Connect: whether calls create leads by
themselves, which calls do it, and who owns the result.

Everything here lives in **Connect ▸ Settings ▸ General**, on the **CRM** tab,
and requires the Connect **Admin** group. The module adds no menus of its own —
it extends the Connect settings form, the call record and the CRM lead.

## Automatic lead creation

The CRM tab has two independent halves, incoming and outgoing. Each starts with
a master switch; the rest of the options in that half appear only once it is on.

**Incoming Calls**

| Setting | What it controls |
| --- | --- |
| **Auto Create Leads** | Master switch for inbound calls. |
| **For Answered Calls** | Create a lead when the call was answered. |
| **For Not Answered Calls** | Create a lead when nobody picked up — this is the setting that stops missed calls from disappearing. |
| **For unknown callers** | Restrict creation to callers not already known in the database, so repeat customers do not generate duplicates. |

**Outgoing Calls**

| Setting | What it controls |
| --- | --- |
| **Auto Create Leads** | Master switch for outbound calls. |
| **For Answered Calls** | Create a lead when the call was answered. |
| **For Not Answered Calls** | Create a lead when the other side did not pick up. |

Nothing is created while the master switch for that direction is off, whatever
the sub-options say.

## Ownership and type

A third group appears as soon as either master switch is on:

| Setting | What it controls |
| --- | --- |
| **Auto create leads sales person** | The user assigned to leads created from calls that have no Connect user attached. Without it, such leads end up unassigned and nobody notices them. |
| **Leads type** | Whether the records created are leads or opportunities. Match this to how your pipeline is organised — if your CRM does not use the lead stage at all, creating leads produces records your salespeople never look at. |

## Choosing a sensible combination

The options multiply quickly, so decide from the outcome you want:

- **Never lose an inbound enquiry:** incoming on, both answered and not
  answered, restricted to unknown callers. Existing customers stay on their
  existing records; strangers always produce something to follow up.
- **Only real conversations:** incoming on, answered only. Fewer records, but a
  missed call from a new number leaves no trace in CRM.
- **Track outbound prospecting:** outgoing on, answered only. Turning on
  outgoing for unanswered calls as well generates a record for every attempt,
  which is noise unless your process specifically wants it.

Whatever you pick, watch the pipeline for a week afterwards. Automatic creation
is the kind of setting whose cost — duplicate or empty leads — only shows up at
volume.

## Calls and leads

The module extends the call record with:

- **Lead** — the linked CRM record, editable and tracked, so a correction is
  visible in the call's history.
- **Source** — the UTM source the call is attributed to.
- the call's **Reference** field, which can now point at a CRM lead.

On the CRM side it adds the **Calls** stat button to the lead form, and **Phone**
and **Mobile** to the lead search view, matched on the normalised number.

## Campaign attribution

UTM sources carry a phone number. Publish a dedicated number for a campaign,
set it on the source, and calls arriving on it are attributed to that campaign —
which is what makes "how many calls did this campaign produce" answerable.

## Messaging destination

The module adds **CRM Lead** as a destination for message configuration, so
inbound messages can be routed to a lead the same way calls are. The routing
itself is configured under **Connect ▸ Messaging ▸ Configuration**.

## After changing these settings

Automatic creation reacts to call status events, so the effect is immediate —
there is no scheduled job to wait for. Place one test call of each kind you
enabled and confirm the result: a lead appears, of the type you chose, assigned
to the person you expect, carrying the phone number.
