from odoo import models, fields, release, api


class Call(models.Model):
    _inherit = 'connect.call'

    elevenlabs_agent = fields.Many2one('connect.elevenlabs_agent', string='Agent', readonly=True)
    elevenlabs_summary = fields.Html(readonly=True)
    elevenlabs_transcript = fields.Text(compute='_get_elevenlabs_recording_data')
    elevenlabs_conversation_id = fields.Char(readonly=True)
    if release.version_info[0] >= 17.0:
        elevenlabs_recording_widget = fields.Html(compute='_get_elevenlabs_recording_data', sanitize=False, string='Agent Recording')
    else:
        elevenlabs_recording_widget = fields.Char(compute='_get_elevenlabs_recording_data', string='Agent Recording')


    def _get_recording_data(self):
        super(Call, self)._get_recording_data()
        for rec in self:
            # Also show recording icons on Agent calls.
            if rec.elevenlabs_agent:
                rec.recording_icon = '<span class="fa fa-file-sound-o"/>'
                # No need for else condition as it's already set in super().

    def elevenlabs_agent_get_call_data(self):
        self.ensure_one()
        users = self.env['connect.user'].search([])
        partner = self.partner
        if not partner:
            # Test outgoing call:
            if self.direction in ['outgoing', 'internal']:
                partner = self.caller_user.partner_id
        data = {
            'id': self.id,
            'caller_number': self.caller,
            'called_number': self.called,
            'partner_name': partner.name or 'Not registered',
            'existing_partner': 'Yes' if partner else 'No',
            'partner_phone': partner.phone,
            'partner_id': partner.id,
            'partner_tz': partner.tz,
            'greeting': partner.name or 'Dear customer',
            'users_directory': ', '.join(['{} <{}>'.format(k.user.name, k.exten.number) for k in users]),
            'previous_conversation_id': '',
            'previous_topics': '',
        }
        if partner.lang:
            # Workaround for pt-br option for the language.
            if partner.lang == 'pt_BR':
                data['partner_language'] = 'pt-br' # Format that Elevenlabs accepts for this.
            else:
                data['partner_language'] = partner.lang.split('_')[0]

        previous_conversations = self.env['connect.call'].sudo().search([
            ('caller', '=', self.caller), ('called', '=', self.called), ('elevenlabs_conversation_id', '!=', False)])
        if previous_conversations:
            data.update({
                'previous_conversation_id': previous_conversations[0].elevenlabs_conversation_id,
                'previous_topics': previous_conversations[0].elevenlabs_summary,
            })
        # Get published extensions for transfer
        published_extens = self.env['connect.exten'].search([('is_published', '=', True)])
        if published_extens:
            data['available_extensions'] = ', '.join(
                ['<{}> "{}"'.format(k.number, k.dst.name if k.dst else '') for k in published_extens]
            )

        return data

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
            recording = recordings.filtered(lambda x: x.call.id == rec.id and x.elevenlabs_transcript)
            if recording:
                rec.elevenlabs_transcript = recording[0].elevenlabs_transcript
                rec.elevenlabs_recording_widget = recording[0].elevenlabs_recording_widget
            else:
                rec.elevenlabs_transcript = ''
                rec.elevenlabs_recording_widget = ''
