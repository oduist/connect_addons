# -*- coding: utf-8 -*-
"""
ODUIST PROPRIETARY LICENSE
Copyright (c) 2025 Oduist

This file contains license validation logic.
Modification is prohibited under Oduist Proprietary License.
See LICENSE and COPYRIGHT files for full terms.
"""

import logging
import re
from urllib.parse import urljoin
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
from twilio.twiml.voice_response import Client, Dial, VoiceResponse
from .settings import format_connect_response, debug, TWILIO_EDGES, DEFAULT_SIP_DOMAIN_SUFFIX
from .twiml import pretty_xml


logger = logging.getLogger(__name__)


class Domain(models.Model):
    _name = "connect.domain"
    _rec_name = "friendly_name"
    _description = "Twilio Domain"
    _order = "friendly_name"

    sid = fields.Char("SID", readonly=True)
    application = fields.Many2one(
        "connect.twiml",
        ondelete="restrict",
        required=True,
        default=lambda self: self.get_domain_app(),
    )
    cred_list_sid = fields.Char("Cred List SID", readonly=True)
    subdomain = fields.Char(required=True)
    domain_name = fields.Char(compute="_get_domain_name")
    edge_domains = fields.Text(compute="_get_domain_name")
    friendly_name = fields.Char(required=True)
    sip_registration = fields.Boolean("SIP Registration", readonly=True, default=True)
    secure_media = fields.Boolean(default=False)
    delete_protection = fields.Boolean(default=True)

    _sql_constrains = [
        ("uniq_subdomain", "UNIQUE(subdomain)", "This subdomain is already used!")
    ]

    def _get_domain_name(self):
        settings = self.env['connect.settings']
        edges = [v[0] for v in TWILIO_EDGES if v[0] != 'roaming']
        suffix = settings.normalized_sip_domain_suffix()
        for rec in self:
            if rec.subdomain:
                rec.domain_name = settings.format_sip_domain_name(rec.subdomain)
                if suffix == DEFAULT_SIP_DOMAIN_SUFFIX:
                    rec.edge_domains = '\n'.join([
                        settings.format_sip_edge_domain(rec.subdomain, edge)
                        for edge in edges
                    ])
                else:
                    rec.edge_domains = rec.domain_name
            else:
                rec.domain_name = ''
                rec.edge_domains = ''

    def get_domain_app(self):
        # Domain must be created.
        app = self.env["connect.twiml"].search(
            [
                ("code_type", "=", "model_method"),
                ("model", "=", "connect.domain"),
                ("method", "=", "route_call"),
            ],
            limit=1,
        )
        if not app:
            # Who removed that!?
            app = self.env["connect.twiml"].create(
                {
                    "model": "connect.domain",
                    "method": "route_call",
                    "code_type": "model_method",
                    "name": "SIP Domains calls",
                    "description": "Required application!",
                }
            )
        return app

    def create_twilio_sip_domain(self, client):
        self.ensure_one()
        region = self.env['connect.settings'].get_param('twilio_region')
        domain = client.sip.domains.create(
            friendly_name=self.friendly_name,
            domain_name=self.domain_name,
            secure=self.secure_media,
            voice_url=self.application.voice_url,
            voice_fallback_url=self.application.voice_fallback_url,
            sip_registration=True,
            voice_status_callback_url=self.application.voice_status_url,
        )
        sip_domain = client.routes.v2.sip_domains(self.domain_name).update(voice_region=region)
        # Create cred lists for domain.
        credential_list = client.sip.credential_lists.create(friendly_name=domain.sid)
        # Assotiate cred list with REGISTER.
        auth_registrations_credential_list_mapping = client.sip.domains(
            domain.sid
        ).auth.registrations.credential_list_mappings.create(
            credential_list_sid=credential_list.sid
        )
        # Assotiate cred list with INVITE.
        auth_registrations_credential_list_mapping = client.sip.domains(
            domain.sid
        ).auth.calls.credential_list_mappings.create(
            credential_list_sid=credential_list.sid
        )
        self.write(
            {
                "sid": domain.sid,
                "cred_list_sid": credential_list.sid,
            }
        )
        debug(self, "Domain {} was created".format(self.friendly_name))

        # Create SIP credentials for existing users in this domain
        self._create_user_credentials_for_domain(client)

        return domain

    def _create_user_credentials_for_domain(self, client=None):
        """Create SIP credentials in Twilio for all connect.user records related to this domain."""
        self.ensure_one()
        if not self.sid or not self.cred_list_sid:
            debug(self, "Cannot create user credentials: domain not properly created in Twilio")
            return

        client = client or self.env["connect.settings"].get_client()

        # Find all users related to this domain that have SIP enabled
        domain_users = self.env['connect.user'].search([
            ('domain', '=', self.id),
            ('sip_enabled', '=', True)
        ])

        debug(self, "Found {} SIP-enabled users for domain {}".format(len(domain_users), self.friendly_name))

        for user in domain_users:
            try:
                # Generate a new password for the user
                password = self.env['connect.user'].generate_twilio_password()

                debug(self, "Creating SIP credential for user {} in domain {}".format(user.username, self.friendly_name))
                credential = client.sip.credential_lists(
                    self.cred_list_sid
                ).credentials.create(
                    username=user.username,
                    password=password
                )

                # Update user with new SID and masked password
                user.with_context(skip_sync=True).write({
                    'sid': credential.sid,
                    'password': '*' * len(password)
                })

                debug(self, "Created SIP credential for user {}".format(user.username))

            except Exception as e:
                debug(self, "Error creating SIP credential for user {}: {}".format(
                    user.username, str(e)), level="error")

    def _import_existing_domain_by_name(self, client=None):
        """Import existing domain from Twilio by domain name (for region migration).

        This handles the case where a domain already exists in Twilio but with a different SID,
        typically when moving between regions or accounts.
        """
        self.ensure_one()
        client = client or self.env["connect.settings"].get_client()

        try:
            # Get all domains from user's Twilio account
            twilio_domains = client.sip.domains.list()

            # Find domain by domain_name
            matching_domain = None
            for domain in twilio_domains:
                if domain.domain_name == self.domain_name:
                    matching_domain = domain
                    break

            if not matching_domain:
                # Domain doesn't exist in user's account - it's used by another account
                raise ValidationError(
                    "Domain name '{}' is already used by another Twilio account. "
                    "Please choose a different subdomain.".format(self.domain_name)
                )

            debug(self, "Found existing domain {} with SID {} in Twilio account".format(
                matching_domain.domain_name, matching_domain.sid))

            # Update Odoo domain with Twilio SID
            old_sid = self.sid

            # Get credential list mappings from both REGISTER and INVITE (calls)
            register_mappings = client.sip.domains(
                matching_domain.sid
            ).auth.registrations.credential_list_mappings.list()

            calls_mappings = client.sip.domains(
                matching_domain.sid
            ).auth.calls.credential_list_mappings.list()

            # Check consistency between register and calls mappings
            if len(register_mappings) != len(calls_mappings):
                logger.warning(
                    "Domain %s has inconsistent credential list mappings: %d for REGISTER, %d for CALLS",
                    matching_domain.domain_name, len(register_mappings), len(calls_mappings)
                )

            if len(register_mappings) > 1:
                logger.warning(
                    "SIP Domain %s has multiple credential lists. Using the first one.",
                    matching_domain.domain_name
                )

            cred_list_sid = None
            if register_mappings:
                # The mapping SID IS the credential list SID (as per original sync code)
                cred_list_sid = register_mappings[0].sid
            elif calls_mappings:
                cred_list_sid = calls_mappings[0].sid

            # Update domain with new SID and credential list SID
            self.write({
                'sid': matching_domain.sid,
                'cred_list_sid': cred_list_sid,
            })

            debug(self, "Updated domain {} SID: {} -> {}".format(
                self.friendly_name, old_sid, matching_domain.sid))

            # Update domain settings in Twilio to match Odoo configuration
            self.update_twilio_domain(client)

            # Import and update SIP credentials
            if cred_list_sid:
                self._import_sip_credentials_from_twilio(client, cred_list_sid)
            else:
                debug(self, "No credential list found for domain {}".format(self.friendly_name))

        except ValidationError:
            # Re-raise validation errors (domain used by another account)
            raise
        except Exception as e:
            debug(self, "Error importing domain by name: {}".format(str(e)), level="error")
            raise ValidationError(
                "Failed to import existing domain '{}': {}".format(
                    self.domain_name, format_connect_response(e)
                )
            )

    def _import_sip_credentials_from_twilio(self, client, cred_list_sid):
        """Import SIP credentials from Twilio and sync with Odoo users (bidirectional).

        1. Import Twilio credentials and update/create Odoo users
        2. Create missing Twilio credentials for existing Odoo users
        """
        self.ensure_one()

        try:
            # Step 1: Get all credentials from Twilio credential list
            twilio_credentials = client.sip.credential_lists(cred_list_sid).credentials.list()

            debug(self, "Found {} SIP credentials in Twilio for domain {}".format(
                len(twilio_credentials), self.friendly_name))

            # Get all users for this domain
            domain_users = self.env['connect.user'].search([('domain', '=', self.id)])
            sip_enabled_users = domain_users.filtered(lambda u: u.sip_enabled)

            debug(self, "Found {} users in Odoo for domain {}, {} with SIP enabled".format(
                len(domain_users), self.friendly_name, len(sip_enabled_users)))

            # Create sets for comparison
            twilio_usernames = {cred.username for cred in twilio_credentials}
            odoo_usernames = {user.username for user in sip_enabled_users}

            # Step 2: Process Twilio credentials -> Odoo users
            for credential in twilio_credentials:
                # Find matching user in Odoo by username
                matching_user = domain_users.filtered(lambda u: u.username == credential.username)

                if matching_user:
                    # Update existing user with Twilio SID
                    old_sid = matching_user.sid
                    matching_user.with_context(skip_sync=True).write({
                        'sid': credential.sid,
                        'sip_enabled': True,
                    })
                    debug(self, "Updated user {} SID: {} -> {}".format(
                        matching_user.username, old_sid, credential.sid))
                else:
                    # Create new user in Odoo for this credential (no Twilio sync)
                    new_user = self.env['connect.user'].with_context(
                        no_twilio_create=True,
                        skip_sync=True
                    ).create({
                        'sid': credential.sid,
                        'username': credential.username,
                        'sip_enabled': True,
                        'domain': self.id,
                        'password': '*' * 12,  # Masked password
                    })
                    debug(self, "Created new user {} from Twilio credential".format(
                        new_user.username))

            # Step 3: Create missing Twilio credentials for Odoo users
            missing_in_twilio = odoo_usernames - twilio_usernames

            if missing_in_twilio:
                debug(self, "Found {} SIP-enabled Odoo users missing in Twilio: {}".format(
                    len(missing_in_twilio), list(missing_in_twilio)))

                for username in missing_in_twilio:
                    odoo_user = sip_enabled_users.filtered(lambda u: u.username == username)
                    if odoo_user:
                        try:
                            # Generate password for new Twilio credential
                            password = self.env['connect.user'].generate_twilio_password()

                            debug(self, "Creating missing Twilio credential for user {}".format(username))
                            credential = client.sip.credential_lists(cred_list_sid).credentials.create(
                                username=username,
                                password=password
                            )

                            # Update Odoo user with new SID
                            old_sid = odoo_user.sid
                            odoo_user.with_context(skip_sync=True).write({
                                'sid': credential.sid,
                                'password': '*' * len(password)  # Mask password
                            })

                            debug(self, "Created Twilio credential for user {} - SID: {} -> {}".format(
                                username, old_sid, credential.sid))

                        except Exception as e:
                            debug(self, "Error creating Twilio credential for user {}: {}".format(
                                username, str(e)), level="error")
            else:
                debug(self, "All SIP-enabled Odoo users already have Twilio credentials")

        except Exception as e:
            debug(self, "Error importing SIP credentials: {}".format(str(e)), level="error")
            # Don't fail the whole process if credential import fails
            logger.warning("Failed to import SIP credentials for domain %s: %s",
                         self.friendly_name, str(e))

    def create_domain(self, client):
        self.ensure_one()
        try:
            # Create app first if requeired.
            self.application = self.get_domain_app()
            # Create domain.
            self.create_twilio_sip_domain(client)
        except Exception as e:
            if "already exists" in str(e):
                raise ValidationError('The hostname is already used in Twilio!')
            else:
                ret = format_connect_response(e)
                raise ValidationError(ret)

    @api.model_create_multi
    def create(self, vals_list):
        rec = super().create(vals_list)
        client = self.env["connect.settings"].get_client()
        if not self.env.context.get("no_twilio_create"):
            rec.create_domain(client)
        return rec

    def unlink(self):
        for rec in self:
            if rec.delete_protection and not self.env.context.get('force_delete'):
                raise ValidationError("Remove delete protection to delete the domain!")
        # Check if twilio_auto_sync is disabled
        if not self.env["connect.settings"].get_param("twilio_auto_sync"):
            return super().unlink()

        client = self.env["connect.settings"].get_client()
        for rec in self:
            try:
                # Remove creds
                client.sip.domains(rec.sid).auth.registrations.credential_list_mappings(
                    rec.cred_list_sid
                ).delete()
                client.sip.domains(rec.sid).auth.calls.credential_list_mappings(
                    rec.cred_list_sid
                ).delete()
                debug(self, "Credential_list_mappings removed.")
                client.sip.credential_lists(rec.cred_list_sid).delete()
                debug(self, "Credential_list removed.")
                # Remove domain
                client.sip.domains(rec.sid).delete()
                debug(self, "Domain removed.")
            except Exception as e:
                if "not found" in str(e):
                    # Domain was removed from Twilio, remove here.
                    pass
                else:
                    raise ValidationError(format_connect_response(e))
        return super().unlink()

    def update_twilio_domain(self, client):
        self.ensure_one()
        region = self.env['connect.settings'].get_param('twilio_region')
        try:
            domain = client.sip.domains(self.sid)
            domain.update(
                friendly_name=self.friendly_name,
                domain_name=self.domain_name,
                secure=self.secure_media,
                voice_url=self.application.voice_url,
                voice_fallback_url=self.application.voice_fallback_url,
                voice_status_callback_url=self.application.voice_status_url,
            )
            sip_domain = client.routes.v2.sip_domains(self.domain_name).update(voice_region=region)
            debug(self, "Domain {} updated".format(self.friendly_name))
        except Exception as e:
            if "was not found" in str(e):
                logger.warning(
                    "Twilio domain %s not found, creating.", self.friendly_name
                )
                self.create_domain(client)
            elif "already exists" in str(e):
                raise ValidationError("This domain name already used in Twilio!")
            else:
                raise

    def write(self, vals):
        # Check if twilio_auto_sync is disabled
        if not self.env["connect.settings"].get_param("twilio_auto_sync"):
            return super().write(vals)

        client = self.env["connect.settings"].get_client()
        # Update only Twilio fields.
        if not (
            set(["friendly_name", "secure_media", "domain_name", "subdomain", "app"]) & set(vals.keys())
        ):
            return super().write(vals)
        res = super().write(vals)
        # Iterate over records and update twilio.
        try:
            for rec in self:
                rec.update_twilio_domain(client)
        except Exception as e:
            raise ValidationError(format_connect_response(e))
        return res

    @api.model
    def sync(self):
        """Sync domains between Odoo and Twilio.

        Rules:
        1. Do NOT import records that exist only in Twilio
        2. Create in Twilio what exists only in Odoo (handles account migration)
        3. Update what exists in both
        """
        client = self.env["connect.settings"].get_client()
        # Twilio records
        twilio_records = client.sip.domains.list()
        twilio_sids = set([k.sid for k in twilio_records])
        # Odoo records
        odoo_records = self.search([])
        odoo_sids = set(odoo_records.mapped("sid"))

        # Remove empty SIDs from Odoo records (should not happen but just in case)
        odoo_sids = {sid for sid in odoo_sids if sid}

        # Sets
        only_in_twilio = twilio_sids - odoo_sids
        debug(self, "Only in Twilio domain SIDs (ignoring): {}".format(only_in_twilio))
        only_in_odoo = odoo_sids - twilio_sids
        debug(self, "Only in Odoo domain SIDs: {}".format(only_in_odoo))
        common_recs = odoo_sids & twilio_sids
        debug(self, "Common domain SIDs: {}".format(common_recs))

        # Rule 4: Do NOT import records that exist only in Twilio
        debug(self, "Skipping import of {} domains that exist only in Twilio".format(len(only_in_twilio)))

        # Rule 5: Handle Twilio account migration - create in Twilio what exists only in Odoo
        for sid in only_in_odoo:
            odoo_domain = self.search([("sid", "=", sid)])
            if odoo_domain:
                debug(self, "Creating domain {} in Twilio account...".format(odoo_domain.friendly_name))
                try:
                    # Store old SID for logging
                    old_sid = sid
                    # This will create in Twilio and update the SID in Odoo
                    odoo_domain.create_twilio_sip_domain(client)
                    debug(self, "Domain {} migrated: old SID {}, new SID {}".format(
                        odoo_domain.friendly_name, old_sid, odoo_domain.sid))
                except Exception as e:
                    if 'already exists' in str(e):
                        debug(self, "Domain {} already exists in Twilio - checking ownership".format(odoo_domain.domain_name))
                        odoo_domain._import_existing_domain_by_name(client)
                    else:
                        raise ValidationError("Error creating domain {} in Twilio: {}".format(
                            odoo_domain.friendly_name, format_connect_response(str(e))))

        # Update what exists in both
        for sid in common_recs:
            odoo_domain = self.search([("sid", "=", sid)])
            if odoo_domain:
                try:
                    odoo_domain.update_twilio_domain(client)
                except Exception as e:
                    raise

    @api.model
    def route_call(self, request, params={}):
        debug(self, "Domain call to %s" % request.get("To"))
        if not self.env["oduist.license"].check_license('connect'):
            return "<Response><Pause length='1'/><Say>This is Oduist Connect. Your trial period is over. Please buy a license to continue.</Say><Pause length='1'/></Response>"
        # Create call + channel
        self.env["connect.call"].on_call_status(request)
        to_val = request.get("To") or ''
        # Extract number for SIP or WhatsApp channels
        found_num = self.env['connect.settings'].parse_sip_to_user(to_val)
        is_whatsapp = False
        if found_num is not None:
            pass
        elif isinstance(to_val, str) and to_val.startswith('whatsapp:'):
            found_num = to_val.split(':', 1)[1]
            is_whatsapp = True
        else:
            found_num = to_val
        exten = self.env["connect.exten"].sudo().search([("number", "=", found_num)])
        # Do not let whatsapp calls to go for external calling
        if not exten and is_whatsapp:
            return "<Response><Say>Oops</Say><Pause length='1'/><Say>Whatsapp Extension not found! Please create an extenstion for this Whatsapp number!</Say></Response>"
        if not exten:
            # Get all extensions and match by pattern.
            # TODO: Handle bad exten numbers like 70[ that cannot be used by re.match.
            all_extensions = self.env["connect.exten"].sudo().search([])
            # Handle case of extension number is defined as E1.64 (with +).
            matching_extensions = all_extensions.filtered(
                lambda x: re.match(
                    r"^{}$".format(
                        "\\" + x.number if x.number.startswith(("+", "*")) else x.number
                    ),
                    found_num,
                )
            )
            if len(matching_extensions) > 1:
                logger.error(
                    "Multiple extensions %s found for number %s",
                    matching_extensions,
                    found_num,
                )
                return "<Response><Say>Multiple extensions found. Check your dialplan. Goodbye! </Say></Response>"
            elif len(matching_extensions) == 1:
                exten = matching_extensions[0]
        if exten:
            # Render extensions dialplan
            res = exten.render(request=request, params=params)
            return res
        elif isinstance(found_num, str) and found_num.startswith("+"):
            # Decide call type (phone vs WhatsApp)
            call_type = 'whatsapp' if (isinstance(to_val, str) and to_val.startswith('whatsapp:')) else 'phone'
            if call_type == 'whatsapp':
                return self.originate_whatsapp_call(found_num, request, params=params)
            else:
                return self.originate_external_call(found_num, request, params=params)
        else:
            return "<Response><Say>Extension not found. Goodbye! </Say></Response>"

    def originate_external_call(self, number, request, params={}):
        debug(self, "Outgoing call to %s" % number)
        default_number = self.env["connect.outgoing_callerid"].search(
            [("is_default", "=", True)], limit=1
        )
        # Find the user by caller.
        user = self.env["connect.user"].get_user_by_uri(request.get("Caller"))
        if user and user.outgoing_callerid:
            callerId = user.outgoing_callerid.number
        else:
            callerId = default_number.number if default_number else False
        if not callerId:
            return "<Response><Say>You must select a default number for caller ID!</Say></Response>"
        response = VoiceResponse()
        api_url = self.env["connect.settings"].get_param("api_url")
        edge = self.env['connect.settings'].get_param('twilio_edge')
        status_url = urljoin(api_url, "twilio/webhook/callstatus#e={}".format(edge))
        record_status_url = urljoin(api_url, "twilio/webhook/recordingstatus#e={}".format(edge))
        call_duration_limit = int(self.env['connect.settings'].sudo().get_param('call_duration_limit'))
        if user.record_calls:
            dial = Dial(
                timeout=60,
                callerId=callerId,
                timeLimit=call_duration_limit,
                record="record-from-answer",
                recordingStatusCallback=record_status_url,
            )
        else:
            dial = Dial(timeout=60, callerId=callerId, timeLimit=call_duration_limit)
        dial.number(
            number,
            statusCallback=status_url,
            statusCallbackEvent="initiated answered completed",
        )
        response.append(dial)
        debug(self, "Originate external: %s" % pretty_xml(str(response)))
        return response

    def originate_whatsapp_call(self, number, request, params={}):
        """Originate a WhatsApp call using WhatsApp sender as Caller ID.
        number: E.164 without prefix (e.g., +123...)
        """
        debug(self, "Outgoing WhatsApp call to %s" % number)
        # Resolve caller's preferred WhatsApp sender
        pbx_user = self.env['connect.user'].get_user_by_uri(request.get('Caller'))
        sender = self.env['connect.whatsapp_sender'].get_default_sender(pbx_user)
        caller_number = sender.number if sender else False
        if not caller_number:
            return "<Response><Say>You must configure a WhatsApp sender!</Say></Response>"
        response = VoiceResponse()
        api_url = self.env["connect.settings"].get_param("api_url")
        edge = self.env['connect.settings'].get_param('twilio_edge')
        status_url = urljoin(api_url, "twilio/webhook/callstatus#e={}".format(edge))
        record_status_url = urljoin(api_url, "twilio/webhook/recordingstatus#e={}".format(edge))
        call_duration_limit = int(self.env['connect.settings'].sudo().get_param('call_duration_limit'))
        # Reuse recording preference from user's settings if available
        record_calls = bool(getattr(pbx_user, 'record_calls', False))
        if record_calls:
            dial = Dial(
                timeout=60,
                callerId=f"whatsapp:{caller_number}",
                timeLimit=call_duration_limit,
                record="record-from-answer",
                recordingStatusCallback=record_status_url,
            )
        else:
            dial = Dial(timeout=60, callerId=f"whatsapp:{caller_number}", timeLimit=call_duration_limit)
        dial.number(
            f"whatsapp:{number}",
            statusCallback=status_url,
            statusCallbackEvent="initiated answered completed",
        )
        response.append(dial)
        debug(self, "Originate WhatsApp: %s" % pretty_xml(str(response)))
        return response
