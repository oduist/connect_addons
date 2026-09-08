# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Remove the event projector cron before its model disappears.

    The cron lives in a noupdate data block, so deleting it from ir_cron.xml
    does not remove it from existing databases, and after this release its
    model (connect.call.event) no longer exists.
    """
    cr.execute(
        """
        DELETE FROM ir_cron
         WHERE id IN (
            SELECT res_id
              FROM ir_model_data
             WHERE module = 'connect'
               AND model = 'ir.cron'
               AND name = 'process_call_events'
         )
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'connect'
           AND model = 'ir.cron'
           AND name = 'process_call_events'
        """
    )
