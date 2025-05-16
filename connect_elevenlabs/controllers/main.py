# -*- coding: utf-8 -*

import json
import logging
import requests
from odoo import http, SUPERUSER_ID, registry, release
from werkzeug.exceptions import BadRequest, NotFound, Unauthorized
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class ConnectElevenlabsController(http.Controller):

    def check_agent_request(self):
        auth_token = http.request.env['connect.settings'].sudo().get_param('elevenlabs_agent_token')
        agent_token = http.request.httprequest.headers.get('x-elevenlabs-agent-token')
        if auth_token != agent_token:
            raise Unauthorized('Unauthorized request')

    @http.route('/connect_elevenlabs/transfer', methods=['POST'], type='http', auth='public', csrf=False)
    def transfer_webhook(self):
        self.check_agent_request()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        agent = http.request.env['connect.elevenlabs_agent'].with_user(
            http.request.env.ref("connect.user_connect_webhook")).sudo()
        agent.transfer(data.get('call_sid'))
        return 'Transfered'


