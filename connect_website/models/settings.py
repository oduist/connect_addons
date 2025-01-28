# -*- coding: utf-8 -*-
import logging
from urllib.parse import urljoin

from odoo.addons.connect.models.settings import strip_number

from odoo import api, fields, models
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)


class Settings(models.Model):
    _inherit = 'connect.settings'

    connect_website_enable = fields.Boolean(string="Talk Button Enable")
    # Restrict deleting an extension that is used here.
    connect_website_connect_extension = fields.Many2one(
        'connect.exten', string='Connect Extension', ondelete='restrict')
    # Allow to clear the settings when deleting domain. It's an extra rare operation and user knows what is doing.
    connect_website_connect_domain = fields.Many2one(
        'connect.domain', string='Connect Domain', ondelete='set null')

    @api.model
    def originate_call(self, number, res_model=None, res_id=None, user=None):
        if len(number) == 8 and not ('+' in number):
            number = strip_number(number)
            client = self.get_client()
            partner = self.env['res.partner'].get_partner_by_number(number)
            user = self.env.user

            if not user.connect_user:
                raise ValidationError('User does not have a SIP username defined!')

            to = 'client:{}?autoAnswer=yes&Partner={}&From={}'.format(
                user.connect_user.uri, partner.id, number)
            caller_id = user.connect_user.exten.number
            api_url = self.sudo().get_param('api_url')
            instance_uid = self.sudo().get_param('instance_uid', '')
            status_url = urljoin(api_url, 'app/connect/webhook/{}/callstatus'.format(instance_uid))
            twiml = """
                <Response>
                    <Dial timeout="10">
                        <Client statusCallback="{}" statusCallbackEvent="initiated answered completed">
                            <Identity>{}</Identity>
                            <Parameter name="CallerName" value=""/>
                            <Parameter name="Partner" value="{}" />
                        </Client>
                    </Dial>
                </Response>
                """.format(status_url, number, partner.id)
            record = user.connect_user.record_calls

            channel = client.calls.create(
                twiml=twiml,
                to=to,
                from_=caller_id,
                status_callback=status_url,
                record=record,
                recording_channels='dual',
                status_callback_event=['initiated', 'answered', 'completed'],
                status_callback_method='POST'
            )

            channel = self.env['connect.channel'].sudo().create({
                'sid': channel.sid,
                'technical_direction': 'outboubd-api',
                'caller_user': user.id,
                'caller_pbx_user': user.connect_user.id,
                'partner': partner.id,
                'called': number,
                'caller': caller_id,
            })
        else:
            return super().originate_call(number, res_model, res_id, user)
