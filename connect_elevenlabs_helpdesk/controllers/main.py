# -*- coding: utf-8 -*

import json
import logging

from werkzeug.exceptions import Unauthorized

from odoo import http, release
from odoo.addons.connect_elevenlabs.controllers.main import ConnectElevenlabsController

logger = logging.getLogger(__name__)
route_type = "json" if release.version_info[0] < 19.0 else 'jsonrpc'


class ConnectElevenlabsHelpdeskController(ConnectElevenlabsController):

    @http.route('/connect_elevenlabs_helpdesk/create_ticket', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def helpdesk_create_ticket(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent create_ticket data: %s', data)
        call_id = int(data.get('call_id'))
        call = http.request.env['connect.call'].sudo().browse(call_id)
        partner_id = data.get('partner_id')
        if partner_id:
            partner = http.request.env['res.partner'].sudo().browse(int(partner_id))
        else:
            partner = call.partner
        team_id = False
        if data.get('team_name'):
            team = http.request.env['helpdesk.team'].sudo().search(
                [('name', 'ilike', data['team_name'])], limit=1)
            if team:
                team_id = team.id
        ticket_vals = {
            'name': data.get('subject', 'Ticket from phone call'),
            'description': data.get('description', ''),
            'partner_id': partner.id if partner else False,
            'partner_email': partner.email if partner else data.get('email'),
            'partner_phone': partner.phone if partner else data.get('phone'),
        }
        if team_id:
            ticket_vals['team_id'] = team_id
        ticket = http.request.env['helpdesk.ticket'].sudo().with_context(
            connect_call_id=call_id).create(ticket_vals)
        logger.info('Helpdesk ticket %s (%s) created', ticket.name, ticket.id)
        call.ticket = ticket.id
        return {
            'ticket_id': ticket.id,
            'ticket_number': ticket.id,
            'ticket_name': ticket.name,
            'message': 'Ticket created successfully'
        }

    @http.route('/connect_elevenlabs_helpdesk/search_tickets', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def helpdesk_search_tickets(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent search_tickets data: %s', data)
        partner_id = data.get('partner_id')
        if not partner_id:
            return {'error': 'Partner ID is required to search tickets'}
        domain = [('partner_id', '=', int(partner_id))]
        if data.get('only_open'):
            open_stages = http.request.env['helpdesk.stage'].sudo().search([('fold', '=', False)])
            domain.append(('stage_id', 'in', open_stages.ids))
        tickets = http.request.env['helpdesk.ticket'].sudo().search(domain, order='id desc', limit=10)
        if not tickets:
            return {'message': 'No tickets found for this partner', 'tickets': []}
        result = []
        for ticket in tickets:
            result.append({
                'ticket_id': ticket.id,
                'ticket_name': ticket.name,
                'stage': ticket.stage_id.name if ticket.stage_id else 'New',
                'create_date': str(ticket.create_date),
                'description': ticket.description or '',
            })
        logger.info('Found %s tickets for partner %s', len(result), partner_id)
        return {'tickets': result}

    @http.route('/connect_elevenlabs_helpdesk/fetch_ticket', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def helpdesk_fetch_ticket(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent fetch_ticket data: %s', data)
        ticket_id = data.get('ticket_id')
        if not ticket_id:
            return {'error': 'Ticket ID is required'}
        ticket = http.request.env['helpdesk.ticket'].sudo().browse(int(ticket_id))
        if not ticket.exists():
            return {'error': 'Ticket not found'}
        result = {
            'ticket_id': ticket.id,
            'ticket_name': ticket.name,
            'description': ticket.description or '',
            'stage': ticket.stage_id.name if ticket.stage_id else 'New',
            'partner_name': ticket.partner_id.name if ticket.partner_id else '',
            'partner_email': ticket.partner_email or '',
            'partner_phone': ticket.partner_phone or '',
            'team': ticket.team_id.name if ticket.team_id else '',
            'assigned_user': ticket.user_id.name if ticket.user_id else 'Unassigned',
            'create_date': str(ticket.create_date),
            'priority': ticket.priority or '0',
        }
        logger.info('Fetched ticket %s: %s', ticket_id, result)
        return result

    @http.route('/connect_elevenlabs_helpdesk/update_ticket', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def helpdesk_update_ticket(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent update_ticket data: %s', data)
        ticket_id = data.get('ticket_id')
        if not ticket_id:
            return {'error': 'Ticket ID is required'}
        ticket = http.request.env['helpdesk.ticket'].sudo().browse(int(ticket_id))
        if not ticket.exists():
            return {'error': 'Ticket not found'}
        update_vals = {}
        if data.get('subject'):
            update_vals['name'] = data['subject']
        if data.get('description'):
            update_vals['description'] = data['description']
        if data.get('priority'):
            update_vals['priority'] = data['priority']
        if data.get('stage_name'):
            stage = http.request.env['helpdesk.stage'].sudo().search(
                [('name', 'ilike', data['stage_name'])], limit=1)
            if stage:
                update_vals['stage_id'] = stage.id
        if update_vals:
            ticket.write(update_vals)
            logger.info('Ticket %s updated with: %s', ticket_id, update_vals)
            return {'message': 'Ticket updated successfully', 'ticket_id': ticket.id}
        return {'message': 'No updates provided', 'ticket_id': ticket.id}

    @http.route('/connect_elevenlabs_helpdesk/ticket_activity', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def helpdesk_ticket_activity(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent ticket_activity data: %s', data)
        ticket_id = data.get('ticket_id')
        if not ticket_id:
            return {'error': 'Ticket ID is required'}
        ticket = http.request.env['helpdesk.ticket'].sudo().browse(int(ticket_id))
        if not ticket.exists():
            return {'error': 'Ticket not found'}
        note = data.get('note', '')
        if not note:
            return {'error': 'Note content is required'}
        ticket.message_post(body=note, message_type='comment')
        logger.info('Added note to ticket %s: %s', ticket_id, note[:100])
        return {'message': 'Note added to ticket successfully', 'ticket_id': ticket.id}
