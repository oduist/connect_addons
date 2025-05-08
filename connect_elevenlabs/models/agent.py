# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml

logger = logging.getLogger(__name__)


class ElevenlabsAgent(models.Model):
    _name = 'connect.elevenlabs_agent'
    _description = 'Elevenlabs Agent'

    name = fields.Char(required=True)
    agent_id = fields.Char(string="Agent ID", required=True)
    exten = fields.Many2one('connect.exten', ondelete='set null', readonly=True)
    exten_number = fields.Char(related='exten.number')

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'elevenlabs_agent')


    def render(self, request, params={}):
        self.ensure_one()
        call_sid = request.get("CallSid")
        elevenlabs_agent_url = self.env['connect.settings'].get_param('elevenlabs_agent_url')
        agent_id = self.agent_id
        connect = Connect()
        connect.stream(url=f"{elevenlabs_agent_url}/twilio/stream/{call_sid}/{agent_id}")
        response = VoiceResponse()
        response.append(connect)
        debug(self, pretty_xml(response))
        return response

    @api.model
    def transfer(self, call_sid):
        self = self.sudo()
        client = self.env['connect.settings'].get_client()
        channel = self.env['connect.channel'].search([('sid', '=', call_sid)])
        twiml = self.search([('phone_number', '=', channel.called)]).render({
            'CallSid': call_sid, 'From': channel.caller
        })
        client.calls(call_sid).update(twiml=twiml)
        return True
