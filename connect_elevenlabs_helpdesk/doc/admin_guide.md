# Connect ElevenLabs Helpdesk — Admin Guide

Giving a voice AI agent the ability to create and manage Helpdesk tickets during
a call.

Requires the Connect **Admin** group. The module depends on `connect_elevenlabs`
and `connect_helpdesk`, and adds no settings and no menus of its own — what it
ships is **tools**, an **agent template**, and the endpoints behind them.

## What the module ships

**Five agent tools**, ready to attach to an agent:

| Tool | Endpoint | What it does |
| --- | --- | --- |
| `helpdesk_create_ticket` | `/connect_elevenlabs_helpdesk/create_ticket` | Creates a ticket. Subject is required; description and team name optional. Returns the ticket id for later use in the same conversation. |
| `helpdesk_search_tickets` | `/connect_elevenlabs_helpdesk/search_tickets` | Lists the tickets of the current caller with id, name and status. |
| `helpdesk_fetch_ticket` | `/connect_elevenlabs_helpdesk/fetch_ticket` | Full detail of one ticket. |
| `helpdesk_update_ticket` | `/connect_elevenlabs_helpdesk/update_ticket` | Changes subject, description, priority or stage. Requires the ticket id plus at least one field. |
| `helpdesk_ticket_activity` | `/connect_elevenlabs_helpdesk/ticket_activity` | Adds a note or activity to a ticket. |

**One agent template**, *Helpdesk Support Agent*, whose system prompt already
describes the capabilities, sets the tone (professional, empathetic,
solution-oriented) and instructs the agent to confirm details before creating or
updating anything.

## Setting it up

1. **Create the agent** under **Connect ▸ Voice ▸ Agents**, based on the
   *Helpdesk Support Agent* template. The template gives you a working prompt;
   edit it to name your company, your products and anything the agent must never
   promise.
2. **Attach the tools** on the agent's **Conversation** tab. Give it only what
   it should do — an agent that can create tickets but not update them is a
   perfectly reasonable first deployment, and a smaller tool set produces more
   predictable behaviour.
3. **Sync the tools** with **SYNC TOOLS** on the ElevenLabs settings page.
   Until you do, ElevenLabs holds no definition for them and the agent silently
   never calls them.
4. **Point a number or extension at the agent**, as described in the
   Connect ElevenLabs guide.
5. **Check the license** — the underlying `connect_helpdesk` integration is
   license-checked, so ticket linking degrades silently without it.

## Choosing what the agent may change

The write-capable tools deserve a decision rather than a default:

- **create_ticket** is the safe one. The worst case is a duplicate ticket, which
  a human closes in seconds.
- **update_ticket** changes records your team is working from. An agent that
  can move stages can, in principle, be talked into closing something. If your
  process relies on stage transitions being deliberate, do not attach it — or
  attach it and constrain the prompt explicitly.
- **ticket_activity** is low risk and high value: notes are additive and never
  destroy anything.

The team-assignment parameter on `create_ticket` is free text matched to a team
name. If your team names are long or similar, expect the agent to occasionally
pick the wrong one; naming teams distinctly helps more than prompt wording does.

## After changing a tool

Any edit to a tool definition — parameters, description, timeout — requires
**SYNC TOOLS** before it takes effect. The tool's **description** is what the
model reads to decide *when* to call it, so a change there alters behaviour as
much as any prompt edit.

## Health check

1. Call the agent's extension and describe a fictional problem.
2. A ticket appears in Helpdesk with a sensible subject and description.
3. The call record shows agent, transcript and summary, and the ticket is linked
   to that call.
4. Call again from the same number and ask for the status — the agent finds the
   ticket it created.
5. Ask it to add a note, and confirm the note lands on the ticket.
