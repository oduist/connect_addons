# Clean numbers + explicit provider for connect.message — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store phone numbers clean (E.164, no `whatsapp:`) everywhere on `connect.message`, carry the provider via `message_type` (lowercase `whatsapp`/`sms`/`mms`), and keep the `whatsapp:` scheme only at the Twilio boundary — fixing the duplicate-channel bug and the WhatsApp 24h-window workaround.

**Architecture:** Inbound webhook strips the scheme and stores clean numbers + a lowercase `message_type`. A `_provider()` helper maps `message_type` → `whatsapp`/`sms`. Channel resolution takes an explicit `provider` argument instead of parsing it out of the number. Outbound `messages.create` re-adds `whatsapp:` at the Twilio call — the only place the scheme exists.

**Tech Stack:** Odoo 19, Python, `connect` addon. Tests are `odoo.tests.common.TransactionCase` run inside the `connect-19` container via the oduflow MCP shell (the test runner collides with the running server on port 8069, so we use the unittest loader through `run_odoo_shell`).

**Spec:** `docs/superpowers/specs/2026-06-11-connect-message-clean-number-provider-design.md`

---

## How to run tests (referenced by every task)

Code reaches the container via git (the env is a fresh clone, not the working tree):

```
1. git add … && git commit -m "…"
2. git push origin 19.0-discuss-on-direct-sms-messages
3. oduflow pull_and_apply  env_name=connect-19      # restarts container (Python changed)
4. oduflow run_odoo_shell  env_name=connect-19  with the loader snippet below
```

Loader snippet (`<METHODS>` = space-separated test method names):

```python
import sys, unittest
from odoo.addons.connect.tests.test_connect_discuss_channel import TestConnectDiscussChannel
suite = unittest.TestSuite()
for name in "<METHODS>".split():
    suite.addTest(TestConnectDiscussChannel(name))
r = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
print('RESULT:', 'OK' if r.wasSuccessful() else 'FAILED',
      '| run=%d failures=%d errors=%d' % (r.testsRun, len(r.failures), len(r.errors)))
for who, tb in r.failures + r.errors:
    print('----', who); print(tb)
```

---

## File structure

- `connect/models/message.py` — inbound parsing/storage, `_provider()` helper, `_strip_provider_scheme()` helper, mirror call.
- `connect/models/discuss_channel.py` — `_get_connect_channel(provider=…)`, lowercase compare, drop `.replace`.
- `connect/models/whatsapp_sender.py` — revert window workaround, lowercase outbound `message_type`.
- `connect/views/message.xml` — filter domain lowercase.
- `connect/tests/test_connect_discuss_channel.py` — updated + new tests.

---

## Task 1: Clean numbers + lowercase provider on connect.message

This is one atomic change: every producer and consumer of `connect.message.message_type='WhatsApp'` flips to lowercase `'whatsapp'`, and inbound numbers are stored clean.

**Files:**
- Modify: `connect/models/message.py` (`get_receive_message_values`, `receive`, add helpers)
- Modify: `connect/models/discuss_channel.py:190`, `connect/models/discuss_channel.py:245`
- Modify: `connect/models/whatsapp_sender.py` (window check, outbound record)
- Modify: `connect/views/message.xml:34`
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Write failing unit tests**

Add to `connect/tests/test_connect_discuss_channel.py` (inside `TestConnectDiscussChannel`):

```python
def test_inbound_whatsapp_stores_clean_number_and_provider(self):
    Msg = self.env['connect.message']
    vals = Msg.get_receive_message_values({
        'From': 'whatsapp:+15551230000', 'To': 'whatsapp:+15550000000',
        'Body': 'hi', 'MessageSid': 'SMwa', 'NumMedia': '0',
    })
    self.assertEqual(vals['message_type'], 'whatsapp')
    self.assertEqual(vals['from_number'], '+15551230000')
    self.assertEqual(vals['to_number'], '+15550000000')

def test_inbound_sms_unchanged(self):
    Msg = self.env['connect.message']
    vals = Msg.get_receive_message_values({
        'From': '+15551230000', 'To': '+15550000000',
        'Body': 'hi', 'MessageSid': 'SMsms', 'NumMedia': '0',
    })
    self.assertEqual(vals['message_type'], 'sms')
    self.assertEqual(vals['from_number'], '+15551230000')

def test_provider_helper(self):
    Msg = self.env['connect.message']
    wa = Msg.sudo().create({'message_sid': 'SMp1', 'from_number': '+1',
        'to_number': '+2', 'body': 'x', 'message_type': 'whatsapp', 'status': 'received'})
    sms = Msg.sudo().create({'message_sid': 'SMp2', 'from_number': '+1',
        'to_number': '+2', 'body': 'x', 'message_type': 'mms', 'status': 'received'})
    self.assertEqual(wa._provider(), 'whatsapp')
    self.assertEqual(sms._provider(), 'sms')
```

Also update the existing WhatsApp references in this file:
- `test_inbound_whatsapp_sets_window` (~line 96): `mtype='WhatsApp'` → `mtype='whatsapp'`.
- `test_whatsapp_window_matches_prefixed_inbound`: rename to `test_whatsapp_window_matches_inbound`, store a **clean** inbound and lowercase type:

```python
def test_whatsapp_window_matches_inbound(self):
    from unittest.mock import patch
    sender = self.env['connect.whatsapp_sender'].create({
        'number': '+15550000000', 'status': 'ONLINE'})
    self.env['connect.message'].sudo().create({
        'message_sid': 'WAin1', 'from_number': '+15551230000',
        'to_number': '+15550000000', 'body': 'hi',
        'message_type': 'whatsapp', 'status': 'received', 'partner': self.partner.id})

    class _Msg:
        sid = 'WAout1'; account_sid = 'ACtest'; messaging_service_sid = False
        num_media = 0; error_code = None; error_message = None
    class _FakeMessages:
        def create(self, **kwargs):
            return _Msg()
    class _FakeClient:
        messages = _FakeMessages()
    with patch.object(type(self.env['oduist.license']), 'check_license', return_value=True), \
         patch.object(type(self.env['connect.settings']), 'get_client', return_value=_FakeClient()):
        msg = sender.send_whatsapp(recipient='+15551230000', body='reply')
    self.assertTrue(msg)
    self.assertEqual(msg.message_type, 'whatsapp')
    self.assertEqual(msg.to_number, '+15551230000')
```

- [ ] **Step 2: Run tests, verify they fail**

Run the loader with `<METHODS>` = `test_inbound_whatsapp_stores_clean_number_and_provider test_provider_helper test_whatsapp_window_matches_inbound`.
Expected: FAIL — `get_receive_message_values` returns `'WhatsApp'` and prefixed numbers; `_provider` AttributeError.

- [ ] **Step 3: Add the helpers + clean inbound storage**

In `connect/models/message.py`, add two methods on `ConnectMessage` (near the top of the class body, after the field block):

```python
    @staticmethod
    def _strip_provider_scheme(number):
        """Return the bare E.164 number without the 'whatsapp:' Twilio scheme."""
        number = number or ''
        return number[len('whatsapp:'):] if number.startswith('whatsapp:') else number

    def _provider(self):
        """Messaging provider for this message: 'whatsapp' or 'sms'."""
        self.ensure_one()
        return 'whatsapp' if self.message_type == 'whatsapp' else 'sms'
```

Replace `get_receive_message_values` head (`message.py:222-234`):

```python
    def get_receive_message_values(self, params):
        from_raw = params.get('From', '') or ''
        num_media = int(params.get('NumMedia', 0))
        if from_raw.startswith('whatsapp:'):
            message_type = 'whatsapp'
        elif num_media > 0:
            message_type = 'mms'
        else:
            message_type = 'sms'
        values = {
            'message_sid': params.get('MessageSid'),
            'from_number': self._strip_provider_scheme(from_raw),
            'to_number': self._strip_provider_scheme(params.get('To')),
            'body': params.get('Body'),
            'num_media': num_media,
            'message_type': message_type,
```
(leave the rest of the `values` dict unchanged.)

- [ ] **Step 4: Use clean numbers in `receive()`**

Replace `message.py:268-270`:

```python
                values = self.get_receive_message_values(params)
                from_number = values['from_number']
                to_number = values['to_number']
```
(`from_number`/`to_number` are now clean and feed the partner lookup, the
`last_message` thread search, the `message_configuration` lookup, and the
Discuss mirror.)

- [ ] **Step 5: Flip the remaining connect.message consumers to lowercase**

`connect/models/discuss_channel.py:190`:
```python
        if connect_message.message_type == 'whatsapp':
```

`connect/models/discuss_channel.py:245` — drop the now-redundant strip:
```python
                to_num = last_inbound.to_number or ''
```

`connect/models/whatsapp_sender.py` — revert the window workaround to a clean lookup (replace the `wa_recipient`/search block added earlier):
```python
        if not content_sid:
            # Find last incoming WhatsApp message from this recipient (clean number).
            last_incoming = self.env['connect.message'].sudo().search([
                ('message_type', '=', 'whatsapp'),
                ('from_number', '=', recipient),
                ('direction', '=', 'incoming')
            ], order='create_date desc', limit=1)
```

`connect/models/whatsapp_sender.py:313` — outbound record type:
```python
            'message_type': 'whatsapp',
```
(Leave `whatsapp_sender.py:346` `message_type='WhatsApp'` — that is the
separate `mail.message` chatter type, out of scope.)

`connect/views/message.xml:34`:
```xml
                <filter string="WhatsApp" name="whatsapp" domain="[('message_type', '=', 'whatsapp')]"/>
```

- [ ] **Step 6: Run tests, verify they pass**

Deliver (commit/push/pull_and_apply) then run `<METHODS>` =
`test_inbound_whatsapp_stores_clean_number_and_provider test_inbound_sms_unchanged test_provider_helper test_whatsapp_window_matches_inbound test_inbound_whatsapp_sets_window`.
Expected: `RESULT: OK | run=5 failures=0 errors=0`.

- [ ] **Step 7: Commit**

```bash
git add connect/models/message.py connect/models/discuss_channel.py \
        connect/models/whatsapp_sender.py connect/views/message.xml \
        connect/tests/test_connect_discuss_channel.py
git commit -m "[connect] store clean numbers + lowercase whatsapp message_type"
```

---

## Task 2: Explicit provider in channel resolution + duplicate-channel fix

**Files:**
- Modify: `connect/models/discuss_channel.py` (`_get_connect_channel`)
- Modify: `connect/models/message.py` (mirror call, ~line 373)
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Write failing tests**

```python
def test_get_connect_channel_uses_explicit_provider(self):
    ch = self.Channel._get_connect_channel(
        self.env['res.partner'], number='+19995551111',
        provider='whatsapp', create_if_not_found=True)
    self.assertEqual(ch.connect_channel_provider, 'whatsapp')
    self.assertEqual(ch.connect_number, '+19995551111')  # stored clean

def test_inbound_whatsapp_with_contact_reuses_channel(self):
    from unittest.mock import patch
    Msg = self.env['connect.message']
    # Contact already linked to its connect_messages channel.
    ch = self.Channel._get_connect_channel(
        self.partner, number='+15551230000', provider='whatsapp',
        create_if_not_found=True)

    def _gp(key, *a, **k):
        return 'ACtest' if key == 'account_sid' else ''
    params = {
        'AccountSid': 'ACtest', 'SmsStatus': 'received',
        'From': 'whatsapp:+15551230000', 'To': 'whatsapp:+15550000000',
        'Body': 'second', 'MessageSid': 'SMsecond', 'NumMedia': '0',
    }
    with patch.object(type(self.env['oduist.license']), 'check_license', return_value=True), \
         patch.object(type(self.env['connect.settings']), 'get_param', side_effect=_gp):
        Msg.with_user(self.agent).receive(params)

    channels = self.Channel.search([
        ('channel_type', '=', 'connect_messages'),
        ('connect_partner_id', '=', self.partner.id)])
    self.assertEqual(channels, ch, "must reuse the partner channel, not create a duplicate")
    msg = Msg.search([('message_sid', '=', 'SMsecond')])
    self.assertEqual(msg.from_number, '+15551230000')
    self.assertEqual(msg.message_type, 'whatsapp')
```

- [ ] **Step 2: Run tests, verify they fail**

`<METHODS>` = `test_get_connect_channel_uses_explicit_provider test_inbound_whatsapp_with_contact_reuses_channel`.
Expected: FAIL — `_get_connect_channel()` has no `provider` arg (TypeError); duplicate channel created.

- [ ] **Step 3: Add `provider` arg to `_get_connect_channel`**

In `connect/models/discuss_channel.py`, change the signature and stop inferring
provider from the number (replace `message.py`'s parse usage with the arg):

```python
    def _get_connect_channel(self, partner=False, number=False, provider='sms', create_if_not_found=False):
        """Find-or-create a connect_messages channel.

        `number` is a clean E.164 number; `provider` ('sms' | 'whatsapp') is
        passed explicitly by the caller and is never parsed out of the number.
        """
        clean_number = self._connect_parse_number(number)[0]  # defensive strip only
```

Then in the same method replace the two `'connect_channel_provider': provider`
assignments — they already read the local name `provider`, which is now the
argument, so no further change is needed there. Remove the old
`clean_number, provider = self._connect_parse_number(number)` line (it is
replaced by the `clean_number = …[0]` line above).

- [ ] **Step 4: Mirror passes clean number + explicit provider**

In `connect/models/message.py` (~line 373), update the mirror call:

```python
                    channel = self.env['discuss.channel']._get_connect_channel(
                        partner, number=from_number, provider=message._provider(),
                        create_if_not_found=True)
                    channel._connect_post_inbound(message)
```

- [ ] **Step 5: Run tests, verify they pass**

`<METHODS>` = `test_get_connect_channel_uses_explicit_provider test_inbound_whatsapp_with_contact_reuses_channel`.
Expected: `RESULT: OK | run=2 failures=0 errors=0`.

- [ ] **Step 6: Commit**

```bash
git add connect/models/discuss_channel.py connect/models/message.py \
        connect/tests/test_connect_discuss_channel.py
git commit -m "[connect] pass provider explicitly to channel resolution; fix duplicate channel"
```

---

## Task 3: Full-suite verification + manual check

**Files:** none (verification only)

- [ ] **Step 1: Run the full connect.discuss test class**

`<METHODS>` = every method in `TestConnectDiscussChannel` (omit the loop filter —
load the whole class instead):

```python
import sys, unittest
from odoo.addons.connect.tests import test_connect_discuss_channel as t
suite = unittest.defaultTestLoader.loadTestsFromTestCase(t.TestConnectDiscussChannel)
r = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
print('RESULT:', 'OK' if r.wasSuccessful() else 'FAILED',
      '| run=%d failures=%d errors=%d' % (r.testsRun, len(r.failures), len(r.errors)))
for who, tb in r.failures + r.errors:
    print('----', who); print(tb)
```
Expected: `RESULT: OK` with 0 failures/errors.

- [ ] **Step 2: Grep for stragglers**

Run: `grep -rn "WhatsApp" connect/models connect/views | grep -i message_type`
Expected: only `whatsapp_sender.py:346` (mail.message chatter type) and
`mail.py` selection entries remain. No `connect.message` value `'WhatsApp'`.

- [ ] **Step 3: Manual UI sanity (optional, needs Twilio egress)**

In Discuss, with a contact already created for a WhatsApp number, simulate/await
a new inbound and confirm it lands in the **existing** channel (no new
number-only channel appears in the sidebar).

- [ ] **Step 4: Final commit if any cleanup was needed**

```bash
git commit -am "[connect] tidy WhatsApp provider normalization" --allow-empty
```

---

## Self-review

- **Spec coverage:** clean inbound storage (T1), lowercase `message_type` (T1), `_provider()` (T1), Twilio-boundary unchanged outbound (T1 keeps `messages.create`), window workaround reverted (T1 step 5), `.replace` removed (T1 step 5), view filter (T1 step 5), explicit `provider` arg (T2), mirror passes provider + clean number (T2), duplicate-channel fix (T2 test), no migration (not implemented, by design). ✓
- **Placeholders:** none — all code blocks are concrete. ✓
- **Type/name consistency:** `_provider()`, `_strip_provider_scheme()`, `_get_connect_channel(..., provider=…)` used consistently across tasks. `message` (the created `connect.message`) is in scope at the mirror call. ✓
