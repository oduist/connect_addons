# -*- coding: utf-8 -*-

import logging

from elevenlabs.conversational_ai.phone_numbers.types import (
    PhoneNumbersCreateRequestBody_SipTrunk,
)
from elevenlabs.core.api_error import ApiError
from elevenlabs.types import InboundSipTrunkConfigRequestModel
from odoo import api, fields, models
from odoo.addons.connect.models.settings import debug

logger = logging.getLogger(__name__)


class ElevenlabsNumber(models.Model):
    _inherit = "connect.number"

    destination = fields.Selection(selection_add=[("elevenlabs_agent", "Agent")])
    elevenlabs_agent = fields.Many2one(
        "connect.elevenlabs_agent", ondelete="set null"
    )
    el_phone_number_uid = fields.Char(
        string="ElevenLabs Phone Number ID",
        readonly=True,
        groups="base.group_erp_manager",
        help="ElevenLabs phone number entity ID assigned to this number.",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_el_agent(self):
        self.ensure_one()
        return self.elevenlabs_agent or False

    def _build_el_inbound_config(self):
        self.ensure_one()
        agent = self._resolve_el_agent()
        allowed_text = (agent.el_inbound_allowed_ips or "") if agent else ""
        allowed = [
            ip.strip()
            for ip in allowed_text.replace("\n", ",").split(",")
            if ip.strip()
        ]
        return InboundSipTrunkConfigRequestModel(
            allowed_addresses=allowed if allowed else None,
        )

    def _find_el_phone_number_uid(self, client):
        """Look up an existing EL phone number entry by phone_number value."""
        self.ensure_one()
        try:
            for pn in client.conversational_ai.phone_numbers.list():
                raw = getattr(pn, "phone_number", None)
                if raw == self.phone_number:
                    return getattr(pn, "phone_number_id", None)
        except Exception as e:
            logger.warning("EL phone number list failed: %s", e)
        return None

    # ------------------------------------------------------------------
    # EL phone number lifecycle
    # ------------------------------------------------------------------

    def _sync_el_phone_number(self):
        """Create or update this number in ElevenLabs and assign the agent."""
        self.ensure_one()
        agent = self._resolve_el_agent()
        if not agent or not agent.agent_uid:
            return

        client = self.env["connect.settings"].get_elevenlabs_client()
        inbound_cfg = self._build_el_inbound_config()

        if self.el_phone_number_uid:
            try:
                client.conversational_ai.phone_numbers.update(
                    self.el_phone_number_uid,
                    agent_id=agent.agent_uid,
                    inbound_trunk_config=inbound_cfg,
                )
                debug(self, "EL phone number %s updated." % self.phone_number)
                return
            except ApiError as e:
                if e.status_code != 404:
                    raise
                # Number was deleted on EL side — recreate below.
                self.with_context(skip_el_sync=True).write(
                    {"el_phone_number_uid": False}
                )

        try:
            result = client.conversational_ai.phone_numbers.create(
                request=PhoneNumbersCreateRequestBody_SipTrunk(
                    provider="sip_trunk",
                    phone_number=self.phone_number,
                    label=self.friendly_name or self.phone_number,
                    inbound_trunk_config=inbound_cfg,
                )
            )
            uid = result.phone_number_id
        except ApiError as e:
            if e.status_code != 409:
                raise
            # Number already registered in EL — find and reuse its ID.
            uid = self._find_el_phone_number_uid(client)
            if not uid:
                raise
        self.with_context(skip_el_sync=True).write({"el_phone_number_uid": uid})

        client.conversational_ai.phone_numbers.update(
            uid,
            agent_id=agent.agent_uid,
        )
        debug(self, "EL phone number %s created and agent assigned." % self.phone_number)

    def _sync_el_phone_number_safe(self):
        try:
            self._sync_el_phone_number()
        except Exception as e:
            logger.exception(
                "EL phone number sync failed for %s: %s", self.phone_number, e
            )

    def _delete_el_phone_number(self):
        self.ensure_one()
        if not self.el_phone_number_uid:
            return
        try:
            client = self.env["connect.settings"].get_elevenlabs_client()
            client.conversational_ai.phone_numbers.delete(self.el_phone_number_uid)
            debug(self, "EL phone number %s deleted." % self.phone_number)
        except ApiError as e:
            if e.status_code != 404:
                raise
        finally:
            self.with_context(skip_el_sync=True).write({"el_phone_number_uid": False})

    def _delete_el_phone_number_safe(self):
        try:
            self._delete_el_phone_number()
        except Exception as e:
            logger.warning(
                "EL phone number delete failed for %s: %s", self.phone_number, e
            )

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    _EL_SYNC_FIELDS = {"destination", "elevenlabs_agent", "phone_number", "friendly_name"}

    def write(self, vals):
        # If destination is leaving elevenlabs_agent, remove from EL first.
        if "destination" in vals and vals["destination"] != "elevenlabs_agent":
            for rec in self:
                if rec.el_phone_number_uid:
                    rec._delete_el_phone_number_safe()
            vals["el_phone_number_uid"] = False
            vals["elevenlabs_agent"] = None

        needs_el_sync = (
            bool(self._EL_SYNC_FIELDS & set(vals.keys()))
            and not self.env.context.get("skip_el_sync")
        )

        res = super().write(vals)

        if needs_el_sync:
            for rec in self:
                if rec.destination == "elevenlabs_agent" and rec._resolve_el_agent():
                    rec._sync_el_phone_number_safe()

        return res

    def unlink(self):
        for rec in self:
            if rec.el_phone_number_uid:
                rec._delete_el_phone_number_safe()
        return super().unlink()

    def action_sync_el_phone_number(self):
        """Manual sync button — create/update this number in ElevenLabs."""
        for rec in self:
            rec._sync_el_phone_number()

    # ------------------------------------------------------------------
    # Call routing
    # ------------------------------------------------------------------

    @api.model
    def route_call(self, request):
        if not self.env["oduist.license"].check_license(
            "connect_elevenlabs", silent=True
        ):
            return super().route_call(request)
        res = super().route_call(request)
        number = self.search([("phone_number", "=", request["Called"])])
        agent = number._resolve_el_agent() if number else False
        if agent and number.destination == "elevenlabs_agent":
            return agent.render(request)
        return res
