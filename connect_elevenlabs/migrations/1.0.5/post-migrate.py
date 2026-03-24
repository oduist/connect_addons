import logging

logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Link transfer_to_agent tool to agents that already have transfer rules."""
    cr.execute("""
        SELECT id FROM ir_model_data
        WHERE module = 'connect_elevenlabs'
          AND name = 'agent_tool_transfer_to_agent'
          AND model = 'connect.elevenlabs_agent_tool'
    """)
    row = cr.fetchone()
    if not row:
        logger.warning("agent_tool_transfer_to_agent XML-ID not found, skipping migration.")
        return
    tool_id = row[0]

    # Get the actual resource id from ir_model_data
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE id = %s
    """, (tool_id,))
    tool_res_id = cr.fetchone()[0]

    # Find agents that have transfer rules but lack the tool in their M2M
    cr.execute("""
        INSERT INTO connect_elevenlabs_agent_connect_elevenlabs_agent_tool_rel
            (connect_elevenlabs_agent_id, connect_elevenlabs_agent_tool_id)
        SELECT DISTINCT t.agent, %(tool_id)s
        FROM connect_elevenlabs_agent_transfer t
        WHERE t.agent IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM connect_elevenlabs_agent_connect_elevenlabs_agent_tool_rel rel
              WHERE rel.connect_elevenlabs_agent_id = t.agent
                AND rel.connect_elevenlabs_agent_tool_id = %(tool_id)s
          )
    """, {"tool_id": tool_res_id})

    count = cr.rowcount
    if count:
        logger.info("Linked transfer_to_agent tool to %d existing agent(s).", count)
