# -*- coding: utf-8 -*-

import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from odoo.addons.connect.models.settings import debug, format_connect_response

logger = logging.getLogger(__name__)


class OriginationURI(models.Model):
    _name = 'connect.byoc_origination_uri'
    _description = 'BYOC Origination URI'
    _rec_name = 'target'
    _order = 'priority'

    sid = fields.Char()
    byoc = fields.Many2one('connect.byoc', required=True, ondelete='cascade')
    target = fields.Char(required=True)
    priority = fields.Integer(required=True, default=10,
                              help='Determines order of preference. Lower numbers = higher priority')
    weight = fields.Integer(required=True, default=10,
                            help='Used only when multiple targets share the same priority. Distributes calls proportionally among them.')

    @api.model_create_multi
    def create(self, vals_list):
        res = super(OriginationURI, self).create(vals_list)
        if self.env.context.get('skip_twilio_sync'):
            return res
        client = self.env["connect.settings"].get_client()
        for rec in res:
            target = client.voice.v1.connection_policies(
                rec.byoc.connection_policy_sid).targets.create(target=rec.target)
            rec.sid = target.sid
        return res

    def unlink(self):
        to_delete = {}
        for rec in self:
            to_delete[rec.sid] = rec.byoc
        res = super(OriginationURI, self).unlink()
        if self.env.context.get('skip_twilio_sync'):
            return res
        client = self.env["connect.settings"].get_client()
        for sid, byoc in to_delete.items():
            try:
                client.voice.v1.connection_policies(byoc.connection_policy_sid).targets(sid).delete()
            except Exception as e:
                if 'was not found' in str(e):
                    logger.warning('Target was not found in Twilio, deleting from Odoo.')
                else:
                    raise
        return res

    def write(self, vals):
        res = super(OriginationURI, self).write(vals)
        if self.env.context.get('skip_twilio_sync'):
            return res
        client = self.env["connect.settings"].get_client()
        for rec in self:
            try:
                client.voice.v1.connection_policies(rec.byoc.connection_policy_sid).targets(rec.sid).update(
                    target=rec.target,
                    priority=rec.priority,
                    weight=rec.weight,
                )
            except Exception as e:
                if 'was not found' in str(e):
                    raise ValidationError('Target not found in Twilio!')
                else:
                    raise
        return res

    @api.constrains('target')
    def _check_uri(self):
        for rec in self:
            if rec.target and not any([rec.target.startswith('sip:'), rec.target.startswith('sips:')]):
                raise ValidationError('SIP URI target must start with sip: or sips:')


class BYOC(models.Model):
    _name = "connect.byoc"
    _description = "BYOC"
    _rec_name = "friendly_name"

    sid = fields.Char()
    friendly_name = fields.Char("Name", required=True)
    origination_uri = fields.Char(required=False, string="Origination URI") # TODO: Remove after 1.0.3 upgrade.
    origination_uris = fields.One2many('connect.byoc_origination_uri', 'byoc', string='Origination URIs')
    voice_url = fields.Char(compute="_get_urls")
    voice_fallback_url = fields.Char(compute="_get_urls")
    voice_status_url = fields.Char(compute="_get_urls")
    connection_policy_sid = fields.Char()
    app = fields.Many2one("connect.twiml", ondelete="restrict")
    domain_name = fields.Char(compute='_get_byoc_domain')
    domain = fields.Many2one('connect.domain', compute='_get_byoc_domain')
    sip_credential_sid = fields.Char()
    sip_username = fields.Char('SIP Username')
    sip_password = fields.Char('SIP password')
    default_callerid = fields.Many2one('connect.outgoing_callerid', ondelete='set null')

    def _get_urls(self):
        api_url = self.env['connect.settings'].get_param('api_url')
        fallback_url = self.env['connect.settings'].get_param('api_fallback_url')
        for rec in self:
            if rec.app:
                rec.voice_status_url = rec.app.voice_status_url
                rec.voice_url = rec.app.voice_url
                rec.voice_fallback_url = rec.app.voice_fallback_url
            else:
                rec.voice_status_url = urljoin(api_url, 'twilio/webhook/callstatus')
                rec.voice_url = urljoin(api_url, 'twilio/webhook/number')
                if fallback_url:
                    rec.voice_fallback_url = urljoin(fallback_url, 'twilio/webhook/number')
                else:
                    rec.voice_fallback_url = ''

    def _get_byoc_domain(self):
        for rec in self:
            domain = self.env['connect.domain'].search([('byoc', '=', rec.id)], limit=1)
            rec.domain_name = domain.domain_name
            rec.domain = domain

    def unlink(self):
        self.env['oduist.license'].check_license('connect_byoc', silent=False)
        for rec in self:
            client = self.env["connect.settings"].get_client()
            # Delete the BYOC trunk in Twilio.
            try:
                client.voice.v1.byoc_trunks(rec.sid).delete()
                # Delete connection_policy resource.
                if rec.connection_policy_sid:
                    client.voice.v1.connection_policies(rec.connection_policy_sid).delete()
            except Exception as e:
                if 'not found' in str(e):
                    # Does not exist in Twilio, ignore and unlink
                    pass
                else:
                    raise
        # Unlink BYOC domain.
        self.env['connect.domain'].search(
            [('byoc', '=', rec.id)]).with_context(force_delete=True).unlink()
        res = super(BYOC, self).unlink()
        return res

    def write(self, vals):
        self.env['oduist.license'].check_license('connect_byoc', silent=False)
        self.ensure_one() # We do not support updating of multiple records.
        if self.env.context.get("skip_twilio_sync"):
            return super(BYOC, self).write(vals)
        if vals.get('sip_username') and self.sip_username:
            raise ValidationError('You cannot change SIP username!')
        sip_password = False
        if vals.get('sip_password'):
            sip_password = vals['sip_password']
            # Replace password to '*'
            vals['sip_password'] = '*' * len(sip_password)
        res = super(BYOC, self).write(vals)
        # Now let's work with SIP account
        if sip_password and not vals.get('sip_username'):
            # Password change
            self._update_sip_password(sip_password)
        elif sip_password and vals.get('sip_username'):
            # New SIP account
            self._create_sip_account(vals['sip_username'], sip_password)
        return res

    def _update_sip_password(self, password):
        self.ensure_one()
        try:
            client = self.env['connect.settings'].get_client()
            credential = client.sip.credential_lists(
                self.domain.cred_list_sid).credentials(self.sip_credential_sid).update(password=password)
        except Exception as e:
            if 'A strong password is required.' in str(e):
                msg = 'A strong password is required. It must have a minimum length of 12, at least one number, uppercase char and lowercase character.'
                raise ValidationError(msg)
            else:
                raise ValidationError(str(e))

    def _create_sip_account(self, username, password):
        self.ensure_one()
        try:
            client = self.env['connect.settings'].get_client()
            credential = client.sip.credential_lists(
                self.domain.cred_list_sid).credentials.create(
                    username=username, password=password)
            if not credential:
                raise ValidationError('Cannot create a SIP account!')
            self.with_context(skip_twilio_sync=True).write({
                'sip_credential_sid': credential.sid
            })
        except Exception as e:
            if 'A strong password is required' in str(e):
                msg = 'A strong password is required. It must have a minimum length of 12, at least one number, uppercase char and lowercase character.'
                raise ValidationError(msg)
            else:
                raise ValidationError(str(e))

    @api.model_create_multi
    def create(self, vals_list):
        self.env['oduist.license'].check_license('connect_byoc', silent=False)
        if self.env.context.get("skip_twilio_sync"):
            return super(BYOC, self).create(vals_list)
        recs = super(BYOC, self).create(vals_list)
        client = self.env["connect.settings"].get_client()
        for rec in recs:
            # Get main domain
            main_domain = self.env['connect.domain'].search([('byoc', '=', False)])[0]
            # Create a new domain
            domain = self.env['connect.domain'].create({
                'friendly_name': main_domain.friendly_name + ' BYOC {}'.format(rec.id),
                'subdomain': main_domain.subdomain + '-byoc-{}'.format(rec.id),
                'byoc': rec.id,
            })
            # Create connection_policy resource.
            connection_policy = client.voice.v1.connection_policies.create(
                friendly_name=rec.friendly_name
            )
            data = {'connection_policy_sid': connection_policy.sid}
            # Create BYOC trunk
            byoc_trunk = client.voice.v1.byoc_trunks.create(
                friendly_name=rec.friendly_name,
                connection_policy_sid=connection_policy.sid,
                from_domain_sid=domain.sid,
                voice_url=rec.voice_url,
                voice_fallback_url=rec.voice_fallback_url,
                status_callback_url=rec.voice_status_url,
            )
            data['sid'] = byoc_trunk.sid
            rec.with_context(skip_twilio_sync=True).write(data)
            # Set BYOC trunk in twilio.
            twilio_domain = client.sip.domains(domain.sid)
            twilio_domain.update(byoc_trunk_sid=byoc_trunk.sid)
        return recs

    @api.model
    def sync(self):
        if not self.env['oduist.license'].check_license('connect_byoc', silent=True):
            return False
        client = self.env["connect.settings"].get_client()
        trunks = client.voice.v1.byoc_trunks.list()
        for trunk in trunks:
            rec = self.search([("sid", "=", trunk.sid)])
            if not rec:
                # Create trunk in Odoo:
                rec = self.with_context(skip_twilio_sync=True).create(
                    {
                        "sid": trunk.sid,
                        "friendly_name": trunk.friendly_name,
                        "connection_policy_sid": trunk.connection_policy_sid,
                    }
                )
                # Update voice URLs.
                rec.update_twilio_byoc(client)
                self.env["connect.settings"].connect_notify(
                    title="Twilio Sync",
                    message="BYOC trunk {} added".format(trunk.friendly_name),
                )
            else:
                # Trunk already in Odoo, update.
                rec.with_context(skip_twilio_sync=True).write(
                    {
                        "sid": trunk.sid,
                        "friendly_name": trunk.friendly_name,
                        "connection_policy_sid": trunk.connection_policy_sid,
                    }
                )
                rec.update_twilio_byoc(client)
        # Remove trunks that exist only in Odoo (trunk was removed in Twilio).
        trunks_to_remove = self.search([("sid", "not in", [k.sid for k in trunks])])
        if trunks_to_remove:
            user_message = "BYOC(s) {} removed in Twilio!".format(
                ",".join([k.friendly_name for k in trunks_to_remove])
            )
            trunks_to_remove.with_context(skip_twilio_sync=True).unlink()
            self.env["connect.settings"].connect_notify(
                title="Twilio Sync", warning=True, sticky=True, message=user_message
            )

    def update_twilio_byoc(self, client=None):
        self.ensure_one()
        if not client:
            client = self.env["connect.settings"].get_client()
        try:
            trunk = client.voice.v1.byoc_trunks(self.sid)
            trunk.update(
                friendly_name=self.friendly_name,
                voice_url=self.voice_url,
                voice_fallback_url=self.voice_fallback_url,
                status_callback_url=self.voice_status_url,
            )
            debug(self, "BYOC {} updated.".format(self.friendly_name))
        except Exception as e:
            logger.exception("BYOC Update Exception:")
            raise ValidationError(format_connect_response(str(e)))
