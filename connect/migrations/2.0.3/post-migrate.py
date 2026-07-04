import logging

from odoo import api
from odoo.api import SUPERUSER_ID

logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Webhook controllers now use sudo() instead of a dedicated service
    account, so remove the Connect webhook user created by older versions.
    The record is noupdate, so it is not garbage collected on upgrade."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    user = env.ref('connect.user_connect_webhook', raise_if_not_found=False)
    if not user:
        return
    try:
        with env.cr.savepoint():
            user.unlink()
        logger.info('Removed obsolete Connect webhook user.')
    except Exception:
        user.active = False
        logger.warning('Could not delete the Connect webhook user, archived it instead.', exc_info=True)
