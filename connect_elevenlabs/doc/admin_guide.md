# Connect ElevenLabs — Admin Guide

Setting up voice AI agents: the ElevenLabs account, the agents themselves, the
tools they may call, how they transfer, and how a caller reaches them.

Everything here needs the Connect **Admin** group. The module requires the
`elevenlabs` Python package and depends on `connect` and `calendar`.

## Where the menus are

| Menu | Purpose |
| --- | --- |
| **Connect ▸ Voice ▸ Agents** | The agents themselves. |
| **Connect ▸ Voice ▸ Agent Templates** | Reusable system-prompt templates. |
| **Connect ▸ Settings ▸ ElevenLabs ▸ Settings** | Account, webhook, agent service. |
| **Connect ▸ Settings ▸ ElevenLabs ▸ Tools** | The tools agents may call. |
| **Connect ▸ Settings ▸ ElevenLabs ▸ Voices** | Voices synced from your account. |

## Connecting the account

**Settings ▸ ElevenLabs ▸ Settings**, tab **API**:

1. Turn on **Enabled**. The rest of the page appears only then.
2. Paste the **API Key**. It is stored write-only and readable only by users with
   ERP-manager rights.
3. Press **SYNC**. This pulls your account's voices into
   **Settings ▸ ElevenLabs ▸ Voices** and links Odoo to the account.
4. Pick the **Selected Voice** — the default voice used where no other is chosen.

Three more buttons live on this page, and it is worth knowing what they do
before you press them:

| Button | Effect |
| --- | --- |
| **SYNC** | Re-reads voices and account data. Safe, run it whenever you add voices at ElevenLabs. |
| **SYNC TOOLS** | Pushes the tool definitions from Odoo to ElevenLabs. Run it after changing a tool, otherwise the agent still uses the old definition. |
| **REGENERATE PROMPTS** | Rebuilds agent prompts from their templates. Use after changing a template that agents are based on. |
| **UNBIND ACCOUNT** | Clears all agent and tool IDs. This detaches every agent from ElevenLabs; they must be re-created there. It asks for confirmation, and you should mean it. |

Voices from the shared library can be added through the link on the same page,
then picked up by the next **SYNC**.

## Post-call webhook

Tab **Webhook** (visible once the account is connected). ElevenLabs calls Odoo
back after each conversation with the transcript and summary — this is what
fills in the transcript, summary and audio you see on the call.

The page shows the **Post Call Webhook URL** to register, and a **Post Call
Webhook Secret** used to authenticate the callback. Register the URL in the
ElevenLabs conversational-AI settings; the page links straight to it.

If calls show an agent but never get a transcript, this webhook is the first
thing to check.

## The agent service

Tab **Agent** holds the **Agent URL** — the address of the service that bridges
telephony and ElevenLabs — and optional **Agent Parameters** in `param=value`
form. The **Agent Ping** button checks that the service answers. Do that after
any change to the URL; a wrong address fails at call time, when a customer is
already on the line.

## Creating an agent

**Connect ▸ Voice ▸ Agents**. An agent's form is organised by concern:

**Prompt** — the system prompt: who the agent is, what it may do, what it must
not do, and how it should behave when it does not know something. This text is
what your customers effectively talk to; it deserves more care than any other
field on the form. An agent can be based on a **Template**, and prompt versions
are kept, so you can see what changed and go back.

**Conversation** — the operational envelope:

| Field | What it controls |
| --- | --- |
| **Voice** | Which synced voice the agent speaks with. |
| **Language** / **Additional languages** | The primary language and any others the agent may switch to. |
| **Tools** | The tools this agent may call (see below). |
| **Transfer to agent** | Rows of target agent plus the **condition** under which the hand-over happens. Only shown when the agent has the transfer tool. |
| **Turn timeout** | How long the agent waits for the caller to say something. |
| **Silence end call timeout** | Seconds of silence after which the call ends. |
| **Max duration** | Hard cap on conversation length, in seconds (default 600). This is a cost control as much as a UX one. |
| **Agent concurrency limit** | How many simultaneous conversations this agent handles. |
| **Daily limit** | Cap on conversations per day. |
| **Exten** | The internal extension created for the agent — use the **Extension** button on the form to create it. |

**LLM / TTS** — the model and speech parameters: the LLM and its max tokens,
audio formats, and the voice-quality dials `temperature`, `stability`, `speed`
and `similarity_boost`. Defaults are sane; change one at a time and listen to
the result, because these interact.

Two limits deserve emphasis: **max duration** and **daily limit** are what stand
between a misbehaving prompt and an unbounded bill. Set them before the agent
takes real calls, not after.

## Tools

**Settings ▸ ElevenLabs ▸ Tools** defines what an agent can *do* beyond talking:
look something up, write something back, transfer the call.

Per tool you configure its **type**, the **URL** and HTTP **method** it calls,
its **parameters** (each with an identifier, data type, whether it is required,
and either a constant value or a dynamic variable), a **response timeout**, and
whether the agent **expects a response** before continuing.

The **description** matters more than it looks: it is what the model reads to
decide when to use the tool. A vague description produces an agent that calls the
tool at the wrong moment, or never.

After editing a tool press **SYNC TOOLS** on the settings page. Until then
ElevenLabs still holds the previous definition.

## Connecting callers to an agent

An agent answers calls once something points at it:

- **A number** — on **Connect ▸ Voice ▸ Numbers**, set the destination to
  **Agent** and pick the agent. Changing the destination away from Agent clears
  the agent link.
- **An extension** — an agent's extension is created from the agent form, and
  extensions can also target an agent directly.

Call flows integrate too: their prompt, invalid-input and voicemail messages can
each use an ElevenLabs audio file instead of synthetic speech, with a preview
player on the form.

## Per-user voicemail in a real voice

A Connect user's **voicemail prompt** can point at an ElevenLabs audio file,
previewable from the user form. This is per user, configured on their Connect
user record.

## Licensing

Agent rendering checks the `connect_elevenlabs` license. Without a valid
license the agent will not answer calls, even though the configuration looks
complete — so if a correctly configured number does not reach its agent, check
the license before rebuilding the agent.

## Cost control — read before going live

Voice agents bill per conversation minute at ElevenLabs, plus LLM tokens. The
settings that bound the bill are, in order of importance:

1. **Max duration** per conversation.
2. **Daily limit** per agent.
3. **Agent concurrency limit**.
4. **Silence end call timeout** — an abandoned call that keeps a line open costs
   money for as long as the timeout allows.

Set all four deliberately before pointing a public number at an agent.

## Health check after setup

1. **SYNC** succeeds and voices appear under **Voices**.
2. **Agent Ping** answers.
3. The post-call webhook URL is registered at ElevenLabs, with the secret.
4. A test call to the agent's extension is answered and the agent speaks.
5. After hanging up, the call record shows agent, transcript, summary and audio
   — that proves the webhook path works end to end.
6. If the agent uses tools, one tool call succeeds during that test conversation.
