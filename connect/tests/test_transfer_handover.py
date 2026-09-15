# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from twilio.twiml.voice_response import VoiceResponse

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestTransferHandover(TransactionCase):
    """A transferred call tells the target who handed it over.

    The caller ID on a transfer leg names the customer -- that is who the
    agent is about to speak to, and render_client deliberately keeps it that
    way. The colleague who transferred therefore has nowhere to go except a
    parameter of its own, which is what the softphone reads to show both.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['connect.settings'].set_param('api_url', 'https://pbx.example.com/')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Acme Customer', 'phone': '+12898283865',
        })
        # connect.user.user is unique, so each PBX user needs an Odoo user of
        # its own rather than a shared one such as the admin.
        cls.agent_odoo_user = cls.env['res.users'].create({
            'name': 'Sara Agent', 'login': 'sara.agent@example.com',
        })
        cls.target_odoo_user = cls.env['res.users'].create({
            'name': 'Marc Target', 'login': 'marc.target@example.com',
        })
        with patch.object(type(cls.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            cls.domain = cls.env['connect.domain'].with_context(
                no_twilio_create=True).create({
                    'subdomain': 'test-transfer-handover',
                    'friendly_name': 'Test Transfer Handover',
                })
            # The agent who answers first and then transfers.
            cls.agent = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'SaraAgent', 'domain': cls.domain.id,
                    'client_enabled': True, 'record_calls': False,
                    'user': cls.agent_odoo_user.id,
                })
            # The colleague the call is transferred on to, on a web phone.
            cls.target = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'MarcTarget', 'domain': cls.domain.id,
                    'client_enabled': True, 'record_calls': False,
                    'user': cls.target_odoo_user.id,
                })
        cls._make_exten('7901', cls.agent)
        cls._make_exten('7902', cls.target)

    @classmethod
    def _make_exten(cls, number, pbx_user):
        exten = cls.env['connect.exten'].create({
            'number': number, 'model': 'connect.user', 'res_id': pbx_user.id,
        })
        pbx_user.exten = exten.id
        return exten

    def _incoming_call(self, sid='CAcustomer'):
        """A customer call already answered by the agent."""
        call = self.env['connect.call'].create({
            'caller': '+12898283865', 'called': '+13658257665',
            'direction': 'incoming', 'status': 'in-progress',
            'partner': self.partner.id,
        })
        self.env['connect.channel'].create({
            'sid': sid, 'call': call.id, 'caller': '+12898283865',
            'called': '+13658257665', 'status': 'in-progress',
            'technical_direction': 'inbound',
        })
        # The leg the platform raised towards the agent, which is what
        # _get_transferring_pbx_user() reads to name the transferrer.
        self.env['connect.channel'].create({
            'sid': '%s-agent' % sid, 'call': call.id,
            'caller': '+12898283865', 'called': '7901',
            'status': 'in-progress', 'technical_direction': 'outbound-dial',
            'called_pbx_user': self.agent.id,
        })
        return call

    def _outgoing_call(self, sid='CAagentdialled'):
        """A call the agent placed from their web phone.

        The agent is the *caller* on their own leg -- the leg that reaches the
        platform and asks it to dial out -- so nothing on this call carries
        them as `called_pbx_user`.
        """
        call = self.env['connect.call'].create({
            'caller': '7901', 'called': '+12898283865',
            'direction': 'outgoing', 'status': 'in-progress',
            'partner': self.partner.id,
        })
        self.env['connect.channel'].create({
            'sid': sid, 'call': call.id, 'caller': '7901',
            'called': '+12898283865', 'status': 'in-progress',
            'technical_direction': 'inbound', 'caller_pbx_user': self.agent.id,
        })
        self.env['connect.channel'].create({
            'sid': '%s-out' % sid, 'call': call.id, 'caller': '+13658257665',
            'called': '+12898283865', 'status': 'in-progress',
            'technical_direction': 'outbound-dial',
        })
        return call

    def _render(self, call, sid='CAcustomer'):
        response = VoiceResponse()
        self.target.render_client(response, {'CallSid': sid}, {})
        return str(response)

    def test_transferred_call_names_the_colleague_who_handed_it_over(self):
        call = self._incoming_call()
        call.add_transferred_user(self.target_odoo_user)

        twiml = self._render(call)

        self.assertIn('name="TransferredBy"', twiml)
        self.assertIn('value="Sara Agent"', twiml)
        # The customer keeps the caller ID and the contact: the parameter adds
        # to what the phone shows, it does not replace it.
        self.assertIn('value="%s"' % self.partner.id, twiml)

    def test_the_agent_who_placed_the_call_is_named_too(self):
        """A transfer out of a call the agent dialled.

        `answered_pbx_user` is only ever set from `called_pbx_user`, and only
        at finalization, so a live outbound call has nothing on the called
        side to name -- the transferrer has to be found on the caller side or
        the recipient is told nothing.
        """
        call = self._outgoing_call()
        call.add_transferred_user(self.target_odoo_user)

        twiml = self._render(call, sid='CAagentdialled')

        self.assertIn('name="TransferredBy"', twiml)
        self.assertIn('value="Sara Agent"', twiml)

    def test_the_transfer_target_is_never_named_as_the_transferrer(self):
        """The colleague being handed the call is not the one handing it over."""
        call = self._incoming_call()
        call.add_transferred_user(self.target_odoo_user)
        # A leg towards the target, as the platform raises when it dials them.
        self.env['connect.channel'].create({
            'sid': 'CAtargetleg', 'call': call.id, 'caller': '+12898283865',
            'called': '7902', 'status': 'in-progress',
            'technical_direction': 'outbound-dial',
            'called_pbx_user': self.target.id,
        })

        twiml = self._render(call)

        self.assertIn('value="Sara Agent"', twiml)
        self.assertNotIn('value="Marc Target"', twiml)

    def test_an_ordinary_call_carries_no_handover(self):
        """Nothing is added to a call that was never transferred."""
        self._incoming_call()

        twiml = self._render(self.env['connect.call'])

        self.assertNotIn('TransferredBy', twiml)
