# ODU-37 Discuss Direct Messaging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let agents read and reply to customer SMS / MMS / WhatsApp from a new "Messages" group inside Odoo Discuss, with one conversation per partner.

**Architecture:** A `discuss.channel` of new type `connect_messages` (one per partner) is the presentation/interaction layer; the existing `connect.message` stays the Twilio transport system-of-record. Inbound Twilio messages are mirrored into the partner's channel (and still posted to chatter); posting in a channel routes outbound through `connect.message.send()` (SMS/MMS) or `connect.whatsapp_sender.send_whatsapp()` (WhatsApp). Client-side OWL patches add the sidebar category and a per-message provider/sender selector. This mirrors Odoo EE's `whatsapp` module pattern.

**Tech Stack:** Odoo 19 (`mail`/`discuss` framework), OWL 2 (JS patches), Twilio (SMS/MMS/WhatsApp via existing `connect` code), Python `unittest`/`TransactionCase`.

**Reference implementation (read-only):** `/Users/poligon/Workspace/odoo19/odoo_enterprise/whatsapp/` — especially `models/discuss_channel.py`, `models/discuss_channel_member.py`, `models/mail_message.py`, and `static/src/core/**`.

---

## Execution environment notes

- **Code delivery:** the connect-19 oduflow env is a fresh GitHub clone (no live mount). Deliver changes by committing on branch `19.0-discuss-on-direct-sms-messages`, pushing, then `pull_and_apply` + restart/upgrade the `connect` module. (See memory: `connect_19_env_mounts_live_working_tree`, `feedback_restart_and_upgrade_after_changes`.)
- **Running tests:** the oduflow `run_odoo_tests` tool collides on port 8069. Run the new `TransactionCase`s as plain unittest via `run_odoo_shell` instead, or locally with the standard runner:
  `odoo -d <db> -i connect --test-enable --test-tags /connect --stop-after-init` (CI form). In task steps the test command is written generically as `RUN TESTS` — use whichever mechanism the executor has available.
- **TDD loop reality:** because of the delivery model, batch a phase's tests and run them together after delivery rather than per-micro-step where the per-step loop is impractical. Keep the write-test-first ordering.

## File structure (created / modified)

**Created**
- `connect/models/discuss_channel.py` — `discuss.channel` inherit: type, fields, find-or-create, inbound mirror, outbound routing, allowed-params, `_to_store`.
- `connect/models/discuss_channel_member.py` — `discuss.channel.member` inherit: autovacuum unpin of idle channels.
- `connect/security/discuss_messages.xml` — `ir.rule` for `connect_messages` channels.
- `connect/tests/test_connect_discuss_channel.py` — backend tests.
- `connect/static/src/core/public_web/discuss_app_model_patch.js` — sidebar category definition.
- `connect/static/src/core/web/discuss_app_category_model_patch.js` — category thread sort.
- `connect/static/src/core/common/store_service_patch.js` — inject provider/sender into post params; open-channel helper.
- `connect/static/src/core/common/composer_messages_patch.js` — composer selector logic + WhatsApp gate.
- `connect/static/src/core/common/composer_messages_patch.xml` — composer selector markup.
- `connect/static/src/core/common/thread_model_patch.js` — expose channel fields to OWL.

**Modified**
- `connect/models/mail.py` — add `connect_message` to `message_type`; add `_to_store` pushing status.
- `connect/models/message.py` — add `mail_message_id` + `channel_id`; make `send()` return the message; support outbound MMS `media_urls`; mirror inbound into channel in `receive()`.
- `connect/models/whatsapp_sender.py` — mirror inbound/outbound WhatsApp into channel; return existing message (already returns).
- `connect/models/__init__.py` — register the two new model files.
- `connect/__manifest__.py` — add security file + JS asset globs.

---

## Phase 1 — Data model & channel find-or-create

### Task 1: Register new model files & add `connect_messages` channel type

**Files:**
- Create: `connect/models/discuss_channel.py`
- Modify: `connect/models/__init__.py`

- [ ] **Step 1: Create the channel model skeleton with the new type**

Create `connect/models/discuss_channel.py`:

```python
# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup

from odoo import api, Command, fields, models
from odoo.tools import html2plaintext

logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    channel_type = fields.Selection(
        selection_add=[('connect_messages', 'Customer Messages')],
        ondelete={'connect_messages': 'cascade'},
    )
    # The customer this conversation belongs to (one channel per partner).
    connect_partner_id = fields.Many2one(
        'res.partner', string='Customer', index='btree_not_null')
    # Phone number we last spoke to the customer on; default reply target.
    connect_number = fields.Char(string='Customer Number')
    # WhatsApp 24h session window (per Twilio/Meta), WhatsApp messages only.
    connect_last_inbound_whatsapp_id = fields.Many2one('mail.message')
    connect_whatsapp_valid_until = fields.Datetime(
        compute='_compute_connect_whatsapp_window')
    connect_whatsapp_window_open = fields.Boolean(
        compute='_compute_connect_whatsapp_window')

    @api.depends('connect_last_inbound_whatsapp_id',
                 'connect_last_inbound_whatsapp_id.create_date')
    def _compute_connect_whatsapp_window(self):
        from datetime import timedelta
        now = fields.Datetime.now()
        for channel in self:
            last = channel.connect_last_inbound_whatsapp_id
            if channel.channel_type == 'connect_messages' and last:
                channel.connect_whatsapp_valid_until = last.create_date + timedelta(hours=24)
                channel.connect_whatsapp_window_open = channel.connect_whatsapp_valid_until > now
            else:
                channel.connect_whatsapp_valid_until = False
                channel.connect_whatsapp_window_open = False
```

- [ ] **Step 2: Register the model**

In `connect/models/__init__.py`, add after `from . import channel`:

```python
from . import discuss_channel
```

(The `discuss_channel_member` import is added in Task 5, when that file is created — do not add it here or the module will fail to import.)

- [ ] **Step 3: RUN TESTS / sanity** — upgrade `connect`; confirm no load error and the selection value exists:

`self.env['discuss.channel']._fields['channel_type'].selection` includes `('connect_messages', 'Customer Messages')`.

- [ ] **Step 4: Commit**

```bash
git add connect/models/discuss_channel.py connect/models/__init__.py
git commit -m "[connect] add connect_messages discuss.channel type and 24h window compute"
```

### Task 2: `_get_connect_channel` find-or-create (shared-inbox membership)

**Files:**
- Modify: `connect/models/discuss_channel.py`
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Write the failing test**

Create `connect/tests/test_connect_discuss_channel.py`:

```python
# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestConnectDiscussChannel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env['discuss.channel']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Acme Customer', 'phone': '+15551230000',
        })
        # An agent user in the Connect User group.
        cls.agent = cls.env['res.users'].create({
            'name': 'Agent A', 'login': 'agent_a',
            'group_ids': [(4, cls.env.ref('connect.group_connect_user').id)],
        })

    def test_get_connect_channel_is_idempotent(self):
        ch1 = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        ch2 = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        self.assertEqual(ch1, ch2, "Must reuse the one per-partner channel")
        self.assertEqual(ch1.channel_type, 'connect_messages')
        self.assertEqual(ch1.connect_partner_id, self.partner)

    def test_get_connect_channel_adds_agents_and_customer(self):
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        member_partners = ch.channel_member_ids.partner_id
        self.assertIn(self.agent.partner_id, member_partners)
        self.assertIn(self.partner, member_partners)

    def test_get_connect_channel_no_create(self):
        ch = self.Channel._get_connect_channel(self.partner)
        self.assertFalse(ch)
```

Add to `connect/tests/__init__.py`:

```python
from . import test_connect_discuss_channel
```

- [ ] **Step 2: RUN TESTS to verify it fails** — Expected: `AttributeError: _get_connect_channel` / failures.

- [ ] **Step 3: Implement `_get_connect_channel`**

Append to `DiscussChannel` in `connect/models/discuss_channel.py`:

```python
    @api.model
    def _connect_agent_partners(self):
        group = self.env.ref('connect.group_connect_user', raise_if_not_found=False)
        if not group:
            return self.env['res.partner']
        users = self.env['res.users'].sudo().search([('all_group_ids', 'in', group.ids)])
        return users.partner_id

    @api.returns('self')
    def _get_connect_channel(self, partner, number=False, create_if_not_found=False):
        """Find-or-create the single connect_messages channel for a partner."""
        if not partner:
            return self.browse()
        channel = self.sudo().search([
            ('channel_type', '=', 'connect_messages'),
            ('connect_partner_id', '=', partner.id),
        ], limit=1)
        if channel:
            if number and channel.connect_number != number:
                channel.connect_number = number
            return channel
        if not create_if_not_found:
            return self.browse()
        members = self._connect_agent_partners() | partner
        channel = self.sudo().with_context(
            mail_create_nosubscribe=True,
        ).create({
            'name': partner.display_name,
            'channel_type': 'connect_messages',
            'connect_partner_id': partner.id,
            'connect_number': number or partner.phone_sanitized,
            'channel_member_ids': [Command.create({'partner_id': p.id}) for p in members],
        })
        return channel
```

- [ ] **Step 4: RUN TESTS to verify pass** — all three pass.

- [ ] **Step 5: Commit**

```bash
git add connect/models/discuss_channel.py connect/tests/test_connect_discuss_channel.py connect/tests/__init__.py
git commit -m "[connect] add _get_connect_channel find-or-create with shared-inbox membership"
```

### Task 3: `connect.message` link fields + `send()` returns the record

**Files:**
- Modify: `connect/models/message.py`
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Write the failing test** (append a method to the test class):

```python
    def test_send_returns_connect_message(self):
        # Patch the Twilio client_send to avoid network and return a fake SID object.
        from unittest.mock import patch

        class _Fake:
            sid = 'SMtest'
            account_sid = 'ACtest'
            messaging_service_sid = False
            num_media = 0
            error_code = None
            error_message = None

        self.agent.connect_user  # ensure connect_user exists in your fixture/env
        with patch.object(type(self.env['connect.message']), 'client_send', return_value=_Fake()):
            msg = self.env['connect.message'].with_user(self.agent).send(
                '+15551230000', 'hello', res_id=self.partner.id, res_model='res.partner',
                outgoing_callerid='+15550000000')
        self.assertTrue(msg, "send() must return the created connect.message")
        self.assertEqual(msg.to_number, '+15551230000')
        self.assertTrue('mail_message_id' in msg._fields)
        self.assertTrue('channel_id' in msg._fields)
```

> Note: `send()` requires the acting user to have a `connect_user` + `outgoing_callerid` unless `outgoing_callerid` is passed. The test passes `outgoing_callerid` explicitly to avoid that dependency.

- [ ] **Step 2: RUN TESTS to verify it fails** — `mail_message_id`/`channel_id` not in `_fields`; `send()` returns `None`.

- [ ] **Step 3: Add fields + return value**

In `connect/models/message.py`, add fields to `ConnectMessage` (after `media_content_type`):

```python
    mail_message_id = fields.Many2one('mail.message', index='btree_not_null',
                                      string='Discuss Message', ondelete='set null')
    channel_id = fields.Many2one('discuss.channel', index='btree_not_null',
                                 string='Discuss Channel', ondelete='set null')
```

At the very end of `def send(self, ...)` (after the chatter block), add:

```python
        return message
```

- [ ] **Step 4: RUN TESTS to verify pass.**

- [ ] **Step 5: Commit**

```bash
git add connect/models/message.py connect/tests/test_connect_discuss_channel.py
git commit -m "[connect] add discuss link fields on connect.message and return record from send()"
```

---

## Phase 2 — Inbound mirroring

### Task 4: Mirror inbound messages into the partner channel

**Files:**
- Modify: `connect/models/discuss_channel.py` (add `_connect_post_inbound`)
- Modify: `connect/models/message.py` (call mirror in `receive()`)
- Modify: `connect/models/whatsapp_sender.py` (mirror inbound WhatsApp)
- Modify: `connect/models/mail.py` (add `connect_message` to `message_type` selection)
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Add `connect_message` message_type** in `connect/models/mail.py` — change the `message_type` selection_add on `MailMessage`:

```python
    message_type = fields.Selection(
        selection_add=[
            ('WhatsApp', 'WhatsApp'),
            ('connect_message', 'Connect Message'),
        ],
        ondelete={
            'WhatsApp': lambda recs: recs.write({'message_type': 'comment'}),
            'connect_message': lambda recs: recs.write({'message_type': 'comment'}),
        },
    )
```

- [ ] **Step 2: Write the failing test** (append):

```python
    def _make_incoming(self, body='hi there', mtype='sms', number='+15551230000'):
        return self.env['connect.message'].sudo().create({
            'message_sid': 'SM' + body[:6], 'from_number': number,
            'to_number': '+15550000000', 'body': body, 'message_type': mtype,
            'status': 'received', 'partner': self.partner.id,
        })

    def test_inbound_mirror_posts_to_channel(self):
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg = self._make_incoming('inbound one')
        msg = ch._connect_post_inbound(cmsg)
        self.assertEqual(msg.message_type, 'connect_message')
        self.assertEqual(msg.author_id, self.partner)
        self.assertEqual(cmsg.mail_message_id, msg)
        self.assertEqual(cmsg.channel_id, ch)
        self.assertIn(msg, ch.message_ids)

    def test_inbound_whatsapp_sets_window(self):
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg = self._make_incoming('wa hello', mtype='WhatsApp')
        msg = ch._connect_post_inbound(cmsg)
        self.assertEqual(ch.connect_last_inbound_whatsapp_id, msg)
        self.assertTrue(ch.connect_whatsapp_window_open)
```

- [ ] **Step 3: RUN TESTS to verify fail** — `_connect_post_inbound` missing.

- [ ] **Step 4: Implement `_connect_post_inbound`** — append to `DiscussChannel`:

```python
    def _connect_post_inbound(self, connect_message):
        """Mirror an incoming connect.message into this channel as a mail.message."""
        self.ensure_one()
        partner = connect_message.partner
        author = partner or self.env.ref('base.partner_root')
        body_txt = connect_message.body or ''
        if connect_message.media_url:
            body = Markup("<div class='d-flex flex-column'>"
                          "<span>{}</span>{}</div>").format(
                              body_txt, connect_message.media_widget)
        else:
            body = Markup("<span>{}</span>").format(body_txt)
        msg = self.sudo().with_context(connect_mirror=True).message_post(
            body=body,
            author_id=author.id,
            message_type='connect_message',
            subtype_xmlid='mail.mt_comment',
        )
        connect_message.write({'mail_message_id': msg.id, 'channel_id': self.id})
        if connect_message.message_type == 'WhatsApp':
            self.connect_last_inbound_whatsapp_id = msg.id
        # Surface in agents' sidebars: pin for all members on new inbound.
        self.channel_member_ids.filtered(lambda m: not m.is_pinned).write({'unpin_dt': False})
        return msg
```

- [ ] **Step 5: Wire SMS/MMS inbound** in `connect/models/message.py` `receive()`. After the chatter post block, where `valid_target and target_msg ...` posts to the record, add a channel mirror keyed on the partner. Locate the line `self.env['connect.settings'].connect_reload_view(target_msg.res_model)` inside the `if valid_target ...` block and **after** it (still inside `if SmsStatus == 'received'`) add:

```python
                # ODU-37: mirror inbound into the partner's Discuss channel.
                try:
                    if partner:
                        channel = self.env['discuss.channel']._get_connect_channel(
                            partner, number=from_number, create_if_not_found=True)
                        channel._connect_post_inbound(message)
                except Exception as e:
                    logger.warning('Connect Discuss mirror failed: %s', e)
```

(`partner` and `message` are already in scope there; `from_number` is defined earlier in the received branch.)

- [ ] **Step 6: Wire WhatsApp inbound.** Inbound WhatsApp also arrives through `connect.message.receive()` (Twilio messaging webhook) with `message_type` resolved to `'WhatsApp'`? Verify: search the WhatsApp inbound path. If WhatsApp inbound creates a `connect.message` with `message_type='WhatsApp'` via `receive()`, Step 5 already covers it. If a separate controller handles WhatsApp inbound, add the same mirror block there. **Action:** grep `connect/controllers` for the WhatsApp inbound route and ensure a `_connect_post_inbound` call exists on the created `connect.message`.

- [ ] **Step 7: RUN TESTS to verify pass.**

- [ ] **Step 8: Commit**

```bash
git add connect/models/discuss_channel.py connect/models/message.py connect/models/mail.py connect/models/whatsapp_sender.py connect/tests/test_connect_discuss_channel.py
git commit -m "[connect] mirror inbound SMS/MMS/WhatsApp into partner Discuss channel"
```

---

## Phase 3 — Outbound send from the channel

### Task 5: `message_post` override + outbound routing + autovacuum

**Files:**
- Modify: `connect/models/discuss_channel.py`
- Create: `connect/models/discuss_channel_member.py`
- Modify: `connect/models/__init__.py`
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Write the failing test** (append):

```python
    def test_outbound_post_sends_sms_and_links(self):
        from unittest.mock import patch

        class _Fake:
            sid = 'SMout'; account_sid = 'ACtest'; messaging_service_sid = False
            num_media = 0; error_code = None; error_message = None

        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        with patch.object(type(self.env['connect.message']), 'client_send', return_value=_Fake()):
            msg = ch.with_user(self.agent).message_post(
                body='reply text', message_type='connect_message',
                connect_provider='sms', connect_sender_id='+15550000000')
        cmsg = self.env['connect.message'].search([('mail_message_id', '=', msg.id)])
        self.assertTrue(cmsg, "Outbound must create a linked connect.message")
        self.assertEqual(cmsg.to_number, '+15551230000')
        self.assertEqual(cmsg.channel_id, ch)

    def test_inbound_mirror_does_not_send(self):
        from unittest.mock import patch
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg_in = self._make_incoming('inbound no send')
        with patch.object(type(self.env['connect.message']), 'client_send') as cs:
            ch._connect_post_inbound(cmsg_in)
            cs.assert_not_called()
```

- [ ] **Step 2: RUN TESTS to verify fail.**

- [ ] **Step 3: Implement override + routing + allowed params** — append to `DiscussChannel`:

```python
    def _get_allowed_message_params(self):
        # Allow the composer to pass provider/sender through the post route.
        return super()._get_allowed_message_params() | {
            'connect_provider', 'connect_sender_id'}

    def message_post(self, *args, **kwargs):
        connect_provider = kwargs.pop('connect_provider', None)
        connect_sender_id = kwargs.pop('connect_sender_id', None)
        is_outbound = (
            self.channel_type == 'connect_messages'
            and kwargs.get('message_type') == 'connect_message'
            and not self.env.context.get('connect_mirror')
        )
        message = super().message_post(*args, **kwargs)
        if is_outbound and message:
            try:
                self._connect_send_outbound(message, connect_provider, connect_sender_id)
            except Exception:
                logger.exception('Connect outbound send failed for channel %s', self.id)
                raise
        return message

    def _connect_recipient(self):
        self.ensure_one()
        if self.connect_number:
            return self.connect_number
        return self.connect_partner_id.phone_sanitized

    def _connect_send_outbound(self, message, provider, sender_id):
        self.ensure_one()
        partner = self.connect_partner_id
        recipient = self._connect_recipient()
        body = html2plaintext(message.body) if message.body else ''
        provider = provider or 'sms'
        if provider == 'whatsapp':
            Sender = self.env['connect.whatsapp_sender']
            sender = Sender.browse(int(sender_id)) if sender_id else Sender.get_default_sender(self.env.user)
            cmsg = sender.send_whatsapp(
                recipient=recipient, body=body,
                res_model='res.partner', res_id=partner.id, raise_on_error=True)
        else:
            media_urls = self._connect_media_urls(message)  # Task 6
            cmsg = self.env['connect.message'].send(
                recipient, body, res_id=partner.id, res_model='res.partner',
                outgoing_callerid=sender_id or None, media_urls=media_urls)
        if cmsg:
            cmsg.sudo().write({'mail_message_id': message.id, 'channel_id': self.id})
        return cmsg

    def _connect_media_urls(self, message):
        # Overridden behavior added in Task 6; default no media.
        return []
```

- [ ] **Step 4: Create the autovacuum** — `connect/models/discuss_channel_member.py`:

```python
# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from odoo import api, models


class DiscussChannelMember(models.Model):
    _inherit = 'discuss.channel.member'

    @api.autovacuum
    def _gc_unpin_connect_channels(self):
        """Unpin read connect_messages channels idle >1 day to keep sidebars clean."""
        one_day_ago = datetime.now() - timedelta(days=1)
        members = self.search([
            ('is_pinned', '=', True),
            ('channel_id.channel_type', '=', 'connect_messages'),
            ('last_seen_dt', '<', one_day_ago),
        ], limit=1000)
        to_unpin = members.filtered(lambda m: m.message_unread_counter == 0)
        to_unpin.unpin_dt = datetime.now()
        for member in to_unpin:
            member._bus_send("discuss.channel/unpin", {"id": member.channel_id.id})
```

Add `from . import discuss_channel_member` to `connect/models/__init__.py` (right after the `discuss_channel` import).

- [ ] **Step 5: RUN TESTS to verify pass.**

- [ ] **Step 6: Commit**

```bash
git add connect/models/discuss_channel.py connect/models/discuss_channel_member.py connect/models/__init__.py connect/tests/test_connect_discuss_channel.py
git commit -m "[connect] route outbound channel posts to Twilio + autovacuum idle channels"
```

### Task 6: Outbound MMS (attachments → Twilio MediaUrl)

**Files:**
- Modify: `connect/models/message.py` (`send()` + `client_send()` accept `media_urls`)
- Modify: `connect/models/discuss_channel.py` (`_connect_media_urls`)
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Write the failing test** (append):

```python
    def test_outbound_media_urls_built_from_attachments(self):
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        att = self.env['ir.attachment'].create({
            'name': 'pic.png', 'datas': 'aGVsbG8=', 'mimetype': 'image/png'})
        msg = self.env['mail.message'].create({
            'model': 'discuss.channel', 'res_id': ch.id, 'message_type': 'connect_message',
            'attachment_ids': [(4, att.id)]})
        urls = ch._connect_media_urls(msg)
        self.assertEqual(len(urls), 1)
        self.assertIn('/web/content/%d' % att.id, urls[0])
        self.assertIn('access_token=', urls[0])
```

- [ ] **Step 2: RUN TESTS to verify fail** — `_connect_media_urls` returns `[]`.

- [ ] **Step 3: Implement media URL builder** — replace `_connect_media_urls` in `discuss_channel.py`:

```python
    def _connect_media_urls(self, message):
        urls = []
        base = self.env['connect.settings'].sudo().get_param('api_url') or self.get_base_url()
        for att in message.attachment_ids:
            token = att.sudo().generate_access_token()[0]
            urls.append('%s/web/content/%d?access_token=%s&download=true' % (
                base.rstrip('/'), att.id, token))
        return urls
```

- [ ] **Step 4: Thread `media_urls` through `send()`/`client_send()`** in `connect/models/message.py`.

Change `def send(self, recipient, body, res_id=None, res_model=None, outgoing_callerid=None):` to:

```python
    def send(self, recipient, body, res_id=None, res_model=None, outgoing_callerid=None, media_urls=None):
```

Change the `message = self.client_send(recipient, sender, body)` line to:

```python
        message = self.client_send(recipient, sender, body, media_urls=media_urls)
```

If media was sent, set the type to mms — after `message_data` is built, add:

```python
        if media_urls:
            message_data['message_type'] = 'mms'
            message_data['num_media'] = len(media_urls)
```

Change `def client_send(self, recipient, sender, body):` to accept and pass media:

```python
    def client_send(self, recipient, sender, body, media_urls=None):
        api_url = self.env['connect.settings'].get_param('api_url')
        status_callback_url = urljoin(api_url, 'twilio/webhook/message_status')
        try:
            client = self.env['connect.settings'].get_client(region=False)
            create_kwargs = {
                'to': recipient, 'from_': sender, 'body': body,
                'status_callback': status_callback_url,
            }
            if media_urls:
                create_kwargs['media_url'] = media_urls
            message = client.messages.create(**create_kwargs)
            if message.error_code:
                return False
            logger.info('Message to %s is sent.', recipient)
            return message
        except Exception as e:
            logger.exception(e)
            return False
```

- [ ] **Step 5: RUN TESTS to verify pass.**

- [ ] **Step 6: Commit**

```bash
git add connect/models/message.py connect/models/discuss_channel.py connect/tests/test_connect_discuss_channel.py
git commit -m "[connect] support outbound MMS via tokenized attachment MediaUrl"
```

---

## Phase 4 — Delivery status on the bubble

### Task 7: Push connect status to the Discuss message store

**Files:**
- Modify: `connect/models/mail.py` (`_to_store`)
- Modify: `connect/models/message.py` (status write → bus push)
- Test: `connect/tests/test_connect_discuss_channel.py`

- [ ] **Step 1: Write the failing test** (append):

```python
    def test_to_store_includes_connect_status(self):
        from odoo.addons.mail.tools.discuss import Store
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg = self._make_incoming('status check')
        msg = ch._connect_post_inbound(cmsg)
        cmsg.status = 'delivered'
        store = Store()
        msg._to_store(store)
        data = store.get_result()
        # The mail.message payload must carry connectStatus for linked messages.
        found = any(
            'connectStatus' in rec for rec in _flatten_store(data))
        self.assertTrue(found)
```

Add this helper at module top of the test file (below imports):

```python
def _flatten_store(data):
    out = []
    for value in (data or {}).values():
        if isinstance(value, list):
            out.extend(v for v in value if isinstance(v, dict))
        elif isinstance(value, dict):
            out.append(value)
    return out
```

- [ ] **Step 2: RUN TESTS to verify fail.**

- [ ] **Step 3: Implement `_to_store`** in `connect/models/mail.py` — add to `MailMessage`:

```python
    def _to_store(self, store, **kwargs):
        super()._to_store(store, **kwargs)
        linked = self.filtered(
            lambda m: m.message_type == 'connect_message' and m.connect_message)
        for message in linked:
            store.add(message, {
                'connectStatus': message.connect_message.status,
                'connectMessageType': message.connect_message.message_type,
            })
```

> Ensure `from odoo.addons.mail.tools.discuss import Store` is imported at top of `mail.py` if a type hint is desired; not required for runtime.

- [ ] **Step 4: Push status updates over the bus** — in `connect/models/message.py`, in `update_message_status` after `message.write(vals)` (and in `whatsapp_sender.update_message_status` similarly), add:

```python
            if message.mail_message_id and message.channel_id:
                message.channel_id._bus_send_store(
                    message.mail_message_id, {'connectStatus': message.status})
```

(Place inside the existing `try`, after `message.write(vals)`.)

- [ ] **Step 5: RUN TESTS to verify pass.**

- [ ] **Step 6: Commit**

```bash
git add connect/models/mail.py connect/models/message.py connect/tests/test_connect_discuss_channel.py
git commit -m "[connect] propagate delivery status onto Discuss message bubble"
```

---

## Phase 5 — Security & manifest wiring

### Task 8: Record rule + manifest data/asset registration

**Files:**
- Create: `connect/security/discuss_messages.xml`
- Modify: `connect/__manifest__.py`

- [ ] **Step 1: Create `connect/security/discuss_messages.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Connect agents can see customer message channels; others cannot. -->
    <record id="rule_connect_messages_channel" model="ir.rule">
        <field name="name">Connect: customer message channels for agents</field>
        <field name="model_id" ref="mail.model_discuss_channel"/>
        <field name="domain_force">
            ['|', ('channel_type', '!=', 'connect_messages'),
             ('channel_member_ids.partner_id', 'in', [user.partner_id.id])]
        </field>
        <field name="groups" eval="[(4, ref('connect.group_connect_user'))]"/>
    </record>
</odoo>
```

> This restricts visibility of `connect_messages` channels to their members (agents added at creation), while leaving all other channel types unaffected. Admins (`group_connect_admin`) inherit user. Adjust if a broader "all agents regardless of membership" rule is wanted later.

- [ ] **Step 2: Register security + assets in `connect/__manifest__.py`**

In the `data` list, after `"security/admin_record_rules.xml",` add:

```python
        "security/discuss_messages.xml",
```

In `assets` → `web.assets_backend`, after the existing `"/connect/static/src/core/common/*",` add:

```python
            "/connect/static/src/core/public_web/*",
            "/connect/static/src/core/web/*",
```

(The `core/common/*` glob already covers the new common patches created in Phase 6–7.)

- [ ] **Step 3: RUN TESTS / upgrade** — upgrade `connect`; confirm the module loads, the rule exists, and a non-Connect user cannot read a `connect_messages` channel while an agent member can.

- [ ] **Step 4: Commit**

```bash
git add connect/security/discuss_messages.xml connect/__manifest__.py
git commit -m "[connect] add record rule and register assets for discuss messaging"
```

---

## Phase 6 — Discuss sidebar "Messages" group (frontend)

> Frontend OWL patches have no unit harness in this repo. Each task ends with a **manual verification** in a running Odoo (deliver via push + pull_and_apply + restart, then hard-refresh the browser).

### Task 9: Add the "Messages" sidebar category

**Files:**
- Create: `connect/static/src/core/public_web/discuss_app_model_patch.js`
- Create: `connect/static/src/core/web/discuss_app_category_model_patch.js`
- Create: `connect/static/src/core/common/thread_model_patch.js`

- [ ] **Step 1: Define the category** — `connect/static/src/core/public_web/discuss_app_model_patch.js`:

```javascript
/* @odoo-module */
import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { Record } from "@mail/core/common/record";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(DiscussApp, {
    new(data) {
        const res = super.new(data);
        res.connect_messages = {
            extraClass: "o-mail-DiscussSidebarCategory-connect",
            icon: "fa fa-comments",
            id: "connect_messages",
            name: _t("Messages"),
            hideWhenEmpty: true,
            canView: false,
            canAdd: false,
            serverStateKey: "is_discuss_sidebar_category_connect_messages_open",
            sequence: 22,
        };
        return res;
    },
});

patch(DiscussApp.prototype, {
    setup(env) {
        super.setup(env);
        this.connect_messages = Record.one("DiscussAppCategory");
    },
});
```

- [ ] **Step 2: Sort threads by recency** — `connect/static/src/core/web/discuss_app_category_model_patch.js`:

```javascript
/* @odoo-module */
import { patch } from "@web/core/utils/patch";
import { DiscussAppCategory } from "@mail/core/public_web/discuss_app_category_model";
import { compareDatetime } from "@mail/utils/common/misc";

patch(DiscussAppCategory.prototype, {
    sortThreads(t1, t2) {
        if (this.id === "connect_messages") {
            return compareDatetime(t2.lastInterestDt, t1.lastInterestDt) || t2.id - t1.id;
        }
        return super.sortThreads(t1, t2);
    },
});
```

- [ ] **Step 3: Expose channel fields to OWL** — `connect/static/src/core/common/thread_model_patch.js`:

```javascript
/* @odoo-module */
import { Thread } from "@mail/core/common/thread_model";
import { Record } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    setup() {
        super.setup();
        this.connect_whatsapp_window_open = false;
        this.connect_whatsapp_valid_until = Record.attr(undefined, { type: "datetime" });
        this.connect_partner_id = Record.one("Persona");
    },
});
```

- [ ] **Step 4: Server `_to_store` for channel** — append to `DiscussChannel` in `connect/models/discuss_channel.py`:

```python
    def _to_store(self, store):
        super()._to_store(store)
        for channel in self.filtered(lambda c: c.channel_type == 'connect_messages'):
            store.add(channel, {
                'connect_whatsapp_window_open': channel.connect_whatsapp_window_open,
                'connect_whatsapp_valid_until': channel.connect_whatsapp_valid_until,
            })
```

Add the import near the top of `discuss_channel.py`:

```python
from odoo.addons.mail.tools.discuss import Store  # noqa: F401 (typing/clarity)
```

- [ ] **Step 5: Commit**

```bash
git add connect/static/src/core/public_web/discuss_app_model_patch.js connect/static/src/core/web/discuss_app_category_model_patch.js connect/static/src/core/common/thread_model_patch.js connect/models/discuss_channel.py
git commit -m "[connect] add Messages sidebar category and expose channel fields to Discuss"
```

- [ ] **Step 6: MANUAL VERIFICATION**
  1. Deliver + upgrade `connect`; hard-refresh.
  2. Send a test inbound SMS to a known number (or create a `connect.message` + call `_connect_post_inbound` via shell) so a channel exists for a partner.
  3. Open **Discuss**. Confirm a **"Messages"** category appears in the sidebar with the partner conversation, and the inbound message body shows in the thread.

---

## Phase 7 — Composer provider/sender selector + WhatsApp gate (frontend)

### Task 10: Pass provider/sender from composer through the post route

**Files:**
- Create: `connect/static/src/core/common/store_service_patch.js`
- Create: `connect/static/src/core/common/composer_messages_patch.js`
- Create: `connect/static/src/core/common/composer_messages_patch.xml`

- [ ] **Step 1: Inject provider/sender into post params** — `connect/static/src/core/common/store_service_patch.js`:

```javascript
/* @odoo-module */
import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    async getMessagePostParams({ thread }) {
        const params = await super.getMessagePostParams(...arguments);
        if (thread.channel_type === "connect_messages") {
            params.post_data.message_type = "connect_message";
            params.post_data.connect_provider = thread.connectProvider || "sms";
            if (thread.connectSenderId) {
                params.post_data.connect_sender_id = thread.connectSenderId;
            }
        }
        return params;
    },
});
```

- [ ] **Step 2: Composer selector state** — `connect/static/src/core/common/composer_messages_patch.js`:

```javascript
/* @odoo-module */
import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    get isConnectMessages() {
        return this.thread?.channel_type === "connect_messages";
    },
    get connectProvider() {
        return this.thread?.connectProvider || "sms";
    },
    setConnectProvider(provider) {
        if (this.thread) {
            this.thread.connectProvider = provider;
        }
    },
    get connectWhatsappBlocked() {
        // WhatsApp outside the 24h window needs a template (server enforces too).
        return (
            this.isConnectMessages &&
            this.connectProvider === "whatsapp" &&
            this.thread &&
            !this.thread.connect_whatsapp_window_open
        );
    },
    get placeholder() {
        if (this.connectWhatsappBlocked) {
            return _t("WhatsApp 24h window closed — send a template from the contact form.");
        }
        return super.placeholder;
    },
    get isSendButtonDisabled() {
        return super.isSendButtonDisabled || this.connectWhatsappBlocked;
    },
});
```

Store `connectProvider`/`connectSenderId` on the Thread — extend `thread_model_patch.js` setup (add to the patch from Task 9 Step 3):

```javascript
        this.connectProvider = "sms";
        this.connectSenderId = undefined;
```

- [ ] **Step 3: Selector markup** — `connect/static/src/core/common/composer_messages_patch.xml`:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<templates xml:space="preserve">
    <t t-inherit="mail.Composer" t-inherit-mode="extension">
        <xpath expr="//div[hasclass('o-mail-Composer-actions')]" position="before">
            <div t-if="isConnectMessages" class="o-connect-Composer-channel d-flex align-items-center gap-2 px-2 py-1">
                <select class="form-select form-select-sm w-auto"
                        t-on-change="(ev) => this.setConnectProvider(ev.target.value)">
                    <option value="sms" t-att-selected="connectProvider === 'sms'">SMS / MMS</option>
                    <option value="whatsapp" t-att-selected="connectProvider === 'whatsapp'">WhatsApp</option>
                </select>
            </div>
        </xpath>
    </t>
</templates>
```

> The exact xpath anchor (`o-mail-Composer-actions`) must be confirmed against the running `mail.Composer` template; if it differs, anchor before the send button container instead. This is the one frontend selector that needs a quick DOM check in the target build.

- [ ] **Step 4: Commit**

```bash
git add connect/static/src/core/common/store_service_patch.js connect/static/src/core/common/composer_messages_patch.js connect/static/src/core/common/composer_messages_patch.xml connect/static/src/core/common/thread_model_patch.js
git commit -m "[connect] add Discuss composer provider selector and WhatsApp window gate"
```

- [ ] **Step 5: MANUAL VERIFICATION**
  1. Deliver + upgrade; hard-refresh.
  2. Open a customer conversation in **Discuss → Messages**.
  3. With **SMS** selected, type a reply and send → confirm the customer receives the SMS, a `connect.message` (outgoing) is created and linked (`mail_message_id`, `channel_id`), and the partner chatter still shows the message (keep-both).
  4. Switch to **WhatsApp**: within an open 24h window, send → WhatsApp delivered; outside the window the composer is disabled with the template hint.
  5. Attach an image with **SMS** selected and send → recipient receives an MMS.
  6. Reply from the customer phone → message appears live in the same conversation and pins it in agents' sidebars.

---

## Phase 8 — Final integration check & docs

### Task 11: End-to-end pass and changelog

- [ ] **Step 1:** Run the full backend suite: `RUN TESTS` (all `test_connect_discuss_channel` green) plus the existing `connect` tests to confirm no regressions.
- [ ] **Step 2:** Manual end-to-end across SMS, MMS, WhatsApp (in/out), shared-inbox visibility (two agent users), and idle auto-unpin (run the autovacuum, confirm a read idle channel unpins).
- [ ] **Step 3:** Update `connect` module `version` in `__manifest__.py` (bump patch) and add a one-line note to any module changelog/readme if present.
- [ ] **Step 4: Commit**

```bash
git add connect/__manifest__.py
git commit -m "[connect] bump version for ODU-37 discuss messaging"
```

- [ ] **Step 5:** Push branch and open PR referencing ODU-37 / #118 (only when the user asks to push).

---

## Self-review — spec coverage

- Per-partner channel in a "Messages" Discuss group → Tasks 1–2, 9. ✓
- SMS + MMS + WhatsApp in/out → inbound Task 4; outbound text Task 5; MMS Task 6; WhatsApp gate Task 10. ✓
- Shared inbox (all agents) → Task 2 membership + Task 8 rule + Task 5 autovacuum. ✓
- Keep-both chatter → preserved: `receive()`/`send()`/`send_whatsapp()` chatter posts untouched; channel mirror is additive (Tasks 4–5). ✓
- Status on bubble → Task 7. ✓
- 24h WhatsApp window → server already enforces in `send_whatsapp`; channel compute (Task 1) + composer gate (Task 10). ✓
- Security → Task 8. ✓
- Testing via `run_odoo_shell`/standard runner → noted in env section; backend tasks ship tests. ✓

**Known follow-ups (out of scope, per spec):** per-agent assignment/routing; "Discuss + link" chatter mode; group MMS; reactions/typing beyond core. **One spec ambiguity resolved here:** shared-inbox membership is implemented as *explicit membership of all Connect agents at channel creation* (not group auto-subscription) for reliability; revisit if it doesn't scale.

**Frontend caveats to verify in the target build (not blockers):** the `mail.Composer` xpath anchor (Task 10 Step 3); the WhatsApp inbound route location (Task 4 Step 6). Both flagged inline.
