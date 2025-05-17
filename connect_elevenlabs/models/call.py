from odoo import models, fields, release, api


class Call(models.Model):
    _inherit = 'connect.call'

    elevenlabs_agent = fields.Many2one('connect.elevenlabs_agent', string='Agent', readonly=True)
    elevenlabs_summary = fields.Html(readonly=True)
    elevenlabs_transcript = fields.Text(compute='_get_elevenlabs_recording_data')
    if release.version_info[0] >= 17.0:
        elevenlabs_recording_widget = fields.Html(compute='_get_elevenlabs_recording_data', sanitize=False, string='Agent Recording')
    else:
        elevenlabs_recording_widget = fields.Char(compute='_get_elevenlabs_recording_data', string='Agent Recording')


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

    def _get_elevenlabs_recording_data(self):
        # Make one query to get all records.
        recordings = self.env['connect.recording'].search([('call', 'in', [k.id for k in self])])
        for rec in self:
            recording = recordings.filtered(lambda x: x.call.id == rec.id)
            if recording and recording[0].elevenlabs_transcript:
                rec.elevenlabs_transcript = recording[0].elevenlabs_transcript
                rec.elevenlabs_recording_widget = recording[0].elevenlabs_recording_widget
            else:
                rec.elevenlabs_transcript = ''
                rec.elevenlabs_recording_widget = ''
