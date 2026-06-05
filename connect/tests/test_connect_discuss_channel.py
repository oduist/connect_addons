# -*- coding: utf-8 -*-
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
        # An agent user in the Connect User group.
        cls.agent = cls.env['res.users'].create({
            'name': 'Agent A', 'login': 'agent_a',
            'group_ids': [(4, cls.env.ref('connect.group_connect_user').id)],
        })

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
