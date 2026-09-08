# Connect ElevenLabs Helpdesk — User Guide

This module teaches the voice AI agent to work with Helpdesk. A customer can
ring, describe a problem, and the agent opens a ticket for it — or finds their
existing tickets and tells them where things stand — without anyone from your
team picking up.

For you, the effect shows up as tickets that appeared while nobody was on the
phone, and as calls that already carry the whole conversation.

## What the agent can do

Five capabilities, all performed during the conversation:

| The customer says | The agent does |
| --- | --- |
| "I have a problem with…" | Creates a ticket with a subject and description, optionally in a specific team. |
| "What's the status of my issue?" | Searches the tickets belonging to that caller and reads back the list. |
| "Tell me about ticket 1234" | Fetches that ticket's details. |
| "Actually it's more urgent than that" | Updates the ticket — subject, description, priority or stage. |
| "Add that we also tried restarting it" | Adds a note to the ticket. |

Whether a given agent can do all of this depends on which tools your
administrator gave it.

## Tickets created by the agent

A ticket created this way looks like any other. What is different is its
origin: the call that produced it is linked, so the ticket carries the
recording, the transcript and the summary of the conversation it came from.

Before replying to such a ticket, read the summary — it is faster than
listening, and the customer already explained the problem once. Making them
repeat it is the main way an AI-answered call still ends up feeling bad.

## When the agent gets it wrong

Agents work from what they hear. A misheard name, an ambiguous description or a
customer who changes their mind halfway can produce a ticket that is inaccurate
rather than merely brief.

Treat agent-created tickets as a first draft: correct the subject, priority or
team as you would for a ticket a colleague raised. The transcript on the linked
call is the record of what was actually said, and it is authoritative when the
ticket and your expectation disagree.

## What you cannot change yourself

Which agent answers, what it is allowed to do, and how it decides — all of that
lives in the agent's prompt and tools, configured by an administrator. See the
Admin Guide.
