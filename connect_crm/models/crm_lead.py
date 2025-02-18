# -*- coding: utf-8 -*
# ©️ OdooPBX by Odooist, Odoo Proprietary License v1.0, 2023
import logging
from phonenumbers import phonenumberutil
import phonenumbers
from odoo import api, models, tools, fields, release
from odoo.exceptions import ValidationError, UserError
from odoo.addons.connect.models.settings import debug, MAX_EXTEN_LEN
from odoo.addons.connect.models.res_partner import strip_number
from odoo.addons.connect.models.res_partner import format_number

logger = logging.getLogger(__name__)


class Lead(models.Model):
    _inherit = 'crm.lead'

    connect_calls = fields.One2many('connect.call', 'lead')
    connect_calls_count = fields.Integer(
        compute='_get_connect_calls_count', string='Calls', store=True)
    phone_normalized = fields.Char(compute='_get_phone_normalized',
                                   index=True, store=True)
    mobile_normalized = fields.Char(compute='_get_phone_normalized',
                                    index=True, store=True)

    def write(self, values):
        res = super(Lead, self).write(values)
        if res:
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return res

    def unlink(self):
        res = super(Lead, self).unlink()
        if res:
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('connect_call_id'):
            call = self.env['connect.call'].sudo().browse(
                self.env.context['connect_call_id'])
            for vals in vals_list:
                # Get call source
                source = self.env['utm.source'].sudo().search(
                    [('phone', '=', call.called)], limit=1)
                if source:
                    vals['source_id'] = source.id
            recs = super(Lead, self).create(vals_list)
            call.lead = recs[0]
        else:
            recs = super(Lead, self).create(vals_list)
        if recs:
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return recs

    @api.depends('phone', 'mobile', 'country_id', 'partner_id', 'partner_id.phone', 'partner_id.mobile')
    def _get_phone_normalized(self):
        for rec in self:
            if release.version_info[0] >= 14:
                # Odoo > 14.0
                if rec.phone:
                    rec.phone_normalized = self.env['res.partner']._normalize_phone(rec.phone)
                if rec.mobile:
                    rec.mobile_normalized = self.env['res.partner']._normalize_phone(rec.mobile)
            else:
                # Old Odoo versions
                if rec.partner_id:
                    # We have partner set, take phones from him.
                    if rec.partner_address_phone:
                        rec.phone_normalized = self.env['res.partner']._normalize_phone(
                            rec.partner_address_phone)
                    if rec.mobile:
                        rec.mobile_normalized = self.env['res.partner']._normalize_phone(rec.mobile)
                else:
                    # No partner set takes phones from lead.
                    if rec.phone:
                        rec.phone_normalized = self.env['res.partner']._normalize_phone(rec.phone)
                    if rec.mobile:
                        rec.mobile_normalized = self.env['res.partner']._normalize_phone(rec.mobile)

    @api.depends('connect_calls')
    def _get_connect_calls_count(self):
        for rec in self:
            rec.connect_calls_count = self.env[
                'connect.call'].search_count([('lead', '=', rec.id)])

    def _search_lead_by_number(self, number):
        # Odoo <= 12 does not have 'is_won' field
        try:
            open_stages_ids = [k.id for k in self.env['crm.stage'].sudo().search(
                [('is_won', '=', False)])]
        except:
            open_stages_ids = [k.id for k in self.env['crm.stage'].sudo().search([])]
        domain = [
            ('active', '=', True),
            '|',
            ('stage_id', 'in', open_stages_ids),
            ('stage_id', '=', False),
            '|',
            ('phone_normalized', '=', number),
            ('mobile_normalized', '=', number)]
        found = self.env['crm.lead'].sudo().search(domain, order='id desc')
        if len(found) > 1:
            logger.warning('[ASTCALLS] MULTIPLE LEADS FOUND BY NUMBER %s', number)
        debug(self, 'Number {} belongs to leads: {}'.format(
            number, found.mapped('id')
        ))
        return found[:1]

    # TODO: Test caching as we call it many times on call status.
    # @tools.ormcache('number', 'country') psycopg2.InterfaceError: Cursor already closed
    def get_lead_by_number(self, number, country=None):
        number = strip_number(number)
        if (not number or 'unknown' in number or
            number == 's' or len(number) < MAX_EXTEN_LEN
        ):
            debug(self, '{} skip search'.format(number))
            # Return empty set.
            return self.env['crm.lead']
        lead = None
        # Search by stripped number prefixed with '+'
        number_plus = '+' + number
        lead = self._search_lead_by_number(number_plus)
        if lead:
            return lead
        # Search by stripped number
        lead = self._search_lead_by_number(number)
        if lead:
            return lead
        # Search by number in e164 format
        e164_number = format_number(
            self, number, country=country, format_type='e164')
        if e164_number not in [number, number_plus]:
            lead = self._search_lead_by_number(e164_number)
        if lead:
            return lead
        # Return empty set.
        return self.env['crm.lead']

