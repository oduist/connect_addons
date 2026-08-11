# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase


class TestConnectDiscussChannel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env['mail.channel']
        cls.Message = cls.env['connect.message']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Connect Customer',
            'phone': '+12125550123',
        })

    def _make_message(self, suffix='1', **values):
        vals = {
            'message_sid': 'SM%s' % suffix,
            'from_number': '+12125550123',
            'to_number': '+12125550000',
            'body': 'Hello',
            'message_type': 'sms',
            'status': 'received',
            'partner': self.partner.id,
        }
        vals.update(values)
        return self.Message.sudo().create(vals)

    def test_partner_channel_is_created_and_reused(self):
        channel = self.Channel._get_connect_channel(
            self.partner,
            number='+12125550123',
            provider='sms',
            create_if_not_found=True,
        )
        reused = self.Channel._get_connect_channel(
            self.partner,
            number='+12125550123',
            provider='sms',
            create_if_not_found=True,
        )
        self.assertEqual(channel, reused)
        self.assertEqual(channel.channel_type, 'connect_messages')
        self.assertEqual(channel.connect_partner_id, self.partner)
        self.assertEqual(channel.connect_number, '+12125550123')
        self.assertIn(self.partner, channel.channel_partner_ids)

    def test_number_only_channel_and_contact_creation(self):
        number = '+12125550999'
        channel = self.Channel._get_connect_channel(
            self.env['res.partner'],
            number=number,
            provider='whatsapp',
            create_if_not_found=True,
        )
        self.assertFalse(channel.connect_partner_id)
        self.assertEqual(channel.connect_number, number)
        self.assertEqual(channel.connect_channel_provider, 'whatsapp')

        result = channel.connect_create_partner('New Customer')
        self.assertTrue(result['partner_id'])
        self.assertEqual(channel.connect_partner_id.id, result['partner_id'])
        self.assertEqual(channel.connect_partner_id.phone, number)
        self.assertIn(channel.connect_partner_id, channel.channel_partner_ids)

    def test_inbound_message_is_mirrored_and_formatted(self):
        channel = self.Channel._get_connect_channel(
            self.partner,
            number='+12125550123',
            create_if_not_found=True,
        )
        connect_message = self._make_message()
        mail_message = channel._connect_post_inbound(connect_message)

        self.assertEqual(connect_message.channel_id, channel)
        self.assertEqual(connect_message.channel_message_id, mail_message)
        self.assertEqual(mail_message.connect_message, connect_message)
        self.assertEqual(mail_message.message_type, 'connect_message')
        formatted = mail_message.message_format()[0]
        self.assertEqual(formatted['connectStatus'], 'received')
        self.assertEqual(formatted['connectMessageType'], 'sms')

    def test_whatsapp_window_uses_last_inbound_message(self):
        channel = self.Channel._get_connect_channel(
            self.partner,
            number='+12125550123',
            provider='whatsapp',
            create_if_not_found=True,
        )
        connect_message = self._make_message(
            suffix='wa', message_type='whatsapp')
        mail_message = channel._connect_post_inbound(connect_message)
        channel.invalidate_cache()

        self.assertEqual(channel.connect_last_inbound_whatsapp_id, mail_message)
        self.assertTrue(channel.connect_whatsapp_window_open)
        self.assertGreater(
            channel.connect_whatsapp_valid_until,
            fields.Datetime.now(),
        )

    def test_outbound_discuss_post_calls_connect_sender(self):
        channel = self.Channel._get_connect_channel(
            self.partner,
            number='+12125550123',
            create_if_not_found=True,
        )
        sent = self._make_message(
            suffix='out',
            from_number='+12125550000',
            to_number='+12125550123',
            status='sent',
            sender_user=self.env.user.id,
        )
        with patch.object(type(self.Message), 'send', return_value=sent) as send:
            message = channel.message_post(
                body='Reply',
                message_type='connect_message',
                subtype_xmlid='mail.mt_comment',
                connect_provider='sms',
            )
        self.assertTrue(send.called)
        self.assertEqual(sent.channel_id, channel)
        self.assertEqual(sent.channel_message_id, message)

    def test_archived_channel_resurfaces(self):
        channel = self.Channel._get_connect_channel(
            self.partner,
            number='+12125550123',
            create_if_not_found=True,
        )
        member = channel.channel_last_seen_partner_ids.filtered(
            lambda rec: rec.partner_id == self.env.user.partner_id)
        self.assertTrue(member)
        member.write({'is_pinned': False})
        channel._connect_resurface()
        self.assertTrue(member.is_pinned)

    def test_connect_sidebar_setting_exists(self):
        settings_model = self.env['res.users.settings']
        self.assertIn(
            'is_discuss_sidebar_category_connect_messages_open',
            settings_model._fields,
        )
        settings = settings_model._find_or_create_for_user(self.env.user)
        self.assertTrue(settings.is_discuss_sidebar_category_connect_messages_open)
        settings.set_res_users_settings({
            'is_discuss_sidebar_category_connect_messages_open': False,
        })
        self.assertFalse(
            settings.is_discuss_sidebar_category_connect_messages_open)

    def test_clean_number_and_provider_are_normalized(self):
        values = self.Message.get_receive_message_values({
            'MessageSid': 'WA1',
            'From': 'whatsapp:+12125550123',
            'To': 'whatsapp:+12125550000',
            'Body': 'Hello',
            'NumMedia': '0',
            'SmsStatus': 'received',
        })
        self.assertEqual(values['from_number'], '+12125550123')
        self.assertEqual(values['to_number'], '+12125550000')
        self.assertEqual(values['message_type'], 'whatsapp')

    def test_idle_read_channels_are_unpinned(self):
        channel = self.Channel._get_connect_channel(
            self.partner,
            number='+12125550123',
            create_if_not_found=True,
        )
        member = channel.channel_last_seen_partner_ids.filtered(
            lambda rec: rec.partner_id == self.env.user.partner_id)
        member.write({
            'is_pinned': True,
            'last_interest_dt': fields.Datetime.now() - timedelta(days=2),
        })
        self.env['mail.channel.partner']._gc_unpin_connect_channels()
        self.assertFalse(member.is_pinned)
