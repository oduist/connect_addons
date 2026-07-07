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
        # Make one query to get all records.
        recordings = self.env['connect.recording'].search([('call', 'in', [k.id for k in self])])
        for rec in self:
            recording = recordings.filtered(lambda x: x.call.id == rec.id)
            if recording:
                # Take the last recording when multiple are attached to one call.
                recording = max(recording, key=lambda x: x.id)
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
        """Add a user to the transferred_users field when a transfer is initiated."""
        self.ensure_one()
        if user and hasattr(user, 'id'):
            current_transfer_ids = self.transferred_users.ids
            if user.id not in current_transfer_ids:
                self.transferred_users = [(4, user.id)]
                if hasattr(self.__class__, '_webhook_expectations'):
                    call_key = f"call_{self.id}"
                    expectations = self.__class__._webhook_expectations.get(call_key, {})
                    if 'ring_group' in expectations:
                        ring_expectation = expectations['ring_group']
                        current_expected = ring_expectation.get('expected_count', 0)
                        if current_expected > 1:
                            new_expected = current_expected - 1
                            ring_expectation['expected_count'] = new_expected
                            logger.info(f"Call {self.id}: Reduced ring_group expectation from {current_expected} to {new_expected} due to transfer")
                            all_call_sids = list(ring_expectation.get('call_sid_states', {}).keys())
                            terminal_sids = [sid for sid, state in ring_expectation.get('call_sid_states', {}).items() if state.get('terminal', False)]
                            if len(all_call_sids) >= new_expected and len(terminal_sids) >= new_expected:
                                logger.info(f"Call {self.id}: ring_group expectation now fulfilled with reduced count - clearing expectation")
                                del expectations['ring_group']
                                if not expectations:
                                    del self.__class__._webhook_expectations[call_key]
                self._set_webhook_expectation('transfer', {
                    'expected_count': 1,
                    'received_count': 0,
                    'target_user_id': user.id,
                    'target_user_login': user.login
                })
                logger.info(f"Call {self.id}: Transfer initiated to {user.login} (added to transferred_users)")
                if not self.call_pattern:
                    detected_pattern = self._detect_call_pattern()
                    if detected_pattern:
                        self.call_pattern = detected_pattern

    def store_transfer_context(self, dial_call_sid, target_user):
        """Store temporary transfer context for webhook processing."""
        self.ensure_one()
        if not dial_call_sid or not target_user:
            return
        current_context = self.transfer_context or {}
        current_context[dial_call_sid] = {
            'user_id': target_user.id,
            'user_login': target_user.login
        }
        self.transfer_context = current_context
        logger.info(f"Call {self.id}: Stored transfer context for {dial_call_sid} -> {target_user.login}")

    def get_transfer_target(self, dial_call_sid):
        """Get transfer target from temporary context storage."""
        self.ensure_one()
        if not self.transfer_context or not dial_call_sid:
            return None
        context_data = self.transfer_context.get(dial_call_sid)
        if context_data and 'user_id' in context_data:
            user = self.env['res.users'].sudo().browse(context_data['user_id'])
            if user.exists():
                logger.info(f"Call {self.id}: Retrieved transfer target from context: {user.login}")
                return user
        return None

    def store_external_call_leg(self, external_call_sid):
        """Store external call leg SID for outgoing call transfers."""
        self.ensure_one()
        if not external_call_sid:
            return
        current_context = self.transfer_context or {}
        current_context['_external_leg'] = external_call_sid
        self.transfer_context = current_context
        logger.info(f"Call {self.id}: Stored external call leg SID: {external_call_sid}")

    def get_external_call_leg(self):
        """Get external call leg SID for outgoing call transfers."""
        self.ensure_one()
        if not self.transfer_context:
            return None
        external_leg = self.transfer_context.get('_external_leg')
        if external_leg:
            logger.info(f"Call {self.id}: Retrieved external call leg SID: {external_leg}")
            return external_leg
        return None

    def clear_transfer_context(self):
        """Clear temporary transfer context after call processing is complete."""
        self.ensure_one()
        if self.transfer_context:
            logger.info(f"Call {self.id}: Clearing transfer context")
            self.transfer_context = None

    @classmethod
    def _cleanup_old_webhook_expectations(cls):
        """Clean up old expectations (older than 10 minutes)"""
        import datetime
        if not hasattr(cls, '_webhook_expectations'):
            return
        cutoff = fields.Datetime.now() - datetime.timedelta(minutes=10)
        to_remove = []
        for call_key, expectations in cls._webhook_expectations.items():
            empty_expectations = []
            for source, data in expectations.items():
                if data['timestamp'] < cutoff:
                    empty_expectations.append(source)
            for source in empty_expectations:
                del expectations[source]
            if not expectations:
                to_remove.append(call_key)
        for call_key in to_remove:
            del cls._webhook_expectations[call_key]
        if to_remove:
            logger.info(f"Cleaned up webhook expectations for {len(to_remove)} completed calls")

    def _set_webhook_expectation(self, source, data):
        """Set expectation for incoming webhook data with per-CallSid tracking"""
        import datetime
        import random
        if random.randint(1, 50) == 1:
            self.__class__._cleanup_old_webhook_expectations()
        if not hasattr(self.__class__, '_webhook_expectations'):
            self.__class__._webhook_expectations = {}
        call_key = f"call_{self.id}"
        if call_key not in self.__class__._webhook_expectations:
            self.__class__._webhook_expectations[call_key] = {}
        expected_call_sids = data.get('expected_call_sids', [])
        self.__class__._webhook_expectations[call_key][source] = {
            'timestamp': fields.Datetime.now(),
            'expected_count': data.get('expected_count', 1),
            'received_count': 0,
            'expected_call_sids': expected_call_sids,
            'call_sid_states': {},
            **{k: v for k, v in data.items() if k not in ['expected_count', 'received_count', 'expected_call_sids']}
        }
        if expected_call_sids:
            logger.info(f"Call {self.id}: Set {source} webhook expectation - expecting CallSids: {expected_call_sids}")
        else:
            logger.info(f"Call {self.id}: Set {source} webhook expectation - expecting {data.get('expected_count', 1)} channels")

    def _update_webhook_expectation_callsid(self, source, call_sid, call_status):
        """Update CallSid state and check if expectation is complete based on terminal states"""
        if not hasattr(self.__class__, '_webhook_expectations'):
            return
        call_key = f"call_{self.id}"
        if call_key not in self.__class__._webhook_expectations:
            return
        expectations = self.__class__._webhook_expectations[call_key]
        if source not in expectations:
            return
        expectation = expectations[source]
        is_terminal = call_status in CALL_END_STATUSES
        expectation['call_sid_states'][call_sid] = {
            'status': call_status,
            'terminal': is_terminal
        }
        logger.info(f"Call {self.id}: {source} CallSid tracking - {call_sid} status: {call_status} (terminal: {is_terminal})")
        expected_count = expectation.get('expected_count', 1)
        all_call_sids = list(expectation['call_sid_states'].keys())
        terminal_sids = [sid for sid, state in expectation['call_sid_states'].items() if state['terminal']]
        logger.info(f"Call {self.id}: {source} CallSids seen: {len(all_call_sids)}, terminal: {len(terminal_sids)}, expected: {expected_count}")
        if len(all_call_sids) >= expected_count and len(terminal_sids) >= expected_count:
            logger.info(f"Call {self.id}: {source} expectation fulfilled - all expected CallSids reached terminal states")
            del expectations[source]
            if not expectations:
                logger.info(f"Call {self.id}: All webhook expectations complete - removing call from tracking")
                del self.__class__._webhook_expectations[call_key]
        else:
            if len(all_call_sids) < expected_count:
                reason = f"waiting for {expected_count - len(all_call_sids)} more CallSids"
            else:
                non_terminal = expected_count - len(terminal_sids)
                reason = f"waiting for {non_terminal} CallSids to reach terminal state"
            logger.info(f"Call {self.id}: {source} expectation not yet fulfilled - {reason}")

    def _has_pending_webhooks(self):
        """Check if we're still expecting webhook data"""
        if not hasattr(self.__class__, '_webhook_expectations'):
            return False
        call_key = f"call_{self.id}"
        if call_key not in self.__class__._webhook_expectations:
            return False
        expectations = self.__class__._webhook_expectations[call_key]
        if not expectations:
            return False
        import datetime
        cutoff = fields.Datetime.now() - datetime.timedelta(seconds=60)
        active_expectations = False
        timed_out_sources = []
        for source, data in expectations.items():
            timestamp = data['timestamp']
            if timestamp > cutoff:
                active_expectations = True
            else:
                timed_out_sources.append(source)
        for source in timed_out_sources:
            logger.warning(f"Call {self.id}: {source} expectation timed out after 60 seconds")
            del expectations[source]
        if not expectations:
            del self.__class__._webhook_expectations[call_key]
        if timed_out_sources and not active_expectations:
            logger.warning(f"Call {self.id}: All webhook expectations timed out, proceeding with finalization")
        return active_expectations

    def _clear_webhook_expectations(self, source=None):
        """Clear webhook expectations for this call, optionally for a specific source"""
        if not hasattr(self.__class__, '_webhook_expectations'):
            return
        call_key = f"call_{self.id}"
        if call_key not in self.__class__._webhook_expectations:
            return
        if source:
            expectations = self.__class__._webhook_expectations[call_key]
            if source in expectations:
                logger.info(f"Call {self.id}: Clearing {source} webhook expectation due to pattern change")
                del expectations[source]
                if not expectations:
                    del self.__class__._webhook_expectations[call_key]
        else:
            logger.info(f"Call {self.id}: Clearing all webhook expectations")
            del self.__class__._webhook_expectations[call_key]

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
    def on_call_status(self, params):
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
    def on_vm_recording_status(self, params):
        debug(self.sudo(), 'On recording status: %s' % json.dumps(params, indent=2))
        channel = self.sudo().env['connect.channel'].search([('sid', '=', params['CallSid'])])
        if channel and channel.call:
            channel.call.write({
                'voicemail_url': params.get('RecordingUrl'),
                'voicemail_duration': int(params.get('RecordingDuration'))
            })
        return True

    @api.model
    def on_call_action(self, params):
        debug(self, 'On call action: %s' % params)
        # Check if this is a Dial action webhook with transfer completion data
        if 'DialCallSid' in params and 'DialCallStatus' in params:
            try:
                self._process_transfer_completion(params)
                logger.info(f"Successfully processed transfer completion")
            except Exception as e:
                logger.error(f"Failed to process transfer completion: {e}")
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
            # No parent call — this is a direct call to *701, just enqueue it
            debug(self, 'park_call: No ParentCallSid, enqueueing CallSid=%s' % call_sid)
            response = VoiceResponse()
            response.enqueue('park-%s' % slot)
            return response

        # Hang up the agent's SIP leg
        response = VoiceResponse()
        response.hangup()
        return response

    @api.model
    def unpark_call(self, request, params):
        """Unpark (retrieve) a call from a parking slot.

        Called when someone dials extension 701-710.
        params['ExtenNumber'] contains the slot number.
        """
        slot = params.get('ExtenNumber', '')
        debug(self, 'unpark_call: Retrieving from slot %s' % slot)

        response = VoiceResponse()
        dial = Dial(timeout=1)
        dial.queue('park-%s' % slot)
        response.append(dial)
        return response
