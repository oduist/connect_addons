# -*- coding: utf-8 -*-

import json
import logging
import os
import threading
import requests
from tempfile import NamedTemporaryFile

import openai

from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from .settings import debug

logger = logging.getLogger(__name__)


class Voicemail(models.Model):
    _name = 'connect.voicemail'
    _description = 'Voicemail'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    call = fields.Many2one('connect.call', ondelete='set null')
    channel = fields.Many2one('connect.channel', ondelete='set null')
    partner = fields.Many2one('res.partner', ondelete='set null')
    sid = fields.Char('SID', readonly=True)
    call_sid = fields.Char(string='Channel SID', readonly=True)
    caller_user = fields.Many2one(related='call.caller_user', store=True, readonly=False)
    caller_number = fields.Char(readonly=True)
    called_number = fields.Char(readonly=True)
    # The mailbox the voicemail was left in.
    user = fields.Many2one('connect.user', ondelete='set null', string='User Mailbox')
    callflow = fields.Many2one('connect.callflow', ondelete='set null', string='Callflow Mailbox')
    media_url = fields.Char(readonly=True)
    duration = fields.Integer(readonly=True)
    duration_human = fields.Char(compute='_get_duration_human')
    status = fields.Char(readonly=True)
    is_new = fields.Boolean(string='New', default=True)
    if release.version_info[0] >= 17.0:
        voicemail_widget = fields.Html(compute='_get_voicemail_widget', string='VoiceMail', sanitize=False)
    else:
        voicemail_widget = fields.Char(compute='_get_voicemail_widget', string='VoiceMail')
    transcript = fields.Text()
    transcription_error = fields.Char()
    pbx_group_user_ids = fields.Many2many(
        'res.users', 'connect_voicemail_pbx_group_users_rel',
        string='PBX Group Users',
        compute='_compute_pbx_group_user_ids', store=True)

    @api.depends('partner', 'caller_number')
    def _compute_display_name(self):
        for rec in self:
            caller = rec.partner.name or rec.caller_number
            if caller:
                rec.display_name = 'Voicemail from {}'.format(caller)
            else:
                rec.display_name = 'Voicemail {}'.format(rec.id or '')

    @api.depends('caller_user', 'user')
    def _compute_pbx_group_user_ids(self):
        for rec in self:
            users = self.env['res.users']
            for u in (rec.caller_user, rec.user.user):
                if u and u.connect_user:
                    for group in u.connect_user.pbx_group_ids:
                        users |= group.user_ids
            rec.pbx_group_user_ids = users

    def _get_voicemail_widget(self):
        proxy_recordings = self.env['connect.settings'].sudo().get_param('proxy_recordings')
        for rec in self:
            if rec.media_url:
                if proxy_recordings:
                    media_url = '/connect/voicemail/{}'.format(rec.id)
                else:
                    media_url = rec.media_url
                rec.voicemail_widget = '<audio id="sound_file" preload="auto" ' \
                    'controls="controls"> ' \
                    '<source src="{}"/>' \
                    '</audio>'.format(media_url)
            else:
                rec.voicemail_widget = ''

    @api.depends('duration')
    def _get_duration_human(self):
        for record in self:
            if record.duration is not None:
                minutes = record.duration // 60
                seconds = record.duration % 60
                record.duration_human = '{:02}:{:02}'.format(minutes, seconds)
            else:
                record.duration_human = "00:00"

    def mark_listened(self):
        # Any user who can see the voicemail may mark it as listened, including
        # read-only followers: check read access, then write via sudo so the
        # read-only record rules do not block the flag.
        self.check_access('read')
        self.sudo().write({'is_new': False})

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        # Users tagged in the chatter must be able to open the voicemail: the
        # follower record rule grants them read access, so subscribe mentioned
        # internal users (sudo as the poster cannot manage followers).
        partner_ids = kwargs.get('partner_ids')
        if partner_ids:
            partners = self.env['res.partner'].sudo().browse(partner_ids)
            internal = partners.filtered(lambda p: any(not u.share for u in p.user_ids))
            if internal:
                self.sudo().message_subscribe(partner_ids=internal.ids)
        return message

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('skip_transcription'):
            return super().create(vals_list)
        recs = super(Voicemail, self.with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True)).create(vals_list)
        openai_key = self.env['connect.settings'].sudo().get_param('openai_api_key')
        if not openai_key:
            logger.warning('OpenAI key is not set! Transcription will not be available.')
            return recs
        # Commit to the database so that a transcription error will not break the voicemail.
        if not getattr(threading.current_thread(), 'testing', False):
            self.env.cr.commit()
        for rec in recs:
            try:
                rec.transcribe_voicemail(openai_key)
            except Exception as e:
                logger.exception('Voicemail transcript error: %s', e)
        return recs

    @api.model
    def on_vm_recording_status(self, params):
        self = self.sudo()
        debug(self, 'On VM recording status: %s' % json.dumps(params, indent=2))
        data = {
            'sid': params.get('RecordingSid'),
            'call_sid': params.get('CallSid'),
            'media_url': params.get('RecordingUrl'),
            'duration': int(params.get('RecordingDuration', 0) or 0),
            'status': params.get('RecordingStatus'),
        }
        channel = self.env['connect.channel'].search([('sid', '=', params.get('CallSid'))], limit=1)
        if channel and channel.call:
            call = channel.call
            data.update({
                'channel': channel.id,
                'call': call.id,
                'partner': call.partner.id,
                'caller_number': call.caller,
                'called_number': call.called,
            })
        # Mailbox owner is passed by the TwiML render via the callback URL.
        try:
            if params.get('vm_user_id'):
                user = self.env['connect.user'].browse(int(params['vm_user_id'])).exists()
                if user:
                    data['user'] = user.id
            elif params.get('vm_callflow_id'):
                callflow = self.env['connect.callflow'].browse(int(params['vm_callflow_id'])).exists()
                if callflow:
                    data['callflow'] = callflow.id
        except (TypeError, ValueError):
            logger.warning('Bad voicemail mailbox reference: %s / %s',
                params.get('vm_user_id'), params.get('vm_callflow_id'))
        # Fallback for calls started before the mailbox reference was added to the URL.
        if not data.get('user') and not data.get('callflow'):
            if channel and channel.call and len(channel.call.called_pbx_users) == 1:
                data['user'] = channel.call.called_pbx_users.id
        voicemail = self.create(data)
        try:
            voicemail._notify_mailbox_users()
        except Exception:
            logger.exception('Voicemail notification error:')
        return True

    def _notify_mailbox_users(self):
        # Let mailbox owners know a voicemail arrived: the user mailbox owner or
        # the ring group users of the callflow mailbox. Recipients are tagged so
        # the message lands in their inbox and message_post makes them followers
        # with read access to the voicemail.
        self.ensure_one()
        if self.user:
            users = self.user.user
        elif self.callflow:
            users = self.callflow.ring_users.mapped('user')
        else:
            return
        partners = users.partner_id
        if not partners:
            return
        if self.partner:
            caller = '{} ({})'.format(self.partner.name, self.caller_number)
        else:
            caller = self.caller_number or 'an unknown number'
        self.message_post(
            body='New voicemail from {}, duration {}.'.format(caller, self.duration_human),
            partner_ids=partners.ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment')

    def get_transcript(self):
        self.ensure_one()
        openai_key = self.env['connect.settings'].sudo().get_param('openai_api_key')
        if not openai_key:
            raise ValidationError('OpenAI key is not set!')
        if not self.media_url:
            raise ValidationError('Voicemail is not available yet!')
        self.transcribe_voicemail(openai_key)

    def transcribe_voicemail(self, openai_api_key):
        self.ensure_one()
        result = {}
        temp_file_path = None
        try:
            client = openai.OpenAI(api_key=openai_api_key)
            response = requests.get(self.media_url, stream=True)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                temp_file_path = temp_file.name
            with open(temp_file_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file,
                    response_format='verbose_json', timestamp_granularities=["segment"])
            segments = ''
            for s in transcript.segments:
                segments += '{}\n'.format(s.text)
            result['transcript'] = segments.strip()
            result['transcription_error'] = False
        except Exception as e:
            logger.exception('Voicemail transcribe error:')
            result['transcription_error'] = str(e)
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            self.write(result)
