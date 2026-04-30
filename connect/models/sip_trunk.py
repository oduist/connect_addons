# -*- coding: utf-8 -*-
"""Twilio Elastic SIP Trunking integration.

Models:
    connect.sip_trunk             — Twilio Trunk resource
    connect.sip_trunk_credential  — username/password termination auth
    connect.sip_trunk_ip_acl      — IP-based termination auth
"""

import ipaddress
import logging
import re

from odoo import api, fields, models, release
from odoo.exceptions import ValidationError

if release.version_info[0] >= 19:
    from odoo.models import Constraint

from .settings import debug, format_connect_response

logger = logging.getLogger(__name__)


TRANSFER_MODE = [
    ('disable-all', 'Disabled'),
    ('enable-all', 'Enabled (PSTN + SIP)'),
    ('sip-only', 'SIP Only'),
]

RECORDING_MODE = [
    ('do-not-record', 'Do not record'),
    ('record-from-ringing', 'Record from ringing'),
    ('record-from-answer', 'Record from answer'),
    ('record-from-ringing-dual', 'Record from ringing (dual)'),
    ('record-from-answer-dual', 'Record from answer (dual)'),
]

AUTH_TYPE = [
    ('credentials', 'SIP Credentials'),
    ('ip_acl', 'IP Access Control List'),
]

DR_METHOD = [
    ('POST', 'POST'),
    ('GET', 'GET'),
]


class SipTrunk(models.Model):
    _name = 'connect.sip_trunk'
    _description = 'SIP Trunk (Twilio Elastic SIP Trunking)'
    _rec_name = 'friendly_name'
    _order = 'friendly_name'

    sid = fields.Char('Trunk SID', readonly=True)
    friendly_name = fields.Char('Name', required=True)
    domain_name = fields.Char(
        'Termination URI',
        help='Public SIP URI your PBX sends INVITEs to '
             '(e.g. mycorp.pstn.twilio.com). Auto-generated if left blank.',
    )
    secure = fields.Boolean('Secure (TLS/SRTP)', default=False)
    cnam_lookup_enabled = fields.Boolean('CNAM Lookup', default=False)
    transfer_mode = fields.Selection(
        TRANSFER_MODE, string='Call Transfer', default='disable-all')
    recording_mode = fields.Selection(
        RECORDING_MODE, string='Recording', default='do-not-record')
    auth_type = fields.Selection(
        AUTH_TYPE, string='Authentication', default='credentials')
    disaster_recovery_url = fields.Char('Disaster Recovery URL')
    disaster_recovery_method = fields.Selection(
        DR_METHOD, string='DR Method', default='POST')

    credential_ids = fields.One2many(
        'connect.sip_trunk_credential', 'sip_trunk', string='SIP Credentials')
    ip_acl_ids = fields.One2many(
        'connect.sip_trunk_ip_acl', 'sip_trunk', string='IP ACL')
    number_ids = fields.One2many(
        'connect.number', 'sip_trunk', string='Phone Numbers')
    number_count = fields.Integer(compute='_compute_number_count')

    credential_list_sid = fields.Char(readonly=True)
    ip_acl_sid = fields.Char(readonly=True)

    if release.version_info[0] >= 19:
        _sid_unique = Constraint(
            'UNIQUE(sid)', 'This Twilio Trunk SID is already used!')
    else:
        _sql_constraints = [
            ('sid_unique', 'UNIQUE(sid)',
             'This Twilio Trunk SID is already used!'),
        ]

    def _compute_number_count(self):
        for rec in self:
            rec.number_count = len(rec.number_ids)

    @api.constrains('domain_name')
    def _check_domain_name(self):
        for rec in self:
            if not rec.domain_name:
                continue
            if not rec.domain_name.endswith('.pstn.twilio.com'):
                raise ValidationError(
                    'Termination URI must end with .pstn.twilio.com')
            prefix = rec.domain_name.replace('.pstn.twilio.com', '')
            if not re.match(r'^[a-z0-9][a-z0-9-]{0,62}$', prefix):
                raise ValidationError(
                    'Termination URI prefix must be lowercase alphanumeric '
                    'with optional hyphens (max 63 chars).')

    def _build_default_domain_name(self):
        self.ensure_one()
        return 'connect-trunk-{}.pstn.twilio.com'.format(self.id)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if self.env.context.get('skip_twilio_sync'):
            return recs
        client = self.env['connect.settings'].get_client()
        for rec in recs:
            if not rec.domain_name:
                rec.with_context(skip_twilio_sync=True).domain_name = \
                    rec._build_default_domain_name()
            try:
                trunk = client.trunking.v1.trunks.create(
                    friendly_name=rec.friendly_name,
                    domain_name=rec.domain_name,
                    secure=rec.secure,
                    cnam_lookup_enabled=rec.cnam_lookup_enabled,
                    transfer_mode=rec.transfer_mode,
                    disaster_recovery_url=rec.disaster_recovery_url or None,
                    disaster_recovery_method=rec.disaster_recovery_method,
                )
            except Exception as e:
                logger.exception('SIP Trunk Create Exception:')
                raise ValidationError(format_connect_response(e))
            rec.with_context(skip_twilio_sync=True).write({'sid': trunk.sid})
            debug(self, 'SIP Trunk {} created in Twilio.'.format(rec.friendly_name))
        return recs

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_twilio_sync'):
            return res
        twilio_fields = {
            'friendly_name', 'domain_name', 'secure', 'cnam_lookup_enabled',
            'transfer_mode', 'disaster_recovery_url', 'disaster_recovery_method',
        }
        if not (twilio_fields & set(vals.keys())):
            return res
        client = self.env['connect.settings'].get_client()
        for rec in self:
            if not rec.sid:
                continue
            try:
                client.trunking.v1.trunks(rec.sid).update(
                    friendly_name=rec.friendly_name,
                    domain_name=rec.domain_name,
                    secure=rec.secure,
                    cnam_lookup_enabled=rec.cnam_lookup_enabled,
                    transfer_mode=rec.transfer_mode,
                    disaster_recovery_url=rec.disaster_recovery_url or None,
                    disaster_recovery_method=rec.disaster_recovery_method,
                )
                debug(self, 'SIP Trunk {} updated.'.format(rec.friendly_name))
            except Exception as e:
                logger.exception('SIP Trunk Update Exception:')
                raise ValidationError(format_connect_response(e))
        return res

    def unlink(self):
        if not self.env.context.get('skip_twilio_sync'):
            client = self.env['connect.settings'].get_client()
            for rec in self:
                if not rec.sid:
                    continue
                try:
                    client.trunking.v1.trunks(rec.sid).delete()
                    debug(self, 'SIP Trunk {} deleted.'.format(rec.friendly_name))
                except Exception as e:
                    if 'not found' in str(e).lower():
                        logger.warning('Trunk %s not found in Twilio.', rec.sid)
                    else:
                        raise ValidationError(format_connect_response(e))
                if rec.credential_list_sid:
                    try:
                        client.sip.credential_lists(
                            rec.credential_list_sid).delete()
                    except Exception:
                        logger.warning(
                            'Failed to delete CredentialList %s',
                            rec.credential_list_sid)
                if rec.ip_acl_sid:
                    try:
                        client.sip.ip_access_control_lists(
                            rec.ip_acl_sid).delete()
                    except Exception:
                        logger.warning(
                            'Failed to delete IpAccessControlList %s',
                            rec.ip_acl_sid)
        return super().unlink()

    def _ensure_credential_list(self, client):
        """Get or create the CredentialList associated with this trunk.

        Order of preference:
          1. Cached SID on the Odoo record.
          2. Existing CredentialList already attached to the Twilio trunk.
          3. Existing CredentialList in the account with matching friendly_name
             (orphan from a previous run — re-attach to this trunk).
          4. Create a new CredentialList and attach it.
        """
        self.ensure_one()
        if self.credential_list_sid:
            return self.credential_list_sid

        target_name = 'Trunk {}'.format(self.friendly_name)
        cred_list_sid = None
        attached = False

        try:
            existing = list(client.trunking.v1.trunks(
                self.sid).credentials_lists.list(limit=1))
            if existing:
                cred_list_sid = existing[0].sid
                attached = True
        except Exception:
            logger.warning(
                'Could not list credentials_lists on trunk %s', self.sid)

        if not cred_list_sid:
            try:
                for lst in client.sip.credential_lists.list():
                    if lst.friendly_name == target_name:
                        cred_list_sid = lst.sid
                        break
            except Exception:
                pass

        if not cred_list_sid:
            cred_list = client.sip.credential_lists.create(
                friendly_name=target_name)
            cred_list_sid = cred_list.sid

        if not attached:
            try:
                client.trunking.v1.trunks(self.sid).credentials_lists.create(
                    credential_list_sid=cred_list_sid)
            except Exception as e:
                if 'already' not in str(e).lower():
                    raise

        self.with_context(skip_twilio_sync=True).credential_list_sid = cred_list_sid
        return cred_list_sid

    def _ensure_ip_acl(self, client):
        """Get or create the IpAccessControlList associated with this trunk.

        Same lookup strategy as _ensure_credential_list.
        """
        self.ensure_one()
        if self.ip_acl_sid:
            return self.ip_acl_sid

        target_name = 'Trunk {}'.format(self.friendly_name)
        acl_sid = None
        attached = False

        try:
            existing = list(client.trunking.v1.trunks(
                self.sid).ip_access_control_lists.list(limit=1))
            if existing:
                acl_sid = existing[0].sid
                attached = True
        except Exception:
            logger.warning(
                'Could not list ip_access_control_lists on trunk %s', self.sid)

        if not acl_sid:
            try:
                for lst in client.sip.ip_access_control_lists.list():
                    if lst.friendly_name == target_name:
                        acl_sid = lst.sid
                        break
            except Exception:
                pass

        if not acl_sid:
            acl = client.sip.ip_access_control_lists.create(
                friendly_name=target_name)
            acl_sid = acl.sid

        if not attached:
            try:
                client.trunking.v1.trunks(
                    self.sid).ip_access_control_lists.create(
                        ip_access_control_list_sid=acl_sid)
            except Exception as e:
                if 'already' not in str(e).lower():
                    raise

        self.with_context(skip_twilio_sync=True).ip_acl_sid = acl_sid
        return acl_sid

    def action_view_numbers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Phone Numbers',
            'res_model': 'connect.number',
            'view_mode': 'list,form',
            'domain': [('sip_trunk', '=', self.id)],
            'context': {'default_sip_trunk': self.id},
        }

    @api.model
    def sync(self):
        """Pull SIP trunks from Twilio into Odoo (mirror)."""
        if not self.env['connect.settings'].sudo().get_param('twilio_auto_sync'):
            return False
        try:
            client = self.env['connect.settings'].get_client()
        except Exception:
            logger.warning('Cannot sync SIP trunks: Twilio client unavailable.')
            return False
        twilio_trunks = client.trunking.v1.trunks.list()
        seen_sids = set()
        for tr in twilio_trunks:
            seen_sids.add(tr.sid)
            rec = self.search([('sid', '=', tr.sid)])
            vals = {
                'friendly_name': tr.friendly_name or tr.sid,
                'domain_name': tr.domain_name or '',
                'secure': bool(tr.secure),
                'cnam_lookup_enabled': bool(tr.cnam_lookup_enabled),
                'transfer_mode': tr.transfer_mode or 'disable-all',
                'disaster_recovery_url': tr.disaster_recovery_url or '',
                'disaster_recovery_method': tr.disaster_recovery_method or 'POST',
            }
            if not rec:
                vals['sid'] = tr.sid
                self.with_context(skip_twilio_sync=True).create(vals)
            else:
                rec.with_context(skip_twilio_sync=True).write(vals)
        if seen_sids:
            stale = self.search(
                [('sid', 'not in', list(seen_sids)), ('sid', '!=', False)])
        else:
            stale = self.search([('sid', '!=', False)])
        if stale:
            stale.with_context(skip_twilio_sync=True).unlink()
        return True


class SipTrunkCredential(models.Model):
    _name = 'connect.sip_trunk_credential'
    _description = 'SIP Trunk Credential'
    _rec_name = 'username'

    sip_trunk = fields.Many2one(
        'connect.sip_trunk', required=True, ondelete='cascade')
    username = fields.Char(required=True)
    password = fields.Char()
    credential_sid = fields.Char(readonly=True)
    credential_list_sid = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if self.env.context.get('skip_twilio_sync'):
            return recs
        client = self.env['connect.settings'].get_client()
        for rec in recs:
            password = rec.password
            if not password:
                continue
            try:
                cred_list_sid = rec.sip_trunk._ensure_credential_list(client)
                cred = client.sip.credential_lists(
                    cred_list_sid).credentials.create(
                        username=rec.username, password=password)
            except Exception as e:
                logger.exception('Credential create failed:')
                raise ValidationError(format_connect_response(e))
            rec.with_context(skip_twilio_sync=True).write({
                'credential_sid': cred.sid,
                'credential_list_sid': cred_list_sid,
                'password': '*' * len(password),
            })
        return recs

    def write(self, vals):
        new_password = vals.get('password')
        is_real_pw = new_password and set(new_password) != {'*'}
        if is_real_pw:
            vals['password'] = '*' * len(new_password)
        res = super().write(vals)
        if self.env.context.get('skip_twilio_sync') or not is_real_pw:
            return res
        client = self.env['connect.settings'].get_client()
        for rec in self:
            if not rec.credential_sid:
                continue
            try:
                client.sip.credential_lists(
                    rec.credential_list_sid
                ).credentials(rec.credential_sid).update(password=new_password)
            except Exception as e:
                raise ValidationError(format_connect_response(e))
        return res

    def unlink(self):
        if not self.env.context.get('skip_twilio_sync'):
            client = self.env['connect.settings'].get_client()
            for rec in self:
                if not (rec.credential_sid and rec.credential_list_sid):
                    continue
                try:
                    client.sip.credential_lists(
                        rec.credential_list_sid
                    ).credentials(rec.credential_sid).delete()
                except Exception as e:
                    if 'not found' not in str(e).lower():
                        raise ValidationError(format_connect_response(e))
        return super().unlink()


class SipTrunkIpAcl(models.Model):
    _name = 'connect.sip_trunk_ip_acl'
    _description = 'SIP Trunk IP Access Control'
    _rec_name = 'friendly_name'

    sip_trunk = fields.Many2one(
        'connect.sip_trunk', required=True, ondelete='cascade')
    friendly_name = fields.Char(required=True)
    ip_address = fields.Char(required=True, help='IPv4 address; CIDR mask supported')
    cidr_prefix_length = fields.Integer(default=32)
    ip_acl_sid = fields.Char(readonly=True)
    ip_address_sid = fields.Char(readonly=True)

    @api.constrains('ip_address', 'cidr_prefix_length')
    def _check_ip(self):
        for rec in self:
            try:
                ipaddress.ip_network(
                    '{}/{}'.format(rec.ip_address, rec.cidr_prefix_length),
                    strict=False)
            except (ValueError, TypeError):
                raise ValidationError(
                    'Invalid IP address or CIDR: {}/{}'.format(
                        rec.ip_address, rec.cidr_prefix_length))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if self.env.context.get('skip_twilio_sync'):
            return recs
        client = self.env['connect.settings'].get_client()
        for rec in recs:
            try:
                acl_sid = rec.sip_trunk._ensure_ip_acl(client)
                ip = client.sip.ip_access_control_lists(
                    acl_sid).ip_addresses.create(
                        friendly_name=rec.friendly_name,
                        ip_address=rec.ip_address,
                        cidr_prefix_length=rec.cidr_prefix_length or 32)
            except Exception as e:
                logger.exception('IP ACL create failed:')
                raise ValidationError(format_connect_response(e))
            rec.with_context(skip_twilio_sync=True).write({
                'ip_acl_sid': acl_sid,
                'ip_address_sid': ip.sid,
            })
        return recs

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_twilio_sync'):
            return res
        if not ({'ip_address', 'friendly_name', 'cidr_prefix_length'} & set(vals.keys())):
            return res
        client = self.env['connect.settings'].get_client()
        for rec in self:
            if not (rec.ip_acl_sid and rec.ip_address_sid):
                continue
            try:
                client.sip.ip_access_control_lists(
                    rec.ip_acl_sid
                ).ip_addresses(rec.ip_address_sid).update(
                    friendly_name=rec.friendly_name,
                    ip_address=rec.ip_address,
                    cidr_prefix_length=rec.cidr_prefix_length or 32)
            except Exception as e:
                raise ValidationError(format_connect_response(e))
        return res

    def unlink(self):
        if not self.env.context.get('skip_twilio_sync'):
            client = self.env['connect.settings'].get_client()
            for rec in self:
                if not (rec.ip_acl_sid and rec.ip_address_sid):
                    continue
                try:
                    client.sip.ip_access_control_lists(
                        rec.ip_acl_sid
                    ).ip_addresses(rec.ip_address_sid).delete()
                except Exception as e:
                    if 'not found' not in str(e).lower():
                        raise ValidationError(format_connect_response(e))
        return super().unlink()
