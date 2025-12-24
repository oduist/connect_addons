# -*- coding: utf-8 -*-

import hashlib
import logging
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urljoin

import jwt
import requests
from odoo import _, api, models, release
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

PUBLIC_KEY_PARAM = "oduist_license.public_key"


def rpc(url: str, request_data: dict) -> dict:
    """Perform a JSON-RPC call to the specified URL."""
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": request_data,
    }
    res = None
    try:
        res = requests.post(url, json=payload, timeout=30)
        res.raise_for_status()
        return res.json().get("result")
    except requests.exceptions.RequestException as e:
        raise ValidationError(f"License check request failed: {str(e)}")

class ConnectLicense(models.AbstractModel):
    """
    License validation and management for Connect OPL-1 modules.
    Handles JWT token validation and 30-day trial period.
    """

    _name = "connect.license"
    _description = "Connect License Manager"

    @api.model
    def _get_license_token(self):
        """Get license token from settings."""
        return (
            self.env["connect.settings"].sudo().get_param("license_token", default="")
        )

    @api.model
    def _get_database_uuid(self):
        """Get database UUID from system parameters."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("connect.instance_uid", default="")
        )

    @api.model
    def _get_public_key(self):
        """Get public key from system parameters."""
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(PUBLIC_KEY_PARAM, default="")
        )

    @api.model
    def _hash_instance_uid(self, instance_uid: str) -> str:
        """Generate SHA-256 hash of instance_uid."""
        return hashlib.sha256(instance_uid.encode()).hexdigest()

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

        public_key = self._get_public_key()
        if not public_key:
            _logger.warning("Public key not configured")
            return None

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={"verify_signature": True},
            )

            db_uuid = self._get_database_uuid()
            expected_hash = self._hash_instance_uid(db_uuid)
            if payload.get("instance_hash") != expected_hash:
                _logger.warning(
                    "Token instance hash mismatch. Expected: %s, Got: %s",
                    expected_hash,
                    payload.get("instance_hash"),
                )
                return None

            return payload

        except jwt.ExpiredSignatureError:
            _logger.warning("Token signature expired")
            return None
        except jwt.InvalidTokenError as e:
            _logger.warning("Invalid token: %s", str(e))
            return None
        except Exception as e:
            _logger.error("Error validating token: %s", str(e))
            return None

    @api.model
    def is_trial_valid(self, module_name="connect"):
        """
        Check if trial period is still valid (30 days from installation).

        Args:
            module_name: Name of the module to check

        Returns:
            tuple: (is_valid: bool, days_left: int)
        """
        module = (
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", module_name), ("state", "=", "installed")], limit=1)
        )

        if not module:
            return False, 0
        install_date = module.create_date or datetime.now() - timedelta(days=30)
        now = datetime.now()
        days_passed = (now - install_date).days
        days_left = 30 - days_passed

        is_valid = days_left > 0

        return is_valid, max(0, days_left)

    @api.model
    def get_license_status(self, module_name="connect"):
        token = self._get_license_token()
        if token:
            payload = self.validate_token(token)
            if payload:
                if payload.get("instance_type") == "demo":
                    return {"status": "demo"}
                purchased_modules = payload.get("purchased_modules", {})
                if module_name in purchased_modules:
                    module_info = purchased_modules[module_name]
                    order_id = module_info.get("order_id", "")
                    return {
                        "status": "licensed",
                        "order_id": order_id,
                        "license_type": module_info.get("license_type"),
                    }
        is_valid, days_left = self.is_trial_valid(module_name)
        if is_valid:
            return {
                "status": "trial_active",
                "days_left": days_left,
            }
        else:
            return {
                "status": "trial_expired",
                "days_left": 0,
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
        return status

    @api.model
    def update_license_status(self, raise_exc=True):
        """
        Check license status with license server.
        Updates license_token, latest_version and description for modules.
        """
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("oduist_license_server")
        )
        if not base_url:
            raise ValidationError("License server URL not configured!")

        instance_uid = (
            self.env["ir.config_parameter"].sudo().get_param("connect.instance_uid")
        )
        if not instance_uid:
            raise ValidationError("Instance UID not configured!")

        Settings = self.env["connect.settings"].sudo()
        ICP = self.env["ir.config_parameter"].sudo()

        subscribe_to_security_alerts = Settings.get_param("subscribe_to_security_alerts", default=False)
        subscribe_to_onboarding = Settings.get_param("subscribe_to_onboarding", default=False)
        subscribe_to_updates = Settings.get_param("subscribe_to_updates", default=False)

        # Get main company (first by ID)
        main_company = self.env["res.company"].search([], order="id", limit=1)
        country_code = main_company.country_id.code if main_company and main_company.country_id else None

        request_data = {
            "instance_hash": self._hash_instance_uid(instance_uid),
            "odoo_version": release.version_info[0],
        }
        
        if country_code:
            request_data["country_code"] = country_code

        if subscribe_to_security_alerts:
            request_data["subscribe_to_security_alerts"] = True
        if subscribe_to_onboarding:
            request_data["subscribe_to_onboarding"] = True
        if subscribe_to_updates:
            request_data["subscribe_to_updates"] = True
        if subscribe_to_security_alerts or subscribe_to_onboarding or subscribe_to_updates:
            admin_email = Settings.get_param("admin_email", default="")
            if admin_email:
                request_data["admin_email"] = admin_email

        license_check_url = urljoin(base_url, "/license/v2/check")
        response = {}
        try:
            response = rpc(license_check_url, request_data)
            print(1111, response)
        except requests.exceptions.RequestException as e:
            _logger.debug('License check request failed: %s', str(e))
            if raise_exc:
                raise ValidationError(f"License check request failed: {str(e)}")

        if not response and raise_exc:
            raise ValidationError("License check failed: empty response")

        if response.get("token"):
            Settings.set_param("license_token", response.get("token"))
            ICP.set_param(PUBLIC_KEY_PARAM, response.get("public_key"))

            token_data = self.validate_token(response.get("token"))
            if token_data and token_data.get("registration_number"):
                ICP.set_param(
                    "connect.registration_number", token_data.get("registration_number")
                )

            from odoo.addons.connect.models.settings import CONNECT_MODULES

            purchased_modules = token_data.get("purchased_modules", {}) if token_data else {}
            modules_data = response.get("modules", {})
            for module_name, module_info in modules_data.items():
                if module_name in CONNECT_MODULES:
                    module = (
                        self.env["ir.module.module"]
                        .sudo()
                        .search(
                            [("name", "=", module_name), ("state", "=", "installed")],
                            limit=1,
                        )
                    )
                    if module:
                        vals = {}
                        if module_info.get("latest_version"):
                            vals["latest_version"] = module_info.get("latest_version")
                        if vals:
                            module.write(vals)
        else:
            error_msg = f"License check failed: {response}"
            _logger.warning(error_msg)
            if raise_exc:
                raise ValidationError(error_msg)

    @api.model
    def buy_licenses(self, module_list):
        """
        Initiate purchase process for specified modules.

        Args:
            module_list: List of module names to purchase

        Returns:
            ir.actions.act_url action to open payment link
        """
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("oduist_license_server")
        )
        if not base_url:
            raise ValidationError("License server URL not configured!")

        instance_uid = (
            self.env["ir.config_parameter"].sudo().get_param("connect.instance_uid")
        )
        if not instance_uid:
            raise ValidationError("Instance UID not configured!")

        request_data = {
            "instance_hash": self._hash_instance_uid(instance_uid),
            "modules": module_list,
        }

        license_buy_url = urljoin(base_url, "/license/v2/buy")

        try:
            response = rpc(license_buy_url, request_data)
        except requests.exceptions.RequestException as e:
            raise ValidationError(f"License buy request failed: {str(e)}")

        if response and response.get("payment_link"):
            _logger.info(f"License buy result: {response}")
            return {
                "type": "ir.actions.act_url",
                "url": response["payment_link"],
                "target": "new",
            }
        else:
            error_msg = f"License buy failed: {response}"
            _logger.warning(error_msg)
            raise ValidationError(error_msg)


def _license(module="connect", raise_an_error=False):
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
            license_manager = self.env["connect.license"]
            status = license_manager.get_license_status(module)

            if status["status"] == "trial_expired":
                message = _(
                    'License required for module "%s".\n\n'
                    "Your trial period has expired. Please obtain a valid license token "
                    "from oduist.com and enter it in Connect Settings.\n\n"
                    "Status: %s"
                ) % (module, status["message"])
                _logger.warning(message)
                if raise_an_error:
                    raise UserError(message)
                return None

            elif status["status"] == "licensed":
                if module not in status.get("modules", []):
                    message = _(
                        'License required for module "%s".\n\n'
                        "Your license does not include this module. "
                        "Please upgrade your license at oduist.com.\n\n"
                        "Currently licensed modules: %s"
                    ) % (module, ", ".join(status.get("modules", [])))
                    _logger.warning(message)
                    if raise_an_error:
                        raise UserError(message)
                    return None

            return func(self, *args, **kwargs)

        return wrapper

    return decorator
