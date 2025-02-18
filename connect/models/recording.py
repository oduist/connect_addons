# -*- coding: utf-8 -*-
# ©️ Connect by Odooist, Odoo Proprietary License v1.0, 2024
import json
import logging
import re
import requests
from urllib.parse import urljoin
import uuid
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import format_connect_response, debug

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
                if (calling_number and re.search(rec.calling_number, calling_number)) and (
                        called_number and re.search(rec.called_number, called_number)):
                    debug(self, 'Transcription rule {} matched!'.format(rec.id))
                    return True
                else:
                    debug(self, 'Transcription rule {} does not match.'.format(rec.id))
            except Exception as e:
                logger.error('Error checking transcription rule %s: %s', rec.id, e)


class Recording(models.Model):
    _name = 'connect.recording'
    _description = 'Recording'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'id'
    _order = 'id desc'

    call = fields.Many2one('connect.call', ondelete='set null')
    channel = fields.Many2one('connect.channel', ondelete='set null')
    partner = fields.Many2one('res.partner', ondelete='set null')
    sid = fields.Char('SID', readonly=True, required=True)
    # It's a channel sid actually.
    call_sid = fields.Char(required=True, string='Channel SID', readonly=True)
    caller_user = fields.Many2one('res.users', ondelete='set null')
    called_user = fields.Many2one('res.users', ondelete='set null')
    caller_number = fields.Char()
    called_number = fields.Char()
    media_url = fields.Char()
    price = fields.Char()
    price_unit = fields.Char()
    source = fields.Char()
    duration = fields.Integer()
    duration_human = fields.Char(compute='_get_duration_human')
    start_time = fields.Datetime()
    status = fields.Char()
    if release.version_info[0] >= 17.0:
        recording_widget = fields.Html(compute='_get_recording_widget', string='Recording', sanitize=False)
    else:
        recording_widget = fields.Char(compute='_get_recording_widget', string='Recording')
    ############## TRANSCRIPTION FIELDS ######################################
    transcript = fields.Text()
    transcription_token = fields.Char()
    transcription_error = fields.Char()
    transcription_price = fields.Char()
    summary = fields.Html()

    ############## TRANSCRIPTION METHODS #####################################

    def get_transcript(self, fail_silently=False):
        self.ensure_one()
        openai_key = self.env['connect.settings'].sudo().get_param('openai_api_key')
        if not openai_key:
            if fail_silently:
                logger.warning('OpenAI key is not set! Transcription will not be available.')
                return False
            else:
                raise ValidationError('OpenAI key is not set!')
        self.env['connect.settings'].connect_notify(
            notify_uid=self.env.user.id,
            title="Recording Transcript",
            message='Request sent, please wait for the update!',
        )
        # First check if the call matches the transcription rules.
        if fail_silently and not self.env['connect.transcription_rule'].sudo().check_rules(
                self.call.caller, self.call.called):
            debug(self, 'No transcription rules matched.')
            return False
        if not self.media_url:
            raise ValidationError('Recording is not available yet!')
        url = urljoin(self.env['connect.settings'].sudo().get_param('api_url'),
            'transcription')
        # Create a token and commit it.
        self.sudo().transcription_token = str(uuid.uuid4())
        self.env.cr.commit()
        try:
            account_sid = self.env['connect.settings'].sudo().get_param('account_sid')
            auth_token = self.env['connect.settings'].sudo().get_param('auth_token')
            res = requests.post(url,
                json={
                    'file_name': '{}.wav'.format(self.media_url.split('/')[-1]),
                    'content_url': self.media_url,
                    'auth': [account_sid, auth_token],
                    'summary_prompt': self.env['connect.settings'].get_param('summary_prompt'),
                    'callback_url': urljoin(
                        self.env['connect.settings'].sudo().get_param('web_base_url'),
                        '/connect/transcript/{}'.format(self.id),
                    ),
                    'transcription_token': self.transcription_token,
                    'customer_key': openai_key,
                    'notify_uid': self.env.user.id,
                },
                headers={
                    'x-instance-uid': self.env['connect.settings'].get_param('instance_uid'),
                    'x-api-key': self.env['ir.config_parameter'].sudo().get_param('connect.api_key')
                })
            if not res.ok:
                self.transcription_error = res.text
                if not fail_silently:
                    raise ValidationError(res.text)
                else:
                    logger.error('Error getting result from transcription service: %s', res.text)
        except Exception as e:
            logger.error('Transcription error: %s', e)
            if not fail_silently:
                raise ValidationError('Transcription error: %s' % e)

    def update_transcript(self, data):
        # Update transcription and also erase access token.
        self.ensure_one()
        transcription_price = data.get('transcription_price')
        if transcription_price:
            # Round
            transcription_price = round(transcription_price, 2)
        vals = {
            'transcript': data.get('transcript'),
            'transcription_price': str(transcription_price),
            'summary': data.get('summary'),
            # Reset the token
            'transcription_token': False,
            'transcription_error': data.get('transcription_error')
        }
        self.with_context(tracking_disable=True).write(vals)
        # Update call summary.
        if self.call:
            self.call.summary = data.get('summary')
        # Reload views when transcription has come.
        self.env['connect.settings'].pbx_reload_view('connect.recording')
        # Notify user
        if data.get('notify_uid'):
            self.env['connect.settings'].connect_notify(
                'Transcription updated', notify_uid=data['notify_uid'])

##########  END OF TRANSCRIPTION METHODS #########################################################

    def _get_recording_widget(self):
        proxy_recordings = self.env['connect.settings'].sudo().get_param('proxy_recordings')
        for rec in self:
            if proxy_recordings:
                media_url = '/connect/recording/{}'.format(rec.id)
            else:
                media_url = rec.media_url
            rec.recording_widget = '<audio id="sound_file" preload="auto" ' \
                'controls="controls"> ' \
                '<source src="{}"/>' \
                '</audio>'.format(media_url)

    @api.model
    def prepare_data(self, rec):
        data = {}
        for field in ['sid', 'call_sid', 'media_url', 'price', 'price_unit',
                      'duration', 'source', 'start_time','status']:
            data[field] = getattr(rec, field)
            if field in ['start_time', 'date_created', 'date_updated']:
                # Parse 2024-05-29 21:44:48+00:00
                data[field] = data[field].utcnow()
        channel = self.env['connect.channel'].search([('sid', '=', rec.call_sid)])
        data['call'] = channel.call.id
        data['channel'] = channel.id
        return data

    def sync(self):
        client = self.env['connect.settings'].get_client()
        for rec in self:
            recording = client.recordings(rec.sid).fetch()
            data = self.prepare_data(recording)
            rec.write(data)

    @api.model_create_multi
    def create(self, vals_list):
        transcript_calls = self.env['connect.settings'].sudo().get_param('transcript_calls')
        recs = super(Recording, self.with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True)).create(vals_list)
        # Commit to the database as recordings are created by the Agent.
        if transcript_calls:
            for rec in recs:
                try:
                    rec.get_transcript(fail_silently=True)
                except Exception as e:
                    logger.exception('Transcript error:')
        return recs

    @api.model
    def on_recording_status(self, params):
        self = self.sudo()
        debug(self, 'On recording status: %s' % json.dumps(params, indent=2))
        # Todo: RecordingChannels
        data = {
            'sid': params['RecordingSid'],
            'call_sid': params['CallSid'],
            'duration': params['RecordingDuration'],
            'status': params['RecordingStatus']
        }
        channel = self.env['connect.channel'].search([('sid', '=', params['CallSid'])])
        if channel:
            call = channel.call
            data['channel'] = channel.id
            data['call'] = call.id
            data['partner'] = call.partner.id
            data['caller_user'] = channel.caller_user.id
            data['called_user'] = channel.called_user.id
            data['caller_number'] = call.caller
            data['called_number'] = call.called
        # Fetch recording
        client = self.env['connect.settings'].get_client()
        try:
            recording = client.recordings(data['sid']).fetch()
            data.update(self.prepare_data(recording))
        except Exception as e:
            logger.error(format_connect_response(e))
        self.create(data)
        return True

    @api.depends('duration')
    def _get_duration_human(self):
        for record in self:
            if record.duration is not None:
                # Compute minutes and seconds
                minutes = record.duration // 60
                seconds = record.duration % 60
                # Format human-readable time as MM:SS
                record.duration_human = '{:02}:{:02}'.format(minutes, seconds)
            else:
                record.duration_human = "00:00"
