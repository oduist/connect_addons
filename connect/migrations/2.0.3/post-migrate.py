# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import fields


END_STATUSES = ("completed", "busy", "failed", "no-answer", "canceled")


def _insert_attempt(
    cr,
    call_id,
    kind,
    parent_sid,
    target_user_id=None,
    dial_call_sid=None,
    external_sid=None,
    context=None,
):
    now = fields.Datetime.now()
    cr.execute(
        """
        INSERT INTO connect_call_attempt (
            kind, call_id, parent_sid, expected_count, target_user_id,
            dial_call_sid, external_sid, state, expires_at, context,
            create_uid, create_date, write_uid, write_date
        )
        VALUES (
            %s, %s, %s, 1, %s, %s, %s, 'pending', %s, %s::jsonb,
            1, %s, 1, %s
        )
        """,
        (
            kind,
            call_id,
            parent_sid,
            target_user_id,
            dial_call_sid,
            external_sid,
            now + timedelta(hours=1),
            context,
            now,
            now,
        ),
    )


def migrate(cr, version):
    """Backfill database-backed runtime state for unfinished legacy calls."""
    cr.execute(
        """
        UPDATE connect_call
           SET finalized_at = COALESCE(finalized_at, write_date, create_date),
               registration_done = TRUE,
               ring_notification_done = TRUE,
               error_notification_done = COALESCE(has_error, FALSE)
         WHERE status IN %s
           AND finalized_at IS NULL
        """,
        (END_STATUSES,),
    )

    cr.execute(
        """
        SELECT id, call_sid, transfer_context
          FROM connect_call
         WHERE status IS NULL OR status NOT IN %s
        """,
        (END_STATUSES,),
    )
    for call_id, call_sid, context in cr.fetchall():
        context = context or {}
        for key, value in context.items():
            if key == "_external_leg":
                _insert_attempt(
                    cr, call_id, "external_leg", call_sid, external_sid=value
                )
            elif key == "_external_termination" and isinstance(value, dict):
                _insert_attempt(
                    cr,
                    call_id,
                    "external_termination",
                    call_sid,
                    dial_call_sid=value.get("transfer_recipient_sid"),
                    external_sid=value.get("external_call_sid"),
                )
            elif isinstance(value, dict) and value.get("user_id"):
                _insert_attempt(
                    cr,
                    call_id,
                    "transfer",
                    call_sid,
                    target_user_id=value["user_id"],
                    dial_call_sid=key,
                )

    cr.execute(
        """
        SELECT relation.call_id, relation.user_id, call.call_sid
          FROM connect_call_transfer_rel relation
          JOIN connect_call call ON call.id = relation.call_id
         WHERE call.status IS NULL OR call.status NOT IN %s
           AND NOT EXISTS (
               SELECT 1
                 FROM connect_call_attempt attempt
                WHERE attempt.call_id = relation.call_id
                  AND attempt.kind = 'transfer'
                  AND attempt.target_user_id = relation.user_id
           )
        """,
        (END_STATUSES,),
    )
    for call_id, user_id, call_sid in cr.fetchall():
        _insert_attempt(
            cr,
            call_id,
            "transfer",
            call_sid,
            target_user_id=user_id,
        )
