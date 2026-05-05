# Spec: Inbound SIP Trunk → ElevenLabs Call Logging in Odoo

## Context and Problem

After implementing [SPEC_SIP_TRUNK.md](./SPEC_SIP_TRUNK.md), inbound calls flow
directly `Twilio → ElevenLabs`, bypassing Odoo entirely. As a result:

- No `connect.call` record is created for the call.
- Nothing appears in call statistics.
- The conversation recording is not saved.
- The EL transcript and summary are not linked to Odoo.

The existing webhook `/connect_elevenlabs/post_call`
([controllers/main.py:78](./controllers/main.py)) is designed **only** for the
legacy scenario where Odoo itself initiates the call and passes `call_id`
via `dynamic_variables`. This path does not apply to inbound SIP-trunk flow:

| Problem | Where it breaks |
|---|---|
| `int(dynamic_variables.get('call_id'))` | `call_id` is absent → `TypeError` |
| `call.channels[0].sid` | the new record has no channels |
| `caller_number` / `called_number` in `dynamic_variables` | Odoo never set them |

## Goal

Extend the webhook so that for inbound SIP-trunk calls a **new** `connect.call`
(+ `connect.recording`) is created from the EL payload, while the legacy branch
(outbound calls initiated by Odoo with a pre-created `connect.call`) continues
to work unchanged.

---

## Architecture Flow (after the fix)

```
Caller
  └─▶ Twilio DID (+19789814066)
        └─▶ Twilio Elastic SIP Trunk
              (Origination URL: sip:sip.rtc.elevenlabs.io;transport=tls)
                └─▶ ElevenLabs SIP ingress
                      └─▶ EL agent answers and handles the conversation
                            └─▶ EL POST /connect_elevenlabs/post_call
                                  └─▶ Odoo creates connect.call + connect.recording
```

The call still bypasses Odoo in real time; Odoo sees it
**post-factum** via the EL webhook.

---

## EL Post-call Webhook: Payload (current schema)

Relevant fields (from EL Conversational AI docs / real logs):

```jsonc
{
  "type": "post_call_transcription",
  "data": {
    "agent_id": "agent_xxx",
    "conversation_id": "conv_xxx",
    "status": "done",
    "transcript": [
      {"role": "agent", "message": "...", "time_in_call_secs": 0},
      {"role": "user",  "message": "...", "time_in_call_secs": 3}
    ],
    "metadata": {
      "start_time_unix_secs": 1714835200,
      "call_duration_secs": 42,
      "cost": 1234,
      "termination_reason": "client_disconnect",
      "phone_call": {
        "direction": "inbound",
        "phone_number_id": "phnum_xxx",   // ← EL phone_number UID
        "agent_number": "+19789814066",   // called (DID)
        "external_number": "+15551234567",// caller
        "type": "sip_trunk",
        "stream_sid": "...",
        "call_sid": "..."
      }
    },
    "analysis": {
      "transcript_summary": "...",
      "call_successful": "success",
      "evaluation_criteria_results": {...},
      "data_collection_results": {...}
    },
    "conversation_initiation_client_data": {
      "dynamic_variables": {
        // for inbound SIP-trunk there is NO call_id, caller_number, called_number here
      }
    }
  }
}
```

> Exact field names must be verified against the first real payload — specifically
> `metadata.phone_call.external_number` vs `from_number`. The implementation below
> uses `payload.get(...)` with fallbacks throughout, see step 1.4.

---

## Field Mapping: EL → Odoo

| Odoo field (`connect.call`)        | Source in payload                                                  |
|---|---|
| `caller`                           | `metadata.phone_call.external_number`                              |
| `called`                           | `metadata.phone_call.agent_number`                                 |
| `direction`                        | `inbound` (fixed — this webhook handles inbound flow only)         |
| `started`                          | `datetime.utcfromtimestamp(metadata.start_time_unix_secs)`         |
| `answered`                         | same as `started` (EL answers immediately)                         |
| `ended`                            | `started + metadata.call_duration_secs`                            |
| `status`                           | `completed` if `call_successful=='success'`, else `failed`         |
| `elevenlabs_conversation_id`       | `data.conversation_id`                                             |
| `elevenlabs_summary`               | `data.analysis.transcript_summary`                                 |
| `partner` / `caller_user`          | lookup by `caller` (standard `connect.call` logic)                 |
| `number` (FK to `connect.number`)  | lookup by `called` or `metadata.phone_call.phone_number_id` via `connect.number.el_phone_number_uid` |

| Odoo field (`connect.recording`)   | Source                                                             |
|---|---|
| `call`                             | id of the created `connect.call`                                   |
| `sid`                              | `data.conversation_id`                                             |
| `call_sid`                         | `metadata.phone_call.call_sid`                                     |
| `start_time`                       | `connect.call.create_date`                                         |
| `duration`                         | `metadata.call_duration_secs`                                      |
| `caller_number` / `called_number`  | same as in `connect.call`                                          |
| `elevenlabs_transcript`            | assembled from `data.transcript`                                   |
| `elevenlabs_summary`               | `data.analysis.transcript_summary`                                 |
| `elevenlabs_media_file`            | `GET /v1/convai/conversations/{id}/audio` → base64                 |
| `status`                           | `completed`                                                        |

---

## Implementation Plan (step by step)

### Step 1. Branch in `post_call_webhook`

File: [controllers/main.py](./controllers/main.py)

1.1. After signature verification and `data` parsing, get
`dynamic_variables = data.get('conversation_initiation_client_data', {}).get('dynamic_variables', {})`.

1.2. Extract `legacy_call_id = dynamic_variables.get('call_id')`.

1.3. Branch:
- if `legacy_call_id` is set — **existing branch** (update
  `connect.call.browse(call_id)`).
- otherwise — **new branch** (see step 2).

1.4. Replace all accesses to `dynamic_variables['caller_number']` and
`['called_number']` with safe fallbacks:
```python
caller = (dynamic_variables.get('caller_number')
          or data['metadata']['phone_call']['external_number'])
called = (dynamic_variables.get('called_number')
          or data['metadata']['phone_call']['agent_number'])
```

### Step 2. New Branch: Create `connect.call` for Inbound SIP-trunk

New private method `_create_inbound_call_from_el_payload(env, data)`
in `controllers/main.py` (or move to `models/call.py` as a classmethod —
see step 5):

2.1. Parse `metadata.phone_call`:
- `phone_number_id` (EL UID)
- `external_number` (caller)
- `agent_number` (called DID)
- `call_sid`, `stream_sid`

2.2. Find `connect.number` by `el_phone_number_uid == phone_number_id`.
If not found — fallback by `phone_number == agent_number`.
If both fail — log a `warning`, still create `connect.call`
without a `number` link.

2.3. Find `res.partner` by `caller` (standard Odoo search by
`mobile`/`phone`).

2.4. Create `connect.call`:
```python
call = env['connect.call'].sudo().create({
    'caller': caller,
    'called': called,
    'direction': 'inbound',
    'started': datetime.utcfromtimestamp(meta['start_time_unix_secs']),
    'answered': datetime.utcfromtimestamp(meta['start_time_unix_secs']),
    'ended': datetime.utcfromtimestamp(
        meta['start_time_unix_secs'] + meta['call_duration_secs']),
    'status': 'completed' if data['analysis'].get('call_successful') == 'success'
              else 'failed',
    'elevenlabs_conversation_id': data['conversation_id'],
    'elevenlabs_summary': data['analysis'].get('transcript_summary', ''),
    'partner': partner.id if partner else False,
    'number': number.id if number else False,
})
```

2.5. Download audio + create `connect.recording` (logic already exists in the
legacy branch; reuse the shared helper `_create_recording(env, call,
data, transcript)` — see step 3).

### Step 3. Extract Recording Creation into a Shared Helper

Current code [main.py:99-122](./controllers/main.py) is duplicated. Create:

```python
def _create_recording(self, env, call, data, transcript):
    url = f"https://api.elevenlabs.io/v1/convai/conversations/{data['conversation_id']}/audio"
    api_key = env['connect.settings'].sudo().get_param('elevenlabs_api_key')
    resp = requests.get(url, headers={"xi-api-key": api_key, "Content-Type": "application/json"})
    if resp.status_code != 200:
        logger.warning("Failed to fetch EL recording: %s", resp.status_code)
        return False
    audio_b64 = base64.b64encode(resp.content)
    return env['connect.recording'].with_context(skip_transcription=True).sudo().create({
        'call': call.id,
        'elevenlabs_transcript': transcript,
        'elevenlabs_summary': data['analysis'].get('transcript_summary', ''),
        'sid': data['conversation_id'],
        'call_sid': call.channels[:1].sid if call.channels else
                    data['metadata']['phone_call'].get('call_sid', ''),
        'start_time': call.create_date,
        'elevenlabs_media_file': audio_b64,
        'duration': data['metadata']['call_duration_secs'],
        'caller_number': call.caller,
        'called_number': call.called,
        'status': 'completed',
        'partner': call.partner.id if call.partner else False,
        'caller_user': call.caller_user.id if call.caller_user else False,
    })
```

Used in both branches (legacy + new).

### Step 4. Recording → Number Link (optional)

`connect.recording` has no direct FK to `connect.number`, but `call.number`
already provides access. If recordings need to be filtered by DID — filter via
`call.number`.

### Step 5. Where to Place the Logic (refactoring)

The controller should not contain business logic. Move
`_create_inbound_call_from_el_payload` and `_create_recording` to
[models/call.py](./models/call.py) as classmethods on `connect.call`:

```python
@api.model
def create_from_elevenlabs_inbound(self, data):
    """Create an inbound call from an EL post_call payload."""
    ...
    return call
```

The controller becomes thin:
```python
if legacy_call_id:
    call = env['connect.call'].browse(int(legacy_call_id))
    call.update_from_elevenlabs_post_call(data)
else:
    call = env['connect.call'].create_from_elevenlabs_inbound(data)
call.attach_elevenlabs_recording(data)
```

### Step 6. Error Handling and Idempotency

6.1. EL may retry the webhook. Before creating — check:
```python
existing = env['connect.call'].search(
    [('elevenlabs_conversation_id', '=', data['conversation_id'])], limit=1)
if existing:
    return existing
```

6.2. If `start_time_unix_secs` or `call_duration_secs` are absent —
log a warning, leave the fields empty (do not crash).

6.3. All payload accesses use `.get()` with fallbacks.

### Step 7. Documentation Update

7.1. In [SPEC_SIP_TRUNK.md](./SPEC_SIP_TRUNK.md) replace the
"Inbound Call Architecture Flow" block — Odoo now participates
post-factum.

7.2. Add **Trigger 8: Post-call webhook from EL → create call in Odoo**
with status ✅ after implementation.

7.3. Mark this spec (`SPEC_INBOUND_CALL_LOGGING.md`) as
"implemented in commit <hash>" upon completion.

---

## Testing

### Manual

1. Call the DID linked to the SIP trunk with the EL agent.
2. Wait for the conversation to end (EL sends the post_call webhook ~30 sec
   after end-of-call).
3. Verify in Odoo:
   - `Voice → Calls`: an inbound record appears with correct caller/called.
   - The record has `elevenlabs_conversation_id` and `elevenlabs_summary` filled.
   - `Recordings`: a record appears with audio, transcript, and summary.
   - Audio plays back correctly.

### Automated

Minimum — unit tests in `tests/test_post_call_webhook.py`:

- `test_legacy_flow_with_call_id` — payload with `call_id`, existing
  `connect.call` is updated.
- `test_inbound_sip_trunk_flow` — payload without `call_id`, new
  `connect.call` is created with correct fields.
- `test_idempotent_on_retry` — repeated POST with the same
  `conversation_id` → returns the existing record, no duplicate.
- `test_missing_metadata_does_not_crash` — payload without
  `start_time_unix_secs` → call is created without started/ended, no 500.
- `test_unknown_phone_number_id` — `el_phone_number_uid` not found →
  call is created with `number = False`, warning in logs.

Mock `requests.get` for audio (return 200 with dummy bytes).

---

## Files Changed

| File | What changes |
|---|---|
| `connect_elevenlabs/controllers/main.py` | Branch in `post_call_webhook`; thin calls to model methods |
| `connect_elevenlabs/models/call.py` | `create_from_elevenlabs_inbound`, `update_from_elevenlabs_post_call`, `attach_elevenlabs_recording` |
| `connect_elevenlabs/SPEC_SIP_TRUNK.md` | Updated architecture flow + Trigger 8 |
| `connect_elevenlabs/SPEC_INBOUND_CALL_LOGGING.md` | This file |
| `connect_elevenlabs/tests/test_post_call_webhook.py` | New file with tests |
| `connect_elevenlabs/__manifest__.py` | Possibly — version bump to `1.0.6` |

---

## Open Questions (to resolve before implementation)

1. **Exact EL payload field names**: `external_number` vs `from_number`,
   `agent_number` vs `to_number`. Verify against the first live webhook
   (enable `logger.info(json.dumps(data))` on staging).

2. **Callflow / IVR**: should a callflow be triggered for an inbound call
   logged post-factum? Or is this purely a statistics record?
   (Currently the legacy branch does not trigger a callflow — the webhook
   is logging-only.)

3. **Multi-company**: if Odoo has multiple companies each with their own
   `connect.number` set — in which company should `connect.call` be created?
   Solution: take `company_id` from the found `connect.number`, otherwise
   fall back to the default from `connect.settings`.

4. **Audio retention**: where is `elevenlabs_media_file` stored (binary in
   the DB)? Large WAV files will bloat the DB. There may already be a
   `recording_storage_mode` config. Check.

5. **Failed calls** (e.g. EL could not reach the agent, busy):
   does EL send a post_call for these? If yes — `metadata.call_duration_secs
   == 0`, handle accordingly.
