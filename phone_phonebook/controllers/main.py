# -*- coding: utf-8 -*-
import hmac

from odoo import http
from odoo.http import request


class PhonebookController(http.Controller):

    def _authorized(self, token):
        expected = request.env['ir.config_parameter'].sudo().get_param(
            'phone_phonebook.token')
        return bool(expected and token) and hmac.compare_digest(expected, token)

    @http.route('/phonebook/<string:brand>.xml', type='http', auth='public',
                methods=['GET'])
    def phonebook(self, brand, token=None, **kwargs):
        if not self._authorized(token):
            return request.make_response('Forbidden', status=403)
        payload = request.env['res.partner']._phonebook_render(brand)
        if payload is None:
            return request.make_response('Unknown phonebook format', status=404)
        return request.make_response(payload, headers=[
            ('Content-Type', 'text/xml; charset=utf-8'),
        ])
