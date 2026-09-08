# Connect ElevenLabs Knowledge — User Guide

This module gives voice AI agents something to read. Instead of knowing only
what its prompt says, an agent can be pointed at your documents — a price list,
a returns policy, a product manual — and answer callers from them.

For most people this module is invisible: you notice it because the agent
answers questions correctly. What follows is what you can see and check.

## The knowledge base

**Connect ▸ Settings ▸ ElevenLabs ▸ Knowledge** lists every document available
to agents. Each row shows:

- **Name** — how the document is identified;
- **Document type** — a URL, an uploaded file, or plain text typed in directly;
- **State** — see below;
- **Agents** — how many agents use this document;
- **Size** and **Updated** — how big it is and when it last changed.

## Document states

A document travels through a short lifecycle, shown as a status bar on its form:

| State | Meaning |
| --- | --- |
| **Draft** | Created in Odoo, not sent to ElevenLabs yet. |
| **Creating** | Being uploaded and processed. |
| **Active** | Ready — agents can answer from it. |
| **Error** | Something went wrong; the reason is on the record. |

Only **Active** documents are usable by an agent. If an agent gives an answer
that ignores a document you expected it to know, check the state first — a
document sitting in **Error** is the usual explanation.

A document in error has a **Retry Creation** button on its form. If the retry
fails again, the error message on the record says why, and that is administrator
territory.

## Which agents use a document

Open a document and press **View Agents** to see every agent that reads it. This
is how you check the blast radius before asking for a document to be changed —
editing a price list read by five agents changes what all five say.

## What an agent reads

Open an agent under **Connect ▸ Voice ▸ Agents** and look at the
**Knowledge Base** tab: it lists the documents that agent can answer from, with
their state.

An agent answers from its prompt *and* its knowledge base. If the two disagree —
the prompt says one thing, the document another — the result is unpredictable,
so it is worth reporting rather than working around.

## Supported document formats

Uploaded files must be one of: `.epub`, `.pdf`, `.docx`, `.txt`, `.html`, `.md`.
Anything else is refused when the record is saved. Alternatively point a document
at a **URL**, or paste the content as **text**.

## Administrator territory

Adding documents, attaching them to agents, and syncing with ElevenLabs all
require administrator rights. See the Admin Guide.
