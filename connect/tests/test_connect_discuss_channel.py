# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


def _flatten_store(data):
    out = []
    for value in (data or {}).values():
        if isinstance(value, list):
            out.extend(v for v in value if isinstance(v, dict))
        elif isinstance(value, dict):
            out.append(value)
    return out


@tagged("post_install", "-at_install")
class TestConnectDiscussChannel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env['discuss.channel']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Acme Customer', 'phone': '+15551230000',
        })
        # An internal agent user in the Connect User group (internal user is
        # required to create mail.message records when posting in the channel).
        cls.agent = cls.env['res.users'].create({
            'name': 'Agent A', 'login': 'agent_a',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('connect.group_connect_user').id),
            ],
        })
        # The line every outgoing message is sent from.
        cls.default_callerid = cls.env['connect.outgoing_callerid'].create({
            'friendly_name': 'Main line', 'number': '+15559990000',
            'callerid_type': 'number', 'is_default': True,
        })

    # Destination for the New SMS tests. These assert on find-or-create, so the
    # number must have no contact or conversation of its own: a real number
    # would match live data and the tests would resume that instead of their
    # own fixture. 555-01xx is the reserved fictional range.
    NEW_SMS_NUMBER = '+12125550111'

    def _assert_new_sms_number_unused(self):
        """Fail loudly if the destination picked above ever gains real data."""
        self.assertFalse(self.Channel.sudo().search([
            ('channel_type', '=', 'connect_messages'),
            ('connect_number', '=', self.NEW_SMS_NUMBER),
        ]), '%s must not already have a conversation' % self.NEW_SMS_NUMBER)
        self.assertFalse(self.env['res.partner'].sudo().search([
            ('phone_sanitized', '=', self.NEW_SMS_NUMBER),
        ]), '%s must not already have a contact' % self.NEW_SMS_NUMBER)

    def _make_incoming(self, body='hi there', mtype='sms', number='+15551230000'):
        return self.env['connect.message'].sudo().create({
            'message_sid': 'SM' + body[:6], 'from_number': number,
            'to_number': '+15550000000', 'body': body, 'message_type': mtype,
            'status': 'received', 'partner': self.partner.id,
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

    def test_send_returns_connect_message(self):
        from unittest.mock import patch

        class _Fake:
            sid = 'SMtest'
            account_sid = 'ACtest'
            messaging_service_sid = False
            num_media = 0
            error_code = None
            error_message = None

        with patch.object(type(self.env['connect.message']), 'client_send', return_value=_Fake()):
            msg = self.env['connect.message'].with_user(self.agent).send(
                '+15551230000', 'hello', res_id=self.partner.id, res_model='res.partner',
                outgoing_callerid='+15550000000')
        self.assertTrue(msg, "send() must return the created connect.message")
        self.assertEqual(msg.to_number, '+15551230000')
        self.assertIn('mail_message_id', msg._fields)
        self.assertIn('channel_id', msg._fields)

    def test_inbound_mirror_posts_to_channel(self):
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg = self._make_incoming('inbound one')
        msg = ch._connect_post_inbound(cmsg)
        self.assertEqual(msg.message_type, 'connect_message')
        self.assertEqual(msg.author_id, self.partner)
        self.assertEqual(cmsg.channel_message_id, msg)
        self.assertEqual(cmsg.channel_id, ch)
        self.assertIn(msg, ch.message_ids)

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

    def test_inbound_whatsapp_sets_window(self):
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg = self._make_incoming('wa hello', mtype='whatsapp')
        msg = ch._connect_post_inbound(cmsg)
        self.assertEqual(ch.connect_last_inbound_whatsapp_id, msg)
        self.assertTrue(ch.connect_whatsapp_window_open)

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
                connect_provider='sms')
        cmsg = self.env['connect.message'].search([('channel_message_id', '=', msg.id)])
        self.assertTrue(cmsg, "Outbound must create a linked connect.message")
        self.assertEqual(cmsg.to_number, '+15551230000')
        self.assertEqual(cmsg.channel_id, ch)
        self.assertEqual(cmsg.from_number, self.default_callerid.number,
                         'a channel with no line of its own falls back to the default')

    def test_inbound_mirror_does_not_send(self):
        from unittest.mock import patch
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg_in = self._make_incoming('inbound no send')
        with patch.object(type(self.env['connect.message']), 'client_send') as cs:
            ch._connect_post_inbound(cmsg_in)
            cs.assert_not_called()

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

    def test_number_only_channel_created_when_no_partner(self):
        """_get_connect_channel creates a phone-number-only channel when partner is falsy."""
        unknown_number = '+19995550001'
        ch = self.Channel._get_connect_channel(
            self.env['res.partner'], number=unknown_number, create_if_not_found=True)
        self.assertTrue(ch, "Must create a channel even without a partner")
        self.assertEqual(ch.channel_type, 'connect_messages')
        self.assertFalse(ch.connect_partner_id)
        self.assertEqual(ch.connect_number, unknown_number)
        self.assertEqual(ch.name, unknown_number)

    def test_number_only_channel_is_idempotent(self):
        unknown_number = '+19995550002'
        ch1 = self.Channel._get_connect_channel(
            self.env['res.partner'], number=unknown_number, create_if_not_found=True)
        ch2 = self.Channel._get_connect_channel(
            self.env['res.partner'], number=unknown_number, create_if_not_found=True)
        self.assertEqual(ch1, ch2, "Must reuse the existing number-only channel")

    def test_connect_create_partner_links_channel(self):
        unknown_number = '+19995550003'
        ch = self.Channel._get_connect_channel(
            self.env['res.partner'], number=unknown_number, create_if_not_found=True)
        result = ch.connect_create_partner(partner_name='New Customer')
        self.assertTrue(result['partner_id'])
        self.assertEqual(result['partner_name'], 'New Customer')
        # Channel must now be linked to the partner.
        self.assertEqual(ch.connect_partner_id.id, result['partner_id'])
        self.assertEqual(ch.name, 'New Customer')
        partner = self.env['res.partner'].browse(result['partner_id'])
        self.assertIn(partner, ch.channel_member_ids.partner_id)
        # New contact gets the default mail "smiley" avatar.
        self.assertTrue(partner.image_1920, "new contact must get a default avatar")

    def test_connect_create_partner_backfills_messages(self):
        unknown_number = '+19995550004'
        ch = self.Channel._get_connect_channel(
            self.env['res.partner'], number=unknown_number, create_if_not_found=True)
        msg = self.env['connect.message'].sudo().create({
            'message_sid': 'SMbackfill', 'from_number': unknown_number,
            'to_number': '+15550000000', 'body': 'test', 'message_type': 'sms',
            'status': 'received',
        })
        self.assertFalse(msg.partner)
        ch.connect_create_partner(partner_name='Back Customer')
        self.assertTrue(msg.partner)

    def test_to_store_includes_connect_status(self):
        from odoo.addons.mail.tools.discuss import Store
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        cmsg = self._make_incoming('status check')
        msg = ch._connect_post_inbound(cmsg)
        cmsg.status = 'delivered'
        store = Store()
        store.add(msg)
        data = store.get_result()
        found = any('connectStatus' in rec for rec in _flatten_store(data))
        self.assertTrue(found)

    def test_whatsapp_window_matches_inbound(self):
        """Regression: a clean-number inbound WhatsApp lets a reply send within
        the 24h window (the window lookup must match the stored clean number)."""
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

    def test_whatsapp_window_raises_without_inbound(self):
        """No prior inbound WhatsApp -> must refuse and ask for a template."""
        from unittest.mock import patch
        from odoo.exceptions import ValidationError

        sender = self.env['connect.whatsapp_sender'].create({
            'number': '+15550000001', 'status': 'ONLINE',
        })
        with patch.object(type(self.env['oduist.license']), 'check_license', return_value=True):
            with self.assertRaises(ValidationError):
                sender.send_whatsapp(recipient='+19998887777', body='cold')

    def test_get_connect_channel_uses_explicit_provider(self):
        # Number-only branch: provider comes from the argument, number stored clean.
        ch = self.Channel._get_connect_channel(
            self.env['res.partner'], number='+19995551111',
            provider='whatsapp', create_if_not_found=True)
        self.assertEqual(ch.connect_channel_provider, 'whatsapp')
        self.assertEqual(ch.connect_number, '+19995551111')  # stored clean
        # Partner-keyed branch (the actual bug site): provider also honoured.
        pch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000',
            provider='whatsapp', create_if_not_found=True)
        self.assertEqual(pch.connect_channel_provider, 'whatsapp')
        self.assertEqual(pch.connect_partner_id, self.partner)

    def test_inbound_whatsapp_with_contact_reuses_channel(self):
        from unittest.mock import patch
        Msg = self.env['connect.message']
        # Use a VALID number so phone_sanitized populates and get_partner_by_number
        # resolves the contact (the fictional +1555... range does not sanitize).
        number = '+12125550123'
        cust = self.env['res.partner'].create({'name': 'WA Cust', 'phone': number})
        self.assertTrue(cust.phone_sanitized, 'precondition: number must sanitize')
        # Contact already linked to its connect_messages channel.
        ch = self.Channel._get_connect_channel(
            cust, number=number, provider='whatsapp', create_if_not_found=True)

        def _gp(key, *a, **k):
            return 'ACtest' if key == 'account_sid' else ''
        params = {
            'AccountSid': 'ACtest', 'SmsStatus': 'received',
            'From': 'whatsapp:' + number, 'To': 'whatsapp:+15550000000',
            'Body': 'second', 'MessageSid': 'SMsecond', 'NumMedia': '0',
        }
        # Run as the real webhook user (production identity) so the
        # connect.message_configuration lookup in receive() does not AccessError
        # and the Discuss mirror actually runs — otherwise this test passes
        # vacuously without exercising the channel-reuse path.
        webhook_user = self.env.ref('connect.user_connect_webhook')
        with patch.object(type(self.env['oduist.license']), 'check_license', return_value=True), \
             patch.object(type(self.env['connect.settings']), 'get_param', side_effect=_gp):
            Msg.with_user(webhook_user).receive(params)

        # Search by NUMBER, not partner: the bug created a number-only duplicate
        # (connect_partner_id=False) which a partner-filtered search would miss.
        channels = self.Channel.search([
            ('channel_type', '=', 'connect_messages'),
            ('connect_number', '=', number)])
        self.assertEqual(channels, ch, "must reuse the existing channel, not create a duplicate")
        msg = Msg.search([('message_sid', '=', 'SMsecond')])
        self.assertEqual(msg.from_number, number)
        self.assertEqual(msg.message_type, 'whatsapp')

    def test_mail_message_type_maps_to_capitalized(self):
        Msg = self.env['connect.message']
        wa = Msg.sudo().create({'message_sid': 'SMm1', 'from_number': '+1',
            'to_number': '+2', 'body': 'x', 'message_type': 'whatsapp', 'status': 'received'})
        sms = Msg.sudo().create({'message_sid': 'SMm2', 'from_number': '+1',
            'to_number': '+2', 'body': 'x', 'message_type': 'sms', 'status': 'received'})
        # mail.message / mail.notification selections use the capitalized 'WhatsApp'.
        self.assertEqual(wa._mail_message_type(), 'WhatsApp')
        self.assertEqual(sms._mail_message_type(), 'sms')

    def test_inbound_whatsapp_chatter_does_not_break_mirror(self):
        """Regression: when receive() posts to the target record's chatter, the
        mail.message message_type must use the mail convention ('WhatsApp'), not
        the lowercase connect provider. Otherwise message_post raises 'Wrong value
        for mail.message.message_type: whatsapp', receive() aborts, and the Discuss
        mirror is skipped (channel_id stays NULL)."""
        from unittest.mock import patch
        Msg = self.env['connect.message']
        number = '+12125550124'
        our = '+15550000000'
        cust = self.env['res.partner'].create({'name': 'WA Cust3', 'phone': number})
        # A prior outbound linked to the partner's chatter makes the next inbound
        # resolve a VALID target -> the chatter-post branch of receive() runs.
        Msg.sudo().create({
            'message_sid': 'SMprior', 'from_number': our, 'to_number': number,
            'body': 'prior', 'message_type': 'whatsapp', 'status': 'sent',
            'res_model': 'res.partner', 'res_id': cust.id, 'sender_user': self.agent.id,
        })

        def _gp(key, *a, **k):
            return 'ACtest' if key == 'account_sid' else ''
        params = {
            'AccountSid': 'ACtest', 'SmsStatus': 'received',
            'From': 'whatsapp:' + number, 'To': 'whatsapp:' + our,
            'Body': 'inbound after', 'MessageSid': 'SMafter', 'NumMedia': '0',
        }
        webhook_user = self.env.ref('connect.user_connect_webhook')
        with patch.object(type(self.env['oduist.license']), 'check_license', return_value=True), \
             patch.object(type(self.env['connect.settings']), 'get_param', side_effect=_gp):
            Msg.with_user(webhook_user).receive(params)

        new = Msg.search([('message_sid', '=', 'SMafter')])
        self.assertTrue(new.channel_id, "inbound must be mirrored to Discuss (channel_id set)")
        self.assertTrue(new.mail_message_id, "inbound must have a mirrored mail.message")
        # The contact-chatter post must be a quiet log note (mt_note), not a
        # comment — a comment emails followers and yields a red delivery-failure
        # envelope when no SMTP is configured.
        self.assertEqual(new.mail_message_id.subtype_id, self.env.ref('mail.mt_note'))
        # ...and carry a display-only WhatsApp notification so the note shows the
        # WhatsApp logo (no email: is_read + 'ready' status).
        wa_notif = new.mail_message_id.notification_ids.filtered(
            lambda n: n.notification_type == 'WhatsApp')
        self.assertTrue(wa_notif, "inbound note must carry a WhatsApp marker notification")
        self.assertEqual(wa_notif.notification_status, 'ready')

    def test_inbound_known_partner_copies_to_partner_chatter(self):
        """Inbound from an existing partner (no prior thread record) still posts a
        copy to the partner's own chatter, and mirrors into Discuss."""
        from unittest.mock import patch
        Msg = self.env['connect.message']
        number = '+12125550133'
        cust = self.env['res.partner'].create({'name': 'Copy Cust', 'phone': number})
        self.assertTrue(cust.phone_sanitized, 'precondition: number must sanitize')

        def _gp(key, *a, **k):
            return 'ACtest' if key == 'account_sid' else ''
        params = {
            'AccountSid': 'ACtest', 'SmsStatus': 'received',
            'From': number, 'To': '+15550000000',
            'Body': 'hello there', 'MessageSid': 'SMcopy', 'NumMedia': '0',
        }
        webhook_user = self.env.ref('connect.user_connect_webhook')
        with patch.object(type(self.env['oduist.license']), 'check_license', return_value=True), \
             patch.object(type(self.env['connect.settings']), 'get_param', side_effect=_gp):
            Msg.with_user(webhook_user).receive(params)
        new = Msg.search([('message_sid', '=', 'SMcopy')])
        # Copy landed on the partner's own record...
        self.assertTrue(new.mail_message_id, 'inbound from known partner must copy to chatter')
        self.assertEqual(new.mail_message_id.model, 'res.partner')
        self.assertEqual(new.mail_message_id.res_id, cust.id)
        # ...and was also mirrored into the Discuss channel.
        self.assertTrue(new.channel_id)
        self.assertTrue(new.channel_message_id)

    def test_outbound_from_chatter_mirrors_to_existing_thread(self):
        """Outbound sent from a record's chatter is mirrored into the existing
        Discuss thread when one exists."""
        from unittest.mock import patch
        number = '+12125550150'
        cust = self.env['res.partner'].create({'name': 'Out Cust', 'phone': number})
        self.assertTrue(cust.phone_sanitized, 'precondition: number must sanitize')
        ch = self.Channel._get_connect_channel(cust, number=number, create_if_not_found=True)

        class _Fake:
            sid = 'SMch'; account_sid = 'ACtest'; messaging_service_sid = False
            num_media = 0; error_code = None; error_message = None
        with patch.object(type(self.env['connect.message']), 'client_send', return_value=_Fake()):
            msg = self.env['connect.message'].with_user(self.agent).send(
                number, 'from chatter', res_id=cust.id, res_model='res.partner',
                outgoing_callerid='+15550000000')
        self.assertEqual(msg.channel_id, ch, 'outbound must mirror into the existing thread')
        self.assertTrue(msg.channel_message_id)
        self.assertIn(msg.channel_message_id, ch.message_ids)

    def test_outbound_from_chatter_no_thread_no_mirror(self):
        """Outbound from chatter must NOT create a Discuss thread when none exists."""
        from unittest.mock import patch
        number = '+12125550151'
        cust = self.env['res.partner'].create({'name': 'Cold Cust', 'phone': number})
        self.assertTrue(cust.phone_sanitized, 'precondition: number must sanitize')

        class _Fake:
            sid = 'SMnt'; account_sid = 'ACtest'; messaging_service_sid = False
            num_media = 0; error_code = None; error_message = None
        with patch.object(type(self.env['connect.message']), 'client_send', return_value=_Fake()):
            msg = self.env['connect.message'].with_user(self.agent).send(
                number, 'cold outbound', res_id=cust.id, res_model='res.partner',
                outgoing_callerid='+15550000000')
        self.assertFalse(msg.channel_id, 'no existing thread -> must not create/mirror')
        self.assertFalse(self.Channel.search([
            ('channel_type', '=', 'connect_messages'),
            ('connect_partner_id', '=', cust.id)]))

    def test_start_sms_channel_normalizes_number_and_creates_contact(self):
        """The typed number is the destination only: it is normalized to E.164
        and gets a contact of its own when the number is unknown."""
        self._assert_new_sms_number_unused()
        res = self.Channel.with_user(self.agent).connect_start_sms_channel(
            ' +1 (212) 555-0111 ')
        channel = self.Channel.browse(res['channel_id'])
        self.assertEqual(channel.channel_type, 'connect_messages')
        self.assertEqual(channel.connect_number, self.NEW_SMS_NUMBER)
        self.assertTrue(channel.connect_partner_id, 'contact must be created')
        self.assertEqual(channel.connect_partner_id.phone_sanitized,
                         self.NEW_SMS_NUMBER)
        self.assertIn(channel.connect_partner_id, channel.channel_member_ids.partner_id)
        self.assertIn(self.agent.partner_id, channel.channel_member_ids.partner_id)

    def test_start_sms_channel_reuses_known_contact(self):
        """A number that already has a contact must not get a second one."""
        cust = self.env['res.partner'].create({
            'name': 'Known Cust', 'phone': '+12125550160'})
        self.assertTrue(cust.phone_sanitized, 'precondition: number must sanitize')
        res = self.Channel.with_user(self.agent).connect_start_sms_channel(
            '+1 212-555-0160')
        channel = self.Channel.browse(res['channel_id'])
        self.assertEqual(channel.connect_partner_id, cust)

    def test_start_sms_channel_reuses_number_only_channel(self):
        """A conversation opened by an earlier inbound is resumed, and the new
        contact is linked to it instead of a second thread being created."""
        self._assert_new_sms_number_unused()
        existing = self.Channel._get_connect_channel(
            number=self.NEW_SMS_NUMBER, provider='sms', create_if_not_found=True)
        self.assertFalse(existing.connect_partner_id, 'precondition: no contact')
        res = self.Channel.with_user(self.agent).connect_start_sms_channel(
            '+1 212 555 0111')
        self.assertEqual(res['channel_id'], existing.id,
                         'must resume the conversation, not start a second one')
        self.assertTrue(existing.connect_partner_id, 'contact must be linked')

    def test_start_sms_channel_rejects_invalid_number(self):
        with self.assertRaises(ValidationError):
            self.Channel.with_user(self.agent).connect_start_sms_channel('not a number')

    def test_start_sms_channel_without_default_number_raises(self):
        """Without a default line we cannot send, so say so up front rather
        than letting the first message fail silently in Discuss."""
        self._assert_new_sms_number_unused()
        self.default_callerid.is_default = False
        with self.assertRaises(ValidationError):
            self.Channel.with_user(self.agent).connect_start_sms_channel(
                self.NEW_SMS_NUMBER)
        self.assertFalse(self.Channel.search([
            ('channel_type', '=', 'connect_messages'),
            ('connect_number', '=', self.NEW_SMS_NUMBER)]))

    def test_inbound_stamps_the_line_the_customer_wrote_to(self):
        """A conversation the customer starts runs on the line they messaged,
        whatever the default is."""
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        # Inbound arrived on +15550000000 (see _make_incoming).
        ch._connect_post_inbound(self._make_incoming('inbound'))
        self.assertEqual(ch.connect_sender_number, '+15550000000')

    def test_outbound_reply_stays_on_the_conversation_line(self):
        """Replies go out on the conversation's own line, so changing the
        default never moves a conversation already under way."""
        from unittest.mock import patch

        class _Fake:
            sid = 'SMdef'; account_sid = 'ACtest'; messaging_service_sid = False
            num_media = 0; error_code = None; error_message = None

        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        ch._connect_post_inbound(self._make_incoming('inbound'))
        with patch.object(type(self.env['connect.message']), 'client_send',
                          return_value=_Fake()):
            msg = ch.with_user(self.agent).message_post(
                body='reply text', message_type='connect_message',
                connect_provider='sms')
        cmsg = self.env['connect.message'].search([('channel_message_id', '=', msg.id)])
        self.assertEqual(cmsg.from_number, '+15550000000',
                         'must reply on the line the customer wrote to')

    def test_outbound_reply_on_legacy_conversation_uses_last_inbound(self):
        """Conversations that predate the per-channel line keep replying on
        the number the customer last messaged."""
        from unittest.mock import patch

        class _Fake:
            sid = 'SMleg'; account_sid = 'ACtest'; messaging_service_sid = False
            num_media = 0; error_code = None; error_message = None

        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        ch._connect_post_inbound(self._make_incoming('inbound'))
        # Simulate a channel created before connect_sender_number existed.
        ch.connect_sender_number = False
        with patch.object(type(self.env['connect.message']), 'client_send',
                          return_value=_Fake()):
            msg = ch.with_user(self.agent).message_post(
                body='reply text', message_type='connect_message',
                connect_provider='sms')
        cmsg = self.env['connect.message'].search([('channel_message_id', '=', msg.id)])
        self.assertEqual(cmsg.from_number, '+15550000000')

    def test_start_sms_channel_uses_picked_line(self):
        """The dialog's line is the one the new conversation runs on."""
        second = self.env['connect.outgoing_callerid'].create({
            'friendly_name': 'Second line', 'number': '+15558880000',
            'callerid_type': 'number',
        })
        self._assert_new_sms_number_unused()
        res = self.Channel.with_user(self.agent).connect_start_sms_channel(
            self.NEW_SMS_NUMBER, second.number)
        channel = self.Channel.browse(res['channel_id'])
        self.assertEqual(channel.connect_sender_number, second.number)

    def test_start_sms_channel_defaults_to_default_line(self):
        self._assert_new_sms_number_unused()
        res = self.Channel.with_user(self.agent).connect_start_sms_channel(
            self.NEW_SMS_NUMBER)
        channel = self.Channel.browse(res['channel_id'])
        self.assertEqual(channel.connect_sender_number,
                         self.default_callerid.number)

    def test_start_sms_channel_rejects_unknown_line(self):
        """The line comes from the browser, so it must be one we offer."""
        with self.assertRaises(ValidationError):
            self.Channel.with_user(self.agent).connect_start_sms_channel(
                self.NEW_SMS_NUMBER, '+19998887777')

    def test_start_sms_channel_keeps_the_line_of_an_existing_conversation(self):
        """Resuming a conversation must not move it onto another line."""
        second = self.env['connect.outgoing_callerid'].create({
            'friendly_name': 'Second line', 'number': '+15558880000',
            'callerid_type': 'number',
        })
        self._assert_new_sms_number_unused()
        existing = self.Channel._get_connect_channel(
            number=self.NEW_SMS_NUMBER, provider='sms', create_if_not_found=True)
        existing.connect_sender_number = '+15557770000'
        res = self.Channel.with_user(self.agent).connect_start_sms_channel(
            self.NEW_SMS_NUMBER, second.number)
        self.assertEqual(res['channel_id'], existing.id)
        self.assertEqual(existing.connect_sender_number, '+15557770000')

    def test_sms_sender_options_offer_twilio_numbers_only(self):
        """Verified caller IDs are voice-only: Twilio rejects them as the From
        of a message, so they must not be offered."""
        self.env['connect.outgoing_callerid'].create({
            'friendly_name': 'Personal mobile', 'number': '+15551112222',
            'callerid_type': 'outgoing_callerid',
        })
        options = self.Channel.with_user(self.agent).connect_sms_sender_options()
        numbers = [o['number'] for o in options['options']]
        self.assertIn(self.default_callerid.number, numbers)
        self.assertNotIn('+15551112222', numbers)
        self.assertEqual(options['default'], self.default_callerid.number)

    def test_connect_sidebar_category_open_setting_persists(self):
        """The 'Messages' sidebar category needs a real res.users.settings field
        so its collapse/expand toggle reads and persists (like channel/chat)."""
        Settings = self.env['res.users.settings']
        self.assertIn('is_discuss_sidebar_category_connect_messages_open', Settings._fields)
        s = Settings._find_or_create_for_user(self.agent)
        self.assertTrue(s.is_discuss_sidebar_category_connect_messages_open, 'defaults to open')
        s.set_res_users_settings(
            {'is_discuss_sidebar_category_connect_messages_open': False})
        self.assertFalse(s.is_discuss_sidebar_category_connect_messages_open)

    def test_archive_then_inbound_resurfaces(self):
        """Archiving unpins the agent's member; a new inbound re-pins it."""
        ch = self.Channel._get_connect_channel(
            self.partner, number='+15551230000', create_if_not_found=True)
        member = ch.channel_member_ids.filtered(
            lambda m: m.partner_id == self.agent.partner_id)
        self.assertTrue(member.is_pinned, 'precondition: thread starts pinned')
        # Agent archives (unpins) the thread.
        ch.with_user(self.agent).channel_pin(pinned=False)
        member.invalidate_recordset(['is_pinned', 'unpin_dt'])
        self.assertFalse(member.is_pinned, 'archive must unpin the agent member')
        # A new inbound un-archives (re-pins) it.
        cmsg = self._make_incoming('back again')
        ch._connect_post_inbound(cmsg)
        member.invalidate_recordset(['is_pinned', 'unpin_dt'])
        self.assertTrue(member.is_pinned, 'new message must un-archive (re-pin) the thread')

    def test_inbound_reply_quotes_parent_in_discuss(self):
        """A customer reply (WhatsApp OriginalRepliedMessageSid) quotes the parent
        message's Discuss mirror via parent_id."""
        from unittest.mock import patch
        Msg = self.env['connect.message']
        number = '+12125550160'
        our = '+15550000000'
        cust = self.env['res.partner'].create({'name': 'Reply Cust', 'phone': number})
        self.assertTrue(cust.phone_sanitized, 'precondition: number must sanitize')
        ch = self.Channel._get_connect_channel(
            cust, number=number, provider='whatsapp', create_if_not_found=True)
        # Earlier outbound, mirrored into the Discuss thread.
        parent = Msg.sudo().create({
            'message_sid': 'WAparent', 'from_number': our, 'to_number': number,
            'body': 'Goes here', 'message_type': 'whatsapp', 'status': 'sent',
            'res_model': 'res.partner', 'res_id': cust.id, 'sender_user': self.agent.id,
        })
        parent_mirror = ch._connect_post_outbound(parent)
        self.assertEqual(parent.channel_message_id, parent_mirror)

        def _gp(key, *a, **k):
            return 'ACtest' if key == 'account_sid' else ''
        params = {
            'AccountSid': 'ACtest', 'SmsStatus': 'received',
            'From': 'whatsapp:' + number, 'To': 'whatsapp:' + our,
            'Body': 'Reply', 'MessageSid': 'WAreply', 'NumMedia': '0',
            'OriginalRepliedMessageSid': 'WAparent',
        }
        webhook_user = self.env.ref('connect.user_connect_webhook')
        with patch.object(type(self.env['oduist.license']), 'check_license', return_value=True), \
             patch.object(type(self.env['connect.settings']), 'get_param', side_effect=_gp):
            Msg.with_user(webhook_user).receive(params)
        new = Msg.search([('message_sid', '=', 'WAreply')])
        self.assertEqual(new.parent_message, parent, 'reply must link the parent connect.message')
        self.assertTrue(new.channel_message_id)
        self.assertEqual(new.channel_message_id.parent_id, parent_mirror,
                         "Discuss mirror must quote the parent's mirror (reply)")
