# -*- coding: utf-8 -*-
import logging
import os
from xml.etree import ElementTree as ET

from odoo import api, release
from odoo.api import SUPERUSER_ID

_logger = logging.getLogger(__name__)

_MODULE = 'connect_elevenlabs'
_MODEL = 'connect.elevenlabs_agent_tool'
_TABLE = 'connect_elevenlabs_agent_tool'


def _env_from_args(args):
    """Resolve an Environment from hook arguments across Odoo versions.

    Modern Odoo passes an Environment; legacy Odoo passes a cursor (and may
    also pass a registry). Keep this branch in the shared Python implementation.
    """
    if release.version_info[0] >= 17:
        return args[0]
    cursor = args[0]
    if isinstance(cursor, api.Environment):
        return cursor
    return api.Environment(cursor, SUPERUSER_ID, {})


def _seed_tool_xmlids():
    """Return ``{xml_id: name}`` for every agent tool declared in data/tools.xml.

    Parsed from the shipped data file so the heal never drifts when seed tools
    are added or removed.
    """
    tools_xml = os.path.join(os.path.dirname(__file__), 'data', 'tools.xml')
    mapping = {}
    for record in ET.parse(tools_xml).getroot().iter('record'):
        if record.get('model') != _MODEL:
            continue
        xml_id = record.get('id')
        name_field = record.find("field[@name='name']")
        if xml_id and name_field is not None and name_field.text:
            mapping[xml_id] = name_field.text.strip()
    return mapping


def relink_orphan_agent_tools(env):
    """Restore missing ir.model.data links for seed agent tools.

    A tool row can outlive its ir.model.data entry (uninstall leftovers, a
    partial database restore, manual cleanup). Without the XML-ID the next
    install/upgrade tries to INSERT the seed record from data/tools.xml and
    fails on the UNIQUE(name) constraint. Re-creating the link lets the data
    loader fall back to UPDATE instead of INSERT.

    Safe to call repeatedly and on a fresh install (the table may not exist
    yet, in which case there is nothing to heal).
    """
    cr = env.cr
    cr.execute("SELECT to_regclass(%s)", [_TABLE])
    if not cr.fetchone()[0]:
        # First install: the table does not exist yet, nothing to re-link.
        return

    relinked = 0
    for xml_id, name in _seed_tool_xmlids().items():
        cr.execute(
            """
            INSERT INTO ir_model_data (module, name, model, res_id, noupdate, create_date, write_date)
                 SELECT %(module)s, %(xml_id)s, %(model)s, t.id, FALSE, now(), now()
                   FROM connect_elevenlabs_agent_tool t
                  WHERE t.name = %(name)s
                    AND NOT EXISTS (
                            SELECT 1 FROM ir_model_data d
                             WHERE d.module = %(module)s
                               AND d.name = %(xml_id)s
                               AND d.model = %(model)s
                        )
            """,
            {'module': _MODULE, 'xml_id': xml_id, 'model': _MODEL, 'name': name},
        )
        relinked += cr.rowcount

    if relinked:
        _logger.info(
            "Re-linked %d orphaned ElevenLabs agent tool(s) to their XML-IDs.", relinked)


def pre_init_hook(*args):
    """Heal orphaned seed tools before the module data files load on install."""
    relink_orphan_agent_tools(_env_from_args(args))
