# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import json
import requests


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
    ('Unsubmitted', 'Unsubmitted'),
    ('Received', 'Received'),
    ('Pending', 'Pending'),
    ('Approved', 'Approved'),
    ('Rejected', 'Rejected'),
    ('Paused', 'Paused'),
    ('Disabled', 'Disabled'),
]

WHATSAPP_CATEGORIES = [
    ('UTILITY', 'UTILITY'),
    ('AUTHENTICATION', 'AUTHENTICATION'),
    ('MARKETING', 'MARKETING'),
    ('TRANSPORTATION_UPDATE', 'TRANSPORTATION_UPDATE'),
]


class ConnectMessageContentTemplate(models.Model):
    _name = 'connect.message_content_template'
    _description = 'WhatsApp Content Template (Twilio Content API)'
    _rec_name = 'friendly_name'
    _order = 'create_date desc'

    friendly_name = fields.Char(required=True)
    language = fields.Many2one('res.lang', string='Language', required=True)
    variables = fields.Text(string='Variables', help='JSON mapping like {"1":"Owl Air Customer"}')
    content_type = fields.Selection(selection=CONTENT_TYPES, required=True)
    body = fields.Text(string='Body')
    actions = fields.Text(string='Actions (JSON)')

    # Twilio returned fields
    sid = fields.Char(readonly=True)
    approval_create_link = fields.Char(readonly=True)
    approval_fetch = fields.Char(readonly=True)
    date_created = fields.Datetime(readonly=True)
    date_updated = fields.Datetime(readonly=True)
    category = fields.Selection(selection=WHATSAPP_CATEGORIES)
    status = fields.Selection(selection=WHATSAPP_STATUSES, readonly=True)
    rejection_reason = fields.Char(readonly=True)

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
                    if not isinstance(val, list):
                        raise ValidationError('Actions must be a JSON list (array) of objects.')
                except Exception as e:
                    raise ValidationError('Actions must be valid JSON: {}'.format(e))

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
                status = (data.get('status')
                          or data.get('approval_status')
                          or data.get('whatsapp_status')
                          or data.get('whatsapp', {}).get('status')
                          or data.get('channels', {}).get('whatsapp', {}).get('status'))
                reason = (data.get('rejection_reason')
                          or data.get('reason')
                          or data.get('whatsapp', {}).get('rejection_reason')
                          or data.get('channels', {}).get('whatsapp', {}).get('rejection_reason'))
                updates = {}
                if status:
                    updates['status'] = status
                if reason:
                    updates['rejection_reason'] = reason
                if updates:
                    rec.write(updates)
            except Exception as e:
                raise ValidationError('Failed to fetch approval status: {}'.format(e))
