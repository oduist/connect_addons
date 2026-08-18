# -*- coding: utf-8 -*-
"""
ODUIST PROPRIETARY LICENSE
Copyright (c) 2025 Oduist

This file contains license validation logic.
Modification is prohibited under Oduist Proprietary License.
See LICENSE and COPYRIGHT files for full terms.
"""

import json
import logging
import os
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin
from markupsafe import Markup
import uuid
from datetime import timedelta

import openai
import requests

from odoo import fields, models, api, release, SUPERUSER_ID, tools, _
from odoo.exceptions import ValidationError, AccessError
from twilio.twiml.voice_response import VoiceResponse, Say, Dial, Conference, Client, Number, Sip
from .settings import debug, MAX_EXTEN_LEN
from .res_partner import strip_number

logger = logging.getLogger(__name__)

CALL_END_STATUSES = ['completed', 'busy', 'failed', 'no-answer', 'canceled']

IGNORE_ERROR_CODES = ['32009']

# Fixed namespace ("class id") for per-call PostgreSQL advisory locks used to
# serialize concurrent Twilio status webhooks targeting the same connect.call.
# Must be a stable constant shared across all worker processes (NOT Python's
# per-process-salted hash()). 0x636E6374 == b'cnct', fits in a signed int4.
CALL_LOCK_CLASS = 0x636E6374


class Call(models.Model):
    _name = 'connect.call'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Call'
    _order = 'id desc'

    name = fields.Char(compute='_get_name')
    channels = fields.One2many('connect.channel', 'call', readonly=True)
    recording = fields.Many2one('connect.recording', compute='_get_recording_data')
    recording_ids = fields.Many2many('connect.recording', string='Recordings',
        compute='_get_recording_data',
        help='Every recording of this conversation. Parking splits a call into '
             'one recording per segment, and they are all stored on the call '
             'the <Dial> ran on, so a retrieval leg lists the recordings of '
             'the call it was retrieved from.')
    # The web client cannot call len() in a view modifier, so the segment list
    # keys its visibility off this count instead of len(recording_ids).
    recording_count = fields.Integer(compute='_get_recording_data',
        string='Recordings Count')
    transcript = fields.Text(compute='_get_recording_data')
    if release.version_info[0] >= 17.0:
        recording_widget = fields.Html(compute='_get_recording_data', sanitize=False)
    else:
        recording_widget = fields.Char(compute='_get_recording_data')
    recording_icon = fields.Html(compute='_get_recording_data', string='R')
    has_activity = fields.Boolean(string='A', compute='_compute_has_activity', store=True)
    disable_recording = fields.Boolean(default=False,
        help='When set, no recording is stored for this call when it ends.')
    summary = fields.Html()
    called = fields.Char(readonly=True, index=True)
    caller = fields.Char(readonly=True, index=True)
    parent_call = fields.Many2one('connect.call', ondelete='cascade', readonly=True)
    partner = fields.Many2one('res.partner', ondelete='set null')
    partner_img = fields.Binary(related='partner.image_1920', string='Partner Image')
    direction = fields.Char(index=True, readonly=True)
    call_type = fields.Selection([
        ('phone', 'Phone'),
        ('whatsapp', 'WhatsApp')
    ], default='phone', index=True)
    status = fields.Char(readonly=True, index=True)
    duration = fields.Integer(string='Seconds', readonly=True, index=True)
    duration_minutes = fields.Float(string='Minutes', compute='_get_duration_human', store=True)
    duration_human = fields.Char(compute='_get_duration_human', string='Duration', store=True)
    # PBX users are Connect SIP or Client users.
    caller_pbx_user = fields.Many2one('connect.user', ondelete='set null', string='Caller PBX User', readonly=True)
    answered_pbx_user = fields.Many2one('connect.user', ondelete='set null', string='Answered PBX User', readonly=True)
    called_pbx_users = fields.Many2many('connect.user', readonly=True)
    # Users are Odoo accounts.
    caller_user = fields.Many2one('res.users', string='Caller User', ondelete='set null', readonly=True)
    caller_user_img = fields.Binary(related='caller_user.image_1920')
    called_users = fields.Many2many('res.users', readonly=True)
    answered_user = fields.Many2one('res.users', ondelete='set null', string='Answered User', readonly=True)
    answered_user_img = fields.Binary(related='answered_user.image_1920', string='Answered User Avatar')
    # Transfer tracking fields
    transferred_users = fields.Many2many('res.users', 'connect_call_transfer_rel', 'call_id', 'user_id', string='Transferred Users', readonly=True)
    completed_by_user = fields.Many2one('res.users', ondelete='set null', string='Completed By', readonly=True)
    if release.version_info[0] > 15.0:
        transfer_context = fields.Json(string='Transfer Context', readonly=True, help='Temporary storage for transfer targets during webhook processing')
    else:
        transfer_context = fields.Text(string='Transfer Context', readonly=True, help='Temporary storage for transfer targets during webhook processing')
    call_pattern = fields.Selection([
        ('ring_group', 'Ring Group (Multiple Users)'),
        ('direct_call', 'Direct Call (Single User)')
    ], string='Call Pattern', readonly=True, help='Detected call pattern: ring group vs direct call')
    # Call parking fields
    park_slot = fields.Char(string='Parking Slot', readonly=True, index=True,
        help='Parking slot the call is currently waiting in. Cleared when the call is retrieved.')
    park_call_sid = fields.Char(string='Parked Call SID', readonly=True,
        help='Twilio CallSid of the leg that was placed into the parking queue.')
    parked_at = fields.Datetime(string='Parked At', readonly=True)
    parked_by_pbx_user = fields.Many2one('connect.user', ondelete='set null',
        string='Parked By', readonly=True)
    # Scheduled fields.
    scheduled_datetime = fields.Datetime()
    # Voicemail fields
    voicemail_url = fields.Char(readonly=True)
    voicemail_duration = fields.Integer(readonly=True)
    voicemail_icon = fields.Html(compute='_get_voicemail_icon', string='V', store=True)
    if release.version_info[0] >= 17.0:
        voicemail_widget = fields.Html(compute='_get_voicemail_widget', string='VoiceMail', sanitize=False)
    else:
        voicemail_widget = fields.Char(compute='_get_voicemail_widget', string='VoiceMail')
    voicemail_transcript = fields.Text()
    voicemail_transcription_error = fields.Char()
    # Reference, to submit call history and summary.
    ref = fields.Reference(selection=[('res.partner', 'Partner')], compute='_get_ref')
    has_error = fields.Boolean(index=True)
    error_code = fields.Char(readonly=True)
    error_message = fields.Text(readonly=True)
    # Call price fields
    price = fields.Float(string='Call Price', readonly=True, digits=(10, 3))
    price_unit = fields.Char(string='Price Unit', readonly=True, help='The currency unit for call price (e.g., USD)')
    price_currency = fields.Char(string='Price Currency', readonly=True, default='USD')
    call_sid = fields.Char(string='Twilio Call SID', readonly=True, index=True, help='Twilio CallSid for fetching price information')
    is_price_fetched = fields.Boolean(string='Price Fetched', default=False, readonly=True, index=True, help='Indicates if call price has been fetched from Twilio API')
    price_fetch_attempts = fields.Integer(string='Price Fetch Attempts', default=0, readonly=True)
    attempt_ids = fields.One2many(
        'connect.call.attempt', 'call_id', string='Runtime Attempts', readonly=True)
    projection_event_id = fields.Integer(readonly=True, index=True)
    finalization_event_id = fields.Integer(readonly=True, index=True)
    finalized_at = fields.Datetime(readonly=True, index=True)
    registration_done = fields.Boolean(default=False, readonly=True, index=True)
    ring_notification_done = fields.Boolean(default=False, readonly=True)
    error_notification_done = fields.Boolean(default=False, readonly=True)
    pbx_group_user_ids = fields.Many2many(
        'res.users', 'connect_call_pbx_group_users_rel',
        string='PBX Group Users',
        compute='_compute_pbx_group_user_ids', store=True)

    @api.depends('caller_user', 'answered_user')
    def _compute_pbx_group_user_ids(self):
        for rec in self:
            users = self.env['res.users']
            for u in (rec.caller_user, rec.answered_user):
                if u and u.connect_user:
                    for group in u.connect_user.pbx_group_ids:
                        users |= group.user_ids
            rec.pbx_group_user_ids = users

    def _get_name(self):
        for rec in self:
            try:
                is_missed_call = (
                    (rec.direction == 'incoming' and
                     rec.status in ['no-answer', 'busy', 'failed'] and
                     not rec.answered_user)
                    or
                    (rec.transferred_users and not rec.completed_by_user)
                )
                if is_missed_call:
                    caller_name = None
                    caller_number = rec.caller
                    if rec.partner:
                        caller_name = rec.partner.name
                    elif rec.caller_user:
                        caller_name = rec.caller_user.name
                    if caller_name and caller_number:
                        caller_display = f"{caller_name} ({caller_number})"
                    elif caller_name:
                        caller_display = caller_name
                    elif caller_number:
                        caller_display = caller_number
                    else:
                        caller_display = "Unknown"
                    rec.name = f"Missed call from {caller_display}"
                else:
                    started = fields.Datetime.context_timestamp(rec, rec.create_date)
                    formatted_time = fields.Datetime.to_string(started)
                    rec.name = '{} {} call at {}'.format(rec.status, rec.direction, formatted_time).capitalize()
            except Exception:
                logger.exception('Call name compute error:')
                rec.name = str(rec.id)

    def _get_ref(self):
        for rec in self:
            if rec.partner:
                rec.ref = 'res.partner,{}'.format(rec.partner.id)
            else:
                rec.ref = False

    def _get_recording_data(self):
        # Parking splits one conversation into a recording per segment, and each
        # segment is stored on the call its <Dial> ran on — the original inbound
        # one. The leg that retrieves the call from the slot therefore owns no
        # recording at all, so it surfaces the recordings of its parent call
        # instead of showing the agent who picked up an empty Recording tab.
        # Make one query to get all records.
        calls = self | self.parent_call
        recordings = self.env['connect.recording'].search([('call', 'in', calls.ids)])
        for rec in self:
            segments = recordings.filtered(
                lambda x: x.call.id in (rec.id, rec.parent_call.id))
            rec.recording_ids = segments
            rec.recording_count = len(segments)
            if segments:
                # Make sure we take the last recording (fix for Elevenlabs agent recording)
                recording = max(segments, key=lambda x: x.id)
                rec.recording = recording
                rec.transcript = recording.transcript
                rec.recording_icon = '<span class="fa fa-file-sound-o"/>'
                rec.recording_widget = recording.recording_widget
            else:
                rec.recording_icon = ''
                rec.transcript = ''
                rec.recording = False
                rec.recording_widget = ''

    @api.depends('activity_ids')
    def _compute_has_activity(self):
        for rec in self:
            rec.has_activity = bool(rec.activity_ids)

    def _recompute_has_activity(self):
        # mail.activity uses a generic (res_model, res_id) reference, so adding
        # or removing an activity does not auto-trigger the activity_ids
        # dependency above. Called from the mail.activity create/write/unlink
        # overrides to keep the stored flag in sync (e.g. on "mark done").
        calls = self.exists()
        if calls:
            calls.invalidate_recordset(['activity_ids'])
            calls._compute_has_activity()

    def _get_voicemail_widget(self):
        proxy_recordings = self.env['connect.settings'].sudo().get_param('proxy_recordings')
        for rec in self:
            if rec.voicemail_url:
                if proxy_recordings:
                    media_url = '/connect/voicemail/{}'.format(rec.id)
                else:
                    media_url = rec.voicemail_url
                rec.voicemail_widget = '<audio id="sound_file" preload="auto" ' \
                    'controls="controls"> ' \
                    '<source src="{}"/>' \
                    '</audio>'.format(media_url)
            else:
                rec.voicemail_widget = ''

    @api.depends('voicemail_url')
    def _get_voicemail_icon(self):
        for rec in self:
            if rec.voicemail_url:
                rec.voicemail_icon = '<span class="fa fa-envelope-o"/>'
            else:
                rec.voicemail_icon = ''

    @api.constrains('voicemail_url')
    def _transcribe_voicemail(self):
        self.ensure_one()
        openai_key = self.env['connect.settings'].sudo().get_param('openai_api_key')
        if not openai_key:
            logger.warning('OpenAI key is not set! Transcription will not be available.')
            return False
        if self.voicemail_url:
            self.transcribe_voicemail(openai_key)
        else:
            logger.warning('Voicemail is not available yet!')

    def transcribe_voicemail(self, openai_api_key):
        result = {}
        try:
            client = openai.OpenAI(api_key=openai_api_key)
            response = requests.get(self.voicemail_url, stream=True)
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
            result['voicemail_transcript'] = segments.strip()
            result['voicemail_transcription_error'] = False
        except Exception as e:
            logger.exception('Voicemail transcribe error:')
            result['voicemail_transcription_error'] = str(e)
        finally:
            self.write(result)

    @api.depends('duration')
    def _get_duration_human(self):
        for record in self:
            if record.duration is not None:
                minutes = record.duration // 60
                seconds = record.duration % 60
                record.duration_human = '{:02}:{:02}'.format(minutes, seconds)
                record.duration_minutes = record.duration / 60.0
            else:
                record.duration_minutes = 0
                record.duration_human = "00:00"

    def _detect_call_pattern(self):
        """
        Detect the call pattern from explicit channel tagging.
        Returns:
            'ring_group': Multiple users rang simultaneously
            'direct_call': Single user called initially
        """
        self.ensure_one()
        if self.call_pattern:
            return self.call_pattern
        if not self.channels:
            return None
        child_channels = self.channels.filtered(lambda c: c.parent_channel and c.called_pbx_user)
        if not child_channels:
            return None
        ring_group_channels = child_channels.filtered(lambda c: c.call_source == 'ring_group')
        direct_call_channels = child_channels.filtered(lambda c: c.call_source == 'direct_call')
        if ring_group_channels:
            pattern = 'ring_group'
        elif direct_call_channels:
            pattern = 'direct_call'
        else:
            return self._detect_call_pattern_fallback()
        return pattern

    def _detect_call_pattern_fallback(self):
        """Fallback pattern detection using timing-based logic."""
        child_channels = self.channels.filtered(lambda c: c.parent_channel and c.called_pbx_user)
        initial_called_users = set()
        for channel in child_channels:
            if channel.called_pbx_user and channel.called_pbx_user.user:
                initial_called_users.add(channel.called_pbx_user.user.id)
        pattern = 'ring_group' if len(initial_called_users) > 1 else 'direct_call'
        return pattern

    def _finalize_call_details(self):
        """
        Called once when all channels are closed to do final call processing.
        """
        self.ensure_one()
        logger.info(f"=== FINALIZING CALL DETAILS FOR CALL {self.id} ===")
        if not self.call_pattern:
            detected_pattern = self._detect_call_pattern()
            if detected_pattern:
                self.call_pattern = detected_pattern
                logger.info(f"Call {self.id}: Set call pattern to '{detected_pattern}'")
        if self.call_pattern == 'direct_call':
            self._populate_user_fields_direct_call()
        elif self.call_pattern == 'ring_group':
            self._populate_user_fields_ring_group()
        else:
            logger.warning(f"Call {self.id}: Unknown call pattern '{self.call_pattern}', using fallback logic")
            self._populate_user_fields_fallback()
        self._set_final_call_status()
        logger.info(f"Call {self.id}: Final status='{self.status}', answered_user='{self.answered_user.login if self.answered_user else None}', completed_by_user='{self.completed_by_user.login if self.completed_by_user else None}', transferred_users={len(self.transferred_users)}")

    def _set_final_call_status(self):
        """Simplified call status logic based on answered_user field."""
        self.ensure_one()
        if self.direction == 'outgoing':
            self.status = 'completed'
            logger.info(f"Call {self.id}: Status set to 'completed' (outgoing call)")
        elif self.answered_user:
            self.status = 'completed'
            logger.info(f"Call {self.id}: Status set to 'completed' (answered by {self.answered_user.login})")
        else:
            channel_statuses = self.channels.mapped('status')
            if 'failed' in channel_statuses:
                self.status = 'failed'
                logger.info(f"Call {self.id}: Status set to 'failed' (channel failed)")
            elif 'no-answer' in channel_statuses:
                self.status = 'no-answer'
                logger.info(f"Call {self.id}: Status set to 'no-answer' (at least one channel rang)")
            elif 'busy' in channel_statuses:
                self.status = 'busy'
                logger.info(f"Call {self.id}: Status set to 'busy' (all channels busy)")
            else:
                self.status = 'no-answer'
                logger.info(f"Call {self.id}: Status set to 'no-answer' (default)")

    def _update_live_status(self):
        """Reflect the live call status while the call is still active.

        The call status is set on creation (ringing) and only finalized once all
        channels end (_set_final_call_status). Without this, the status never moves
        to 'in-progress' on answer. Derive it from the current channel statuses so
        the UI shows ringing -> in-progress. Terminal statuses are left to
        _set_final_call_status().
        """
        self.ensure_one()
        chan_statuses = self.channels.mapped('status')
        if 'in-progress' in chan_statuses:
            live_status = 'in-progress'
        elif 'ringing' in chan_statuses:
            live_status = 'ringing'
        else:
            return
        if self.status != live_status:
            self.status = live_status

    def _populate_user_fields_direct_call(self):
        """Populate user fields for direct call pattern."""
        self.ensure_one()
        logger.info(f"Call {self.id}: Populating user fields for direct call pattern")
        if self.direction == 'outgoing':
            self._populate_outgoing_call_user_fields()
            return
        user_channels = self.channels.filtered(lambda c: c.called_pbx_user and c.called_pbx_user.user)
        if not user_channels:
            logger.warning(f"Call {self.id}: No channels with users found for direct call")
            return
        user_channels_by_time = user_channels.sorted('create_date')
        completed_channels = user_channels.filtered(lambda c: c.status == 'completed')
        if self.transferred_users and completed_channels:
            initial_answered_channels = completed_channels.filtered(
                lambda c: c.called_pbx_user.user not in self.transferred_users
            )
            if initial_answered_channels:
                if len(initial_answered_channels) > 1:
                    answered_channel = initial_answered_channels.sorted('id')[0]
                else:
                    answered_channel = initial_answered_channels[0]
                self.answered_user = answered_channel.called_pbx_user.user
                self.answered_pbx_user = answered_channel.called_pbx_user
                logger.info(f"Call {self.id}: answered_user set to {self.answered_user.login} (initial answerer, excluding transfers)")
            else:
                logger.info(f"Call {self.id}: No initial answerer found (all completed channels are transfers)")
        elif completed_channels:
            if len(completed_channels) > 1:
                answered_channel = completed_channels.sorted('id')[0]
            else:
                answered_channel = completed_channels[0]
            self.answered_user = answered_channel.called_pbx_user.user
            self.answered_pbx_user = answered_channel.called_pbx_user
            logger.info(f"Call {self.id}: answered_user set to {self.answered_user.login} (completed channel, no transfers)")
        else:
            logger.info(f"Call {self.id}: No completed channels found - leaving answered_user empty")
        if self.transferred_users:
            if not self.completed_by_user:
                all_user_channels = self.channels.filtered(lambda c: c.called_pbx_user and c.called_pbx_user.user)
                completed_channels = all_user_channels.filtered(lambda c: c.status == 'completed')
                transfer_completed_channels = completed_channels.filtered(
                    lambda c: c.called_pbx_user.user in self.transferred_users
                )
                if transfer_completed_channels:
                    if len(transfer_completed_channels) > 1:
                        final_channel = transfer_completed_channels.sorted('id')[-1]
                    else:
                        final_channel = transfer_completed_channels[0]
                    self.completed_by_user = final_channel.called_pbx_user.user
                    logger.info(f"Call {self.id}: completed_by_user set to transfer recipient {self.completed_by_user.login} (from channel)")
                else:
                    logger.info(f"Call {self.id}: Transfer failed - completed_by_user left empty for missed call notifications")
            else:
                logger.info(f"Call {self.id}: completed_by_user already set by extension handler: {self.completed_by_user.login}")
        else:
            self.completed_by_user = self.answered_user
            if self.completed_by_user:
                logger.info(f"Call {self.id}: completed_by_user set to original answerer {self.completed_by_user.login} (no transfer)")

    def _populate_outgoing_call_user_fields(self):
        """Populate user fields for outgoing calls."""
        self.ensure_one()
        logger.info(f"Call {self.id}: Populating user fields for outgoing call")
        outbound_channel = None
        for channel in self.channels:
            if channel.technical_direction == 'outbound-dial':
                outbound_channel = channel
                break
        if outbound_channel:
            external_number = outbound_channel.called_number
            if outbound_channel.partner and outbound_channel.partner.user_id:
                self.called_users = [(4, outbound_channel.partner.user_id.id)]
                logger.info(f"Call {self.id}: called_users set to Odoo contact {outbound_channel.partner.name}")
            else:
                self.called_users = [(5,)]
                logger.info(f"Call {self.id}: External party {external_number} has no Odoo user - called_users cleared")
            external_answered = (outbound_channel.status in ['in-progress', 'completed'] and
                               outbound_channel.duration and outbound_channel.duration > 0)
            if external_answered:
                if outbound_channel.partner and outbound_channel.partner.user_id:
                    self.answered_user = outbound_channel.partner.user_id
                    logger.info(f"Call {self.id}: answered_user set to Odoo contact {outbound_channel.partner.name}")
                else:
                    logger.info(f"Call {self.id}: External party {external_number} answered, but no Odoo contact found")
            else:
                logger.info(f"Call {self.id}: External party didn't answer (status: {outbound_channel.status})")
        internal_channels = self.channels.filtered(lambda c: c.called_pbx_user and c.called_pbx_user.user)
        if internal_channels:
            completed_internal = internal_channels.filtered(lambda c: c.status == 'completed')
            if completed_internal:
                if len(completed_internal) > 1:
                    completed_channel = completed_internal.sorted('id')[-1]
                else:
                    completed_channel = completed_internal[0]
                self.completed_by_user = completed_channel.called_pbx_user.user
                logger.info(f"Call {self.id}: completed_by_user set to transfer recipient {self.completed_by_user.login}")
            else:
                logger.info(f"Call {self.id}: Transfer attempted but no transfer recipient completed - completed_by_user remains empty")
        else:
            self._set_original_caller_as_completer()

    def _set_original_caller_as_completer(self):
        """Helper to set original caller as completed_by_user for outgoing calls"""
        caller_channel = None
        for channel in self.channels:
            if channel.caller_pbx_user and channel.caller_pbx_user.user:
                caller_channel = channel
                break
        if caller_channel:
            self.completed_by_user = caller_channel.caller_pbx_user.user
            logger.info(f"Call {self.id}: completed_by_user set to original caller {self.completed_by_user.login}")
        else:
            logger.warning(f"Call {self.id}: Could not identify original caller for outgoing call")

    def _populate_user_fields_ring_group(self):
        """Populate user fields for ring group pattern."""
        self.ensure_one()
        logger.info(f"Call {self.id}: Populating user fields for ring group pattern")
        ring_group_channels = self.channels.filtered(lambda c: c.call_source == 'ring_group' and c.called_pbx_user and c.called_pbx_user.user)
        if not ring_group_channels:
            logger.warning(f"Call {self.id}: No ring_group channels with users found")
            return
        completed_ring_channels = ring_group_channels.filtered(lambda c: c.status == 'completed')
        if not completed_ring_channels:
            logger.info(f"Call {self.id}: No completed ring_group channels found - no one answered")
            return
        if self.transferred_users:
            genuine_ring_answered = completed_ring_channels.filtered(
                lambda c: c.called_pbx_user.user not in self.transferred_users
            )
            if genuine_ring_answered:
                completed_ring_channels = genuine_ring_answered
        if len(completed_ring_channels) > 1:
            answered_channel = completed_ring_channels.sorted('id')[0]
        else:
            answered_channel = completed_ring_channels[0]
        self.answered_user = answered_channel.called_pbx_user.user
        self.answered_pbx_user = answered_channel.called_pbx_user
        logger.info(f"Call {self.id}: answered_user set to {self.answered_user.login} (answered from ring group)")
        if self.transferred_users:
            if not self.completed_by_user:
                transfer_completed_channels = []
                for user in self.transferred_users:
                    user_channels = self.channels.filtered(lambda c: c.called_user and c.called_user.id == user.id and c.status == 'completed')
                    transfer_completed_channels.extend(user_channels)
                if transfer_completed_channels:
                    latest_channel = sorted(transfer_completed_channels, key=lambda c: c.id)[-1]
                    self.completed_by_user = latest_channel.called_user
                    logger.info(f"Call {self.id}: completed_by_user set to transfer recipient {self.completed_by_user.login} (from channel)")
                else:
                    logger.info(f"Call {self.id}: Transfer failed - completed_by_user left empty for missed call notifications")
            else:
                logger.info(f"Call {self.id}: completed_by_user already set by extension handler: {self.completed_by_user.login}")
        else:
            self.completed_by_user = self.answered_user
            logger.info(f"Call {self.id}: completed_by_user set to answerer {self.answered_user.login} (no transfer)")

    def _populate_user_fields_fallback(self):
        """Fallback user field population when pattern detection fails."""
        self.ensure_one()
        logger.info(f"Call {self.id}: Using fallback user field population")
        completed_channels = self.channels.filtered(lambda c: c.status == 'completed' and c.called_pbx_user and c.called_pbx_user.user)
        if completed_channels:
            sorted_channels = completed_channels.sorted('write_date')
            first_channel = sorted_channels[0]
            self.answered_user = first_channel.called_pbx_user.user
            self.answered_pbx_user = first_channel.called_pbx_user
            last_channel = sorted_channels[-1]
            self.completed_by_user = last_channel.called_pbx_user.user
            logger.info(f"Call {self.id}: Fallback - answered_user={self.answered_user.login}, completed_by_user={self.completed_by_user.login}")

    def add_transferred_user(self, user):
        """Persist transfer runtime state so every worker observes it."""
        self.ensure_one()
        if user and hasattr(user, 'id'):
            current_transfer_ids = self.transferred_users.ids
            if user.id not in current_transfer_ids:
                self.transferred_users = [(4, user.id)]
                self._set_webhook_expectation('transfer', {
                    'expected_count': 1,
                    'target_user_id': user.id,
                })
                logger.info(f"Call {self.id}: Transfer initiated to {user.login} (added to transferred_users)")
                if not self.call_pattern:
                    detected_pattern = self._detect_call_pattern()
                    if detected_pattern:
                        self.call_pattern = detected_pattern

    def store_transfer_context(self, dial_call_sid, target_user):
        """Store transfer context in the database (legacy JSON is read-only)."""
        self.ensure_one()
        if not dial_call_sid or not target_user:
            return
        attempt = self.attempt_ids.filtered(
            lambda rec: rec.kind == 'transfer'
            and rec.state == 'pending'
            and rec.target_user_id == target_user
        )[:1]
        if attempt:
            attempt.write({'dial_call_sid': dial_call_sid})
        else:
            self.env['connect.call.attempt'].sudo().create({
                'kind': 'transfer',
                'call_id': self.id,
                'parent_sid': self.call_sid or self.channels[:1].sid,
                'dial_call_sid': dial_call_sid,
                'target_user_id': target_user.id,
            })
        logger.info(f"Call {self.id}: Stored transfer context for {dial_call_sid} -> {target_user.login}")

    def get_transfer_target(self, dial_call_sid):
        """Get a transfer target from runtime attempts, then legacy JSON."""
        self.ensure_one()
        if not dial_call_sid:
            return None
        attempt = self.attempt_ids.filtered(
            lambda rec: rec.kind == 'transfer'
            and rec.dial_call_sid == dial_call_sid
            and rec.target_user_id
        )[:1]
        if attempt:
            return attempt.target_user_id
        context_data = (self.transfer_context or {}).get(dial_call_sid)
        if context_data and 'user_id' in context_data:
            user = self.env['res.users'].sudo().browse(context_data['user_id'])
            if user.exists():
                logger.info(f"Call {self.id}: Retrieved transfer target from context: {user.login}")
                return user
        return None

    def store_external_call_leg(self, external_call_sid):
        """Store an external leg without mutating connect.call."""
        self.ensure_one()
        if not external_call_sid:
            return
        attempt = self.attempt_ids.filtered(
            lambda rec: rec.kind == 'external_leg' and rec.state == 'pending'
        )[:1]
        if attempt:
            attempt.write({'external_sid': external_call_sid})
        else:
            self.env['connect.call.attempt'].sudo().create({
                'kind': 'external_leg',
                'call_id': self.id,
                'parent_sid': self.call_sid or self.channels[:1].sid,
                'external_sid': external_call_sid,
            })
        logger.info(f"Call {self.id}: Stored external call leg SID: {external_call_sid}")

    def get_external_call_leg(self):
        """Get an external leg from runtime attempts, then legacy JSON."""
        self.ensure_one()
        attempt = self.attempt_ids.filtered(
            lambda rec: rec.kind == 'external_leg' and rec.external_sid
        )[:1]
        external_leg = attempt.external_sid if attempt else (
            (self.transfer_context or {}).get('_external_leg'))
        if external_leg:
            logger.info(f"Call {self.id}: Retrieved external call leg SID: {external_leg}")
            return external_leg
        return None

    def clear_transfer_context(self):
        """Resolve runtime attempts; keep the legacy JSON field untouched."""
        self.ensure_one()
        self.attempt_ids.filtered(
            lambda rec: rec.state == 'pending'
        ).mark_resolved()

    def _set_webhook_expectation(self, source, data):
        """Create a persistent expectation shared by all Odoo workers."""
        self.ensure_one()
        kind = source if source in {
            'direct_call', 'ring_group', 'transfer', 'external_leg',
            'external_termination'
        } else 'direct_call'
        expected_call_sids = data.get('expected_call_sids', [])
        vals = {
            'kind': kind,
            'call_id': self.id,
            'parent_sid': self.call_sid or self.channels[:1].sid,
            'expected_count': data.get('expected_count', 1),
            'target_user_id': data.get('target_user_id'),
            'dial_call_sid': expected_call_sids[0] if len(expected_call_sids) == 1 else False,
            'context': data,
        }
        attempt = self.env['connect.call.attempt'].sudo().create(vals)
        if expected_call_sids:
            logger.info(f"Call {self.id}: Set {source} webhook expectation - expecting CallSids: {expected_call_sids}")
        else:
            logger.info(f"Call {self.id}: Set {source} webhook expectation - expecting {data.get('expected_count', 1)} channels")
        return attempt

    def _update_webhook_expectation_callsid(self, source, call_sid, call_status):
        """Compatibility helper for code paths that still update a leg directly."""
        attempts = self.attempt_ids.filtered(
            lambda rec: rec.kind == source and rec.state == 'pending')
        if call_status in CALL_END_STATUSES:
            for attempt in attempts:
                channels = self.channels.filtered(
                    lambda channel: channel.call_source == source
                    and channel.status in CALL_END_STATUSES)
                if len(channels) >= attempt.expected_count:
                    attempt.mark_resolved()

    def _has_pending_webhooks(self):
        """Check persistent, non-expired runtime expectations."""
        now = fields.Datetime.now()
        expired = self.attempt_ids.filtered(
            lambda rec: rec.state == 'pending' and rec.expires_at <= now)
        if expired:
            expired.write({'state': 'expired', 'resolved_at': now})
        return bool(self.attempt_ids.filtered(
            lambda rec: rec.state == 'pending'
            and rec.kind not in ('external_leg', 'external_termination')))

    def _clear_webhook_expectations(self, source=None):
        """Resolve persistent expectations, optionally filtered by kind."""
        attempts = self.attempt_ids.filtered(
            lambda rec: rec.state == 'pending'
            and (not source or rec.kind == source))
        attempts.mark_resolved()

    @api.model
    def ensure_initial_call(self, payload):
        """Synchronously and idempotently create the root channel and call."""
        self = self.sudo()
        payload = dict(payload or {})
        sid = payload.get('CallSid')
        if not sid:
            return self
        channel_model = self.env['connect.channel']
        channel = channel_model.search([('sid', '=', sid)], limit=1)
        if not channel:
            event_model = self.env['connect.call.event']
            vals = event_model._channel_vals(payload, self, channel_model)
            vals.update({
                'sid': sid,
                'sequence_number': int(payload.get('SequenceNumber') or 0),
                'event_timestamp': event_model._parse_timestamp(payload)
                    or fields.Datetime.now(),
            })
            channel = channel_model.with_context(
                tracking_disable=True).create(vals)
        return self._ensure_call_from_channel(channel)

    @api.model
    def _ensure_call_from_channel(self, channel):
        """Create the aggregate for an already known root channel."""
        self = self.sudo()
        if channel.call:
            return channel.call
        if channel.parent_channel and channel.parent_channel.call:
            channel.with_context(tracking_disable=True).write({
                'call': channel.parent_channel.call.id,
            })
            return channel.parent_channel.call
        if channel.parent_channel:
            return self
        if channel.technical_direction == 'outbound-api':
            direction = 'outgoing'
        elif channel.technical_direction == 'inbound' and channel.caller_pbx_user:
            direction = 'outgoing'
        elif channel.technical_direction == 'inbound':
            direction = 'incoming'
        else:
            direction = 'outgoing'
        call = self.with_context(tracking_disable=True).create({
            'partner': channel.partner.id,
            'called': channel.called_number,
            'caller': channel.caller_number,
            'status': channel.status,
            'caller_pbx_user': channel.caller_pbx_user.id,
            'caller_user': channel.caller_user.id,
            'direction': direction,
            'call_type': channel.call_type or 'phone',
            'call_pattern': (
                'direct_call' if direction in ('outgoing', 'internal') else False
            ),
            'call_sid': channel.sid,
        })
        channel.with_context(tracking_disable=True).write({'call': call.id})
        return call

    def _after_call_projection(self, finalized, changed_fields):
        """Extension hook invoked after an idempotent call projection."""
        return True

    def write(self, vals: dict):
        if release.version_info[0] <= 15.0 and 'transfer_context' in vals:
            vals['transfer_context'] = json.dumps(vals['transfer_context'])
        return super().write(vals)

    def read(self, fields=None, **kwargs):
        records = super().read(fields, **kwargs)
        if release.version_info[0] <= 15.0 and 'transfer_context' in (fields or []):
            for record in records:
                if record.get('transfer_context'):
                    record['transfer_context'] = json.loads(record['transfer_context'])
        return records

    @api.model
    def _on_call_status_legacy(self, params):
        self = self.sudo()
        # Create channel
        channel = self.env['connect.channel'].on_call_status(params)
        if not channel:
            logger.error('No channel returned from on_call_status!')
            return False
        if not self.env['oduist.license'].check_license('connect', silent=True):
            return False
        if not channel.parent_channel and not channel.call:
            # Create a new call.
            if channel.technical_direction == 'outbound-api':
                # Click2call originated call.
                debug(self, 'outbound-api channel direction.')
                direction = 'outgoing'
            elif channel.technical_direction == 'inbound' and channel.caller_pbx_user:
                # Outgoing call from SIP or Client.
                debug(self, 'inbound channel direction with caller_pbx_user.')
                direction = 'outgoing'
            elif channel.technical_direction == 'inbound' and not channel.caller_pbx_user:
                # Incoming DID call
                debug(self, 'inbound channel direction without caller_pbx_user. Assuming DID call.')
                direction = 'incoming'
            else:
                # Default
                debug(self, 'Setting default call direction to outgoing.')
                direction = 'outgoing'
            # Set call pattern for outgoing and internal calls (always direct_call since they're one-to-one)
            call_pattern = 'direct_call' if direction in ('outgoing', 'internal') else False
            call = self.with_context(tracking_disable=True).create({
                'partner': channel.partner.id,
                'called': channel.called_number,
                'caller': channel.caller_number,
                'status': channel.status,
                'caller_pbx_user': channel.caller_pbx_user.id,
                'caller_user': channel.caller_user.id,
                'direction': direction,
                'call_type': channel.call_type or 'phone',
                'call_pattern': call_pattern,
            })
            channel.call = call
        elif channel.parent_channel and channel.parent_channel.call:
            # Secondary channel, assign the call from the parent.
            channel.call = channel.parent_channel.call
        # DATABASE LOCKING: serialize all concurrent webhooks for this call.
        # Twilio fires the parent leg and every child (ring-group) leg almost
        # simultaneously; each lands in its own HTTP worker / transaction and they
        # all mutate the same connect.call row plus its m2m relations. Acquiring a
        # per-call transaction-level advisory lock here — as the FIRST contended
        # resource, before ANY write to the call or its relations — forces those
        # webhooks into a single queue and removes the lock-ordering cycle that
        # previously produced "deadlock detected ... FOR UPDATE" on connect_call.
        if channel.call:
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                (CALL_LOCK_CLASS, channel.call.id),
            )
        # Detect internal calls: both sides are PBX users (extension-to-extension).
        # This also reclassifies outgoing→internal when the child channel reveals the called user.
        if channel.parent_channel and channel.parent_channel.call:
            if channel.caller_pbx_user and channel.parent_channel.called_pbx_user:
                channel.call.direction = 'internal'
            elif channel.called_pbx_user and channel.parent_channel.caller_pbx_user:
                if not channel.call.transferred_users:
                    channel.call.direction = 'internal'
        # Set called from 2nd call leg for click2call external calls.
        if channel.parent_channel and channel.parent_channel.technical_direction == 'outbound-api':
            channel.call.called = channel.called_number
        # User processing moved to earlier in webhook processing to prevent race conditions
        if channel.called_pbx_user:
            channel.call.called_pbx_users = [(4, channel.called_pbx_user.id)]
        # Check if we need to set a partner from child channel
        if not channel.call.partner and channel.partner:
            channel.call.partner = channel.partner
        # Update call duration based on all channels
        if channel.call:
            if channel.call.channels:
                total_duration = sum(channel.call.channels.mapped('duration') or [0])
                channel.call.duration = total_duration
            # Pattern detection from explicit tagging
            if not channel.call.call_pattern:
                detected_pattern = channel.call._detect_call_pattern()
                if detected_pattern:
                    channel.call.call_pattern = detected_pattern
                    logger.info(f"Call {channel.call.id}: Pattern detection set to '{detected_pattern}'")
        if (channel.call.direction == 'incoming' and params.get('CallStatus') == 'initiated' and
                params.get('To').startswith('sip:')):
            # Desktop notification only for SIP calls.
            channel.connect_notify()
        # NOTE: concurrent webhooks are already serialized by the per-call advisory
        # lock acquired above (pg_advisory_xact_lock), so no late row-level
        # SELECT ... FOR UPDATE is needed here.
        # Set called users - all called users including transfer recipients
        if channel.called_user:
            if channel.called_user.id not in channel.call.called_users.ids:
                channel.call.called_users = [(4, channel.called_user.id)]
                logger.info(f"Added {channel.called_user.login} to called_users (call_source: {getattr(channel, 'call_source', 'None')}) for call {channel.call.id}")
        # Update webhook expectations for child call webhooks
        if params.get('ParentCallSid'):
            call_status = params.get('CallStatus')
            call_sid = params.get('CallSid')
            if hasattr(channel, 'call_source') and channel.call_source:
                expectation_source = channel.call_source
            else:
                expectation_source = 'ring_group'
            channel.call._update_webhook_expectation_callsid(expectation_source, call_sid, call_status)
        # Determine finalization authority
        is_parent_call_webhook = not params.get('ParentCallSid')
        if channel.call.direction == 'outgoing':
            if params.get('ParentCallSid'):
                parent_completed = any(ch.sid == params.get('ParentCallSid') and ch.status in CALL_END_STATUSES
                                     for ch in channel.call.channels)
                can_trigger_finalization = parent_completed
            else:
                can_trigger_finalization = True
        else:
            can_trigger_finalization = is_parent_call_webhook
        # Register call only when ALL channels have ended AND no pending webhook expectations AND can trigger finalization
        all_channels_ended = all(ch.status in CALL_END_STATUSES for ch in channel.call.channels)
        has_pending_webhooks = channel.call._has_pending_webhooks()
        if (all_channels_ended and
            params.get('CallStatus') in CALL_END_STATUSES and
            not has_pending_webhooks and
            can_trigger_finalization):
            current_called_users = set(channel.call.called_users.ids)
            current_status = channel.call.status
            logger.info(f"Call {channel.call.id}: All conditions met for finalization")
            channel.call._finalize_call_details()
            new_called_users = set(channel.call.called_users.ids)
            status_changed = channel.call.status != current_status
            users_changed = current_called_users != new_called_users
            if users_changed or current_status != 'busy':
                self.register_call(channel, params)
            # Mark call for price fetching by cron (no immediate API call)
            if self.env['connect.settings'].sudo().get_param('fetch_call_prices'):
                self.save_call_price(channel.call, params)
        else:
            if not all_channels_ended:
                reason = "channels still active"
            elif has_pending_webhooks:
                reason = "pending webhook expectations"
            elif not can_trigger_finalization:
                reason = "child call webhook (parent call authority)"
            else:
                reason = "channel not ending"
            logger.info(f"Call {channel.call.id}: Finalization deferred - {reason}")
            # Call is still active: keep its status live (ringing -> in-progress).
            channel.call._update_live_status()
        if params.get('ErrorCode') and params.get('ErrorCode') not in IGNORE_ERROR_CODES:
            channel.call.update({
                'has_error': True,
                'error_code': params.get('ErrorCode'),
                'error_message': params.get('ErrorMessage')
            })
            # Notify caller user on errors on outgoing calls.
            user = channel.caller_user or channel.call.caller_user
            if channel.call.direction == 'outgoing' and user:
                if 'No International Permission' in params.get('ErrorMessage', ''):
                    message_text = re.sub(
                        r'(https?://\S+)',
                        r'<strong><a target="_blank" href="\1">your Twilio Console</a></strong>',
                        params.get('ErrorMessage', ''))
                else:
                    message_text = params.get('ErrorMessage', '')
                self.env['connect.settings'].connect_notify(
                    notify_uid=user.id,
                    title="Call Error",
                    message=message_text,
                    warning=True,
                )
        return channel.call.id

    @api.model
    def on_call_status(self, params, token=None):
        """Compatibility entry point: enqueue lifecycle work."""
        event = self.env['connect.call.event'].sudo().ingest(
            'call_status', params, token=token)
        return event.call_id.id if event.call_id else False

    @api.model
    def on_vm_recording_status(self, params, token=None):
        self.env['connect.call.event'].sudo().ingest(
            'voicemail_status', params, token=token)
        return True

    @api.model
    def on_call_action(self, params, token=None):
        self.env['connect.call.event'].sudo().ingest(
            'dial_action', params, token=token)
        return '<Response><Hangup/></Response>'

    def _process_transfer_completion(self, params):
        """
        Process Dial action webhook to update existing transfer recipient channel.
        """
        dial_call_sid = params.get('DialCallSid')
        dial_status = params.get('DialCallStatus')
        original_call_sid = params.get('CallSid')
        original_channel = self.env['connect.channel'].search([('sid', '=', original_call_sid)], limit=1)
        if not original_channel or not original_channel.call:
            logger.warning(f"Could not find original channel for transfer CallSid: {original_call_sid}")
            return
        call = original_channel.call
        recipient_channel = None
        if call.call_pattern == 'ring_group':
            child_channels = call.channels.filtered(lambda c: c.parent_channel)
            if child_channels:
                potential_recipients = child_channels.filtered(lambda c: c.status in ['no-answer', 'ringing', 'in-progress'])
                if potential_recipients:
                    recipient_channel = potential_recipients.sorted('id', reverse=True)[0]
                else:
                    logger.error(f"No suitable recipient channels found for ring group call {call.id}")
                    return
            else:
                logger.error(f"No child channels found for ring group call {call.id}")
                return
        elif call.call_pattern == 'direct_call':
            recipient_channel = self._create_missing_transfer_channel(call, dial_call_sid, dial_status, params)
            if recipient_channel:
                logger.info(f"Created missing transfer channel {recipient_channel.id}")
            else:
                logger.error(f"Could not create missing transfer channel for call {call.id}")
                return
        else:
            logger.error(f"Cannot process transfer completion for call {call.id} with unknown pattern '{call.call_pattern}'")
            return
        if recipient_channel and recipient_channel.called_pbx_user:
            if dial_status == 'completed':
                new_status = 'completed'
                duration = int(params.get('DialCallDuration', 0))
            elif dial_status == 'busy':
                new_status = 'busy'
                duration = 0
            elif dial_status == 'no-answer':
                new_status = 'no-answer'
                duration = 0
            elif dial_status == 'failed':
                new_status = 'failed'
                duration = 0
            else:
                new_status = dial_status
                duration = int(params.get('DialCallDuration', 0))
            recipient_channel.write({
                'status': new_status,
                'duration': duration,
            })
        else:
            logger.warning(f"Could not identify transfer recipient channel or PBX user")

    def _create_missing_transfer_channel(self, call, dial_call_sid, dial_status, params):
        """Create a missing transfer channel for direct calls."""
        try:
            parent_channel = call.channels.filtered(lambda c: not c.parent_channel)
            if not parent_channel:
                logger.warning(f"No parent channel found for call {call.id}")
                return None
            parent_channel = parent_channel[0]
            target_user = None
            target_user = call.get_transfer_target(dial_call_sid)
            if not target_user:
                original_call_sid = params.get('CallSid')
                if original_call_sid:
                    target_user = call.get_transfer_target(original_call_sid)
            if not target_user:
                call_with_sudo = call.sudo()
                if call_with_sudo.transferred_users:
                    target_user = call_with_sudo.transferred_users[-1]
            if not target_user:
                logger.error(f"Cannot determine transfer target for call {call.id}")
                return None
            pbx_user = self.env['connect.user'].sudo().search([('user', '=', target_user.id)], limit=1)
            if not pbx_user:
                logger.warning(f"Could not find PBX user for {target_user.login}")
                return None
            channel_data = {
                'sid': dial_call_sid,
                'call': call.id,
                'parent_channel': parent_channel.id,
                'technical_direction': 'outbound-dial',
                'status': dial_status,
                'duration': int(params.get('DialCallDuration', 0)),
                'called_pbx_user': pbx_user.id,
                'called_user': target_user.id,
                'call_source': 'transfer',
                'caller': parent_channel.caller,
                'called': pbx_user.uri
            }
            recipient_channel = self.env['connect.channel'].create(channel_data)
            return recipient_channel
        except Exception as e:
            logger.error(f"Failed to create missing transfer channel: {e}", exc_info=True)
            return None

    def save_call_price(self, call, params):
        """Mark call as needing price fetch (will be processed by cron job)"""
        try:
            call_sid = params.get('CallSid')
            if not call_sid:
                debug(self, 'No CallSid in webhook params, cannot store for price fetching')
                return

            # Store CallSid in call record for later price fetching by cron
            call.write({
                'call_sid': call_sid,
                'is_price_fetched': False,
            })
            debug(self, f'Marked call {call.id} (CallSid: {call_sid}) for price fetching by cron job')

        except Exception as e:
            logger.error(f'Error in save_call_price: {e}')

    def _fetch_call_price_from_api(self, call, call_sid):
        """Fetch call price from Twilio REST API"""
        try:
            client = self.env['connect.settings'].get_client()
            twilio_call = client.calls(call_sid).fetch()

            debug(self, f'Fetched call data: price={twilio_call.price}, price_unit={twilio_call.price_unit}')

            if twilio_call.price is not None and twilio_call.price != '':
                # Convert price to positive float (Twilio returns negative values)
                try:
                    price_value = round(abs(float(twilio_call.price)), 3)
                    price_unit = twilio_call.price_unit or 'USD'

                    call.write({
                        'price': price_value,
                        'price_unit': price_unit,
                        'price_currency': price_unit,
                    })
                    debug(self, f'Saved call price: ${price_value:.3f} {price_unit} for call {call.id}')
                    return True

                except ValueError as e:
                    logger.error(f'Error converting call price {twilio_call.price} to float: {e}')

            else:
                debug(self, f'Call price not yet available for {call_sid}, will be available later')

        except Exception as e:
            logger.error(f'Error fetching call price from API for {call_sid}: {e}')

        return False

    PRICE_FETCH_MAX_ATTEMPTS = 10

    @api.model
    def fetch_call_prices_batch(self):
        """Cron job method to fetch prices for calls that don't have them yet"""
        if not self.env['connect.settings'].sudo().get_param('fetch_call_prices'):
            debug(self, 'Call price fetching is disabled in settings')
            return

        # Find calls that need price fetching (completed calls without price,
        # not exceeding max retry attempts)
        calls_to_fetch = self.search([
            ('is_price_fetched', '=', False),
            ('call_sid', '!=', False),
            ('status', 'in', CALL_END_STATUSES),
            ('price_fetch_attempts', '<', self.PRICE_FETCH_MAX_ATTEMPTS),
            ('create_date', '>=', fields.Datetime.now() - timedelta(days=30))
        ])

        debug(self, f'Found {len(calls_to_fetch)} calls needing price fetch')

        for call in calls_to_fetch:
            try:
                call.write({'price_fetch_attempts': call.price_fetch_attempts + 1})
                success = self._fetch_call_price_from_api(call, call.call_sid)
                if success:
                    call.write({'is_price_fetched': True})
                    debug(self, f'Successfully fetched price for call {call.id}')
                else:
                    if call.price_fetch_attempts >= self.PRICE_FETCH_MAX_ATTEMPTS:
                        logger.warning(f'Call {call.id}: max price fetch attempts ({self.PRICE_FETCH_MAX_ATTEMPTS}) reached, giving up')
                    else:
                        debug(self, f'Price not yet available for call {call.id}, attempt {call.price_fetch_attempts}/{self.PRICE_FETCH_MAX_ATTEMPTS}')
            except Exception as e:
                logger.error(f'Error fetching price for call {call.id}: {e}')

        debug(self, f'Batch price fetch completed')

    def _format_missed_call_message(self, channel):
        """Create a clean missed call message format."""
        caller_name = None
        caller_number = None
        if channel.call.direction == 'incoming':
            caller_number = channel.call.caller
            if channel.call.partner:
                caller_name = channel.call.partner.name
            elif channel.call.caller_user:
                caller_name = channel.call.caller_user.name
        else:
            caller_number = channel.call.called
            if channel.call.partner:
                caller_name = channel.call.partner.name
        if caller_name and caller_number:
            caller_display = f"{caller_name} ({caller_number})"
        elif caller_name:
            caller_display = caller_name
        elif caller_number:
            caller_display = caller_number
        else:
            caller_display = "Unknown"
        call_link = f" <a href='/web#id={channel.call.id}&model=connect.call&view_type=form'>Click to view the call details</a>."
        transfer_info = ""
        if channel.call.answered_user:
            transfer_info = f" Call transferred to you by {channel.call.answered_user.name}."
        body = Markup(f"You missed a call from {caller_display}.{transfer_info}{call_link}")
        subject = f"Missed call from {caller_display}"
        return subject, body

    def get_notification_users(self):
        """Gets all users who should receive missed call notifications for this call."""
        notify_users = []
        # Rule 1: called_users only (no other fields) - everyone gets notification
        if (self.called_users and
            not self.answered_user and
            not self.transferred_users and
            not self.completed_by_user):
            for user in self.called_users:
                connect_user = user.connect_user
                if connect_user and connect_user[0].missed_calls_notify:
                    notify_users.append(user)
        # Rule 3: transferred_users + NO completed_by_user - only transferred users get notification
        elif (self.transferred_users and
              not self.completed_by_user):
            for user in self.transferred_users:
                connect_user = user.connect_user
                if connect_user and connect_user[0].missed_calls_notify:
                    notify_users.append(user)
        return notify_users

    def register_call(self, channel, params):
        try:
            notify_users = []
            # Construct base message
            message = [channel.call.status.capitalize(), channel.call.direction,
                       'call at {}, '.format(channel.create_date.strftime('%Y-%m-%d %H:%M:%S'))]
            if channel.call.caller_user:
                message.append('caller: {}, '.format(channel.call.caller_user.name))
            if channel.call.duration:
                message.append('duration: {}, '.format(channel.call.duration_human))
            if channel.call.answered_user:
                message.append('answered by: {}, '.format(channel.call.answered_user.name))
            if channel.call.called_users:
                message.append('dialed users: {}, '.format(', '.join(k.name for k in channel.call.called_users)))
            # Use extracted notification method
            notify_users = channel.call.get_notification_users()
            # Register call at partner.
            if channel.call.partner:
                message.insert(3, 'partner: {}, '.format(channel.call.partner.name))
                final_message = ' '.join(message)
                if final_message.endswith(', '):
                    final_message = final_message[:-2] + '.'
                channel.call.register_call_post_message(
                    channel.call.partner, body=final_message, subtype_xmlid='mail.mt_note')
            # Send notifications if any users were identified
            if notify_users:
                logger.info(f"Sending notifications to {len(notify_users)} users: {[u.login for u in notify_users]}")
                # Deduplicate
                original_count = len(notify_users)
                notify_users = list(set(notify_users))
                if len(notify_users) < original_count:
                    logger.warning(f"Removed {original_count - len(notify_users)} duplicate users from notification list")
                debug(self, 'Missed call notification to users: {}'.format(notify_users))
                notify_subject, notify_body = self._format_missed_call_message(channel)
                channel.call.register_call_post_message(
                    channel.call,
                    subtype_xmlid='mail.mt_comment',
                    subject=notify_subject,
                    body=notify_body,
                    partner_ids=[k.partner_id.id for k in notify_users]
                )
            # Clear temporary transfer context after call processing is complete
            channel.call.clear_transfer_context()
        except Exception as e:
            logger.exception('Register call error:', e)

    def register_call_post_message(self, obj, **kwargs):
        try:
            obj.with_user(SUPERUSER_ID).with_context(mail_create_nosubscribe=False).message_post(**kwargs)
        except Exception:
            logger.exception('Register call error: ')

    def register_summary_to_rec(self, rec, summary):
        try:
            if release.version_info[0] < 14:
                rec.sudo(SUPERUSER_ID).message_post(body=summary)
            else:
                rec.with_user(SUPERUSER_ID).message_post(body=summary)
        except Exception as e:
            logger.error('Cannot register summary: %s', e)

    @api.constrains('summary')
    def register_partner_call_summary(self):
        register_summary = self.env['connect.settings'].sudo().get_param('register_summary')
        if not register_summary:
            return
        for rec in self:
            if rec.partner and rec.summary:
                self.register_summary_to_rec(rec.partner, rec.summary)

    def create_partner_button(self):
        self.ensure_one()
        name_number = self.caller if self.direction == 'incoming' else self.called
        context = {
            'connect_call_id': self.id,
            'default_phone': name_number,
        }
        # Check if it's a click on a call with existing partner (linking)
        if not self.partner:
            partner = self.env['res.partner'].get_partner_by_number(name_number)
            if partner:
                self.sudo().partner = partner  # Use sudo as user has not access to write to call.
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.partner.id,
            'name': self.partner.name if self.partner else 'New Partner',
            'view_mode': 'form',
            'target': 'current',
            'context': context,
        }

    def transfer_button(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'connect.transfer_wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': 'Transfer Wizard'
        }

    def transfer(self, user=None):
        self.ensure_one()
        if False:  # self.status not in ['in-progress', 'ringing']:
            logger.warning('Call not in progress, cannot transfer')
            return
        # Get the PBX user doing trasnfer
        if not user:
            user = self.env.user.connect_user
            user = self.channels[0].caller_pbx_user or self.channels[0].called_pbx_user
        """
        # Case 1: User is on primary channel.
        primary_channel = self.channels.filtered(lambda x: x.parent_channel == False)
        if primary_channel and primary_channel.caller_pbx_user:
            print(111, 'PRIMARY CHANNEL CALLER', primary_channel)
        elif primary_channel and primary_channel.called_pbx_user:
            print(1111, 'PRIMARY CHANNEL CALLED', primary_channel)
        # Find current user on all channels.
        print(111111, self.channels)
        """
        user_channel = self.channels.filtered(
            lambda x: (x.caller_pbx_user == user or x.called_pbx_user == user))
        if not user_channel:
            logger.warning('Cannot get user channel for call %s for user %s', self.id, user.name)
            return
        other_channel = self.channels - user_channel
        if len(other_channel) != 1:
            logger.warning('Cannot transfer call, number of other channels: %s', len(other_channel))
            return
        client = self.env['connect.settings'].get_client()
        conf_id = uuid.uuid4().hex

        def transfer_other():
            # Put other channel into conference.
            response = VoiceResponse()
            response.say('Transfer')
            dial = Dial()
            dial.conference('user-{}-{}'.format(user.id, conf_id))
            response.append(dial)
            # response.play('http://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3')
            client.calls(other_channel.sid).update(twiml=response)

        def transfer_user():
            # Dial a new call party.
            response = VoiceResponse()
            response.say('Transfer')
            dial = Dial()
            sip = Sip('sip:user@devmax17.sip.twilio.com')
            # dial.conference('user-{}-{}'.format(user.id,  conf_id))
            dial.append(sip)
            response.append(dial)
            # response.play('http://com.twilio.music.classical.s3.amazonaws.com/BusyStrings.mp3')
            client.calls(user_channel.sid).update(twiml=response)

        transfer_user()
        transfer_other()

    def redial(self):
        self.ensure_one()
        self.originate_call(
            number=self.called if self.direction == 'outgoing' else self.caller,
        )

    @api.model
    def originate_call(
        self, number, res_model=None, res_id=None, user=None, whatsapp_call=False
    ):
        number = strip_number(number)
        if len(number) > MAX_EXTEN_LEN:
            number = "+{}".format(number)
        client = self.env['connect.settings'].get_client()
        partner_id = False
        obj = self.env[res_model].browse(res_id) if res_model and res_id else False
        caller_name = ""
        if res_model == "res.partner" and obj:
            partner_id = res_id
            caller_name = obj.display_name
        elif obj and hasattr(obj, "partner_id") and obj.partner_id:
            partner_id = obj.partner_id.id
            caller_name = obj.partner_id.display_name
        elif obj and hasattr(obj, "partner") and obj.partner:
            partner_id = obj.partner.id
            caller_name = obj.partner.display_name
        if not user:
            user = self.env.user
        if not user.connect_user:
            raise ValidationError("User does not have a SIP username defined!")
        first_flow = self.env["connect.user_callflow"].search(
            [("user", "=", user.id), ("callflow_type", "in", ["client", "sip"])],
            order="prio",
            limit=1,
        )
        if first_flow.callflow_type == "sip":
            to = self.env['connect.settings'].compute_sip_uri(user)
        else:
            to = "client:{}?autoAnswer=yes&Partner={}&CallerName={}".format(
                self.env.user.connect_user.uri, partner_id or "", caller_name or ""
            )
        if "client:" in to:
            to += "&From={}".format((number or "").replace("+", ""))
        self.env["oduist.license"].check_license("connect", silent=False)
        exten = self.env["connect.exten"].search([("number", "=", number)], limit=1)
        api_url = self.env['connect.settings'].sudo().get_param("api_url")
        edge = self.env["connect.settings"].get_param("twilio_edge")
        status_url = urljoin(api_url, "twilio/webhook/callstatus#e={}".format(edge))
        record_status_url = urljoin(
            api_url, "twilio/webhook/recordingstatus#e={}".format(edge)
        )
        if exten:
            callerId = user.connect_user.exten.number
            twiml = exten.render()
        else:
            if whatsapp_call:
                pbx_user = user.connect_user
                sender = self.env["connect.whatsapp_sender"].get_default_sender(
                    pbx_user
                )
                caller_number = sender.number if sender else False
                if not caller_number:
                    raise ValidationError("You must configure a WhatsApp sender!")
                callerId = f"whatsapp:{caller_number}"
                twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial callerId="{}">
        <WhatsApp statusCallback="{}" statusCallbackEvent="ringing answered completed">{}</WhatsApp>
    </Dial>
</Response>""".format(callerId, status_url, number)
            else:
                default_number = self.env["connect.outgoing_callerid"].search(
                    [("is_default", "=", True)], limit=1
                )
                if user.connect_user.outgoing_callerid:
                    callerId = user.connect_user.outgoing_callerid.number
                else:
                    callerId = default_number.number
                dial_record = (
                    'record-from-answer-dual'
                    if self.env.user.connect_user.record_calls
                    else 'do-not-record'
                )
                twiml = self.env['connect.settings'].get_external_call_route(
                    number, callerId, status_url,
                    record=dial_record, record_status_url=record_status_url)
        record = self.env.user.connect_user.record_calls
        debug(self, "Originate destination TwiML: {}".format(twiml))
        channel = client.calls.create(
            twiml=twiml,
            to=to,
            from_=callerId,
            status_callback=status_url,
            record=record,
            recording_channels="dual",
            recording_status_callback=record_status_url,
            recording_status_callback_event=["completed"],
            status_callback_event=["initiated", "answered", "completed"],
        )
        self.env["connect.channel"].sudo().create(
            {
                "sid": channel.sid,
                "technical_direction": "outboubd-api",
                "caller_user": user.id,
                "caller_pbx_user": user.connect_user.id,
                "partner": partner_id,
                "called": number,
                "caller": callerId,
            }
        )

    @api.model
    def get_widget_calls(self, domain, limit=None, offset=0, order='id desc', fields=[]):
        calls = self.search(domain, offset, limit, order)
        payload = []
        read_fields = self.get_widget_fields()
        if isinstance(fields, list):
            read_fields.extend(fields)
        for call in calls:
            call_data = call.read(read_fields)[0]
            if call.called_users:
                call_data.update({'called_users': list(call.called_users.read(['id', 'name'])[0].values())})
            # Add notification users for phone UI highlighting
            notification_users = call.get_notification_users()
            call_data.update({'notification_user_ids': [user.id for user in notification_users]})
            payload.append(call_data)
        return payload

    def get_widget_fields(self):
        return [
            "id",
            "called",
            "caller",
            "caller_user",
            "called_users",
            "partner",
            "create_date",
            "direction",
            "status",
            "answered_user",
            "completed_by_user",
            "transferred_users",
            "call_pattern",
            "disable_recording",
        ]

    @api.model
    def set_disable_recording(self, call_id, value=True):
        """Toggle the disable_recording flag on a call from the active calls widget.

        Restricted to members of the "Do not record" group.
        """
        if not self.env.user.has_group('connect.group_connect_do_not_record'):
            raise AccessError(_('You are not allowed to disable call recording.'))
        call = self.browse(call_id)
        call.sudo().disable_recording = bool(value)
        return call.sudo().disable_recording

    @api.model
    def can_disable_recording(self):
        """Whether the current user may disable recording from the active calls
        widget: member of the "Do not record" group AND their own calls are
        recorded (otherwise there is nothing to disable)."""
        user = self.env.user
        return user.has_group('connect.group_connect_do_not_record') and bool(user.connect_user.record_calls)

    @api.model
    def park_call(self, request, params):
        """Park a call into a specific parking slot.

        Called via SIP REFER when agent dials *701-*710.
        The slot number is derived from the extension number (e.g. *701 -> 701).

        In referUrl context, CallSid = the child call (agent's SIP leg).
        The returned TwiML applies to the child call.
        We must redirect the parent call (customer) to Enqueue via REST API
        and hang up the agent's SIP leg.
        """
        exten = params.get('ExtenNumber', '')
        slot = exten.lstrip('*')
        call_sid = request.get('CallSid')
        parent_call_sid = request.get('ParentCallSid')
        # Twilio omits ParentCallSid for SIP REFER fired from a Dial inside a
        # callflow path. Fall back to our channel records, where the parent
        # relation is stored from prior status webhooks.
        if not parent_call_sid and call_sid:
            channel = self.env['connect.channel'].sudo().search(
                [('sid', '=', call_sid)], limit=1)
            root = channel
            while root.parent_channel:
                root = root.parent_channel
            if root and root.sid and root.sid != call_sid:
                parent_call_sid = root.sid
                debug(self, 'park_call: resolved parent via channel: %s' % parent_call_sid)
        debug(self, 'park_call: CallSid=%s ParentCallSid=%s slot=%s' % (call_sid, parent_call_sid, slot))

        # Redirect the parent call (customer) to the parking queue
        if parent_call_sid:
            try:
                client = self.env['connect.settings'].get_client()
                enqueue_twiml = VoiceResponse()
                enqueue_twiml.enqueue('park-%s' % slot)
                client.calls(parent_call_sid).update(twiml=str(enqueue_twiml))
                debug(self, 'park_call: Redirected parent %s to park-%s' % (parent_call_sid, slot))
            except Exception as e:
                logger.error('park_call: Failed to redirect parent call: %s', e)
            else:
                self._register_parked_call(parent_call_sid, slot, request)
        else:
            # No parent call — this is a direct call to *701, just enqueue it
            debug(self, 'park_call: No ParentCallSid, enqueueing CallSid=%s' % call_sid)
            self._register_parked_call(call_sid, slot, request)
            response = VoiceResponse()
            response.enqueue('park-%s' % slot)
            return response

        # Hang up the agent's SIP leg
        response = VoiceResponse()
        response.hangup()
        return response

    @api.model
    def _register_parked_call(self, parked_call_sid, slot, request):
        """Remember which call is waiting in which parking slot.

        Without this the retrieval leg has no way to know who is parked, so it
        cannot present the original caller ID nor link the two calls together
        in the call log.
        """
        call = self._get_call_by_sid(parked_call_sid)
        if not call:
            logger.warning('park_call: no call found for CallSid=%s, slot %s not tracked',
                           parked_call_sid, slot)
            return self.browse()
        parked_by = self.env['connect.user'].sudo().get_user_by_uri(request.get('Caller'))[:1]
        call.sudo().write({
            'park_slot': slot,
            'park_call_sid': parked_call_sid,
            'parked_at': fields.Datetime.now(),
            'parked_by_pbx_user': parked_by.id if parked_by else False,
        })
        call._message_log(body=Markup(_('Call parked in slot %(slot)s by %(user)s.')) % {
            'slot': slot,
            'user': parked_by.name if parked_by else _('an unknown user'),
        })
        debug(self, 'park_call: call %s parked in slot %s' % (call.id, slot))
        return call

    @api.model
    def _get_call_by_sid(self, call_sid):
        """Resolve the connect.call a Twilio CallSid belongs to."""
        if not call_sid:
            return self.browse()
        channel = self.env['connect.channel'].sudo().search(
            [('sid', '=', call_sid)], limit=1)
        return channel.call.sudo() if channel.call else self.browse()

    @api.model
    def _get_parked_call(self, slot):
        """The call to be retrieved from a slot.

        Twilio dequeues the longest waiting caller, so when several calls share
        a slot we must pick the oldest one to stay in sync with the queue.
        Calls that have already ended are skipped: their Twilio call is gone,
        so the retrieval redirect fails and the caller is bridged through the
        plain queue instead. That bridge carries no referUrl, which leaves the
        agent who picked the call up unable to park it a second time.
        """
        if not slot:
            return self.browse()
        return self.sudo().search([
            ('park_slot', '=', slot),
            ('park_call_sid', '!=', False),
            ('status', 'not in', CALL_END_STATUSES),
        ], order='parked_at asc, id asc', limit=1)

    @api.model
    def unpark_call(self, request, params):
        """Unpark (retrieve) a call from a parking slot.

        Called when someone dials extension 701-710.
        params['ExtenNumber'] contains the slot number.

        The retrieving phone dialed the slot number, so its display shows the
        slot (e.g. "702") and Twilio never re-signals the remote identity when
        it bridges a queued caller into that established leg. To show the real
        caller ID we hang up the retrieval leg and instead redirect the parked
        call to dial the retriever back, presenting the original caller.
        When the parked call is unknown (parked before this feature, tracking
        lost, Twilio API error, ...) we fall back to the plain queue bridge.
        """
        slot = params.get('ExtenNumber', '')
        debug(self, 'unpark_call: Retrieving from slot %s' % slot)
        retriever = self.env['connect.user'].sudo().get_user_by_uri(request.get('Caller'))[:1]
        parked_call = self._get_parked_call(slot)
        # Link the retrieval leg to the parked call so the call log keeps the
        # customer's identity instead of showing a bare "exten -> slot" call.
        self._link_park_retrieval_leg(request, slot, parked_call, retriever)
        if parked_call and retriever:
            if self._dial_back_parked_call(parked_call, retriever, slot, request):
                # The parked call is now dialing the retriever, release the leg
                # the retriever dialed the slot with.
                response = VoiceResponse()
                response.hangup()
                return response
        else:
            debug(self, 'unpark_call: slot %s parked call %s retriever %s, using queue bridge' % (
                slot, parked_call.id if parked_call else False,
                retriever.username if retriever else False))
        response = VoiceResponse()
        dial = Dial(timeout=1)
        dial.queue('park-%s' % slot)
        response.append(dial)
        return response

    @api.model
    def _link_park_retrieval_leg(self, request, slot, parked_call, retriever):
        """Attach the "dialed the slot" call to the call being retrieved.

        Retrieving a parked call creates its own <exten> -> <slot> call record.
        Left alone it is an orphan with no partner, which is what made the call
        log show "702" instead of the customer.
        """
        retrieval_call = self._get_call_by_sid(request.get('CallSid'))
        if not retrieval_call or retrieval_call == parked_call:
            return self.browse()
        if parked_call:
            vals = {'parent_call': parked_call.id}
            if parked_call.partner and not retrieval_call.partner:
                vals['partner'] = parked_call.partner.id
            retrieval_call.sudo().write(vals)
            parked_call.sudo()._message_log(body=Markup(_(
                'Call retrieved from parking slot %(slot)s by %(user)s.')) % {
                    'slot': slot,
                    'user': retriever.name if retriever else _('an unknown user'),
                })
        retrieval_call.sudo()._message_log(body=Markup(_(
            'Retrieval of the call parked in slot %(slot)s.')) % {'slot': slot})
        return retrieval_call

    @api.model
    def _dial_back_parked_call(self, parked_call, retriever, slot, request):
        """Take the parked call out of the queue and dial the retriever back.

        Returns True when the redirect was accepted by Twilio, False to let the
        caller fall back to the plain queue bridge.
        """
        # Serialize concurrent retrievals of the same slot: whoever gets the row
        # lock first takes the call, the other one falls back to the queue.
        parked_call.flush_recordset(['park_slot'])
        self.env.cr.execute(
            'SELECT park_slot FROM connect_call WHERE id = %s FOR UPDATE',
            (parked_call.id,))
        row = self.env.cr.fetchone()
        if not row or not row[0]:
            debug(self, 'unpark_call: call %s already retrieved' % parked_call.id)
            return False
        caller_uri = request.get('Caller') or ''
        twiml = self._build_park_retrieval_twiml(
            parked_call, retriever, slot, from_client=caller_uri.startswith('client:'))
        if twiml is None:
            return False
        try:
            client = self.env['connect.settings'].get_client()
            client.calls(parked_call.park_call_sid).update(twiml=str(twiml))
        except Exception as e:
            logger.error('unpark_call: failed to redirect parked call %s: %s',
                         parked_call.park_call_sid, e)
            return False
        debug(self, 'unpark_call: redirected parked call %s to %s' % (
            parked_call.id, retriever.username))
        # Keep park_call_sid: the retrieval Dial action re-parks the caller when
        # the retriever does not answer.
        parked_call.sudo().write({'park_slot': False})
        return True

    def _should_record_park_retrieval(self, retriever):
        """Whether the leg retrieving this call from a slot is recorded.

        Recording is a property of the conversation, settled when the call was
        first answered. Deciding it from the retrieving agent's own
        record_calls flag instead loses the second half of every parked
        conversation that is picked up by someone who does not record, while
        the first half stays on file.
        """
        self.ensure_one()
        if self.disable_recording:
            return False
        # parked_by_pbx_user is not a reliable fallback on its own: Twilio sends
        # the customer as Caller on the park webhook, so it is often unset.
        policy_user = self.answered_pbx_user or self.parked_by_pbx_user
        return (policy_user or retriever).record_calls

    @api.model
    def _build_park_retrieval_twiml(self, parked_call, retriever, slot, from_client=False):
        """TwiML making the parked call ring the retriever with the real caller ID.

        The retriever is called back on the device they retrieved from, so a
        user with both a SIP phone and a web phone does not get both ringing.
        Returns None when the retriever has no reachable endpoint.
        """
        caller_id = parked_call.caller
        if not caller_id:
            logger.warning('unpark_call: call %s has no caller number', parked_call.id)
            return None
        use_client = retriever.client_enabled and (from_client or not retriever.sip_enabled)
        if not use_client and not retriever.sip_enabled:
            logger.warning('unpark_call: user %s has no enabled endpoint', retriever.username)
            return None
        settings = self.env['connect.settings'].sudo()
        api_url = settings.get_param('api_url')
        edge = settings.get_param('twilio_edge')
        status_url = urljoin(api_url, 'twilio/webhook/callstatus#e={}'.format(edge))
        record_status_url = urljoin(api_url, 'twilio/webhook/recordingstatus#e={}'.format(edge))
        refer_url = urljoin(api_url, 'twilio/webhook/sip_refer#e={}'.format(edge))
        action_url = urljoin(api_url, 'twilio/webhook/park_retrieve/{}/{}#e={}'.format(
            parked_call.id, slot, edge))
        dial_kwargs = {
            'timeout': (retriever.client_ring_timeout if use_client else retriever.sip_ring_timeout) or 30,
            'callerId': caller_id,
            'action': action_url,
        }
        if not use_client:
            dial_kwargs['referUrl'] = refer_url
        if parked_call._should_record_park_retrieval(retriever):
            dial_kwargs.update({
                'record': 'record-from-answer-dual',
                'recordingStatusCallback': record_status_url,
            })
        dial = Dial(**dial_kwargs)
        if use_client:
            client = Client(
                statusCallbackEvent='initiated answered completed',
                statusCallback=status_url)
            client.identity(retriever.get_client_identity())
            client.parameter(
                name='CallerName',
                value=parked_call.partner.name if parked_call.partner else caller_id)
            client.parameter(
                name='Partner',
                value=parked_call.partner.id if parked_call.partner else False)
            dial.append(client)
        else:
            dial.sip(
                'sip:{}{}'.format(
                    retriever.uri,
                    ';secure=true' if retriever.domain.secure_media else ''),
                statusCallbackEvent='initiated answered completed',
                statusCallback=status_url)
        response = VoiceResponse()
        response.append(dial)
        debug(self, 'unpark_call: retrieval TwiML for slot %s: %s' % (slot, str(response)))
        return response

    @api.model
    def on_park_retrieve_action(self, call_id, slot, params):
        """Dial action of the park retrieval leg.

        The parked caller was taken out of the queue to ring the retriever. If
        that call was not answered the caller must go back to their slot rather
        than be dropped.

        The action can also arrive after the agent who took the call parked it
        again — parking, retrieving and re-parking the same customer is
        ordinary use. Such an action belongs to a retrieval that is already
        over, and it must not touch the parking state the newer park has just
        written: clearing it leaves the caller waiting in a Twilio queue that
        Odoo no longer tracks, so the next retrieval falls back to the plain
        queue bridge and presents the slot number instead of the customer's
        own.
        """
        call = self.sudo().browse(call_id).exists()
        dial_status = params.get('DialCallStatus')
        debug(self, 'on_park_retrieve_action: call %s slot %s status %s' % (
            call_id, slot, dial_status))
        response = VoiceResponse()
        # A retrieval clears park_slot, so a call that has one is parked again
        # rather than being retrieved right now — whatever slot it went into.
        current_slot = call.park_slot if call else False
        if current_slot:
            debug(self, 'on_park_retrieve_action: call %s is parked in slot %s, '
                        'ignoring the stale action of slot %s' % (
                            call_id, current_slot, slot))
            response.enqueue('park-%s' % current_slot)
            return response
        if dial_status == 'completed' or not slot:
            if call:
                call.write({'park_slot': False, 'park_call_sid': False})
            response.hangup()
            return response
        # Not answered: put the caller back into the parking slot.
        if call:
            call.write({'park_slot': slot, 'parked_at': fields.Datetime.now()})
        response.enqueue('park-%s' % slot)
        return response
