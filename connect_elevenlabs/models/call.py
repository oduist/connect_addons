from odoo import models, fields


class Call(models.Model):
    _inherit = 'connect.call'

    elevenlabs_transcription = fields.Text()
    elevenlabs_summary = fields.Text()
