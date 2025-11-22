# -*- coding: utf-8 -*-

import logging
import io
from odoo import models, api
from odoo.tools import human_size

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        """Override message_post to add voice mail attachments for outgoing messages."""
        # Check if auto voice mail is enabled
        settings_model = self.env['connect.settings']
        auto_voice_mail_enabled = settings_model.get_param('elevenlabs_auto_voice_mail')
        elevenlabs_enabled = settings_model.get_param('elevenlabs_enabled')
        
        if not auto_voice_mail_enabled or not elevenlabs_enabled:
            return super().message_post(**kwargs)

        # Check if this is an outgoing message (has author_id and it's not a system notification)
        author_id = kwargs.get('author_id')
        if not author_id or author_id == self.env.ref('base.partner_root').id:
            return super().message_post(**kwargs)

        # Check if body exists and has content
        body = kwargs.get('body', '')
        if not body or body.strip() == '':
            return super().message_post(**kwargs)

        # Check if voice is configured
        voice_id = settings_model.get_param('elevenlabs_voice')
        if not voice_id:
            return super().message_post(**kwargs)

        try:
            # Get voice record
            voice_record = self.env['connect.elevenlabs_voice'].browse(voice_id)
            if not voice_record.exists():
                return super().message_post(**kwargs)
            
            # Generate audio from text
            audio_content = self._generate_speech(body, voice_record)
            
            if audio_content:
                # Create attachment
                import uuid
                attachment = self.env['ir.attachment'].create({
                    'name': f'voice_message_{uuid.uuid4().hex[:8]}.mp3',
                    'datas': audio_content,
                    'res_model': self._name,
                    'res_id': self.id,
                    'type': 'binary',
                    'mimetype': 'audio/mpeg',
                })
                
                # Add attachment to message post kwargs
                attachments = kwargs.get('attachment_ids', [])
                attachments.append((4, attachment.id))
                kwargs['attachment_ids'] = attachments
                
        except Exception as e:
            _logger.error("Failed to generate voice mail: %s", e)
            # Continue with normal message posting if voice generation fails
            
        return super().message_post(**kwargs)

    def _generate_speech(self, text, voice):
        """Generate speech from text using ElevenLabs API."""
        try:
            # Get ElevenLabs client
            settings = self.env['connect.settings'].sudo()
            client = settings.get_elevenlabs_client()
            
            # Generate speech
            audio = client.generate(
                text=text,
                voice=voice.voice_id,
                model="eleven_multilingual_v2"
            )
            
            # Convert to base64
            import base64
            data = b''.join(audio)
            audio_b64 = base64.b64encode(data).decode('utf-8')
            
            return audio_b64
            
        except Exception as e:
            _logger.error("Error generating speech: %s", e)
            return None