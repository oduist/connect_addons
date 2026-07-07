"""Migrate EL routing from connect.sip_trunk to connect.elevenlabs_agent.

Before 1.0.7 the chain was: exten/number -> connect.sip_trunk -> connect.elevenlabs_agent
After 1.0.7:
  * extensions point at the agent directly (dst = connect.elevenlabs_agent);
  * numbers no longer have an 'elevenlabs_agent' destination — inbound DIDs
    reach an agent via a connect.exten(number -> agent) resolved by
    domain.route_call, so we repoint numbers by creating that extension and
    clearing their old trunk destination.
SIP routing data (virtual EL phone-number UID, allowed IPs) moves from trunk to agent.
"""
import logging

from odoo import SUPERUSER_ID, api

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

    # 3. Repoint numbers that routed to an agent-via-trunk onto the agent using
    #    the new mechanism: a connect.exten(number -> agent) resolved by
    #    domain.route_call. The old destination='elevenlabs_agent' value and the
    #    connect.number.elevenlabs_agent field were removed in this release, so
    #    they must NOT be written. Clearing the trunk destination also restores
    #    the number's voice webhook (native trunk attach bypasses it); the
    #    Twilio-side detach may still need a manual number Sync.
    cr.execute(
        """
        SELECT n.id, n.phone_number, t.elevenlabs_agent
          FROM connect_number n
          JOIN connect_sip_trunk t ON n.sip_trunk = t.id
         WHERE n.destination = 'sip_trunk'
           AND t.elevenlabs_agent IS NOT NULL
        """
    )
    rows = cr.fetchall()
    if rows:
        env = api.Environment(cr, SUPERUSER_ID, {})
        Exten = env["connect.exten"].with_context(
            skip_elevenlabs=True, skip_twilio_sync=True)
        for _number_id, phone_number, agent_id in rows:
            if not phone_number:
                continue
            try:
                existing = Exten.search([("number", "=", phone_number)], limit=1)
                if existing:
                    if not existing.dst:
                        existing.write({
                            "model": "connect.elevenlabs_agent",
                            "res_id": agent_id,
                        })
                else:
                    Exten.create({
                        "number": phone_number,
                        "model": "connect.elevenlabs_agent",
                        "res_id": agent_id,
                    })
            except Exception as e:
                logger.warning(
                    "Could not route number %s to agent %s via extension: %s",
                    phone_number, agent_id, e)
        cr.execute(
            "UPDATE connect_number SET destination = NULL, sip_trunk = NULL "
            "WHERE id IN %s",
            (tuple(r[0] for r in rows),),
        )
        logger.info("Repointed %d number(s) to agent via extension.", len(rows))

    # 4. Drop now-orphan EL columns on connect_sip_trunk so they cannot drift.
    for col in ("elevenlabs_agent", "el_virtual_number_uid", "el_inbound_allowed_ips"):
        if _column_exists(cr, "connect_sip_trunk", col):
            cr.execute(f"ALTER TABLE connect_sip_trunk DROP COLUMN {col}")
            logger.info("Dropped orphan column connect_sip_trunk.%s", col)
