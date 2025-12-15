# -*- coding: utf-8 -*-
import logging
import jwt
from datetime import datetime, timedelta
from functools import wraps

from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Public key for JWT RS256 verification
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApghblBkWHc4sGxTcKRvb
sSs70Z9TMcGNZVJhZbPB6/WKREBrfNOJjz06pfae8iMk8LSnYlGLcKw6lVutpBce
FIMifmYQJRmgFbNqZ2M+Ew8me8o6gF2k2gwhNT6yo8avq2iFd9cC/Lbb+p7M3Lkn
vVz/RXHJ4QRvS+xbzfSsyE9E1CpYus8MccapuE3Jq4g6dWWU5Pk7bC5jJN3cpbcf
c2r29Wjh3dGw45tx54IQ7kz56z4uHPQZ6UKaZZDLhFxYq59rE3rrYi1m4YZIs36E
PXsj0dij391KNtMmUZ/qSNqYII6eprKiHjZNVpANb2ee32xJTq2fIPSvw4qILOn/
nwIDAQAB
-----END PUBLIC KEY-----"""

TRIAL_DAYS = 30


class ConnectLicense(models.AbstractModel):
    """
    License validation and management for Connect OPL-1 modules.
    Handles JWT token validation and 30-day trial period.
    """
    _name = 'connect.license'
    _description = 'Connect License Manager'

    @api.model
    def _get_license_token(self):
        """Get license token from settings."""
        return self.env['connect.settings'].sudo().get_param('license_token', default='')

    @api.model
    def _get_database_uuid(self):
        """Get database UUID from system parameters."""
        return self.env['ir.config_parameter'].sudo().get_param('database.uuid', default='')

    @api.model
    def validate_token(self, token):
        """
        Validate JWT token with RS256 algorithm.

        Returns:
            dict: Decoded payload if valid
            None: If token is invalid
        """
        if not token:
            return None

        try:
            payload = jwt.decode(
                token,
                PUBLIC_KEY,
                algorithms=['RS256'],
                options={'verify_signature': True}
            )

            # Verify issuer
            if payload.get('issuer') != 'oduist.com':
                _logger.warning('Invalid token issuer: %s', payload.get('issuer'))
                return None

            # Verify instance UUID
            db_uuid = self._get_database_uuid()
            if payload.get('instance_uid') != db_uuid:
                _logger.warning('Token instance_uid mismatch. Expected: %s, Got: %s',
                              db_uuid, payload.get('instance_uid'))
                return None

            # Verify expiration
            expire_timestamp = payload.get('expire')
            if expire_timestamp and datetime.now().timestamp() > expire_timestamp:
                _logger.warning('Token expired at %s',
                              datetime.fromtimestamp(expire_timestamp))
                return None

            return payload

        except jwt.ExpiredSignatureError:
            _logger.warning('Token signature expired')
            return None
        except jwt.InvalidTokenError as e:
            _logger.warning('Invalid token: %s', str(e))
            return None
        except Exception as e:
            _logger.error('Error validating token: %s', str(e))
            return None

    @api.model
    def is_trial_valid(self, module_name='connect'):
        """
        Check if trial period is still valid (30 days from installation).

        Args:
            module_name: Name of the module to check

        Returns:
            tuple: (is_valid: bool, days_left: int)
        """
        module = self.env['ir.module.module'].sudo().search([('name', '=', module_name)], limit=1)

        if not module:
            # Module not found, consider trial invalid
            return False, 0

        install_date = module.create_date
        now = datetime.now()
        days_passed = (now - install_date).days
        days_left = TRIAL_DAYS - days_passed

        is_valid = days_left > 0

        return is_valid, max(0, days_left)

    @api.model
    def get_license_status(self, module_name='connect'):
        """
        Get comprehensive license status for a module.

        Returns:
            dict: {
                'status': 'trial_active' | 'trial_expired' | 'licensed' | 'invalid_token',
                'days_left': int (for trial),
                'expire_date': datetime (for licensed),
                'modules': list (for licensed),
                'partner_name': str (for licensed),
                'message': str (user-friendly message)
            }
        """
        token = self._get_license_token()

        # Try to validate token first
        if token:
            payload = self.validate_token(token)
            if payload:
                modules = payload.get('modules', [])
                if module_name in modules:
                    expire_timestamp = payload.get('expire')
                    expire_date = datetime.fromtimestamp(expire_timestamp) if expire_timestamp else None

                    return {
                        'status': 'licensed',
                        'expire_date': expire_date,
                        'modules': modules,
                        'partner_name': payload.get('partner_name', ''),
                        'partner_id': payload.get('partner_id', ''),
                        'type': payload.get('type', 'production'),
                        'message': _('Licensed to %s') % payload.get('partner_name', 'Unknown')
                    }
            else:
                # Token exists but invalid
                # Fall back to trial check
                pass

        # No valid token, check trial
        is_valid, days_left = self.is_trial_valid(module_name)

        if is_valid:
            return {
                'status': 'trial_active',
                'days_left': days_left,
                'message': _('Trial: %d days remaining') % days_left
            }
        else:
            return {
                'status': 'trial_expired',
                'days_left': 0,
                'message': _('Trial expired. Please register your copy.')
            }

    @api.model
    def check_license(self, module_name):
        """
        Check if user has access to a specific module.
        Raises UserError if no valid license found.

        Args:
            module_name: Name of the module to check

        Raises:
            UserError: If license is invalid or expired
        """
        status = self.get_license_status(module_name)

        # For now, we don't block functionality, just inform
        # In future, you can uncomment the following to block:
        # if status['status'] not in ['trial_active', 'licensed']:
        #     raise UserError(_(
        #         'License required for module "%s".\n\n'
        #         'Your trial period has expired. Please obtain a valid license token.\n\n'
        #         'Contact: oduist.com'
        #     ) % module_name)

        return status


def _license(module='connect'):
    """
    Decorator to check license for specific module before executing method.

    Usage:
        from odoo.addons.connect.models.license import _license

        class MyModel(models.Model):
            _name = 'my.model'

            @_license(module='connect_crm')
            def action_call(self):
                # This method requires connect_crm license
                pass

    Args:
        module: Name of the module to check license for

    Raises:
        UserError: If license is not valid for the specified module
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Check license
            license_manager = self.env['connect.license']
            status = license_manager.get_license_status(module)

            # Block if trial expired and no valid license
            if status['status'] == 'trial_expired':
                raise UserError(_(
                    'License required for module "%s".\n\n'
                    'Your trial period has expired. Please obtain a valid license token '
                    'from oduist.com and enter it in Connect Settings.\n\n'
                    'Status: %s'
                ) % (module, status['message']))

            # If licensed, check if module is in the licensed modules list
            if status['status'] == 'licensed':
                if module not in status.get('modules', []):
                    raise UserError(_(
                        'License required for module "%s".\n\n'
                        'Your license does not include this module. '
                        'Please upgrade your license at oduist.com.\n\n'
                        'Currently licensed modules: %s'
                    ) % (module, ', '.join(status.get('modules', []))))

            # Execute the original function
            return func(self, *args, **kwargs)

        return wrapper
    return decorator
