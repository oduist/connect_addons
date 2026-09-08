# Connect ElevenLabs Knowledge — Admin Guide

Managing the documents voice AI agents answer from: adding them, attaching them
to agents, keeping Odoo and ElevenLabs in step, and deleting them safely.

Requires the Connect **Admin** group. The module extends `connect_elevenlabs`
and adds no settings of its own beyond one sync button — the documents *are* the
configuration.

## Where it lives

| Location | Purpose |
| --- | --- |
| **Connect ▸ Settings ▸ ElevenLabs ▸ Knowledge** | The document library. |
| **Connect ▸ Voice ▸ Agents ▸ Knowledge Base** tab | Which documents an agent reads. |
| **Connect ▸ Settings ▸ ElevenLabs ▸ Settings**, **SYNC KNOWLEDGE** button | Pulls the document list from ElevenLabs. |

## Adding a document

Create a record under **Knowledge** and choose its **Document type**:

| Type | What to provide | When to use it |
| --- | --- | --- |
| **File** | An upload | Existing documents: manuals, policies, price lists. |
| **URL** | A link | Content that already lives on your site and changes there. |
| **Text** | Typed content | Short, agent-specific facts that have no document of their own. |

Uploaded files are restricted to `.epub`, `.pdf`, `.docx`, `.txt`, `.html` and
`.md`; anything else is rejected on save with a validation error.

On save the record is pushed to ElevenLabs: it moves **Draft → Creating →
Active**, or lands in **Error** with the reason stored on the record. Only
**Active** documents are usable by an agent.

Documents in **Error** carry a **Retry Creation** button. Retry after fixing the
cause — a file too large, an unreachable URL, an ElevenLabs-side failure.

## Attaching documents to agents

Two directions, same relationship:

- from the **agent**: open it, go to the **Knowledge Base** tab, add documents;
- from the **document**: **View Agents** shows every agent using it.

Attach deliberately rather than attaching everything to everyone. A knowledge
base is what the model searches; more documents mean more chances to retrieve
the wrong passage, and every irrelevant document makes the agent's answers a
little worse rather than a little better.

## Keeping Odoo and ElevenLabs in step

**SYNC KNOWLEDGE**, on the ElevenLabs settings page next to the other sync
buttons, reads the document list back from ElevenLabs. Use it when documents
were created or removed on the ElevenLabs side, or when Odoo's list looks stale.

The name of a document can be updated in place, and the change propagates.

## Deleting documents

Deleting a document removes it from ElevenLabs too. If it is still attached to
agents, the deletion is refused — which is the desired behaviour, since removing
a document silently changes what those agents can answer.

The record carries a **Force delete** flag for the case where you mean it
anyway. Use it knowingly: every agent listed under **View Agents** loses that
knowledge the moment it goes.

## Content that works

The document library is where an agent's factual accuracy comes from, and it
rewards the same discipline as any other reference material:

- **One topic per document.** Retrieval works better on a focused document than
  on a 200-page everything-manual.
- **Keep it current.** An outdated price list does not read as outdated to the
  model — it reads as fact, and the agent will quote it to a customer.
- **Prefer text over scans.** A PDF of scanned images carries no extractable
  text; the agent gets nothing from it.
- **Do not duplicate the prompt.** If the prompt and a document disagree, the
  agent's behaviour becomes unpredictable. Rules belong in the prompt, facts in
  the knowledge base.

## Health check

1. A new document reaches **Active** rather than sticking in **Creating**.
2. It appears on the intended agent's **Knowledge Base** tab.
3. A test call asks the agent something answerable *only* from that document,
   and the agent gets it right.
4. **SYNC KNOWLEDGE** runs without error and does not reveal documents you did
   not expect.
