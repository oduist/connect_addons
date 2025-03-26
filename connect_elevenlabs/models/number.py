# -*- coding: utf-8 -*-

import logging
from urllib.parse import urlparse

from odoo import models, fields, release, api
from twilio.twiml.voice_response import VoiceResponse, Connect
logger = logging.getLogger(__name__)


class Number(models.Model):
    _inherit = 'connect.number'

    enable_ai_agent = fields.Boolean()
    agent = fields.Many2one('connect_elevenlabs.ai_agent')

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
            host = urlparse(agent_url).hostname
            agent_id = number.agent.agent_id

            connect = Connect()
            connect.stream(url=f"wss://{host}/twilio/stream/{call_sid}/{agent_id}")
            response = VoiceResponse()
            response.append(connect)
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
