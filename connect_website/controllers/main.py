# -*- coding: utf-8 -*-
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

from odoo import http, release
from odoo.http import request

route_type = "json" if release.version_info[0] < 19.0 else 'jsonrpc'

class APIConnectWidget(http.Controller):
    @http.route('/get_connect_website_config', type=route_type, auth='public', sitemap=False)
    def get_connect_website_config(self):
        enabled = request.env['connect.settings'].sudo().get_param('connect_website_enable')
        number = request.env['connect.settings'].sudo().get_param('connect_website_connect_extension').number
        return {'enabled': enabled, 'number': number}

    @http.route('/get_connect_website_button_token', type=route_type, auth='public', sitemap=False)
    def get_connect_website_button_token(self, identity):
        account_sid = request.env['connect.settings'].sudo().get_param('account_sid')
        api_key = request.env['connect.settings'].sudo().get_param('twilio_api_key')
        api_secret = request.env['connect.settings'].sudo().get_param('twilio_api_secret')
        exten = request.env['connect.settings'].sudo().get_param('connect_website_connect_extension')
        domain = request.env['connect.settings'].sudo().get_param('connect_website_connect_domain')
        token = AccessToken(account_sid, api_key, api_secret, identity=identity, ttl=3600)
        voice_grant = VoiceGrant(
            outgoing_application_sid=domain.application.sid,
            outgoing_application_params={'GrantFullAccess': True},
            incoming_allow=True,
        )
        token.add_grant(voice_grant)
        return token.to_jwt()
