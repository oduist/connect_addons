# -*- coding: utf-8 -*
# ©️ OdooPBX by Odooist, Odoo Proprietary License v1.0, 2023
import logging
from phonenumbers import phonenumberutil
import phonenumbers
from odoo import api, models, tools, fields, release
from odoo.exceptions import ValidationError, UserError
from odoo.addons.connect.models.settings import debug, MAX_EXTEN_LEN
from odoo.addons.connect.models.res_partner import strip_number

logger = logging.getLogger(__name__)


class Ticket(models.Model):
    _inherit = 'helpdesk.ticket'

    connect_calls_count = fields.Integer(
        compute='_get_connect_calls_count', string='Calls', store=True)
    connect_calls = fields.One2many('connect.call', 'ticket')
    phone_normalized = fields.Char(compute='_get_phone_normalized', index=True, store=True)

    @api.depends('connect_calls')
    def _get_connect_calls_count(self):
        for rec in self:
            rec.connect_calls_count = self.env['connect.call'].search_count([('ticket', '=', rec.id)])

    @api.model_create_multi
    def create(self, vals_list):
        recs = super(Ticket, self).create(vals_list)
        if self.env.context.get('connect_call_id'):
            call = self.env['connect.call'].sudo().browse(self.env.context['connect_call_id'])
            call.ticket = recs[0]
        if recs:
            if release.version_info[0] >= 17:
                self.env.registry.clear_cache()
            else:
                self.clear_caches()
        return recs

    @api.depends('partner_phone')
    def _get_phone_normalized(self):
        for rec in self:
            if rec.partner_phone:
                rec.phone_normalized = '+{}'.format(strip_number(rec.partner_phone))
            else:
                rec.phone_normalized = ''

    def _search_ticket_by_number(self, number):
        open_stages_ids = self.env['helpdesk.stage'].sudo().search([('fold', '=', False)]).mapped('id')
        domain = [
            ('active', '=', True),
            '|',
            ('stage_id', 'in', open_stages_ids),
            ('stage_id', '=', False),
            ('phone_normalized', '=', number)]
        found = self.env['helpdesk.ticket'].sudo().search(domain, order='id desc')
        if len(found) > 1:
            logger.warning('MULTIPLE OPEN TICKETS FOUND BY NUMBER %s, SELECTING THE 1ST', number)
        debug(self, 'Number {} belongs to tickets: {}'.format(
            number, found.mapped('id')
        ))
        return found[:1]

    # TODO: Test caching as we call it many times on call status.
    # @tools.ormcache('number', 'country') psycopg2.InterfaceError: Cursor already closed
    def get_ticket_by_number(self, number, country=None):
        number = strip_number(number)
        if not number or len(number) < MAX_EXTEN_LEN:
            debug(self, 'Ticket by number {}: skip search'.format(number))
            # Return empty set.
            return self.env['helpdesk.ticket']
        # Search by stripped number prefixed with '+'
        ticket = self._search_ticket_by_number('+{}'.format(number))
        if ticket:
            return ticket
            # Search by stripped number
            ticket = self._search_ticket_by_number(number)
            if ticket:
                return ticket
        # Return empty set.
        return self.env['helpdesk.ticket']
