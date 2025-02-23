# -*- coding: utf-8 -*
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.addons.connect.models.settings import debug


logger = logging.getLogger(__name__)


class CrmCall(models.Model):
    _inherit = 'connect.call'

    lead = fields.Many2one('crm.lead', ondelete='set null', tracking=True)
    source = fields.Many2one('utm.source', ondelete='set null', tracking=True)
    ref = fields.Reference(selection_add=[('crm.lead', 'Lead')])

    # Override ref
    def _get_ref(self):
        for rec in self:
            if rec.lead:
                rec.ref = 'crm.lead,{}'.format(rec.lead.id)
            else:
                super()._get_ref()

    @api.model
    def on_call_status(self, params, skip_twilio_check=False):
        call_id = super().on_call_status(params,skip_twilio_check=skip_twilio_check)
        if not call_id:
            debug(self, 'CRM on_call_status error, no call.')
            return call_id
        call = self.browse(call_id)
        if call.lead:
            return call_id
        # Update call source
        if call.direction == 'incoming':
            call.source = self.env['utm.source'].sudo().search(
                [('phone', '=', call.called)], limit=1)
            # Update reference if not set.
        try:
            lead = None
            # No reference was set, so we have a change to set it to a lead
            if call.direction == 'incoming':
                lead = self.env['crm.lead'].get_lead_by_number(call.caller)
            else:
                lead = self.env['crm.lead'].get_lead_by_number(call.called)
            if lead:
                debug(self, 'Call {} assign <{}> "{}"'.format(call.id, lead.id, lead.name))
                call.lead = lead
            else:
                pass
                # TODO: Autocreate leads
        except Exception:
            logger.exception('Update call lead error:')
        return call_id

    def _auto_create_lead(self, country=None):
        self.ensure_one()
        # Do not consider reference to a partner as a condition to skip
        if self.lead and not self.lead._name == 'res.partner':
            debug(self, '{} reference already set: {}'.format(self.id, self.lead))
            return False
        # Skip if direction is unknown
        if not self.direction:
            debug(self, 'Call direction undefined for : {}'.format(self.id))
            return False
        auto_create_leads_for_in_calls = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_in_calls')
        auto_create_leads_for_out_calls = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_out_calls')
        auto_create_leads_for_in_answered_calls = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_in_answered_calls')
        auto_create_leads_for_in_missed_calls = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_in_missed_calls')
        auto_create_leads_for_in_unknown_callers = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_in_unknown_callers')
        auto_create_leads_for_out_calls = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_out_calls')
        auto_create_leads_for_out_answered_calls = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_out_answered_calls')
        auto_create_leads_for_out_missed_calls = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_for_out_missed_calls')
        default_sales_person = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_sales_person')
        lead_type = self.env[
            'connect.settings'].get_param(
            'auto_create_leads_type')
        # Get call source
        source = self.env['utm.source'].sudo().search(
            [('phone', '=', self.called_number)], limit=1)
        if self.direction == 'in':
            if not auto_create_leads_for_in_calls:
                debug(self, 'Autocreate not enabled for incomig calls')
                return False
            # Incoming answered call
            elif self.status == 'answered' \
                    and auto_create_leads_for_in_answered_calls:
                debug(self, 'Creating a lead for answered incoming call.')
            # Not answered 2nd leg and auto create for missed calls is set.
            elif self.status != 'answered' and \
                    auto_create_leads_for_in_missed_calls and \
                    not self.is_active:
                debug(self, 'Creating a lead for missed incoming call.')
            # Incoming Call from unknown caller.
            elif auto_create_leads_for_in_unknown_callers:
                debug(self, 'Creating a lead for unknown incoming call.')
            else:
                debug(self, 'No incoming rule matched for {}'.format(self.id))
                return False
            # Define a salesperson for the lead
            user_id = self.answered_user.id or self.called_users[:1].id
            if not user_id:
                user_id = self.env['connect.user'].search(
                    [('exten', '=', self.called_number)],
                        limit=1).user.id
            if not user_id:
                user_id = default_sales_person.id
            # Data dict for created lead
            data = {
                'name': self.partner.name or self.calling_number,
                'type': lead_type,
                'user_id': user_id,
                'partner_id': self.partner.id,
                'source_id': source.id,
            }
            # set number only if partner is not set
            if not self.partner:
                data['phone'] = self.calling_number
        elif self.direction == 'out':
            if not auto_create_leads_for_out_calls:
                debug(self, 'Autocreate not enabled for outgoing calls')
                return False
            if self.called_users:
                debug(self, 'Autocreate skip "out" call to local users')
                return False
            # Answered call
            elif self.status == 'answered' \
                    and auto_create_leads_for_out_answered_calls:
                debug(self, 'Creating a lead for answered outgoing call.')
            # Not answered 2nd leg and auto create for missed calls is set.
            elif self.status != 'answered' and \
                    auto_create_leads_for_out_missed_calls and \
                    not self.is_active:
                debug(self, 'Creating a lead for missed outgoing call.')
            else:
                debug(self, 'No outgoing rule matched for {}'.format(self.id))
                return False
            # Data dict for created lead
            data = {
                'name': self.partner.name or self.called_number,
                'type': lead_type,
                'user_id': self.calling_user.id or default_sales_person.id,
                'partner_id': self.partner.id,
                'source_id': source.id,
            }
            # set number only if partner is not set
            if not self.partner:
                data['phone'] = self.called_number
        # Finally create a lead
        debug(self, 'Lead create data: {}'.format(data))
        lead = self.env['crm.lead'].create(data)
        debug(self, 'Set lead {} for call {}'.format(lead.id, self.id))
        self.lead = lead
        return True

    def create_lead_button(self):
        self.ensure_one()
        name_number = self.caller if self.direction == 'incoming' else self.called
        context = {
            'connect_call_id': self.id,
            'default_phone': name_number,
            'default_partner_id': self.partner.id,
        }
        # Check if it's a click on a call with existing partner (linking)
        if not self.lead:
            lead = self.env['crm.lead'].get_lead_by_number(name_number)
            if lead:
                self.sudo().lead = lead
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': self.lead.id,
            'name': self.lead.name if self.lead else 'New Lead',
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
            'context': context,
        }

    def unlink_crm_lead(self):
        self.ensure_one()
        self.lead = False

    def get_widget_fields(self):
        fields = super().get_widget_fields()
        fields.append('lead')
        return fields
