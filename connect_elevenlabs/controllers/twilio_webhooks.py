# -*- coding: utf-8 -*

import logging

from odoo.http import request, route
from odoo.addons.connect.controllers.twilio_webhooks import ConnectController
import json
logger = logging.getLogger(__name__)


class ConnectController(ConnectController):

    @route('/connect_elevenlabs/transfer', methods=['POST'], type='http', auth='public', csrf=False)
    def transfer_webhook(self):
        data = json.loads(request.httprequest.get_data(as_text=True))
        agent = request.env['connect.elevenlabs_agent'].with_user(request.env.ref("connect.user_connect_webhook")).sudo()
        agent.transfer(data.get('call_sid'))
        return ''


