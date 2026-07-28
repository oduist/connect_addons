# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Merge duplicate Twilio legs before the SID unique constraint is applied."""
    cr.execute(
        """
        CREATE TEMP TABLE connect_channel_sid_merge (
            duplicate_id integer PRIMARY KEY,
            keeper_id integer NOT NULL
        ) ON COMMIT DROP
        """
    )
    cr.execute(
        """
        UPDATE connect_channel
           SET parent_channel = NULL,
               parent_sid = NULL
         WHERE parent_channel = id
        """
    )
    cr.execute(
        """
        INSERT INTO connect_channel_sid_merge (duplicate_id, keeper_id)
        SELECT id, keeper_id
        FROM (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY sid
                    ORDER BY
                        sequence_number DESC NULLS LAST,
                        (
                            (call IS NOT NULL)::integer
                            + (partner IS NOT NULL)::integer
                            + (caller_pbx_user IS NOT NULL)::integer
                            + (called_pbx_user IS NOT NULL)::integer
                            + (caller IS NOT NULL)::integer
                            + (called IS NOT NULL)::integer
                            + (duration IS NOT NULL)::integer
                        ) DESC,
                        id DESC
                ) AS keeper_id,
                count(*) OVER (PARTITION BY sid) AS duplicate_count
            FROM connect_channel
            WHERE sid IS NOT NULL
        ) ranked
        WHERE duplicate_count > 1 AND id != keeper_id
        """
    )
    cr.execute(
        """
        UPDATE connect_channel channel
           SET parent_channel = merge.keeper_id
          FROM connect_channel_sid_merge merge
         WHERE channel.parent_channel = merge.duplicate_id
        """
    )
    cr.execute(
        """
        UPDATE connect_channel
           SET parent_channel = NULL,
               parent_sid = NULL
         WHERE parent_channel = id
        """
    )
    cr.execute(
        """
        UPDATE connect_recording recording
           SET channel = merge.keeper_id
          FROM connect_channel_sid_merge merge
         WHERE recording.channel = merge.duplicate_id
        """
    )
    cr.execute(
        """
        INSERT INTO connect_channel_pbx_group_users_rel (
            connect_channel_id, res_users_id
        )
        SELECT DISTINCT merge.keeper_id, relation.res_users_id
          FROM connect_channel_pbx_group_users_rel relation
          JOIN connect_channel_sid_merge merge
            ON merge.duplicate_id = relation.connect_channel_id
        ON CONFLICT DO NOTHING
        """
    )
    cr.execute(
        """
        DELETE FROM connect_channel_pbx_group_users_rel relation
         USING connect_channel_sid_merge merge
         WHERE relation.connect_channel_id = merge.duplicate_id
        """
    )
    cr.execute(
        """
        DELETE FROM connect_channel channel
         USING connect_channel_sid_merge merge
         WHERE channel.id = merge.duplicate_id
        """
    )
