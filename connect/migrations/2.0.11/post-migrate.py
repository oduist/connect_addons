from odoo import api
from odoo.api import SUPERUSER_ID


def migrate(cr, version):
    if not version:
        # Fresh install - nothing to move.
        return
    # Move voicemails stored in connect.call columns into the new
    # connect.voicemail model. The old columns are still present in the
    # database at this point because Odoo does not drop columns of removed
    # fields.
    cr.execute("""
        INSERT INTO connect_voicemail
            ("call", partner, caller_user, caller_number, called_number, media_url,
             duration, transcript, transcription_error, status, is_new,
             create_date, write_date, create_uid, write_uid)
        SELECT c.id, c.partner, c.caller_user, c.caller, c.called, c.voicemail_url,
               COALESCE(c.voicemail_duration, 0), c.voicemail_transcript,
               c.voicemail_transcription_error, 'completed', false,
               c.create_date, c.write_date, c.create_uid, c.write_uid
        FROM connect_call c
        WHERE c.voicemail_url IS NOT NULL
    """)
    migrated = cr.rowcount
    # Attribute the mailbox owner where the call rang exactly one PBX user.
    cr.execute("""
        UPDATE connect_voicemail vm
        SET "user" = sub.user_id
        FROM (
            SELECT rel.connect_call_id AS call_id, MIN(rel.connect_user_id) AS user_id
            FROM connect_call_connect_user_rel rel
            GROUP BY rel.connect_call_id
            HAVING COUNT(*) = 1
        ) sub
        WHERE vm."user" IS NULL AND vm."call" = sub.call_id
    """)
    # Compute the stored pbx_group_user_ids used by record rules.
    env = api.Environment(cr, SUPERUSER_ID, {})
    voicemails = env['connect.voicemail'].search([])
    if voicemails:
        voicemails._compute_pbx_group_user_ids()
    # The voicemail data now lives in connect_voicemail.
    for column in ('voicemail_url', 'voicemail_duration', 'voicemail_transcript',
                   'voicemail_transcription_error', 'voicemail_icon'):
        cr.execute('ALTER TABLE connect_call DROP COLUMN IF EXISTS {}'.format(column))
    print('Connect voicemail migration is done ({} voicemails moved).'.format(migrated))
