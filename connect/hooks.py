# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Hook called after module installation.
    Creates a record in connect.module to track installation date for trial period.
    """
    try:
        # Check if record already exists
        existing = env['connect.module'].sudo().search([('name', '=', 'connect')], limit=1)

        if not existing:
            env['connect.module'].sudo().create({
                'name': 'connect',
                'description': 'Oduist Connect - Twilio Integration for Odoo'
            })
            _logger.info('Connect module installation tracked for trial period')
        else:
            _logger.info('Connect module already tracked (reinstall)')

    except Exception as e:
        _logger.error('Error in post_init_hook: %s', str(e))


def uninstall_hook(env):
    """
    Hook called before module uninstallation.
    Removes the tracking record from connect.module.
    """
    try:
        module = env['connect.module'].sudo().search([('name', '=', 'connect')], limit=1)

        if module:
            module.unlink()
            _logger.info('Connect module uninstall: tracking record removed')

    except Exception as e:
        _logger.error('Error in uninstall_hook: %s', str(e))
