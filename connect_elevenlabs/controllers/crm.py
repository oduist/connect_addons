# -*- coding: utf-8 -*

import json
import logging
import requests
from odoo import http, SUPERUSER_ID, registry, release
from werkzeug.exceptions import BadRequest, NotFound

from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class ConnectCrmController(http.Controller):

    @http.route('/connect_elevenlabs/create_partner', methods=['POST'], type='json',
                auth='public', csrf=False)
    def create_partner(self):
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        #auth_token = http.request.env['connect.settings'].sudo().get_param('elevenlabs_agent_token')
        partner = http.request.env['res.partner'].sudo().with_context(
            connect_call_id=int(data['call_id'])).create({
                'name': data['name'],
                'phone': data['partner_phone']
            })
        print('Partner created: ', partner)
        # Now assign partner to the call.
        http.request.env['connect.call'].sudo().partner = partner.id
        return {
            'partner_id': partner.id,
            'message': 'Partner created'

        }


    @http.route('/connect_elevenlabs/create_lead', methods=['POST'], type='json',
                auth='public', csrf=False)
    def create_lead(self):
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        #auth_token = http.request.env['connect.settings'].sudo().get_param('elevenlabs_agent_token')
        lead = http.request.env['crm.lead'].sudo().with_context(
            connect_call_id=int(data['call_id'])).create({
                'name': data.get('subject'),
                'partner_id': data.get('partner_id'),
                'user_id': 2,
            })
        print('Lead created: ', lead)
        return {'lead_number': lead.id}


    @http.route('/connect_elevenlabs/search_lead', methods=['POST'], type='json',
                auth='public', csrf=False)
    def search_lead(self):
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        #auth_token = http.request.env['connect.settings'].sudo().get_param('elevenlabs_agent_token')
        print(data)
        res = http.request.env['crm.lead'].sudo().search([('id', '=', data['number'])])
        print(res)
        return {'name': res.name, 'description': res.description, 'date_deadline': res.date_deadline}
