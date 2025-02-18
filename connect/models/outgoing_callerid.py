# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import debug

logger = logging.getLogger(__name__)


class OutgoingCallerID(models.Model):
    _name = 'connect.outgoing_callerid'
    _description = 'Outgoing CallerId'
    _order = 'number'

    name = fields.Char(compute='_get_name')
    sid = fields.Char(readonly=True)
    friendly_name = fields.Char(required=True)
    number = fields.Char(required=True)
    status = fields.Char(readonly=True)
    validation_code = fields.Char(readonly=True)
    callerid_type = fields.Selection([('outgoing_callerid', 'CallerID'), ('number', 'DID Number')],
                                     required=True, readonly=True, default='outgoing_callerid')
    is_default = fields.Boolean(string='Default')
    callerid_users = fields.One2many(comodel_name='connect.user',
                                     inverse_name='outgoing_callerid', string='callerId Users')

    _sql_constraints = [('number_uniq', 'UNIQUE(number)', 'This number is already used!')]


    def _get_name(self):
        for rec in self:
            rec.name = '{} "{}"'.format(rec.number, rec.friendly_name)

    def sync_outgoing_callerid(self, callerid_type):
        client = self.env['connect.settings'].get_client()
        if callerid_type == 'outgoing_callerid':
            numbers = client.outgoing_caller_ids.list()
        else:
            numbers = client.incoming_phone_numbers.list()
        # First get numbers from Twilio.
        for number in numbers:
            existing_number = self.env['connect.outgoing_callerid'].search([
                ('sid', '=', number.sid)])
            if not existing_number:
                # New number added, create record in Odoo.
                data = {
                    'sid': number.sid,
                    'callerid_type': callerid_type,
                    'number': number.phone_number,
                    'friendly_name': number.friendly_name,
                }
                if callerid_type == 'outgoing_callerid':
                    data['status'] = 'validated'
                self.with_context(skip_validation=True).create(data)
                debug(self, 'CallerID {} ({}) created in Odoo from {}'.format(
                    number.phone_number, number.friendly_name, callerid_type))
            else:
                # CallerID exists, update friendly name to Twilio
                if number.friendly_name != existing_number.friendly_name:
                    debug(self, 'Update CallerID {} friendly name.'.format(existing_number.number))
                    if callerid_type == 'outgoing_callerid':
                        client.outgoing_caller_ids(existing_number.sid).update(
                            friendly_name=existing_number.friendly_name)
                    else:
                        client.incoming_phone_numbers(existing_number.sid).update(
                            friendly_name=existing_number.friendly_name)
        # Now sync numbers from Odoo
        recs_to_remove = self.env['connect.outgoing_callerid'].search(
            [('sid', 'not in', [k.sid for k in numbers]), ('callerid_type', '=', callerid_type)])
        debug(self, 'Removing {} CallerIds: {}'.format(callerid_type, [k.number for k in recs_to_remove]))
        recs_to_remove.unlink()

    @api.model
    def sync(self):
        self.sync_outgoing_callerid('outgoing_callerid')
        self.sync_outgoing_callerid('number')

    @api.model
    def update_status(self, params):
        self = self.sudo()
        number = self.search([('number', '=', params['Called']),
                              ('callerid_type', '=', 'outgoing_callerid')])
        if not number:
            logger.error('Unknown validation request for number %s', params['Called'])
            return False
        if params['VerificationStatus'] == 'success':
            number.write({'status': 'validated', 'sid': params['OutgoingCallerIdSid']})
        else:
            number.status = 'validation failed'
        self.env['connect.settings'].connect_reload_view('connect.outgoing_callerid')
        return True

    def validate(self):
        self.ensure_one()
        if self.sid:
            raise ValidationError('Outgoing callerid is already validated!')
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        status_url = urljoin(api_url, 'twilio/webhook/outgoing_callerid')
        client = self.env['connect.settings'].get_client()
        try:
            validation_request = client.validation_requests.create(
                status_callback=status_url,
                friendly_name=self.friendly_name, phone_number=self.number)
            self.validation_code = validation_request.validation_code
        except Exception as e:
            if 'Phone number is already verified.' in str(e):
                # Remove number and sync
                self.unlink()
                self.sync()
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'connect.outgoing_callerid',
                    'view_mode': 'tree' if release.version_info[0] < 18 else 'list',
                    'name': 'Outgoing CallerIds',
                }
            else:
                logger.error('Validate request error: %s', e)
                raise ValidationError('Validate request error, check Odoo log!')

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('skip_validation'):
            return super().create(vals_list)
        for vals in vals_list:
            vals['callerid_type'] = 'outgoing_callerid'
            vals['status'] = 'not validated'
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('number'):
            raise ValidationError('Number cannot be modified!')
        if 'friendly_name' in vals:
            client = self.env['connect.settings'].get_client()
            for rec in self:
                client.outgoing_caller_ids(rec.sid).update(
                                friendly_name=vals['friendly_name'])
        return super().write(vals)


    def unlink(self):
        sids = {}
        for rec in self:
            if rec.sid:
                sids[rec.sid] = rec.number
        res = super().unlink()
        client = self.env['connect.settings'].get_client()
        for sid in sids.keys():
            try:
                client.outgoing_caller_ids(sid).delete()
            except Exception as e:
                logger.error('Could not delete outgoing callerid number %s', sids[sid])
        return res

    @api.constrains('number')
    def _check_number(self):
        if self.number and not self.number.startswith('+'):
            raise ValidationError('Number must start with +')
        if self.number and not re.search(r'^\+[0-9]+$', self.number):
            raise ValidationError('Number must contain only digits!')

    @api.constrains('is_default')
    def _reset_default(self):
        for rec in self:
            if not self.env.context.get('skip_reset_default'):
                context = {
                    'skip_reset_default': True,
                }
                default = rec.is_default
                # Reset all defaults.
                self.with_context(context).search(
                    []).write({'is_default': False})
                # Set back the default to current.
                rec.with_context(context).is_default = default

    @api.constrains('is_default')
    def _check_default(self):
        for rec in self:
            if rec.is_default:
                if rec.callerid_type == 'outgoing_callerid' and rec.status != 'validated':
                    raise ValidationError('Validate the number first!')
