# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import json
import requests
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


CONTENT_TYPES = [
    ('twilio/text', 'twilio/text'),
    ('twilio/media', 'twilio/media'),
    ('twilio/location', 'twilio/location'),
    ('twilio/list-picker', 'twilio/list-picker'),
    ('twilio/call-to-action', 'twilio/call-to-action'),
    ('twilio/quick-reply', 'twilio/quick-reply'),
    ('twilio/card', 'twilio/card'),
    ('twilio/carousel', 'twilio/carousel'),
    ('twilio/catalog', 'twilio/catalog'),
    ('twilio/pay', 'twilio/pay'),
    ('twilio/flows', 'twilio/flows'),
    ('whatsapp/authentication', 'whatsapp/authentication'),
    ('whatsapp/card', 'whatsapp/card'),
]

WHATSAPP_STATUSES = [
    ('unsubmitted', 'Unsubmitted'),
    ('received', 'Received'),
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('paused', 'Paused'),
    ('disabled', 'Disabled'),
]

WHATSAPP_CATEGORIES = [
    ('UTILITY', 'Utility'),
    ('AUTHENTICATION', 'Authentication'),
    ('MARKETING', 'Marketing')
]


class ConnectMessageContentTemplate(models.Model):
    _name = 'connect.message_content_template'
    _description = 'WhatsApp Content Template (Twilio Content API)'
    _rec_name = 'friendly_name'
    _order = 'create_date desc'

    # Link template to a specific Odoo model it applies to
    model_id = fields.Many2one('ir.model', string='Model', help='Model this template applies to.')
    sender_id = fields.Many2one('connect.whatsapp_sender', string='Sender', help='Limit template to a specific WhatsApp sender (optional).')

    friendly_name = fields.Char(string='Name', required=True)
    language = fields.Many2one('res.lang', string='Language', required=True)
    variables = fields.Text(string='Variables', help='JSON mapping like {"1":"Owl Air Customer"}')
    content_type = fields.Selection(selection=CONTENT_TYPES, required=True)
    body = fields.Text(string='Body')
    actions = fields.Text(string='Actions (JSON)')

    # Twilio returned fields
    sid = fields.Char(string="SID", readonly=True)
    approval_create_link = fields.Char(readonly=True)
    approval_fetch = fields.Char(readonly=True)
    date_created = fields.Datetime(readonly=True)
    date_updated = fields.Datetime(readonly=True)
    category = fields.Selection(selection=WHATSAPP_CATEGORIES)
    status = fields.Selection(selection=WHATSAPP_STATUSES, default='unsubmitted', required=True, readonly=True)
    rejection_reason = fields.Char(readonly=True)
    allow_category_change = fields.Boolean(readonly=True)

    display_status = fields.Html(string='Status', compute='_compute_display_status', sanitize=False)

    @api.constrains('variables')
    def _check_variables_json(self):
        for rec in self:
            if rec.variables:
                try:
                    val = json.loads(rec.variables)
                    if not isinstance(val, dict):
                        raise ValidationError('Variables must be a JSON object, e.g., {"1":"Value"}.')
                except Exception as e:
                    raise ValidationError('Variables must be valid JSON: {}'.format(e))

    @api.constrains('actions')
    def _check_actions_json(self):
        for rec in self:
            if rec.actions:
                try:
                    val = json.loads(rec.actions)
                    print(rec.actions)
                    print(type(val), val)
                    if not isinstance(val, list):
                        raise ValidationError('Actions must be a JSON list (array) of objects.')
                except Exception as e:
                    raise ValidationError('Actions must be valid JSON: {}'.format(e))

    def _compute_display_status(self):
        icon_map = {
            'approved': ('fa fa-check-circle text-success', 'Approved'),
            'pending': ('fa fa-clock-o text-warning', 'Pending'),
            'received': ('fa fa-clock-o text-warning', 'Received'),
            'paused': ('fa fa-pause-circle text-warning', 'Paused'),
            'disabled': ('fa fa-ban text-danger', 'Disabled'),
            'rejected': ('fa fa-times-circle text-danger', 'Rejected'),
            'unsubmitted': ('fa fa-circle-o text-muted', 'Unsubmitted'),
        }
        for rec in self:
            st = (rec.status or 'unsubmitted').lower()
            icon, label = icon_map.get(st, ('fa fa-circle-o text-muted', st.title()))
            rec.display_status = f"<span><i class='{icon}' style='margin-right:6px;'></i>{label}</span>"

    def _normalize_twilio_datetime(self, value):
        if not value:
            return False
        try:
            s = str(value)
            if s.endswith('Z'):
                s = s.replace('Z', '+00:00')
            dt = datetime.fromisoformat(s)
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return fields.Datetime.to_string(dt)
        except Exception:
            return False

    def create_in_twilio(self):
        self.ensure_one()
        account_sid = self.env['connect.settings'].get_param('account_sid')
        auth_token = self.env['connect.settings'].get_param('auth_token')
        self.ensure_one()
        # Block posting if already approved (shouldn't happen on create, but safe)
        if not account_sid or not auth_token:
            raise ValidationError('Twilio credentials are not configured.')
        # Build payload
        lang_code = (self.language.code or 'en').split('_')[0]
        variables = {}
        if self.variables:
            variables = json.loads(self.variables)
            if not isinstance(variables, dict):
                raise ValidationError('Variables must be a JSON object.')
        type_payload = {}
        if self.body:
            type_payload['body'] = self.body
        if self.content_type == 'twilio/quick-reply' and self.actions:
            actions = json.loads(self.actions)
            if not isinstance(actions, list):
                raise ValidationError('Actions must be a JSON list.')
            type_payload['actions'] = actions
        payload = {
            'friendly_name': self.friendly_name,
            'language': lang_code,
            'variables': variables,
            'types': {self.content_type: type_payload or {'body': self.body or ''}},
        }
        if self.category:
            payload['category'] = self.category.upper()
        try:
            resp = requests.post(
                'https://content.twilio.com/v1/Content',
                auth=(account_sid, auth_token),
                json=payload,
                timeout=30,
            )
            if resp.status_code >= 400:
                raise ValidationError('Twilio error: {} {}'.format(resp.status_code, resp.text))
            data = resp.json()
            links = data.get('links') or {}
            date_created = data.get('date_created') or data.get('dateCreated')
            date_updated = data.get('date_updated') or data.get('dateUpdated')
            status_val = (data.get('status') or data.get('whatsapp', {}).get('status') or 'unsubmitted')
            self.write({
                'sid': data.get('sid'),
                'date_created': self._normalize_twilio_datetime(date_created),
                'date_updated': self._normalize_twilio_datetime(date_updated),
                'approval_create_link': links.get('approval_create') or links.get('whatsapp_approval_create'),
                'approval_fetch': links.get('approval_fetch') or links.get('whatsapp_approval_fetch'),
                'status': str(status_val).lower(),
            })
        except Exception as e:
            raise ValidationError('Failed to create content in Twilio: {}'.format(e))



    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec.create_in_twilio()
        return records

    def _twilio_submit_for_approval(self):
        """Submit current content to Twilio WhatsApp approval API and update fields."""
        self.ensure_one()
        if not self.sid:
            raise ValidationError('Content SID is missing. Save the template first.')
        account_sid = self.env['connect.settings'].get_param('account_sid')
        auth_token = self.env['connect.settings'].get_param('auth_token')
        if not account_sid or not auth_token:
            raise ValidationError('Twilio credentials are not configured.')
        # sanitize name and compute category
        import re
        name = re.sub(r'[^a-z0-9_]', '_', (self.friendly_name or '').lower())
        allowed = {'UTILITY', 'MARKETING', 'AUTHENTICATION'}
        category_send = self.category if self.category in allowed else 'UTILITY'
        url = self.approval_create_link or f'https://content.twilio.com/v1/Content/{self.sid}/ApprovalRequests/whatsapp'
        payload = {'name': name, 'category': category_send}
        try:
            resp = requests.post(url, auth=(account_sid, auth_token), json=payload, timeout=30)
            if resp.status_code >= 400:
                raise ValidationError('Twilio error: {} {}'.format(resp.status_code, resp.text))
            data = resp.json()
            updates = {
                'status': str(data.get('status', 'received')).lower(),
                'rejection_reason': data.get('rejection_reason') or '',
            }
            if data.get('category'):
                updates['category'] = data.get('category')
            self.write(updates)
            return data
        except Exception as e:
            raise ValidationError('Failed to submit for approval: {}'.format(e))

    def action_approve(self):
        for rec in self:
            # If previously rejected: remove in Twilio, recreate, then submit again
            if rec.status == 'rejected':
                rec.delete_in_twilio()
                # clear Twilio-related fields before re-creating
                rec.write({
                    'sid': False,
                    'approval_create_link': False,
                    'approval_fetch': False,
                    'date_created': False,
                    'date_updated': False,
                    'status': 'unsubmitted',
                    'rejection_reason': False,
                })
                rec.create_in_twilio()
                rec._twilio_submit_for_approval()
                continue
            # Normal path: only allow unsubmitted to be sent
            if rec.status and rec.status != 'unsubmitted':
                raise ValidationError('This content has already been submitted. Current status: %s' % rec.status)
            rec._twilio_submit_for_approval()

    def delete_in_twilio(self):
        """Delete content objects from Twilio Content API (best-effort)."""
        account_sid = self.env['connect.settings'].get_param('account_sid')
        auth_token = self.env['connect.settings'].get_param('auth_token')
        for rec in self:
            try:
                if rec.sid and account_sid and auth_token:
                    url = f'https://content.twilio.com/v1/Content/{rec.sid}'
                    resp = requests.delete(url, auth=(account_sid, auth_token), timeout=30)
                    if resp.status_code == 404:
                        logger.warning('Content %s not found in Twilio during delete', rec.sid)
                    elif resp.status_code >= 400:
                        raise ValidationError('Twilio delete error for %s: %s %s' % (rec.sid, resp.status_code, resp.text))
            except Exception as e:
                logger.warning('Failed to delete content %s in Twilio: %s', rec.sid or '?', e)
        return True

    def unlink(self):
        # Remove in Twilio first, then local unlink
        self.delete_in_twilio()
        return super().unlink()

    def write(self, vals):
        # Prevent changing content unless status is unsubmitted or rejected.
        # Exception: allow changing 'category' when status is 'approved' AND allow_category_change is True.
        content_fields = {'friendly_name', 'language', 'variables', 'content_type', 'body', 'actions', 'category'}
        if any(f in vals for f in content_fields):
            for rec in self:
                # Non-category fields are always restricted to unsubmitted/rejected
                blocked_other = any(k in vals for k in (content_fields - {'category'})) and \
                                (rec.status not in ('unsubmitted', 'rejected'))
                # Category field special-case
                changing_category = 'category' in vals
                category_allowed = (rec.status in ('unsubmitted', 'rejected')) or \
                                   (rec.status == 'approved' and rec.allow_category_change)
                if blocked_other:
                    raise ValidationError('Content can be modified only when status is Unsubmitted or Rejected.')
                if changing_category and not category_allowed:
                    raise ValidationError('Category can be modified only when status is Unsubmitted/Rejected or when Approved with Allow Category Change.')
        return super().write(vals)

    def action_fetch_approval_status(self):
        for rec in self:
            link = rec.approval_fetch
            if not link:
                raise ValidationError('Approval fetch link is not set for this template.')
            account_sid = self.env['connect.settings'].get_param('account_sid')
            auth_token = self.env['connect.settings'].get_param('auth_token')
            if not account_sid or not auth_token:
                raise ValidationError('Twilio credentials are not configured.')
            try:
                resp = requests.get(link, auth=(account_sid, auth_token), timeout=30)
                if resp.status_code >= 400:
                    raise ValidationError('Twilio error: {} {}'.format(resp.status_code, resp.text))
                data = resp.json() if resp.headers.get('Content-Type','').startswith('application/json') else {}
                # Flexible parsing
                date_created = data.get('date_created') or data.get('dateCreated')
                date_updated = data.get('date_updated') or data.get('dateUpdated')
                status = (data.get('status')
                          or data.get('approval_status')
                          or data.get('whatsapp_status')
                          or data.get('whatsapp', {}).get('status')
                          or data.get('channels', {}).get('whatsapp', {}).get('status'))
                reason = (data.get('rejection_reason')
                          or data.get('reason')
                          or data.get('whatsapp', {}).get('rejection_reason')
                          or data.get('channels', {}).get('whatsapp', {}).get('rejection_reason'))
                allow_change = (data.get('allow_category_change')
                                or data.get('whatsapp', {}).get('allow_category_change')
                                or data.get('channels', {}).get('whatsapp', {}).get('allow_category_change'))
                updates = {}
                if status:
                    updates['status'] = str(status).lower()
                if reason:
                    updates['rejection_reason'] = reason
                if allow_change is not None:
                    updates['allow_category_change'] = bool(allow_change)
                # Update dates if present
                if date_created:
                    updates['date_created'] = rec._normalize_twilio_datetime(date_created)
                if date_updated:
                    updates['date_updated'] = rec._normalize_twilio_datetime(date_updated)
                if updates:
                    rec.write(updates)
            except Exception as e:
                raise ValidationError('Failed to fetch approval status: {}'.format(e))
            except Exception as e:
                raise ValidationError('Failed to fetch approval status: {}'.format(e))
