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


def _should_skip_twilio_sync(env):
    """Skip Twilio API calls when explicitly requested or when no creds.

    Used by SIP-trunk-related models so that data records loaded at module
    install time (or on Odoo instances that don't have Twilio configured)
    do not crash with HTTP 401 when Twilio credentials are blank.
    """
    if env.context.get('skip_twilio_sync'):
        return True
    settings = env['connect.settings'].sudo()
    return not (settings.get_param('account_sid')
                and settings.get_param('auth_token'))


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

RECORDING_TRIM = [
    ('trim-silence', 'Trim silence'),
    ('do-not-trim', 'Do not trim'),
]

TRANSFER_CALLER_ID = [
    ('from-transferee', 'From Transferee'),
    ('from-transferor', 'From Transferor'),
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
    transfer_caller_id = fields.Selection(
        TRANSFER_CALLER_ID, string='Transfer Caller ID',
        default='from-transferee',
        help='Whose CallerID to present after a SIP REFER transfer.')
    recording_mode = fields.Selection(
        RECORDING_MODE, string='Recording', default='do-not-record')
    recording_trim = fields.Selection(
        RECORDING_TRIM, string='Recording Trim', default='do-not-trim')
    disaster_recovery_url = fields.Char('Disaster Recovery URL')
    disaster_recovery_method = fields.Selection(
        DR_METHOD, string='DR Method', default='POST')

    render_sip_url = fields.Char(
        'Dial SIP URI',
        help='SIP URI dialed when this trunk is used as an extension destination '
             '(e.g. sip:+19789814066@sip.rtc.elevenlabs.io:5060;transport=tcp). '
             'Leave blank to say "not configured".',
    )
    exten = fields.Many2one('connect.exten', string='Extension', ondelete='set null')
    exten_number = fields.Char(related='exten.number', store=True)

    credential_ids = fields.One2many(
        'connect.sip_trunk_credential', 'sip_trunk', string='SIP Credentials')
    ip_acl_ids = fields.One2many(
        'connect.sip_trunk_ip_acl', 'sip_trunk', string='IP ACL')
    origination_url_ids = fields.One2many(
        'connect.sip_trunk_origination_url', 'sip_trunk',
        string='Origination URLs')
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
        if _should_skip_twilio_sync(self.env):
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
                    transfer_caller_id=rec.transfer_caller_id,
                    disaster_recovery_url=rec.disaster_recovery_url or None,
                    disaster_recovery_method=rec.disaster_recovery_method,
                )
            except Exception as e:
                logger.exception('SIP Trunk Create Exception:')
                raise ValidationError(format_connect_response(e))
            rec.with_context(skip_twilio_sync=True).write({'sid': trunk.sid})
            rec._push_recording_to_twilio(client)
            debug(self, 'SIP Trunk {} created in Twilio.'.format(rec.friendly_name))
        return recs

    def _push_recording_to_twilio(self, client):
        """Push recording_mode/trim via the dedicated Recording sub-resource.

        Twilio doesn't accept `recording` on Trunk create/update; the only
        way to set it is POST /Trunks/{sid}/Recording. Calling with the
        defaults is a harmless no-op.
        """
        self.ensure_one()
        if not self.sid:
            return
        try:
            # `recordings()` invokes RecordingList.__call__ to get a
            # RecordingContext; `.recordings.update` would AttributeError
            # because the list itself has no update method.
            client.trunking.v1.trunks(self.sid).recordings().update(
                mode=self.recording_mode or 'do-not-record',
                trim=self.recording_trim or 'do-not-trim',
            )
        except Exception as e:
            logger.exception('SIP Trunk Recording update failed:')
            raise ValidationError(format_connect_response(e))

    def write(self, vals):
        res = super().write(vals)
        if 'exten' in vals:
            for rec in self:
                if rec.exten and (rec.exten.model != rec._name
                                  or rec.exten.res_id != rec.id):
                    rec.exten.with_context(skip_twilio_sync=True).write({
                        'model': rec._name,
                        'res_id': rec.id,
                    })
        if _should_skip_twilio_sync(self.env):
            return res
        twilio_fields = {
            'friendly_name', 'domain_name', 'secure', 'cnam_lookup_enabled',
            'transfer_mode', 'transfer_caller_id', 'disaster_recovery_url',
            'disaster_recovery_method',
        }
        recording_changed = bool(
            {'recording_mode', 'recording_trim'} & set(vals.keys()))
        if not (twilio_fields & set(vals.keys())) and not recording_changed:
            return res
        client = self.env['connect.settings'].get_client()
        for rec in self:
            if not rec.sid:
                continue
            try:
                if twilio_fields & set(vals.keys()):
                    client.trunking.v1.trunks(rec.sid).update(
                        friendly_name=rec.friendly_name,
                        domain_name=rec.domain_name,
                        secure=rec.secure,
                        cnam_lookup_enabled=rec.cnam_lookup_enabled,
                        transfer_mode=rec.transfer_mode,
                        transfer_caller_id=rec.transfer_caller_id,
                        disaster_recovery_url=rec.disaster_recovery_url or None,
                        disaster_recovery_method=rec.disaster_recovery_method,
                    )
                    debug(self, 'SIP Trunk {} updated.'.format(rec.friendly_name))
            except Exception as e:
                logger.exception('SIP Trunk Update Exception:')
                raise ValidationError(format_connect_response(e))
            if recording_changed:
                rec._push_recording_to_twilio(client)
        return res

    def unlink(self):
        if not _should_skip_twilio_sync(self.env):
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

    def render(self, request={}, params={}):
        from twilio.twiml.voice_response import Dial, VoiceResponse
        self.ensure_one()
        response = VoiceResponse()
        if not self.render_sip_url:
            response.say('SIP trunk is not configured for dialing.')
            return response
        dial = Dial(callerId=self._resolve_caller_id(request))
        dial.sip(self.render_sip_url)
        response.append(dial)
        return response

    def _resolve_caller_id(self, request):
        # Twilio rejects Dial->SIP with non-E.164 callerId chars (e.g. the
        # 'client:admin@...' From of JS-SDK callers triggers error 13247).
        # Pick the first sane source.
        self.ensure_one()
        caller = (request or {}).get('Caller') or ''
        if caller.startswith('+') and caller[1:].isdigit():
            return caller
        default = self.env['connect.outgoing_callerid'].sudo().search(
            [('is_default', '=', True)], limit=1)
        if default and default.number:
            return default.number
        if self.number_ids:
            return self.number_ids[0].phone_number
        return 'anonymous'

    def create_extension(self):
        self.ensure_one()
        return self.env['connect.exten'].create_extension(self, 'sip_trunk')

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

    @staticmethod
    def _read_recording(twilio_trunk):
        """Extract (mode, trim) from a Twilio Trunk recording attribute.

        Twilio returns recording as a dict, but defensively handle obj-style.
        """
        rec = getattr(twilio_trunk, 'recording', None) or {}
        if hasattr(rec, 'get'):
            mode = rec.get('mode')
            trim = rec.get('trim')
        else:
            mode = getattr(rec, 'mode', None)
            trim = getattr(rec, 'trim', None)
        return mode or 'do-not-record', trim or 'do-not-trim'

    @api.model
    def sync(self):
        """Pull SIP trunks from Twilio into Odoo (mirror).

        Mirrors the trunk and its sub-resources: origination URLs and
        attached phone numbers. Credentials and IP ACL contents are not
        pulled here — they are managed from Odoo.
        """
        if not self.env['connect.settings'].sudo().get_param('twilio_auto_sync'):
            return False
        if _should_skip_twilio_sync(self.env):
            logger.info('SIP trunk sync skipped: Twilio not configured.')
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
            rec_mode, rec_trim = self._read_recording(tr)
            vals = {
                'friendly_name': tr.friendly_name or tr.sid,
                'domain_name': tr.domain_name or '',
                'secure': bool(tr.secure),
                'cnam_lookup_enabled': bool(tr.cnam_lookup_enabled),
                'transfer_mode': tr.transfer_mode or 'disable-all',
                'transfer_caller_id': (
                    getattr(tr, 'transfer_caller_id', None)
                    or 'from-transferee'),
                'recording_mode': rec_mode,
                'recording_trim': rec_trim,
                'disaster_recovery_url': tr.disaster_recovery_url or '',
                'disaster_recovery_method': tr.disaster_recovery_method or 'POST',
            }
            if not rec:
                vals['sid'] = tr.sid
                rec = self.with_context(skip_twilio_sync=True).create(vals)
            else:
                rec.with_context(skip_twilio_sync=True).write(vals)
            rec._sync_origination_urls(client)
            rec._sync_phone_numbers(client)
        if seen_sids:
            stale = self.search(
                [('sid', 'not in', list(seen_sids)), ('sid', '!=', False)])
        else:
            stale = self.search([('sid', '!=', False)])
        if stale:
            stale.with_context(skip_twilio_sync=True).unlink()
        return True

    def _sync_origination_urls(self, client):
        """Mirror Twilio trunk's OriginationUrls into Odoo records."""
        self.ensure_one()
        if not self.sid:
            return
        try:
            twilio_urls = list(client.trunking.v1.trunks(
                self.sid).origination_urls.list())
        except Exception:
            logger.warning(
                'Cannot list origination URLs for trunk %s', self.sid)
            return
        OUrl = self.env['connect.sip_trunk_origination_url']
        seen = set()
        for ou in twilio_urls:
            seen.add(ou.sid)
            rec = OUrl.search([('origination_url_sid', '=', ou.sid)], limit=1)
            vals = {
                'sip_trunk': self.id,
                'friendly_name': ou.friendly_name or '',
                'sip_url': ou.sip_url,
                'priority': (
                    ou.priority if ou.priority is not None else 10),
                'weight': ou.weight if ou.weight is not None else 10,
                'enabled': bool(ou.enabled),
            }
            if not rec:
                vals['origination_url_sid'] = ou.sid
                OUrl.with_context(skip_twilio_sync=True).create(vals)
            else:
                rec.with_context(skip_twilio_sync=True).write(vals)
        stale = OUrl.search([
            ('sip_trunk', '=', self.id),
            ('origination_url_sid', '!=', False),
            ('origination_url_sid', 'not in', list(seen) or [False]),
        ])
        if stale:
            stale.with_context(skip_twilio_sync=True).unlink()

    def _sync_phone_numbers(self, client):
        """Mirror trunk's PhoneNumbers membership onto connect.number.sip_trunk."""
        self.ensure_one()
        if not self.sid:
            return
        try:
            twilio_pns = list(client.trunking.v1.trunks(
                self.sid).phone_numbers.list())
        except Exception:
            logger.warning(
                'Cannot list phone_numbers for trunk %s', self.sid)
            return
        seen_sids = {pn.sid for pn in twilio_pns}
        Number = self.env['connect.number']
        for pn_sid in seen_sids:
            num = Number.search([('sid', '=', pn_sid)], limit=1)
            if num and num.sip_trunk.id != self.id:
                num.with_context(skip_twilio_sync=True).sip_trunk = self.id
        detach = Number.search([
            ('sip_trunk', '=', self.id),
            ('sid', '!=', False),
            ('sid', 'not in', list(seen_sids) or [False]),
        ])
        if detach:
            detach.with_context(skip_twilio_sync=True).write({'sip_trunk': False})


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
        if _should_skip_twilio_sync(self.env):
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
        if not is_real_pw or _should_skip_twilio_sync(self.env):
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
        if not _should_skip_twilio_sync(self.env):
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
        if _should_skip_twilio_sync(self.env):
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
        if _should_skip_twilio_sync(self.env):
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
        if not _should_skip_twilio_sync(self.env):
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


class SipTrunkOriginationUrl(models.Model):
    _name = 'connect.sip_trunk_origination_url'
    _description = 'SIP Trunk Origination URL'
    _rec_name = 'sip_url'
    _order = 'priority, weight desc, id'

    sip_trunk = fields.Many2one(
        'connect.sip_trunk', required=True, ondelete='cascade')
    friendly_name = fields.Char()
    sip_url = fields.Char(
        required=True,
        help='sip: or sips: URI of your PBX/SBC '
             '(e.g. sip:pbx.example.com:5060).')
    priority = fields.Integer(
        default=10, help='0-65535. Lower wins.')
    weight = fields.Integer(
        default=10,
        help='1-65535. Load-share within the same priority.')
    enabled = fields.Boolean(default=True)
    origination_url_sid = fields.Char(readonly=True)

    @api.constrains('sip_url')
    def _check_sip_url(self):
        for rec in self:
            if not rec.sip_url:
                continue
            scheme = rec.sip_url.split(':', 1)[0].lower()
            if scheme not in ('sip', 'sips'):
                raise ValidationError(
                    'Origination URL must start with sip: or sips:')

    @api.constrains('priority', 'weight')
    def _check_priority_weight(self):
        for rec in self:
            if not 0 <= rec.priority <= 65535:
                raise ValidationError('Priority must be between 0 and 65535.')
            if not 1 <= rec.weight <= 65535:
                raise ValidationError('Weight must be between 1 and 65535.')

    def _twilio_payload(self):
        self.ensure_one()
        return {
            'sip_url': self.sip_url,
            'friendly_name': self.friendly_name or self.sip_url,
            'priority': self.priority,
            'weight': self.weight,
            'enabled': self.enabled,
        }

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if _should_skip_twilio_sync(self.env):
            return recs
        client = self.env['connect.settings'].get_client()
        for rec in recs:
            if not rec.sip_trunk.sid:
                continue
            try:
                ou = client.trunking.v1.trunks(
                    rec.sip_trunk.sid).origination_urls.create(
                        **rec._twilio_payload())
            except Exception as e:
                logger.exception('OriginationUrl create failed:')
                raise ValidationError(format_connect_response(e))
            rec.with_context(skip_twilio_sync=True).write(
                {'origination_url_sid': ou.sid})
        return recs

    def write(self, vals):
        res = super().write(vals)
        if _should_skip_twilio_sync(self.env):
            return res
        twilio_fields = {
            'sip_url', 'friendly_name', 'priority', 'weight', 'enabled'}
        if not (twilio_fields & set(vals.keys())):
            return res
        client = self.env['connect.settings'].get_client()
        for rec in self:
            if not (rec.sip_trunk.sid and rec.origination_url_sid):
                continue
            try:
                client.trunking.v1.trunks(
                    rec.sip_trunk.sid
                ).origination_urls(rec.origination_url_sid).update(
                    **rec._twilio_payload())
            except Exception as e:
                logger.exception('OriginationUrl update failed:')
                raise ValidationError(format_connect_response(e))
        return res

    def unlink(self):
        if not _should_skip_twilio_sync(self.env):
            client = self.env['connect.settings'].get_client()
            for rec in self:
                if not (rec.sip_trunk.sid and rec.origination_url_sid):
                    continue
                try:
                    client.trunking.v1.trunks(
                        rec.sip_trunk.sid
                    ).origination_urls(rec.origination_url_sid).delete()
                except Exception as e:
                    if 'not found' not in str(e).lower():
                        raise ValidationError(format_connect_response(e))
        return super().unlink()
