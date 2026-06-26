# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID
from odoo.addons.connect_elevenlabs.hooks import relink_orphan_agent_tools


def migrate(cr, version):
    """Re-link orphaned seed agent tools before data/tools.xml is loaded.

    Covers the upgrade path; the install path is handled by ``pre_init_hook``.
    Both call the same helper.
    """
    if not version:
        return
    relink_orphan_agent_tools(api.Environment(cr, SUPERUSER_ID, {}))
