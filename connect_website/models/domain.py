# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging
import re
from urllib.parse import urljoin
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from odoo import models, api
from odoo.addons.connect.models.settings import debug

logger = logging.getLogger(__name__)


class Domain(models.Model):
    _inherit = 'connect.domain'

    @api.model
    def route_call(self, request, params={}):
        # Check access only for Twilio Service agent.
        if not self.env.user.has_group('connect.group_connect_webhook'):
            logger.error('Access to Twilio webhook is denied!')
            return '<Response><Say>You must select a default number for caller ID!</Say></Response>'
        re_call_uri = re.compile(r'^(?:sip|client):([^\s@]+)@[^\s;]+(?:;[^&\s]+(?:&[^&\s]+)*)?')
        found_uri = re_call_uri.search(request.get('Called'))
        called = ''
        if found_uri:
            called = found_uri.group(1)
        else:
            called = request.get('Called')
        if request.get('GrantFullAccess') == 'true' and ('+' in request.get('To')):
            return False
        if request.get('Source') == 'website':
            debug(self, 'Routing call from Website {}'.format(request.get('Caller')))
            request.update({'From': request.get('From').replace('client:', '')})
            request.update({'Caller': request.get('Caller').replace('client:', '')})
            # Create call
            call_id = self.env['connect.call'].on_call_status(request, skip_twilio_check=True)
            caller_name = None
            partner = self.env['res.partner'].sudo().get_partner_by_number(request['Caller'])
            if partner:
                call = self.env['connect.call'].browse(call_id)
                call.partner = partner.id
                caller_name = partner.name
            elif request.get('UserId') != "false":
                user = self.env['res.users'].sudo().browse(int(request.get('UserId')))
                call = self.env['connect.call'].browse(call_id)
                call.partner = user.partner_id
                caller_name = user.partner_id.name

            exten = self.env['connect.settings'].sudo().get_param('connect_website_connect_extension')
            if exten:
                res = exten.render(request, {'CallerName': caller_name} if caller_name else {})
                return res
        elif len(called) == 8 and not ('+' in called):
            debug(self, 'Routing call to Website ID {}'.format(called))
            user = self.env['connect.user'].get_user_by_uri(request.get('From'))
            caller_name = None
            if user:
                caller_id = user.exten.number or ''
                if not caller_id:
                    logger.warning('Exten not set for user %s', user.name)
                caller_name = user.name
            else:
                caller_id = request.get('From')

            dial_client = Dial(timeout=10, callerId=caller_id)
            api_url = self.env['connect.settings'].sudo().get_param('api_url')
            instance_uid = self.env['connect.settings'].sudo().get_param('instance_uid')
            status_url = urljoin(api_url, 'app/connect/webhook/{}/callstatus'.format(instance_uid))

            client = Client(
                statusCallbackEvent='initiated answered completed',
                statusCallback=status_url)
            client.identity(called)
            client.parameter(name='CallerName', value=caller_name)

            dial_client.append(client)
            response = VoiceResponse()
            response.append(dial_client)
            self.env['connect.call'].on_call_status(request)
            return response
        else:
            return super().route_call(request, params)
