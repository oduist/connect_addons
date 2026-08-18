# -*- coding: utf-8 -*-

import hashlib
import json
import logging
from collections import defaultdict
from datetime import timedelta, timezone

from dateutil.parser import parse as parse_datetime

from odoo import SUPERUSER_ID, api, fields, models
from odoo.modules.registry import Registry


logger = logging.getLogger(__name__)

CALL_END_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}
PROJECTOR_LOCK_CLASS = 0x636E6576  # "cnev"


class PendingProjection(Exception):
    """The event references a leg which has not arrived yet."""


class CallEventDedup(models.Model):
    _name = "connect.call.event.dedup"
    _description = "Call Event Deduplication Tombstone"
    _order = "id desc"

    dedup_key = fields.Char(required=True, readonly=True, index=True)
    expires_at = fields.Datetime(required=True, readonly=True, index=True)

    _dedup_key_unique = models.Constraint(
        "UNIQUE(dedup_key)", "The call event tombstone key must be unique."
    )


class CallEvent(models.Model):
    _name = "connect.call.event"
    _description = "Twilio Call Event"
    _order = "id desc"
    _rec_name = "dedup_key"

    event_type = fields.Selection(
        [
            ("call_status", "Call Status"),
            ("dial_action", "Dial Action"),
            ("voicemail_status", "Voicemail Status"),
        ],
        required=True,
        index=True,
    )
    dedup_key = fields.Char(required=True, readonly=True, index=True)
    idempotency_token = fields.Char(readonly=True, index=True)
    call_sid = fields.Char(readonly=True, index=True)
    parent_call_sid = fields.Char(readonly=True, index=True)
    root_call_sid = fields.Char(readonly=True, index=True)
    sequence_number = fields.Integer(readonly=True, index=True)
    event_timestamp = fields.Datetime(readonly=True, index=True)
    payload = fields.Json(required=True, readonly=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        readonly=True,
        index=True,
    )
    attempts = fields.Integer(default=0, readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    processed_at = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)
    call_id = fields.Many2one(
        "connect.call", readonly=True, ondelete="set null", index=True
    )
    channel_id = fields.Many2one(
        "connect.channel", readonly=True, ondelete="set null", index=True
    )
    command_type = fields.Selection(
        [("hangup_call", "Hang up external call")], readonly=True
    )
    command_payload = fields.Json(readonly=True)
    command_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        readonly=True,
        index=True,
    )
    command_attempts = fields.Integer(default=0, readonly=True)

    _dedup_key_unique = models.Constraint(
        "UNIQUE(dedup_key)", "The Twilio event deduplication key must be unique."
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS connect_call_event_queue_idx
                ON connect_call_event (state, next_attempt_at, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS connect_call_event_aggregate_idx
                ON connect_call_event (root_call_sid, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS connect_call_event_leg_sequence_idx
                ON connect_call_event (call_sid, sequence_number, id)
            """
        )

    @api.model
    def _parse_timestamp(self, payload):
        value = payload.get("Timestamp") or payload.get("EventTimestamp")
        if not value:
            return False
        try:
            parsed = parse_datetime(value)
            if parsed.tzinfo:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except (TypeError, ValueError, OverflowError):
            logger.warning("Cannot parse Twilio event timestamp %r", value)
            return False

    @api.model
    def _dedup_key(self, event_type, payload, token=None):
        if token:
            return "%s:token:%s" % (event_type, token)
        normalized = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return "%s:payload:%s" % (event_type, digest)

    @staticmethod
    def _has_sequence(event):
        return event.payload.get("SequenceNumber") not in (None, "")

    @api.model
    def ingest(self, event_type, payload, token=None):
        """Atomically append an event without reading or updating connect.call."""
        if event_type not in dict(self._fields["event_type"].selection):
            raise ValueError("Unsupported call event type %r" % event_type)
        payload = dict(payload or {})
        call_sid = payload.get("CallSid") or payload.get("DialCallSid")
        parent_sid = payload.get("ParentCallSid")
        root_sid = parent_sid or payload.get("CallSid") or call_sid
        sequence = payload.get("SequenceNumber")
        try:
            sequence = int(sequence) if sequence not in (None, "") else None
        except (TypeError, ValueError):
            sequence = None
        event_timestamp = self._parse_timestamp(payload) or None
        dedup_key = self._dedup_key(event_type, payload, token)
        now = fields.Datetime.now()
        lock_key = int.from_bytes(
            hashlib.sha256(dedup_key.encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )

        # PostgreSQL can raise a serialization failure for two concurrent
        # INSERT .. ON CONFLICT statements under Odoo's REPEATABLE READ
        # isolation. Serialize only the identical dedup key, then check through
        # a fresh cursor so a row committed after this request's snapshot is
        # still visible.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
        self.env.cr.execute(
            "SELECT 1 FROM connect_call_event_dedup WHERE dedup_key = %s",
            (dedup_key,),
        )
        if self.env.cr.fetchone():
            return self.search([("dedup_key", "=", dedup_key)], limit=1)
        with Registry(self.env.cr.dbname).cursor() as check_cr:
            check_cr.execute(
                "SELECT 1 FROM connect_call_event_dedup WHERE dedup_key = %s",
                (dedup_key,),
            )
            if check_cr.fetchone():
                return self

        self.env.cr.execute(
            """
            INSERT INTO connect_call_event_dedup (
                dedup_key, expires_at,
                create_uid, create_date, write_uid, write_date
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedup_key) DO NOTHING
            """,
            (
                dedup_key,
                now + timedelta(days=1),
                self.env.uid,
                now,
                self.env.uid,
                now,
            ),
        )
        self.env.cr.execute(
            """
            INSERT INTO connect_call_event (
                event_type, dedup_key, idempotency_token,
                call_sid, parent_call_sid, root_call_sid,
                sequence_number, event_timestamp, payload, state, attempts,
                create_uid, create_date, write_uid, write_date
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                'pending', 0, %s, %s, %s, %s
            )
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id
            """,
            (
                event_type,
                dedup_key,
                token,
                call_sid,
                parent_sid,
                root_sid,
                sequence,
                event_timestamp,
                json.dumps(payload),
                self.env.uid,
                now,
                self.env.uid,
                now,
            ),
        )
        row = self.env.cr.fetchone()
        event = self.browse(row[0]) if row else self.search(
            [("dedup_key", "=", dedup_key)], limit=1
        )
        if row:
            self._trigger_projector_after_commit()
        return event

    @api.model
    def _trigger_projector_after_commit(self):
        db_name = self.env.cr.dbname

        def trigger():
            try:
                with Registry(db_name).cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env.ref("connect.process_call_events")._trigger()
                    cr.commit()
            except Exception:
                logger.exception("Could not trigger the call event projector")

        self.env.cr.postcommit.add(trigger)

    @api.model
    def process_pending_events(self, limit=200):
        """Project pending inbox rows in one serialized cron transaction."""
        self = self.sudo()
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, 0)", (PROJECTOR_LOCK_CLASS,)
        )
        if not self.env.cr.fetchone()[0]:
            return 0

        now = fields.Datetime.now()
        events = self.search(
            [
                ("state", "=", "pending"),
                "|",
                ("next_attempt_at", "=", False),
                ("next_attempt_at", "<=", now),
            ],
            order="id",
            limit=limit,
        )
        event_sids = set(
            events.mapped("call_sid") + events.mapped("parent_call_sid")
        )
        channels = self.env["connect.channel"].search(
            [("sid", "in", list(event_sids))]
        )
        call_by_sid = {
            channel.sid: channel.call.id
            for channel in channels
            if channel.sid and channel.call
        }
        parent_by_sid = {
            channel.sid: channel.parent_sid
            for channel in channels
            if channel.sid and channel.parent_sid
        }
        parent_by_sid.update(
            {
                event.call_sid: event.parent_call_sid
                for event in events
                if event.call_sid and event.parent_call_sid
            }
        )

        def aggregate_sid(event):
            sid = event.call_sid or event.root_call_sid
            seen = set()
            while sid and parent_by_sid.get(sid) and sid not in seen:
                seen.add(sid)
                sid = parent_by_sid[sid]
            return sid or event.root_call_sid or str(event.id)

        groups = defaultdict(lambda: self.browse())
        for event in events:
            call_id = event.call_id.id or call_by_sid.get(event.call_sid)
            call_id = call_id or call_by_sid.get(event.parent_call_sid)
            root_sid = aggregate_sid(event)
            key = "call:%s" % call_id if call_id else "sid:%s" % root_sid
            groups[key] |= event
            if root_sid and event.root_call_sid != root_sid:
                event.root_call_sid = root_sid

        processed = 0
        commands_scheduled = bool(
            self.search_count(
                [("command_state", "in", ["pending", "error"])], limit=1
            )
        )
        for group in groups.values():
            for event in group:
                event.write(
                    {
                        "state": "processing",
                        "attempts": event.attempts + 1,
                        "error_message": False,
                    }
                )
            try:
                with self.env.cr.savepoint():
                    self._project_group(group)
            except PendingProjection as exc:
                self._defer_or_fail(group, str(exc))
            except Exception as exc:
                logger.exception("Call event projection failed for %s", group.ids)
                self._defer_or_fail(group, str(exc))
            else:
                group.write(
                    {
                        "state": "done",
                        "processed_at": fields.Datetime.now(),
                        "next_attempt_at": False,
                        "error_message": False,
                    }
                )
                processed += len(group)
                commands_scheduled |= any(group.mapped("command_state"))

        self._vacuum()
        if commands_scheduled:
            self._run_commands_after_commit()
        return processed

    def _defer_or_fail(self, events, message):
        now = fields.Datetime.now()
        oldest = min(events.mapped("create_date"))
        terminal = oldest <= now - timedelta(hours=1)
        retry_at = False if terminal else now + timedelta(seconds=5)
        events.write(
            {
                "state": "error" if terminal else "pending",
                "next_attempt_at": retry_at,
                "error_message": message[:4000],
            }
        )
        if retry_at:
            self.env.ref("connect.process_call_events")._trigger(at=retry_at)

    def _project_group(self, events):
        root_sid = events[0].root_call_sid
        call = self._resolve_group_call(events, root_sid)
        call_vals = {}

        ordered = events.sorted(
            key=lambda event: (
                event.event_type != "call_status",
                bool(event.parent_call_sid),
                event.sequence_number
                if self._has_sequence(event)
                else 2**31,
                event.event_timestamp or event.create_date,
                event.id,
            )
        )
        for event in ordered:
            if event.event_type == "call_status":
                channel = self._apply_call_status_event(event, call)
                call = channel.call or call
            elif event.event_type == "dial_action":
                channel = self._apply_dial_action_event(event, call)
                call = channel.call or call
            else:
                channel = self._resolve_event_channel(event, call)
                call_vals.update(
                    {
                        "voicemail_url": event.payload.get("RecordingUrl"),
                        "voicemail_duration": int(
                            event.payload.get("RecordingDuration") or 0
                        ),
                    }
                )
            event.write(
                {
                    "call_id": call.id if call else False,
                    "channel_id": channel.id if channel else False,
                }
            )

        if not call:
            raise PendingProjection("Call has not been created yet")
        self._refresh_attempts(call, ordered)
        self._project_call(call, ordered, call_vals)

    def _resolve_group_call(self, events, root_sid):
        calls = events.mapped("call_id").exists()
        if calls:
            return calls[0]
        sids = set(events.mapped("call_sid") + events.mapped("parent_call_sid"))
        channels = self.env["connect.channel"].search([("sid", "in", list(sids))])
        calls = channels.mapped("call")
        if calls:
            return calls[0]
        root_channel = self.env["connect.channel"].search(
            [("sid", "=", root_sid)], limit=1
        )
        if root_channel:
            return self.env["connect.call"]._ensure_call_from_channel(root_channel)
        root_events = events.filtered(
            lambda event: event.event_type == "call_status"
            and not event.parent_call_sid
        )
        if root_events:
            return self.env["connect.call"].ensure_initial_call(root_events[0].payload)
        return self.env["connect.call"]

    def _resolve_event_channel(self, event, call):
        channel = self.env["connect.channel"].search(
            [("sid", "=", event.call_sid)], limit=1
        )
        if not channel or (not channel.call and not call):
            raise PendingProjection("Channel %s has not arrived yet" % event.call_sid)
        if not channel.call and call:
            channel.write({"call": call.id})
        return channel

    def _is_stale(self, channel, event):
        if not channel:
            return False
        if self._has_sequence(event):
            current_sequence = channel.sequence_number
            if event.sequence_number < current_sequence:
                return True
            if event.sequence_number > (current_sequence or 0):
                return False
        current_time = channel.event_timestamp
        event_time = event.event_timestamp or event.create_date
        if current_time and event_time < current_time:
            return True
        if current_time and event_time == current_time:
            return event.id <= (channel.last_event_id or 0)
        return False

    def _apply_call_status_event(self, event, call):
        payload = event.payload
        sid = payload.get("CallSid")
        if not sid:
            raise ValueError("Call status event has no CallSid")
        channel_model = self.env["connect.channel"]
        channel = channel_model.search([("sid", "=", sid)], limit=1)
        if self._is_stale(channel, event):
            return channel

        parent = channel_model
        parent_sid = payload.get("ParentCallSid")
        if parent_sid:
            parent = channel_model.search([("sid", "=", parent_sid)], limit=1)
            if not parent:
                raise PendingProjection("Parent channel %s has not arrived yet" % parent_sid)
            call = parent.call or call
        if not call and channel and channel.call:
            call = channel.call
        if not call and not parent_sid:
            call = self.env["connect.call"].ensure_initial_call(payload)
            channel = channel_model.search([("sid", "=", sid)], limit=1)
        if not call:
            raise PendingProjection("Call for channel %s has not arrived yet" % sid)

        vals = self._channel_vals(payload, call, parent)
        vals.update(
            {
                "call": call.id,
                "sequence_number": event.sequence_number
                if self._has_sequence(event)
                else (channel.sequence_number if channel else 0),
                "event_timestamp": event.event_timestamp or event.create_date,
                "last_event_id": event.id,
            }
        )
        if channel:
            channel.with_context(tracking_disable=True).write(vals)
        else:
            vals["sid"] = sid
            channel = channel_model.with_context(tracking_disable=True).create(vals)
        self._prepare_external_command(event, call, channel)
        return channel

    def _channel_vals(self, payload, call, parent):
        def strip_whatsapp(value):
            if isinstance(value, str) and value.startswith("whatsapp:"):
                return value.split(":", 1)[1]
            return value

        caller_raw = payload.get("Caller") or payload.get("From")
        called_raw = payload.get("Called") or payload.get("To")
        to_raw = payload.get("To")
        caller = strip_whatsapp(caller_raw)
        called = strip_whatsapp(called_raw)
        to = strip_whatsapp(to_raw)
        call_type = (
            "whatsapp"
            if any(
                isinstance(value, str) and value.startswith("whatsapp:")
                for value in (caller_raw, called_raw, to_raw)
            )
            else "phone"
        )
        vals = {
            "technical_direction": payload.get("Direction"),
            "status": payload.get("CallStatus"),
            "duration": int(payload.get("CallDuration") or 0),
            "call_type": call_type,
        }
        if caller:
            vals["caller"] = caller
        if called:
            vals["called"] = called
        if to:
            vals["to"] = to
        if payload.get("SipCallId"):
            vals["sip_call_id"] = payload["SipCallId"]
        if parent:
            vals.update({"parent_channel": parent.id, "parent_sid": parent.sid})

        caller_pbx = (
            self.env["connect.user"].get_user_by_uri(caller_raw)
            if caller_raw
            else self.env["connect.user"]
        )
        called_pbx = (
            self.env["connect.user"].get_user_by_uri(called_raw)
            if called_raw
            else self.env["connect.user"]
        )
        if caller_pbx:
            vals.update(
                {
                    "caller_pbx_user": caller_pbx.id,
                    "caller_user": caller_pbx.user.id,
                }
            )
        if called_pbx:
            vals.update(
                {
                    "called_pbx_user": called_pbx.id,
                    "called_user": called_pbx.user.id,
                }
            )

        partner = self.env["res.partner"]
        if caller_pbx and called and called.startswith(("+", "sip:+")):
            partner = self.env["res.partner"].get_partner_by_number(called)
        elif called_pbx and caller and caller.startswith("+"):
            partner = self.env["res.partner"].get_partner_by_number(caller)
        elif payload.get("Direction") == "outbound-dial" and called:
            partner = self.env["res.partner"].get_partner_by_number(called)
        elif (
            payload.get("Direction") == "inbound"
            and called
            and called.startswith("+")
            and caller
            and caller.startswith("+")
        ):
            partner = self.env["res.partner"].get_partner_by_number(caller)
        if partner:
            vals["partner"] = partner.id

        if parent:
            attempt = call.attempt_ids.filtered(
                lambda item: item.state == "pending"
                and (
                    item.dial_call_sid == payload.get("CallSid")
                    or (
                        item.target_user_id
                        and called_pbx
                        and item.target_user_id == called_pbx.user
                    )
                )
            )[:1]
            if attempt:
                vals["call_source"] = (
                    "external_dial"
                    if attempt.kind == "external_leg"
                    else attempt.kind
                )
            elif call.call_pattern == "ring_group":
                vals["call_source"] = "ring_group"
            elif called_raw and called_raw.startswith(("sip:", "client:")):
                vals["call_source"] = "direct_call"
            else:
                vals["call_source"] = "external_dial"
        return vals

    def _apply_dial_action_event(self, event, call):
        payload = event.payload
        original = self.env["connect.channel"].search(
            [("sid", "=", payload.get("CallSid"))], limit=1
        )
        call = original.call or call
        if not original or not call:
            raise PendingProjection(
                "Dial action parent %s has not arrived yet" % payload.get("CallSid")
            )
        dial_sid = payload.get("DialCallSid")
        if not dial_sid:
            return original
        channel = self.env["connect.channel"].search(
            [("sid", "=", dial_sid)], limit=1
        )
        if payload.get("ConnectActionModel") not in (None, "connect.call"):
            if payload.get("DialCallStatus") in CALL_END_STATUSES:
                action_model = payload.get("ConnectActionModel")
                kinds = (
                    ("direct_call",)
                    if action_model == "connect.user"
                    else ("direct_call", "ring_group")
                )
                call.attempt_ids.filtered(
                    lambda item: item.state == "pending"
                    and item.kind in kinds
                ).mark_resolved()
            # Leg status callbacks carry the addressing information needed to
            # create and sequence a complete channel. A generic Dial action
            # must neither manufacture a transfer leg nor regress its status.
            return channel or original

        attempt = call.attempt_ids.filtered(
            lambda item: item.dial_call_sid in (dial_sid, payload.get("CallSid"))
            and item.kind == "transfer"
        )[:1]
        target_user = attempt.target_user_id if attempt else call.transferred_users[-1:]
        pbx_user = (
            self.env["connect.user"].search(
                [("user", "=", target_user.id)], limit=1
            )
            if target_user
            else self.env["connect.user"]
        )
        vals = {
            "call": call.id,
            "parent_channel": original.id,
            "parent_sid": original.sid,
            "technical_direction": "outbound-dial",
            "status": payload.get("DialCallStatus"),
            "duration": int(payload.get("DialCallDuration") or 0),
            "call_source": "transfer",
            "last_event_id": event.id,
            "event_timestamp": event.event_timestamp or event.create_date,
        }
        if pbx_user:
            vals.update(
                {
                    "called_pbx_user": pbx_user.id,
                    "called_user": target_user.id,
                    "called": pbx_user.uri,
                    "caller": original.caller,
                }
            )
        if channel:
            channel.with_context(tracking_disable=True).write(vals)
        else:
            vals["sid"] = dial_sid
            channel = self.env["connect.channel"].with_context(
                tracking_disable=True
            ).create(vals)
        if attempt and channel.status in CALL_END_STATUSES:
            attempt.mark_resolved()
        if (
            attempt
            and channel.status == "completed"
            and not event.command_state
        ):
            external_leg = call.attempt_ids.filtered(
                lambda item: item.kind == "external_leg"
                and item.external_sid
            ).sorted("id")[-1:]
            if external_leg:
                termination = call.attempt_ids.filtered(
                    lambda item: item.kind == "external_termination"
                    and item.state == "pending"
                    and item.dial_call_sid == channel.sid
                )[:1]
                if not termination:
                    self.env["connect.call.attempt"].create(
                        {
                            "kind": "external_termination",
                            "call_id": call.id,
                            "parent_sid": original.sid,
                            "dial_call_sid": channel.sid,
                            "external_sid": external_leg.external_sid,
                        }
                    )
                self._prepare_external_command(event, call, channel)
        return channel

    def _refresh_attempts(self, call, events):
        now = fields.Datetime.now()
        for attempt in call.attempt_ids.filtered(lambda item: item.state == "pending"):
            if attempt.expires_at <= now:
                attempt.write({"state": "expired", "resolved_at": now})
                continue
            if attempt.kind == "external_leg":
                continue
            channels = call.channels
            if attempt.dial_call_sid:
                channels = channels.filtered(
                    lambda channel: channel.sid == attempt.dial_call_sid
                )
            elif attempt.target_user_id:
                channels = channels.filtered(
                    lambda channel: channel.called_user == attempt.target_user_id
                )
            elif attempt.kind in ("ring_group", "direct_call", "transfer"):
                channels = channels.filtered(
                    lambda channel: channel.call_source == attempt.kind
                )
            terminal = channels.filtered(
                lambda channel: channel.status in CALL_END_STATUSES
            )
            if len(terminal) >= attempt.expected_count:
                attempt.mark_resolved()

    def _project_call(self, call, events, extra_vals):
        channels = call.channels
        roots = channels.filtered(lambda channel: not channel.parent_channel)
        root = roots.filtered(lambda channel: channel.sid == call.call_sid)[:1]
        root = root or roots[:1]
        if not root:
            raise PendingProjection("Call %s has no root channel" % call.id)

        direction = call.direction
        if root.technical_direction == "outbound-api" or (
            root.technical_direction == "inbound" and root.caller_pbx_user
        ):
            direction = "outgoing"
        elif root.technical_direction == "inbound":
            direction = "incoming"
        if any(
            channel.parent_channel
            and (
                (
                    channel.caller_pbx_user
                    and channel.parent_channel.called_pbx_user
                )
                or (
                    channel.called_pbx_user
                    and channel.parent_channel.caller_pbx_user
                )
            )
            for channel in channels
        ) and not call.transferred_users:
            direction = "internal"

        transferred_ids = set(call.transferred_users.ids)
        transferred_ids.update(
            call.attempt_ids.filtered(
                lambda attempt: attempt.kind == "transfer" and attempt.target_user_id
            ).mapped("target_user_id").ids
        )
        user_channels = channels.filtered(
            lambda channel: channel.called_pbx_user
            and channel.called_pbx_user.user
        )
        called_user_ids = set(user_channels.mapped("called_user").ids)
        called_pbx_ids = set(user_channels.mapped("called_pbx_user").ids)
        completed = user_channels.filtered(
            lambda channel: channel.status == "completed"
        )
        initial_completed = completed.filtered(
            lambda channel: channel.called_user.id not in transferred_ids
        )
        answered_channel = (initial_completed or completed).sorted("id")[:1]
        transfer_completed = completed.filtered(
            lambda channel: channel.called_user.id in transferred_ids
        ).sorted("id")

        answered_user = answered_channel.called_user
        answered_pbx = answered_channel.called_pbx_user
        if transfer_completed:
            completed_by = transfer_completed[-1].called_user
        elif direction == "outgoing":
            caller_channels = channels.filtered(
                lambda channel: channel.caller_user
            ).sorted("id")
            completed_by = caller_channels[:1].caller_user
        else:
            completed_by = answered_user

        ring_channels = channels.filtered(
            lambda channel: channel.call_source == "ring_group"
        )
        if ring_channels:
            pattern = "ring_group"
        elif call.call_pattern:
            pattern = call.call_pattern
        elif direction in ("outgoing", "internal") or user_channels:
            pattern = "direct_call"
        else:
            pattern = False

        attempts_pending = call.attempt_ids.filtered(
            lambda attempt: attempt.state == "pending"
            and attempt.kind not in ("external_leg", "external_termination")
        )
        all_terminal = bool(channels) and all(
            channel.status in CALL_END_STATUSES for channel in channels
        )
        finalized = (
            root.status in CALL_END_STATUSES
            and all_terminal
            and not attempts_pending
        )
        statuses = set(channels.mapped("status"))
        if finalized:
            if direction == "outgoing" or answered_user:
                status = "completed"
            elif "failed" in statuses:
                status = "failed"
            elif "no-answer" in statuses:
                status = "no-answer"
            elif "busy" in statuses:
                status = "busy"
            else:
                status = "no-answer"
        elif "in-progress" in statuses:
            status = "in-progress"
        elif "ringing" in statuses:
            status = "ringing"
        else:
            status = root.status

        latest_event = events.sorted("id")[-1]
        latest_error_event = events.filtered(
            lambda event: event.payload.get("ErrorCode")
            and event.payload.get("ErrorCode") != "32009"
        ).sorted("id")
        partner = channels.filtered("partner")[:1].partner
        called = root.called_number
        if root.technical_direction == "outbound-api":
            outbound = channels.filtered(
                lambda channel: channel.technical_direction == "outbound-dial"
            )[:1]
            called = outbound.called_number or called

        vals = {
            "partner": partner.id,
            "called": called,
            "caller": root.caller_number,
            "status": status,
            "duration": sum(channels.mapped("duration") or [0]),
            "caller_pbx_user": root.caller_pbx_user.id,
            "caller_user": root.caller_user.id,
            "direction": direction,
            "call_type": root.call_type or "phone",
            "call_pattern": pattern,
            "called_pbx_users": [(6, 0, sorted(called_pbx_ids))],
            "called_users": [(6, 0, sorted(called_user_ids))],
            "transferred_users": [(6, 0, sorted(transferred_ids))],
            "answered_pbx_user": answered_pbx.id,
            "answered_user": answered_user.id,
            "completed_by_user": completed_by.id,
            "call_sid": root.sid,
            "projection_event_id": max(events.ids),
        }
        vals.update(extra_vals)
        if latest_error_event:
            payload = latest_error_event[-1].payload
            vals.update(
                {
                    "has_error": True,
                    "error_code": payload.get("ErrorCode"),
                    "error_message": payload.get("ErrorMessage"),
                }
            )
        notify_error = bool(
            latest_error_event
            and direction == "outgoing"
            and not call.error_notification_done
            and (root.caller_user or call.caller_user)
        )
        if notify_error:
            vals["error_notification_done"] = True
        first_finalization = finalized and not call.finalized_at
        if finalized:
            vals.update(
                {
                    "finalized_at": call.finalized_at or fields.Datetime.now(),
                    "finalization_event_id": max(events.ids),
                    "registration_done": True,
                    # A call that ended is not waiting in a slot any more. Left
                    # registered, it is what the next retrieval of that slot
                    # resolves to — and redirecting its dead Twilio call fails.
                    "park_slot": False,
                    "park_call_sid": False,
                }
            )
            if (
                first_finalization
                and self.env["connect.settings"].sudo().get_param(
                    "fetch_call_prices"
                )
            ):
                vals["is_price_fetched"] = False

        notify_ringing = (
            direction == "incoming"
            and not call.ring_notification_done
            and any(
                event.payload.get("CallStatus") == "initiated"
                and (event.payload.get("To") or "").startswith("sip:")
                for event in events
            )
        )
        if notify_ringing:
            vals["ring_notification_done"] = True
        changed_fields = self._changed_fields(call, vals)
        call.with_context(tracking_disable=True).write(vals)

        if first_finalization:
            call.register_call(root, latest_event.payload)
        if notify_ringing:
            root.connect_notify()
        if notify_error:
            error_payload = latest_error_event[-1].payload
            message = error_payload.get("ErrorMessage") or ""
            self.env["connect.settings"].connect_notify(
                notify_uid=(root.caller_user or call.caller_user).id,
                title="Call Error",
                message=message,
                warning=True,
            )
        call._after_call_projection(finalized, changed_fields)

    def _changed_fields(self, call, vals):
        changed = set()
        for field_name, value in vals.items():
            field = call._fields[field_name]
            current = call[field_name]
            if field.type == "many2many":
                target = set(value[0][2]) if value else set()
                if set(current.ids) != target:
                    changed.add(field_name)
            elif field.type == "many2one":
                if current.id != (value or False):
                    changed.add(field_name)
            elif current != value:
                changed.add(field_name)
        return changed

    def _prepare_external_command(self, event, call, channel):
        if channel.status not in CALL_END_STATUSES:
            return
        attempts = call.attempt_ids.filtered(
            lambda attempt: attempt.kind == "external_termination"
            and attempt.state == "pending"
            and attempt.dial_call_sid == channel.sid
            and attempt.external_sid
        )
        if not attempts:
            return
        attempt = attempts[0]
        event.write(
            {
                "command_type": "hangup_call",
                "command_payload": {
                    "call_sid": attempt.external_sid,
                    "source_event_key": event.dedup_key,
                },
                "command_state": "pending",
            }
        )
        attempt.mark_resolved()

    @api.model
    def _run_commands_after_commit(self):
        db_name = self.env.cr.dbname

        def run():
            try:
                with Registry(db_name).cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env["connect.call.event"]._execute_pending_commands()
                    cr.commit()
            except Exception:
                logger.exception("Could not run call event post-commit commands")

        self.env.cr.postcommit.add(run)

    @api.model
    def _execute_pending_commands(self):
        cutoff = fields.Datetime.now() - timedelta(hours=1)
        expired = self.sudo().search(
            [
                ("command_state", "in", ["pending", "error"]),
                ("create_date", "<=", cutoff),
            ]
        )
        if expired:
            expired.write(
                {
                    "state": "error",
                    "command_state": False,
                    "error_message": "Post-commit command retry window expired",
                }
            )
        events = self.sudo().search(
            [
                ("command_state", "in", ["pending", "error"]),
                ("create_date", ">", cutoff),
            ],
            order="id",
            limit=50,
        )
        for event in events:
            try:
                if event.command_type == "hangup_call":
                    sid = (event.command_payload or {}).get("call_sid")
                    self.env["connect.settings"].sudo().get_client().calls(sid).update(
                        status="completed"
                    )
                event.write(
                    {
                        "command_state": "done",
                        "command_attempts": event.command_attempts + 1,
                        "error_message": False,
                    }
                )
            except Exception as exc:
                event.write(
                    {
                        "command_state": "error",
                        "command_attempts": event.command_attempts + 1,
                        "error_message": str(exc)[:4000],
                    }
                )
        self._vacuum()

    @api.model
    def _vacuum(self):
        now = fields.Datetime.now()
        settings = self.env["connect.settings"].sudo()
        delete_immediately = settings.get_param("delete_processed_call_events")
        done_domain = [
            ("state", "=", "done"),
            "|",
            ("command_state", "=", False),
            ("command_state", "=", "done"),
        ]
        if not delete_immediately:
            done_domain.append(("processed_at", "<=", now - timedelta(hours=1)))
        done = self.search(done_domain)
        errors = self.search(
            [
                ("state", "=", "error"),
                ("write_date", "<=", now - timedelta(hours=1)),
            ]
        )
        (done | errors).unlink()
        self.env["connect.call.event.dedup"].sudo().search(
            [("expires_at", "<=", now)]
        ).unlink()
        self.env["connect.call.attempt"].vacuum()
