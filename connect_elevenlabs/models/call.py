from odoo import models, fields, release


class Call(models.Model):
    _inherit = 'connect.call'

    elevenlabs_transcription = fields.Text(compute='_get_elevenlabs_recording_data')
    elevenlabs_summary = fields.Html()
    if release.version_info[0] >= 17.0:
        elevenlabs_recording_widget = fields.Html(compute='_get_elevenlabs_recording_data', sanitize=False)
    else:
        elevenlabs_recording_widget = fields.Char(compute='_get_elevenlabs_recording_data')

    def _get_elevenlabs_recording_data(self):
        # Make one query to get all records.
        recordings = self.env['connect.recording'].search([('call', 'in', [k.id for k in self])])
        for rec in self:
            recording = recordings.filtered(lambda x: x.call.id == rec.id)
            if recording and recording[0].elevenlabs_transcription:
                rec.elevenlabs_transcription = recording[0].elevenlabs_transcription
                rec.elevenlabs_recording_widget = recording[0].elevenlabs_recording_widget
            else:
                rec.elevenlabs_transcription = ''
                rec.elevenlabs_recording_widget = ''
