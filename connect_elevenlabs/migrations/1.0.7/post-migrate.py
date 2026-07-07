"""Migrate legacy ElevenLabs number->agent routing onto the new model.

Two legacy shapes reached an agent from a phone number; both are removed in
this release, where inbound DIDs reach an agent via a connect.exten(number ->
agent) resolved by domain.route_call:

  * ORIGINAL: connect.number.destination = 'elevenlabs_agent' with a
    connect.number.elevenlabs_agent FK.
  * INTERMEDIATE: connect.number.destination = 'sip_trunk' -> connect.sip_trunk
    -> connect.sip_trunk.elevenlabs_agent (plus SIP routing data on the trunk).

For each affected number we create the routing extension and clear the now
invalid destination (which would otherwise leave the number unroutable, or, in
the trunk case, natively attached to Twilio and bypassing the voice webhook).
The Twilio-side trunk detach may still need a manual number Sync. The orphan
EL columns are dropped afterwards so they cannot drift.
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


def _route_number_to_agent(Exten, phone_number, agent_id):
    """Ensure a connect.exten(number -> agent) exists for this DID."""
    if not phone_number or not agent_id:
        return
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


def _migrate_original_number_field(cr):
    """ORIGINAL model: connect.number.destination='elevenlabs_agent' + FK."""
    if not _column_exists(cr, "connect_number", "elevenlabs_agent"):
        return
    cr.execute(
        """
        SELECT id, phone_number, elevenlabs_agent
          FROM connect_number
         WHERE destination = 'elevenlabs_agent'
           AND elevenlabs_agent IS NOT NULL
        """
    )
    rows = cr.fetchall()
    if rows:
        Exten = api.Environment(cr, SUPERUSER_ID, {})["connect.exten"].with_context(
            skip_elevenlabs=True, skip_twilio_sync=True)
        for _number_id, phone_number, agent_id in rows:
            _route_number_to_agent(Exten, phone_number, agent_id)
        logger.info("Repointed %d number(s) from destination='elevenlabs_agent'"
                    " to agent via extension.", len(rows))
    # Clear the now-invalid destination on every such number (even without a
    # linked agent) so none is left with an orphan selection value, then drop
    # the orphan FK column.
    cr.execute(
        "UPDATE connect_number SET destination = NULL, elevenlabs_agent = NULL "
        "WHERE destination = 'elevenlabs_agent'"
    )
    cr.execute("ALTER TABLE connect_number DROP COLUMN elevenlabs_agent")
    logger.info("Dropped orphan column connect_number.elevenlabs_agent")


def _migrate_intermediate_trunk(cr):
    """INTERMEDIATE model: number -> sip_trunk -> elevenlabs_agent."""
    if not _column_exists(cr, "connect_sip_trunk", "elevenlabs_agent"):
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

    # 3. Repoint numbers that routed to an agent-via-trunk onto the agent via a
    #    connect.exten(number -> agent), and clear the trunk destination.
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
        Exten = api.Environment(cr, SUPERUSER_ID, {})["connect.exten"].with_context(
            skip_elevenlabs=True, skip_twilio_sync=True)
        for _number_id, phone_number, agent_id in rows:
            _route_number_to_agent(Exten, phone_number, agent_id)
        cr.execute(
            "UPDATE connect_number SET destination = NULL, sip_trunk = NULL "
            "WHERE id IN %s",
            (tuple(r[0] for r in rows),),
        )
        logger.info("Repointed %d number(s) from sip_trunk to agent via extension.",
                    len(rows))

    # 4. Drop now-orphan EL columns on connect_sip_trunk so they cannot drift.
    for col in ("elevenlabs_agent", "el_virtual_number_uid", "el_inbound_allowed_ips"):
        if _column_exists(cr, "connect_sip_trunk", col):
            cr.execute(f"ALTER TABLE connect_sip_trunk DROP COLUMN {col}")
            logger.info("Dropped orphan column connect_sip_trunk.%s", col)


def migrate(cr, version):
    _migrate_original_number_field(cr)
    _migrate_intermediate_trunk(cr)
