# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import debug, format_connect_response

logger = logging.getLogger(__name__)


class BYOC(models.Model):
    _name = 'connect.byoc'
    _description = 'BYOC'
    _rec_name = 'friendly_name'

    sid = fields.Char(required=True)
    friendly_name = fields.Char('Name', required=True)
    voice_url = fields.Char(compute='_get_urls')
    voice_fallback_url = fields.Char(compute='_get_urls')
    voice_status_url = fields.Char(compute='_get_urls')
    connection_policy_sid = fields.Char(required=True)
    from_domain_sid = fields.Char(required=True)
    url = fields.Char(required=True)
    app = fields.Many2one('connect.twiml', ondelete='restrict')

    def _get_urls(self):
        for rec in self:
            rec.voice_status_url =  rec.app.voice_status_url
            rec.voice_url = rec.app.voice_url
            rec.voice_fallback_url = rec.app.voice_fallback_url

    @api.model
    def sync(self):
        client = self.env['connect.settings'].get_client()
        trunks = client.voice.v1.byoc_trunks.list()
        for trunk in trunks:
            rec = self.search([('sid', '=', trunk.sid)])
            if not rec:
                # Create trunk in Odoo:
                rec = self.create({
                    'sid': trunk.sid,
                    'friendly_name': trunk.friendly_name,
                    'connection_policy_sid': trunk.connection_policy_sid,
                    'from_domain_sid': trunk.from_domain_sid,
                    'url': trunk.url,
                })
                # Update voice URLs.
                rec.update_twilio_byoc(client)
                self.env['connect.settings' ].connect_notify(
                    title="Twilio Sync",
                    message='BYOC trunk {} added'.format(trunk.friendly_name)
                )
            else:
                # Number already in Odoo, update Voice URLs
                rec.write({
                    'sid': trunk.sid,
                    'friendly_name': trunk.friendly_name,
                    'connection_policy_sid': trunk.connection_policy_sid,
                    'from_domain_sid': trunk.from_domain_sid,
                    'url': trunk.url,
                })
                rec.update_twilio_byoc(client)
        # Remove trunks that exist only in Odoo (trunk was removed in Twilio).
        trunks_to_remove = self.search([('sid', 'not in', [k.sid for k in trunks])])
        if trunks_to_remove:
            user_message = 'BYOC(s) {} removed in Twilio!'.format(
                ','.join([k.friendly_name for k in trunks_to_remove]))
            trunks_to_remove.unlink()
            self.env['connect.settings' ].connect_notify(
                title="Twilio Sync",
                warning=True,
                sticky=True,
                message=user_message
            )

    def update_twilio_byoc(self, client=None):
        self.ensure_one()
        if not client:
            client = self.env['connect.settings'].get_client()
        try:
            if not self.voice_url:
                logger.warning('BYOC app not set, not updating Twilio webhooks.')
                return
            trunk = client.voice.v1.byoc_trunks(self.sid)
            trunk.update(
                friendly_name=self.friendly_name,
                voice_url=self.voice_url,
                voice_fallback_url=self.voice_fallback_url,
                status_callback_url=self.voice_status_url
            )
            debug(self, 'BYOC {} updated.'.format(self.friendly_name))
        except Exception as e:
            logger.exception('BYOC Update Exception:')
            raise ValidationError(format_connect_response(str(e)))

    @api.constrains('app')
    def sync_app(self):
        for rec in self:
            if rec.app:
                rec.update_twilio_byoc()
