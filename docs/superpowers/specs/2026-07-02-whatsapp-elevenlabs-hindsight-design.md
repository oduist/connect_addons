# WhatsApp → ElevenLabs agent → Hindsight memory — Design

**Goal:** Let a customer place a **WhatsApp voice call** to the business number, have an **ElevenLabs conversational agent** answer it, and give that agent **long-term memory via Hindsight** — recalling the caller's history (and shared business knowledge) live during the call, and retaining the conversation afterwards. Memory is scoped **per commercial partner** so it unifies with the `memory` module's `partner-<id>` banks.

**Status:** Design (re-baselined on top of the existing `connect_addons` platform). Supersedes the earlier standalone/SIP-trunk design — most of that is already solved by `connect`/`connect_elevenlabs`.

---

## 1. What already exists (reuse as-is)

The `connect_addons` platform (Twilio ↔ Odoo, proprietary Oduist) already implements the whole call path; only the memory layer is missing.

| Capability | Where | Notes |
|---|---|---|
| WhatsApp inbound calling plumbing | `connect/models/whatsapp_sender.py:61,176-180` | `voice_application` (→ `connect.twiml`) is pushed to Twilio as `configuration.voice_application_sid` on the WhatsApp sender. Default = "SIP Domain Calls" app. |
| Inbound call routing | `connect/models/domain.py:516-571` | `route_call` detects `To = whatsapp:<number>` (`:528`), looks up a `connect.exten` by that number (`:533`); renders it, or says *"Whatsapp Extension not found"* (`:535`). |
| Extension → destination | `connect/models/exten.py` | `connect.exten.dst` (Reference) can point at any destination incl. `connect.elevenlabs_agent`; `render()` delegates to `dst.render()`. |
| Call ↔ ElevenLabs bridge | `connect_elevenlabs/models/agent.py:311-316` | `<Connect><Stream url="wss://…/twilio/stream/{agent_uid}/{call_id}/{channel_sid}">` — **Twilio Media Streams**, not a SIP trunk. No Opus↔G711 codec problem. |
| Agent lifecycle (create/update/delete) | `connect_elevenlabs/models/agent.py` | Managed from Odoo via the ElevenLabs `conversational_ai` API. |
| Agent tools (webhook) | `connect_elevenlabs/models/agent_tool.py:26-27`, `data/tools.xml` | `tool_type ∈ {system, webhook, client}`. Webhook tools POST to Odoo routes. |
| Tool params w/ call context | `connect.agent_tool_params` (`value_type ∈ {description, dynamic_variable}`) | e.g. `transfer_to_exten` binds `channel_sid` via `value_type=dynamic_variable`. |
| Tool auth | `connect_elevenlabs/controllers/main.py:23-36` | Header `x-elevenlabs-agent-token` vs setting `elevenlabs_agent_token`. |
| Dynamic variables into the conversation | `connect_elevenlabs/models/call.py:34-35`, `agent.py:438` | `call_id`, `channel_sid`, `caller_number`, `called_number` available as dynamic variables. |
| Post-call webhook (transcript + partner) | `connect_elevenlabs/controllers/main.py:78-123` | HMAC-verified; already resolves `call_id → connect.call → call.partner`, stores transcript/summary/recording. |

**Consequence:** transport (WhatsApp→agent) and agent management are done. We do **not** build a SIP trunk, a media bridge, or custom call webhooks.

## 2. What's missing (the gap this design fills)

`grep -ri 'mcp\|hindsight'` over `connect_addons` is empty. There is no memory layer on the agent. We add:

1. **Routing config**: a `connect.exten` whose number = the WhatsApp business number, `dst` = the target ElevenLabs agent (so inbound WhatsApp calls reach the agent instead of the "extension not found" message).
2. **Live recall**: agent **webhook tools** that call token-protected Odoo endpoints which query Hindsight and return context.
3. **Retain**: push the post-call transcript into Hindsight, scoped to the caller's partner bank.

## 3. Key decisions

- **Transport:** existing Twilio Media Streams bridge (decided by what's already built). SIP-trunk approach dropped.
- **Agent ↔ Hindsight:** **webhook tools through Odoo** (not native MCP). Rationale: fits the platform's existing webhook-tool pattern; Odoo already resolves caller→partner from call context; the Hindsight key stays server-side (never shipped to ElevenLabs); central logging/approval; and it lets us reuse the `memory` module's banks/pipeline. (Native MCP remains a possible future variant but is not used here.)
- **Bank naming:** personal = `partner-<commercial_partner_id>` (same convention as `memory`'s `_memory_scope_for_partner`); shared = `business-knowledge` (configurable). Unknown caller with no resolvable partner → fallback bank `whatsapp-<E164>`.
- **Retain path:** canonical write on post-call. If the `memory` module is installed in the same DB, enqueue via `memory.outbox` so the existing Hindsight gateway performs the `retain` (single write path, unified with email/chatter capture). Otherwise, retain directly from this module. Detected at runtime; no hard dependency.
- **Module home:** new `connect_elevenlabs_memory` (depends on `connect_elevenlabs`), mirroring the existing `connect_elevenlabs_{helpdesk,knowledge,sale}` add-on pattern.

**Confirmed:** `connect` and `memory` run in the **same Odoo database**, so `res.partner` ids match and the `partner-<id>` banks genuinely unify with the `memory` module's capture pipeline. (The `whatsapp-<E164>` key is therefore only the fallback for callers with no resolvable partner, not a cross-DB workaround.)

## 4. Architecture / data flow

```
Customer ─WhatsApp voice call─► Twilio (WhatsApp Business Calling)
                                   │  voice_application_sid → TwiML webhook
                                   ▼
                    connect.domain.route_call  ──► connect.exten (number = WA business #)
                                   │                         dst = ElevenLabs agent
                                   ▼
                    <Connect><Stream> ──► ElevenLabs agent (STT+LLM+TTS)
    live recall  ┌───── webhook tool: memory_recall(query, call_id) ─────┐
                 ▼                                                        │
   POST /connect_elevenlabs/memory/recall  (x-elevenlabs-agent-token)    │
     call_id → connect.call → partner → Hindsight recall:                │
        • bank_id = partner-<id>        (personal history)               │
        • bank_id = business-knowledge  (shared facts)   ──► merged text ┘
                                   │
   call ends ──► POST /connect_elevenlabs/post_call (HMAC)  [existing, extended]
     transcript + partner ──► retain into bank_id = partner-<id>
        via memory.outbox (if memory installed) else direct Hindsight
```

## 5. Components / file structure (`connect_elevenlabs_memory`)

| File | Responsibility |
|---|---|
| `__manifest__.py` | `depends = ['connect_elevenlabs']`; external python dep `requests` (already present); version tracks branch series. |
| `models/hindsight_client.py` | Thin, dependency-light Hindsight REST client (`recall`, `reflect`, `retain`) reading base URL + key from settings. Pure-ish, unit-testable. |
| `models/settings.py` | Extend `connect.settings` with `hindsight_base_url`, `hindsight_api_key`, `hindsight_shared_bank` (default `business-knowledge`), `hindsight_memory_enabled`. |
| `models/agent.py` | Helper to compute a caller's `bank_id` from a `connect.call` (`partner-<commercial_partner_id>` or `whatsapp-<E164>` fallback). Optional: inject a memory instruction block into the agent prompt. |
| `models/call.py` (or `recording.py`) | Retain hook invoked from post-call (see §6.3): build transcript payload → outbox/enqueue or direct retain. |
| `controllers/main.py` | New route `POST /connect_elevenlabs/memory/recall` (token-checked, reuses `check_tool_token`). Optional `…/memory/reflect`. |
| `data/tools.xml` | `memory_recall` webhook tool + its params (`query` = description, `call_id` = dynamic_variable). Optional `memory_reflect`. |
| `data/agent_templates.xml` (or prompt snippet) | Prompt guidance: when to call `memory_recall`; that business facts come from recall. |
| `security/*.xml` | Access + record rules consistent with `connect_elevenlabs`. |
| `tests/` | Unit tests for `hindsight_client` (mocked HTTP) and bank-id computation; integration test for the recall endpoint (token + partner resolution). |

## 6. Interfaces

### 6.1 Recall tool (live, LLM-invoked)
- **Tool** (`connect.elevenlabs_agent_tool`): `name=memory_recall`, `tool_type=webhook`, `path=/connect_elevenlabs/memory/recall`, `method=POST`, `param_type=body`, `response_timeout_secs≈10`.
- **Params** (`connect.agent_tool_params`): `query` (`value_type=description`, LLM-filled), `call_id` (`value_type=dynamic_variable`, `dynamic_variable=call_id`).
- **Endpoint** `POST /connect_elevenlabs/memory/recall`:
  - Auth: `check_tool_token()` (header `x-elevenlabs-agent-token`).
  - Body: `{ "query": str, "call_id": int }`.
  - Logic: `browse(call_id)` → `call.partner` → `bank_id`. Call Hindsight `recall(query, bank_id=partner-<id>)` and `recall(query, bank_id=business-knowledge)`; merge, truncate to a token budget.
  - Response: `{ "context": "<merged snippets>" }` (plain text the agent reads). Empty string on no hits.

### 6.2 Prompt behaviour
Agent system prompt instructs: at the start of a call (and whenever personalization would help) call `memory_recall` with a query describing the caller/topic; treat returned `context` as trusted background; never read tool mechanics aloud.

### 6.3 Retain (post-call)
Extend the existing post-call flow (`connect_elevenlabs/controllers/main.py:78-123`) without breaking it. Prefer an ORM hook over editing the controller: on creation of the post-call `connect.recording` (which already carries `elevenlabs_transcript`, `elevenlabs_summary`, `partner`), the new module:
- computes `bank_id` from `partner`;
- builds a compact memory payload (summary + salient transcript);
- **if `memory` module installed:** `env['memory.outbox'].enqueue(...)` targeting `partner-<id>` (gateway retains) ; **else:** `hindsight_client.retain(content, bank_id=partner-<id>)` directly.
Failures are swallowed/logged so they never break call handling (same principle as `memory`'s capture layer).

### 6.4 Settings
New `connect.settings` params: `hindsight_base_url` (default `https://api.hindsight.vectorize.io`), `hindsight_api_key`, `hindsight_shared_bank` (default `business-knowledge`), `hindsight_memory_enabled` (master switch). Key sourced from the same secret used in `memory/deploy/.env`; stored via `ir.config_parameter`, never shipped to ElevenLabs.

## 7. Routing WhatsApp → agent (config, not code)
Create a `connect.exten` with `number` = the WhatsApp business number (E.164, matching `route_call`'s lookup) and `dst` = the chosen `connect.elevenlabs_agent`. Ensure the WhatsApp sender's `voice_application` is set (auto-set to the SIP Domain app on sync) so Twilio delivers the call. Optionally provide a one-click helper/action to create this extension for a sender.

## 8. Error handling
- Recall endpoint: bad/absent token → 401; unknown `call_id`/partner → recall shared bank only (still useful) and return `{context: ""}` rather than error; Hindsight timeout → return empty context fast (never stall the live call).
- Retain: never raises into call handling; log and continue.
- Region/enablement failures are external (Meta/Twilio) — surfaced in setup docs, not code.

## 9. Testing
- Unit: `hindsight_client` request shaping/parsing (mocked `requests`); bank-id computation (partner vs fallback).
- Integration (Odoo test runner): recall endpoint token check + partner resolution → correct `bank_id`s queried (Hindsight mocked); post-call retain routes to outbox when `memory` installed, direct otherwise.
- Manual (oduflow env): place a real WhatsApp call → agent answers → recall returns known fact → after hangup, memory appears in `partner-<id>`.

## 10. Prerequisites (external, verify before go-live)
- WhatsApp Business Calling enabled on the Meta/Twilio side for the sender (messaging tier ≥ 2000/24h; Calling enabled in WhatsApp Manager).
- Geographic limits: WhatsApp Business Calling is unavailable in US, Canada, Egypt, Vietnam, Nigeria.
- A Hindsight bank `business-knowledge` seeded with business/FAQ facts (one-off).
- `elevenlabs_agent_token` and post-call HMAC secret configured (already used by the platform).

## 11. Out of scope / future
- Native MCP attachment on the agent (alternative to webhook tools).
- Phone→partner auto-creation policy tuning; caller identity authentication.
- Outbound WhatsApp calling with memory (this design is inbound-first).
- Cross-DB partner id reconciliation (only needed if `connect` and `memory` are split across databases).

## 12. Open questions
- Recall trigger: prompt-driven tool call at start (chosen) vs a guaranteed conversation-initiation preload — revisit if latency/quality needs it.
