# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
from odoo.addons.connect.models.settings import debug
from odoo.addons.connect.models.twiml import pretty_xml

logger = logging.getLogger(__name__)


class ElevenlabsAgent(models.Model):
    _name = 'connect.elevenlabs_agent'

    name = fields.Char(required=True)
    agent_id = fields.Char(string="Agent ID", required=True)

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'elevenlabs_agent')


    @api.model
    def route_call(self, request):
        # Find the number
        number = self.sudo().search([('phone_number', '=', request['Called'])])

        if number.enable_ai_agent and number.agent:
            # Create call
            self.env['connect.call'].sudo().on_call_status(request)
            # Collect data for agent
            call_sid = request.get("CallSid")
            agent_url = self.env['connect.settings'].get_param('agent_url')
            agent_id = number.agent.agent_id
            connect = Connect()
            connect.stream(url=f"{agent_url}/twilio/stream/{call_sid}/{agent_id}")
            response = VoiceResponse()
            response.append(connect)
            debug(self, pretty_xml(response))
            return response

        return super().route_call(request)

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
