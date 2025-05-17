from odoo import models, fields, api


class Call(models.Model):
    _inherit = 'connect.call'

    elevenlabs_agent = fields.Many2one('connect.elevenlabs_agent', string='Agent', readonly=True)
    elevenlabs_transcription = fields.Text(readonly=True, string='Transcription')
    elevenlabs_summary = fields.Text(readonly=True, string='Summary')

    def elevenlabs_agent_get_call_data(self):
        self.ensure_one()
        users = self.env['connect.user'].search([])
        return {
            'id': self.id,
            'caller_user_name': self.caller_user.name,
            'caller_number': self.caller,
            'called_number': self.called,
            'partner_name': self.partner.name,
            'partner_language': 'ru', #self.partner.lang.split('_')[0] if self.partner.lang else 'en',
            'partner_phone': self.called if self.direction == 'outgoing' else self.caller,
            'partner_id': self.partner.id or self.caller_user.partner_id.id,
            'greeting_name': self.partner.name or self.caller_user.name or 'Dear customer',
            'users_directory': ', '.join(['{} <{}>'.format(k.user.name, k.exten.number) for k in users])
        }

    @api.model
    def elevenlabs_agent_start_call_event(self, params):
        call_id=params['call_id']
        agent_uid=params['agent_uid']
        # aio_odoorpc cannot pass positional args?
        call = self.sudo().browse(int(call_id))
        agent = self.env['connect.elevenlabs_agent'].sudo().search([('agent_uid', '=', agent_uid)])
        # Link call to the Agent.
        call.elevenlabs_agent = agent.id
        return call.elevenlabs_agent_get_call_data()
