# -*- coding: utf-8 -*-
import logging
from urllib.parse import urljoin
from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.addons.connect.models.res_partner import strip_number

logger = logging.getLogger(__name__)


class Call(models.Model):
    _inherit = 'connect.call'

    @api.model
    def originate_call(self, number, res_model=None, res_id=None, user=None, whatsapp_call=False):
        if len(number) == 8 and '+' not in number:
            number = strip_number(number)
            client = self.env['connect.settings'].get_client()
            partner = self.env['res.partner'].get_partner_by_number(number)
            user = self.env.user
            if not user.connect_user:
                raise ValidationError('User does not have a SIP username defined!')
            # check license
            if not self.env['oduist.license'].check_license('connect_website'):
                raise ValidationError('Connect Website License has expired! Please buy a license.')
            to = 'client:{}?autoAnswer=yes&Partner={}&From={}'.format(
                user.connect_user.uri, partner.id, number)
            caller_id = user.connect_user.exten.number
            api_url = self.env['connect.settings'].sudo().get_param('api_url')
            status_url = urljoin(api_url, 'connect/webhook/callstatus')
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
            return super().originate_call(number, res_model, res_id, user, whatsapp_call=whatsapp_call)
