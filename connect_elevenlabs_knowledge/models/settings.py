import logging

from odoo import models

logger = logging.getLogger(__name__)


class ElevenlabsSettings(models.Model):
    _inherit = 'connect.settings'

    def action_sync_from_elevenlabs(self):
        """Sync knowledge base documents from ElevenLabs"""
        result = self.env['connect.elevenlabs_knowledge'].sync_with_elevenlabs()
        logger.info('Synced knowledge from ElevenLabs: %s', result)
        return True
