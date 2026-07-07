"""Migrate EL routing from connect.sip_trunk to connect.elevenlabs_agent.

Before 1.0.7 the chain was: exten/number -> connect.sip_trunk -> connect.elevenlabs_agent
After 1.0.7 the agent is the destination directly: exten/number -> connect.elevenlabs_agent
SIP routing data (virtual EL phone-number UID, allowed IPs) moves from trunk to agent.
"""
import logging

logger = logging.getLogger(__name__)


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return cr.fetchone() is not None


def migrate(cr, version):
    if not _column_exists(cr, "connect_sip_trunk", "elevenlabs_agent"):
        logger.info("connect_sip_trunk.elevenlabs_agent not found — nothing to migrate.")
        return

    # 1. Copy SIP routing data from each linked trunk onto its agent.
    extra_cols = []
    if _column_exists(cr, "connect_sip_trunk", "el_virtual_number_uid"):
        extra_cols.append(("el_virtual_number_uid", "el_virtual_number_uid"))
    if _column_exists(cr, "connect_sip_trunk", "el_inbound_allowed_ips"):
        extra_cols.append(("el_inbound_allowed_ips", "el_inbound_allowed_ips"))

    for agent_col, trunk_col in extra_cols:
        cr.execute(
            f"""
            UPDATE connect_elevenlabs_agent a
               SET {agent_col} = t.{trunk_col}
              FROM connect_sip_trunk t
             WHERE t.elevenlabs_agent = a.id
               AND t.{trunk_col} IS NOT NULL
               AND (a.{agent_col} IS NULL OR a.{agent_col} = '')
            """
        )
        logger.info("Copied %s from trunk to agent on %d row(s).", trunk_col, cr.rowcount)

    # 2. Repoint extensions: dst from sip_trunk(linked) -> elevenlabs_agent.
    cr.execute(
        """
        UPDATE connect_exten e
           SET model = 'connect.elevenlabs_agent',
               res_id = t.elevenlabs_agent
          FROM connect_sip_trunk t
         WHERE e.model = 'connect.sip_trunk'
           AND e.res_id = t.id
           AND t.elevenlabs_agent IS NOT NULL
        """
    )
    logger.info("Repointed %d exten(s) from sip_trunk to elevenlabs_agent.", cr.rowcount)

    # 3. Repoint numbers: destination=sip_trunk(linked) -> elevenlabs_agent.
    cr.execute(
        """
        UPDATE connect_number n
           SET destination = 'elevenlabs_agent',
               elevenlabs_agent = t.elevenlabs_agent
          FROM connect_sip_trunk t
         WHERE n.destination = 'sip_trunk'
           AND n.sip_trunk = t.id
           AND t.elevenlabs_agent IS NOT NULL
        """
    )
    logger.info("Repointed %d number(s) from sip_trunk to elevenlabs_agent.", cr.rowcount)

    # 4. Drop now-orphan EL columns on connect_sip_trunk so they cannot drift.
    for col in ("elevenlabs_agent", "el_virtual_number_uid", "el_inbound_allowed_ips"):
        if _column_exists(cr, "connect_sip_trunk", col):
            cr.execute(f"ALTER TABLE connect_sip_trunk DROP COLUMN {col}")
            logger.info("Dropped orphan column connect_sip_trunk.%s", col)
