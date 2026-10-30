# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

logger = logging.getLogger(__name__)


class TranscriptionQueue(models.AbstractModel):
    """Audio waiting for speech-to-text.

    Webhooks and the Transcribe button only mark a record pending. The
    "Transcribe queued audio" cron (connect.settings._cron_transcribe_queue)
    does the slow part -- download, speech-to-text, summary -- so a Twilio
    webhook never waits on a transcription server, nor holds the call's
    advisory locks while it runs.
    """
    _name = 'connect.transcription.queue'
    _description = 'Transcription Queue'

    transcription_pending = fields.Boolean(readonly=True, index=True, copy=False)
    # Who pressed Transcribe, to notify when the cron is done; empty when the
    # transcription was queued automatically.
    transcription_requested_by = fields.Many2one(
        'res.users', readonly=True, copy=False, ondelete='set null')

    def _queue_transcription(self, requested_by=False):
        if not self:
            return
        self.write({
            'transcription_pending': True,
            'transcription_requested_by': requested_by and requested_by.id,
        })
        cron = self.env.ref('connect.transcribe_queue', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        else:
            logger.warning('The Transcribe queued audio cron is missing; %s %s stays queued.',
                           self._name, self.ids)

    def _transcription_queued_action(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Transcription',
                'message': 'Queued. You will be notified when the transcript is ready.',
                'type': 'info',
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _transcribe_queued(self):
        """Transcribe this record now. Each queued model implements it."""
        raise NotImplementedError()

    def _run_queued_transcription(self):
        self.ensure_one()
        requested_by = self.transcription_requested_by
        try:
            with self.env.cr.savepoint():
                self._transcribe_queued()
        except Exception as e:
            logger.exception('Queued transcription error: %s', e)
            self.transcription_error = str(e)
        self.write({'transcription_pending': False, 'transcription_requested_by': False})
        if requested_by:
            name = '{} {}'.format(self._description, self.id)
            if self.transcription_error:
                self.env['connect.settings'].connect_notify(
                    '{}: {}'.format(name, self.transcription_error), title='Transcription failed',
                    notify_uid=requested_by.id, warning=True)
            else:
                self.env['connect.settings'].connect_notify(
                    '{}: the transcript is ready.'.format(name), title='Transcription',
                    notify_uid=requested_by.id)
