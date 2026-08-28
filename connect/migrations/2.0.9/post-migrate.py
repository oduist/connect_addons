# -*- coding: utf-8 -*-

END_STATUSES = ("completed", "busy", "failed", "no-answer", "canceled")


def migrate(cr, version):
    """Clean up after the removal of the async call event projector.

    Webhooks update calls synchronously again. Events that were still
    pending will never be projected, so calls they kept alive are closed
    from their channels' terminal statuses, and the event tables and
    projector-only columns are dropped.
    """
    # Finalize calls stuck in a live status even though every channel ended
    # (their pending events died with the projector). Mirrors the priority
    # of _set_final_call_status as closely as plain SQL allows.
    cr.execute(
        """
        UPDATE connect_call call
           SET status = CASE
                   WHEN EXISTS (SELECT 1 FROM connect_channel c
                                 WHERE c.call = call.id
                                   AND c.status = 'completed')
                       THEN 'completed'
                   WHEN EXISTS (SELECT 1 FROM connect_channel c
                                 WHERE c.call = call.id
                                   AND c.status = 'failed')
                       THEN 'failed'
                   WHEN EXISTS (SELECT 1 FROM connect_channel c
                                 WHERE c.call = call.id
                                   AND c.status = 'no-answer')
                       THEN 'no-answer'
                   WHEN EXISTS (SELECT 1 FROM connect_channel c
                                 WHERE c.call = call.id
                                   AND c.status = 'busy')
                       THEN 'busy'
                   ELSE 'no-answer'
               END,
               park_slot = NULL,
               park_call_sid = NULL
         WHERE (call.status IS NULL OR call.status NOT IN %s)
           AND EXISTS (SELECT 1 FROM connect_channel c
                        WHERE c.call = call.id)
           AND NOT EXISTS (SELECT 1 FROM connect_channel c
                            WHERE c.call = call.id
                              AND (c.status IS NULL
                                   OR c.status NOT IN %s))
        """,
        (END_STATUSES, END_STATUSES),
    )

    cr.execute("DROP TABLE IF EXISTS connect_call_event_dedup")
    cr.execute("DROP TABLE IF EXISTS connect_call_event")

    for column in (
        "projection_event_id",
        "finalization_event_id",
        "finalized_at",
        "registration_done",
        "ring_notification_done",
        "error_notification_done",
    ):
        cr.execute(
            "ALTER TABLE connect_call DROP COLUMN IF EXISTS %s" % column
        )
    for column in ("event_timestamp", "last_event_id"):
        cr.execute(
            "ALTER TABLE connect_channel DROP COLUMN IF EXISTS %s" % column
        )
