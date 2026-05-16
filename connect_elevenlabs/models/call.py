import logging

from odoo import models, fields, release, api

logger = logging.getLogger(__name__)


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
            # Also show recording icons on Agent calls when recording exists.
            if rec.elevenlabs_agent and rec.recording:
                rec.recording_icon = '<span class="fa fa-file-sound-o"/>'

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
                ['<{}> "{}"'.format(k.number, k.dst.display_name if k.dst else '') for k in published_extens]
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

    @api.model
    def create_from_elevenlabs_inbound(self, data):
        conversation_id = data.get('conversation_id', '')
        if conversation_id:
            existing = self.sudo().search(
                [('elevenlabs_conversation_id', '=', conversation_id)], limit=1)
            if existing:
                logger.info('EL inbound: call already exists for conversation_id=%s, skipping', conversation_id)
                return existing

        meta = data.get('metadata', {})
        phone_call = meta.get('phone_call', {})
        caller = phone_call.get('external_number', '')
        called = phone_call.get('agent_number', '')
        call_sid = phone_call.get('call_sid', '')
        phone_number_id = phone_call.get('phone_number_id', '')
        duration = meta.get('call_duration_secs', 0)

        analysis = data.get('analysis', {})
        status = 'completed' if analysis.get('call_successful') == 'success' else 'failed'

        number = False
        if phone_number_id:
            number = self.env['connect.number'].sudo().search(
                [('el_phone_number_uid', '=', phone_number_id)], limit=1)
        if not number and called:
            number = self.env['connect.number'].sudo().search(
                [('phone_number', '=', called)], limit=1)
        if not number:
            logger.warning('EL inbound: connect.number not found for phone_number_id=%s / called=%s',
                           phone_number_id, called)

        partner = self.env['res.partner'].sudo().get_partner_by_number(caller) if caller else False
        agent_id = data.get('agent_id', '')
        agent = self.env['connect.elevenlabs_agent'].sudo().search(
            [('agent_uid', '=', agent_id)], limit=1) if agent_id else False

        call = self.sudo().create({
            'caller': caller,
            'called': called,
            'direction': 'inbound',
            'status': status,
            'duration': duration,
            'call_sid': call_sid,
            'elevenlabs_conversation_id': conversation_id,
            'elevenlabs_summary': analysis.get('transcript_summary', ''),
            'partner': partner.id if partner else False,
            'elevenlabs_agent': agent.id if agent else False,
        })
        logger.info('EL inbound: created connect.call id=%s for conversation_id=%s caller=%s',
                    call.id, conversation_id, caller)
        return call

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
