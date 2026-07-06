# Connect ElevenLabs Memory — end-to-end workflow

How an inbound **WhatsApp voice call** reaches an **ElevenLabs agent** and gains
long-term **Hindsight** memory. Spans `connect`, `connect_elevenlabs`, this
module, and the `memory` module (which owns the Hindsight connection).

```
Customer ──WhatsApp voice call──► Meta WhatsApp Business Calling
                                        │
                                        ▼  (Twilio is the sender's voice provider)
                              Twilio Programmable Voice
                                        │  voice_application_sid → TwiML app voice_url
                                        ▼
        POST /twilio/webhook/twiml/<id>  ─►  connect.domain.route_call
                                        │  match connect.exten by dialed WhatsApp number
                                        ▼
                        connect.elevenlabs_agent.render()
                                        │  <Connect><Stream wss://…/twilio/stream/{agent_uid}/{call_id}/{channel_sid}>
                                        ▼  (Twilio Media Streams — no SIP, no codec issues)
                              ElevenLabs Agent (STT + LLM + TTS)
                ┌────── tool: memory_recall(query, call_id) ───────┐
                ▼  (live, during the call)                          │  webhook tool
   POST /connect_elevenlabs/memory/recall  (x-elevenlabs-agent-token)
     call_id → connect.call → partner → resolve banks:             │
         • bank partner-<commercial_id>   (personal history)       │
         • bank business-knowledge        (shared facts)           │
                    │  POST {memory.service_url}/recall  (memory.token)
                    ▼                                               │
     memory gateway → Hindsight reflect per bank ──► merged context ┘
                                        │
   call ends ──► POST /connect_elevenlabs/post_call (HMAC)
     creates connect.recording (transcript + summary + partner)
                                        │  connect.recording.create override
                                        ▼
     retain: memory.outbox.enqueue → memory gateway retains into
             bank partner-<commercial_id>  (unified with the rest of Memory)
```

## Roles

| Layer | Responsibility |
|---|---|
| **Meta WhatsApp Business Calling** | Delivers the customer's WhatsApp voice call to the business number. |
| **Twilio Programmable Voice** | The WhatsApp sender's voice provider. `voice_application_sid` on the sender routes inbound calls to a TwiML app whose `voice_url` is the Odoo webhook. Also bridges call audio to ElevenLabs via **Media Streams**. |
| **`connect`** | Call routing (`connect.domain.route_call`), extensions (`connect.exten`), WhatsApp senders, TwiML apps, recordings, settings. |
| **`connect_elevenlabs`** | Manages ElevenLabs agents/tools/voices. Bridges a call to an agent with `<Connect><Stream>`. Post-call webhook stores transcript + recording. |
| **`connect_elevenlabs_memory`** (this) | Live recall tool + endpoint (proxies to the memory service); retain on post-call via `memory.outbox`; per-caller bank resolution; ElevenLabs-specific recall settings; WhatsApp→agent routing helper. |
| **`memory`** (required) | Owns the engine connection: provides `memory.service_url` + `memory.token`. Retain flows through `memory.outbox` → the gateway; the gateway also answers the synchronous recall (`POST /recall`). |
| **Hindsight** | External memory engine (`api.hindsight.vectorize.io`). Reached only by the memory gateway (key in `memory/deploy/.env`), never by Odoo. Banks: `partner-<commercial_partner_id>` (per customer) + a shared knowledge bank. |

## Inbound call — step by step

1. Customer calls the business WhatsApp number (e.g. `+19789814066`). Twilio marks it `Direction: inbound`, `From: whatsapp:<customer>`.
2. The sender's `voice_application_sid` → Twilio fires the TwiML app → `POST /twilio/webhook/twiml/<id>` → `connect.domain.route_call`.
3. `route_call` reads `To = whatsapp:<number>`, strips the prefix, and searches a `connect.exten` with `number == <number>`.
   - **No extension** → the caller hears *"Whatsapp Extension not found! Please create an extension for this Whatsapp number!"* and the call ends. *(This is exactly what happens until an agent + extension are configured.)*
   - **Extension found** → `exten.render()` delegates to the destination.
4. Destination = ElevenLabs agent → `connect.elevenlabs_agent.render()` returns `<Connect><Stream url="wss://<elevenlabs_agent_url>/twilio/stream/<agent_uid>/<call_id>/<channel_sid>">`. Twilio Media Streams pipes audio both ways.
5. The conversation starts with dynamic variables `call_id`, `caller_number`, `called_number`, `channel_sid` available to the agent.

## Recall (live, during the call)

6. The agent calls the webhook tool **`memory_recall(query, call_id)`** → `POST /connect_elevenlabs/memory/recall` with header `x-elevenlabs-agent-token` (checked against `connect.settings.elevenlabs_agent_token`).
7. The endpoint resolves `call_id → connect.call → partner` and builds the banks:
   - personal bank `partner-<commercial_partner_id>` (fallback `whatsapp-<E164>` if no partner),
   - shared bank (default `business-knowledge`),
   then POSTs `{banks, query}` to the **memory service** (`{memory.service_url}/recall`, auth `memory.token`, ~9s). The gateway runs Hindsight `reflect` per bank within one shared budget, merges, and returns `{"context": "..."}`. The Hindsight key never leaves the service; failures return empty context fast — never stall the call.

## Retain (after the call)

8. ElevenLabs sends the **post-call webhook** → `POST /connect_elevenlabs/post_call` (HMAC-verified) → `connect.recording` is created with `elevenlabs_transcript`, `elevenlabs_summary`, and `partner`.
9. This module overrides `connect.recording.create` → `_retain_to_memory()`: gated by `memory.enabled`, it calls `memory.outbox.enqueue(envelope)` (text = summary + transcript, `dedup_key = connect-recording-<id>`, scope = commercial partner). The gateway performs the Hindsight retain into `partner-<commercial_partner_id>` — one write path, unified with the rest of Oduist Memory. Any error is logged and swallowed, never breaking call handling.

## Configuration (connect.settings)

| Key | Notes |
|---|---|
| `api_url` | **Must be a public HTTPS URL**, not localhost (webhook URLs are built from it). For dev use an ngrok static domain. |
| Twilio account / auth token, `twilio_edge` | Twilio API access. |
| `elevenlabs_api_key`, `elevenlabs_agent_token`, `elevenlabs_agent_url` | ElevenLabs API + tool auth + media-stream host. |
| `elevenlabs_post_call_webhook_secret` | HMAC secret for the post-call webhook. |
| `hindsight_memory_enabled`, `hindsight_shared_bank` | Memory tab (ElevenLabs-specific): master toggle + shared knowledge bank. |
| `memory.service_url`, `memory.token` | **From the `memory` module's settings**, not connect. Recall POSTs to `{memory.service_url}/recall` with this token; the Hindsight key lives only in `memory/deploy/.env`. |

## Setup checklist

1. Set a public `api_url` (ngrok static domain in dev), then **Sync** the WhatsApp sender (registers `voice_application_sid` + webhook URLs in Twilio).
2. Enable WhatsApp Business Calling for the sender (Meta / WhatsApp Manager). Region limits: not available in US, Canada, Egypt, Vietnam, Nigeria.
3. Create an **ElevenLabs agent** (needs `elevenlabs_api_key` + a valid `connect_elevenlabs` license).
4. Route the WhatsApp number to the agent: `sender.action_route_calls_to_agent(agent)` (or create a `connect.exten` with `number = <WhatsApp E.164>`, destination = the agent).
5. Attach the **`memory_recall`** tool to the agent and sync the agent to ElevenLabs.
6. In the **Memory** settings tab enable ElevenLabs voice memory + set the shared bank; configure the memory service (`memory.service_url` + `memory.token`) in the `memory` module's settings; seed the `business-knowledge` bank with FAQ/business facts.
7. Install `memory` in the same DB and run the gateway (`memory/deploy`) with `RECALL_PORT` reachable from Odoo — it serves both retain (pull) and the synchronous `POST /recall`.

## Dependency model

- **Hard dependencies (manifest `depends`):** `connect_elevenlabs` **and
  `memory`**. `memory_addons` must therefore be on the addons path wherever this
  module is installed.
- **Retain** always flows through `memory.outbox.enqueue` → the gateway (unified
  with the rest of Oduist Memory). There is no direct-Hindsight path in Odoo.
- **Recall** needs a synchronous answer, so it POSTs to the memory gateway's
  `POST /recall` (auth `memory.token`), which does the Hindsight `reflect`. Odoo
  never talks to Hindsight and holds no engine key — connect keeps only the
  ElevenLabs-specific `hindsight_memory_enabled` / `hindsight_shared_bank`.

## Live test reference (Call 44)

Observed on the dev env: an inbound WhatsApp call `whatsapp:+37367597308 →
whatsapp:+19789814066` reached `/twilio/webhook/twiml/1` (the "SIP Domain Calls"
app → `route_call`), but ended `no-answer` because **no extension existed for the
WhatsApp number and no ElevenLabs agent was configured** — confirming the
transport works and only steps 3–5 of the setup checklist remained.
