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
