# -*- coding: utf-8 -*-
from odoo import fields, models, release


class Recording(models.Model):
    _inherit = 'connect.recording'

    elevenlabs_transcript = fields.Text(readonly=True)
    elevenlabs_summary = fields.Text(readonly=True)
    elevenlabs_media_file = fields.Binary()
    if release.version_info[0] >= 17.0:
        elevenlabs_recording_widget = fields.Html(compute='_elevenlabs_recording_widget',
                                                  sanitize=False)
    else:
        elevenlabs_recording_widget = fields.Char(compute='_elevenlabs_recording_widget')

    def _elevenlabs_recording_widget(self):
        for rec in self:
            rec.elevenlabs_recording_widget = '<audio id="sound_file" preload="auto" ' \
                'controls="controls"> ' \
                '<source src="/web/content?model=connect.recording&' \
                'id={recording_id}&filename={filename}&field={source}&' \
                'filename_field=recording_filename&download=True" />' \
                '</audio>'.format(
                    recording_id=rec.id,
                    filename='elevenlabs_recording.mp3',
                    source='elevenlabs_media_file')

    def _get_list_view_summary(self):
        for rec in self:
            if rec.elevenlabs_summary:
                rec.list_view_summary = rec.elevenlabs_summary
            else:
                rec.list_view_summary = rec.summary
