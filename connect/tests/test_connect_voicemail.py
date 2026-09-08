# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestConnectVoicemail(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Make sure voicemail creation does not attempt a real transcription.
        cls.env['connect.settings'].sudo().set_param('openai_api_key', False)
        cls.partner = cls.env['res.partner'].create({
            'name': 'Acme Customer', 'phone': '+15551230000',
        })
        cls.domain = cls.env['connect.domain'].with_context(no_twilio_create=True).create({
            'subdomain': 'test-vm', 'friendly_name': 'Test VM Domain',
        })
        cls.mailbox_owner = cls.env['res.users'].create({
            'name': 'Mailbox Owner', 'login': 'vm_mailbox_owner',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('connect.group_connect_user').id),
            ],
        })
        cls.pbx_user = cls.env['connect.user'].with_context(no_twilio_create=True).create({
            'username': 'vmtestuser', 'domain': cls.domain.id, 'user': cls.mailbox_owner.id,
        })
        cls.call = cls.env['connect.call'].sudo().create({
            'partner': cls.partner.id,
            'caller': '+15551230000',
            'called': '+15550000000',
            'direction': 'incoming',
            'status': 'no-answer',
        })
        cls.channel = cls.env['connect.channel'].sudo().create({
            'sid': 'CAvmtest00000000000000000000000001',
            'call': cls.call.id,
            'caller': '+15551230000',
            'called': '+15550000000',
        })

    def _vm_params(self, **overrides):
        params = {
            'CallSid': self.channel.sid,
            'RecordingSid': 'REvmtest0000000000000000000000001',
            'RecordingUrl': 'https://api.twilio.com/recording/REvmtest1',
            'RecordingDuration': '42',
            'RecordingStatus': 'completed',
        }
        params.update(overrides)
        return params

    def test_webhook_creates_voicemail(self):
        self.env['connect.voicemail'].on_vm_recording_status(
            self._vm_params(vm_user_id=str(self.pbx_user.id)))
        voicemail = self.env['connect.voicemail'].search([('call', '=', self.call.id)])
        self.assertEqual(len(voicemail), 1)
        self.assertEqual(voicemail.media_url, 'https://api.twilio.com/recording/REvmtest1')
        self.assertEqual(voicemail.duration, 42)
        self.assertEqual(voicemail.sid, 'REvmtest0000000000000000000000001')
        self.assertEqual(voicemail.call_sid, self.channel.sid)
        self.assertEqual(voicemail.channel, self.channel)
        self.assertEqual(voicemail.partner, self.partner)
        self.assertEqual(voicemail.caller_number, '+15551230000')
        self.assertEqual(voicemail.called_number, '+15550000000')
        self.assertEqual(voicemail.user, self.pbx_user)
        self.assertTrue(voicemail.is_new)

    def test_webhook_callflow_attribution(self):
        callflow = self.env['connect.callflow'].sudo().create({'name': 'VM Flow'})
        self.env['connect.voicemail'].on_vm_recording_status(
            self._vm_params(vm_callflow_id=str(callflow.id)))
        voicemail = self.env['connect.voicemail'].search([('call', '=', self.call.id)])
        self.assertEqual(voicemail.callflow, callflow)
        self.assertFalse(voicemail.user)

    def test_webhook_fallback_user_attribution(self):
        # No mailbox reference in the URL: fall back to the only called PBX user.
        self.call.sudo().called_pbx_users = [(4, self.pbx_user.id)]
        self.env['connect.voicemail'].on_vm_recording_status(self._vm_params())
        voicemail = self.env['connect.voicemail'].search([('call', '=', self.call.id)])
        self.assertEqual(voicemail.user, self.pbx_user)

    def test_webhook_bad_mailbox_reference(self):
        self.env['connect.voicemail'].on_vm_recording_status(
            self._vm_params(vm_user_id='garbage'))
        voicemail = self.env['connect.voicemail'].search([('call', '=', self.call.id)])
        self.assertEqual(len(voicemail), 1)
        self.assertFalse(voicemail.user)

    def test_call_voicemail_computes(self):
        self.assertFalse(self.call.voicemail)
        self.assertEqual(self.call.voicemail_icon, '')
        self.assertEqual(self.call.voicemail_widget, '')
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
            'duration': 42,
            'transcript': 'Please call me back.',
        })
        self.call.invalidate_recordset()
        self.assertEqual(self.call.voicemail, voicemail)
        self.assertEqual(self.call.voicemail_transcript, 'Please call me back.')
        self.assertIn('fa-envelope-o', self.call.voicemail_icon)
        self.assertIn('<audio', self.call.voicemail_widget)

    def test_mark_listened(self):
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
        })
        self.assertTrue(voicemail.is_new)
        voicemail.mark_listened()
        self.assertFalse(voicemail.is_new)

    def test_user_voicemail_notifies_owner(self):
        self.env['connect.voicemail'].on_vm_recording_status(
            self._vm_params(vm_user_id=str(self.pbx_user.id)))
        voicemail = self.env['connect.voicemail'].search([('call', '=', self.call.id)])
        message = voicemail.message_ids.filtered(
            lambda m: self.mailbox_owner.partner_id in m.partner_ids)
        self.assertTrue(message, 'Mailbox owner must be notified about the new voicemail')
        self.assertIn('New voicemail from', str(message.body))
        self.assertIn(self.mailbox_owner.partner_id, voicemail.message_partner_ids)

    def test_callflow_voicemail_notifies_ring_users(self):
        callflow = self.env['connect.callflow'].sudo().create({
            'name': 'VM Ring Flow', 'ring_users': [(4, self.pbx_user.id)],
        })
        self.env['connect.voicemail'].on_vm_recording_status(
            self._vm_params(vm_callflow_id=str(callflow.id)))
        voicemail = self.env['connect.voicemail'].search([('call', '=', self.call.id)])
        message = voicemail.message_ids.filtered(
            lambda m: self.mailbox_owner.partner_id in m.partner_ids)
        self.assertTrue(message, 'Ring group users must be notified about the new voicemail')
        # Notified ring users become followers and can read the voicemail.
        self.assertIn(self.mailbox_owner.partner_id, voicemail.message_partner_ids)
        self.env.invalidate_all()
        read_vals = voicemail.with_user(self.mailbox_owner).read(['media_url'])
        self.assertEqual(read_vals[0]['id'], voicemail.id)

    def test_tagged_user_gets_access(self):
        tagged_user = self.env['res.users'].create({
            'name': 'Tagged User', 'login': 'vm_tagged_user',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('connect.group_connect_user').id),
            ],
        })
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
        })
        # Not related to the voicemail in any way: no access.
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            voicemail.with_user(tagged_user).read(['media_url'])
        # Tag the user in the chatter: they become a follower and gain read access.
        voicemail.sudo().message_post(
            body='Please handle this voicemail',
            partner_ids=[tagged_user.partner_id.id],
            message_type='comment', subtype_xmlid='mail.mt_comment')
        self.assertIn(tagged_user.partner_id, voicemail.message_partner_ids)
        self.env.invalidate_all()
        read_vals = voicemail.with_user(tagged_user).read(['media_url'])
        self.assertEqual(read_vals[0]['id'], voicemail.id)

    def test_tagged_external_partner_not_subscribed(self):
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
        })
        # A customer partner without an internal user must not become a follower.
        voicemail.sudo().message_post(
            body='FYI', partner_ids=[self.partner.id],
            message_type='comment', subtype_xmlid='mail.mt_comment')
        self.assertNotIn(self.partner, voicemail.message_partner_ids)

    def test_tagged_user_gets_call_and_voicemail_access(self):
        tagged_user = self.env['res.users'].create({
            'name': 'Call Tagged User', 'login': 'vm_call_tagged_user',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('connect.group_connect_user').id),
            ],
        })
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
        })
        # Not related to the call in any way: no access to the call or voicemail.
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.call.with_user(tagged_user).read(['caller'])
        with self.assertRaises(AccessError):
            voicemail.with_user(tagged_user).read(['media_url'])
        # Tag the user in the call chatter: they can read the call and,
        # through the bridge rule, the voicemails of that call.
        self.call.sudo().message_post(
            body='Please handle this call',
            partner_ids=[tagged_user.partner_id.id],
            message_type='comment', subtype_xmlid='mail.mt_comment')
        self.assertIn(tagged_user.partner_id, self.call.message_partner_ids)
        self.env.invalidate_all()
        self.assertEqual(self.call.with_user(tagged_user).read(['caller'])[0]['id'], self.call.id)
        self.assertEqual(voicemail.with_user(tagged_user).read(['media_url'])[0]['id'], voicemail.id)

    def test_follower_can_mark_listened(self):
        tagged_user = self.env['res.users'].create({
            'name': 'Listener User', 'login': 'vm_listener_user',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('connect.group_connect_user').id),
            ],
        })
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
        })
        # Without access to the voicemail marking it as listened is refused.
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            voicemail.with_user(tagged_user).mark_listened()
        # A tagged (read-only follower) user can mark it as listened.
        voicemail.sudo().message_post(
            body='Please listen', partner_ids=[tagged_user.partner_id.id],
            message_type='comment', subtype_xmlid='mail.mt_comment')
        self.env.invalidate_all()
        voicemail.with_user(tagged_user).mark_listened()
        self.assertFalse(voicemail.sudo().is_new)

    def test_display_name(self):
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
            'caller_number': '+15551230000',
        })
        self.assertEqual(voicemail.display_name, 'Voicemail from +15551230000')
        voicemail.sudo().partner = self.partner
        self.assertEqual(voicemail.display_name, 'Voicemail from Acme Customer')

    def test_duration_human(self):
        voicemail = self.env['connect.voicemail'].sudo().create({
            'call': self.call.id,
            'media_url': 'https://api.twilio.com/recording/REvmtest1',
            'duration': 75,
        })
        self.assertEqual(voicemail.duration_human, '01:15')
