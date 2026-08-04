# -*- coding: utf-8 -*

import logging
from odoo import models, fields
from odoo.exceptions import ValidationError
from odoo.addons.connect.models.settings import debug

logger = logging.getLogger(__name__)


class HelpdeskCall(models.Model):
    _inherit = 'connect.call'

    ticket = fields.Many2one('helpdesk.ticket', ondelete='set null', tracking=True)

    def _after_call_projection(self, finalized, changed_fields):
        res = super()._after_call_projection(finalized, changed_fields)
        self.ensure_one()
        if not self.env["oduist.license"].check_license('connect_helpdesk'):
            return res
        call = self
        if call.ticket:
            return res
        try:
            ticket = None
            if call.direction == 'incoming':
                ticket = self.env['helpdesk.ticket'].get_ticket_by_number(call.caller)
            else:
                ticket = self.env['helpdesk.ticket'].get_ticket_by_number(call.called)
            if ticket:
                debug(self, 'Call {} assign <{}> "{}"'.format(call.id, ticket.id, ticket.name))
                call.ticket = ticket
            else:
                pass
                # TODO: Auto create ticket
        except Exception:
            logger.exception('Update call ticket error:')
        return res

    def create_ticket_button(self):
        self.ensure_one()
        if not self.env["oduist.license"].check_license('connect_helpdesk'):
            raise ValidationError('Connect Helpdesk license is not activated!')
        name_number = self.caller if self.direction == 'incoming' else self.called
        context = {
            'connect_call_id': self.id,
            'default_partner_phone': name_number,
            'default_partner_id': self.partner.id,
        }
        # Check if it's a click on a call with existing partner (linking)
        if not self.ticket:
            ticket = self.env['helpdesk.ticket'].get_ticket_by_number(name_number)
            if ticket:
                self.sudo().ticket = ticket
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket',
            'res_id': self.ticket.id,
            'name': self.ticket.name if self.ticket else 'New ticket',
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
            'context': context,
        }

    def unlink_ticket(self):
        self.ensure_one()
        self.ticket = False

    def get_widget_fields(self):
        fields = super().get_widget_fields()
        fields.append('ticket')
        return fields
