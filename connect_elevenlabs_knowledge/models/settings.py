import logging

from odoo import models
from odoo.addons.connect.models.settings import PROTECTED_FIELDS

logger = logging.getLogger(__name__)

PROTECTED_FIELDS.append('display_elevenlabs_api_key')
PROTECTED_FIELDS.append('display_elevenlabs_post_call_webhook_secret')


class ElevenlabsSettings(models.Model):
    _inherit = 'connect.settings'

    def action_sync_from_elevenlabs(self):
        """Sync knowledge base documents from ElevenLabs"""
        result = self.env['connect.elevenlabs_knowledge'].sync_with_elevenlabs()
        logger.info('Synced knowledge from ElevenLabs: %s', result)
        return True
