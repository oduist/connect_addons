# Move memory settings out of ir.config_parameter (connect_memory.*) and into
# connect.settings fields, so existing installs keep their configured values
# after the settings moved into Connect Settings.
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# old ir.config_parameter key -> (connect.settings field, type)
MAPPING = {
    "connect_memory.enabled": ("memory_enabled", "bool"),
    "connect_memory.service_url": ("memory_service_url", "char"),
    "connect_memory.token": ("memory_service_token", "char"),
    "connect_memory.default_engine": ("memory_default_engine", "char"),
    "connect_memory.outbox_retention_days": ("memory_outbox_retention_days", "int"),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    icp = env["ir.config_parameter"].sudo()
    settings = env["connect.settings"].sudo()
    for param, (field, typ) in MAPPING.items():
        raw = icp.get_param(param)
        if raw in (None, False, ""):
            continue
        if typ == "bool":
            value = str(raw) in ("1", "True", "true")
        elif typ == "int":
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
        else:
            value = raw
        settings.set_param(field, value)
        icp.set_param(param, False)
        _logger.info("connect_memory: migrated %s -> connect.settings.%s", param, field)
