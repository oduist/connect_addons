# -*- coding: utf-8 -*

import logging

from odoo.http import request, route
from odoo.addons.connect.controllers.twilio_webhooks import ConnectController
import json
logger = logging.getLogger(__name__)


class ConnectController(ConnectController):

    @route('/twilio/webhook/transfer', methods=['POST'], type='http', auth='public', csrf=False)
    def transfer_webhook(self):
        data = json.loads(request.httprequest.get_data(as_text=True))
        number = request.env['connect.number'].with_user(request.env.ref("connect.user_connect_webhook")).sudo()
        number.transfer(data.get('call_sid'))
        return ''


