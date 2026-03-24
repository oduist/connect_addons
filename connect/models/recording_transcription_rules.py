import logging
import re

from odoo.addons.connect.models.settings import debug

from odoo import models, fields, api

logger = logging.getLogger(__name__)


class TranscriptionRules(models.Model):
    _name = 'connect.transcription_rule'
    _description = 'Transcription rule'
    _order = 'id'

    settings = fields.Many2one('connect.settings', required=True, default=1)
    calling_number = fields.Char(required=True)
    called_number = fields.Char(required=True)

    @api.model
    def check_rules(self, calling_number, called_number):
        for rec in self.search([]):
            try:
                if calling_number and not re.search(rec.calling_number, calling_number):
                    debug(self, 'Transcription rule {} calling number pattern does not match'.format(rec.id))
                    continue
                if called_number and not re.search(rec.called_number, called_number):
                    debug(self, 'Transcription rule {} called number pattern does not match'.format(rec.id))
                    continue
                debug(self, 'Transcription rule {} matched!'.format(rec.id))
                return True
            except Exception as e:
                logger.error('Error checking transcription rule %s: %s', rec.id, e)
