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
        duration = meta.get('call_duration_secs', 0)

        analysis = data.get('analysis', {})
        status = 'completed' if analysis.get('call_successful') == 'success' else 'failed'

        number = False
        if called:
            number = self.env['connect.number'].sudo().search(
                [('phone_number', '=', called)], limit=1)
        if not number:
            logger.warning('EL inbound: connect.number not found for called=%s', called)

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
