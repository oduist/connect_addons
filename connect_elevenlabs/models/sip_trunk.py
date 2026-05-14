# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.addons.connect.models.sip_trunk import _should_skip_twilio_sync
from elevenlabs.conversational_ai.phone_numbers.types import (
    PhoneNumbersCreateRequestBody_SipTrunk,
)
from elevenlabs.core.api_error import ApiError
from elevenlabs.types import InboundSipTrunkConfigRequestModel

logger = logging.getLogger(__name__)

TWILIO_SIP_SIGNALING_IPS = (
    "54.172.60.0/23",
    "54.244.51.0/24",
    "54.171.127.192/30",
    "35.156.191.128/25",
    "35.162.40.0/23",
    "54.65.63.192/26",
    "54.169.127.128/26",
    "54.252.254.64/26",
    "177.71.206.192/26",
)


class ElevenlabsSipTrunk(models.Model):
    _inherit = "connect.sip_trunk"

    elevenlabs_agent = fields.Many2one(
        "connect.elevenlabs_agent",
        string="ElevenLabs Agent",
        ondelete="set null",
        help="Default ElevenLabs Conversational AI agent for all inbound calls "
             "on this trunk. Numbers on this trunk with no per-number agent "
             "override will use this agent.",
    )
    el_inbound_allowed_ips = fields.Text(
        string="Inbound Allowed IPs",
        default="\n".join(TWILIO_SIP_SIGNALING_IPS),
        help="Comma- or newline-separated IP addresses / CIDR blocks that "
             "ElevenLabs will accept SIP INVITEs from. Defaults to Twilio's "
             "published SIP signaling ranges. Leave empty to allow all sources.",
    )
    el_virtual_number_uid = fields.Char(
        string="ElevenLabs Virtual Number ID",
        readonly=True,
        groups="base.group_erp_manager",
        help="ElevenLabs phone_number entity ID for agent_uid-based routing "
             "(used when no real phone number is attached to this trunk).",
    )

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get('skip_el_sync'):
            for rec in recs:
                if rec.elevenlabs_agent:
                    rec._ensure_el_origination_url()
                    if not self.env.context.get('skip_agent_sync'):
                        prev_trunk = rec.elevenlabs_agent.sip_trunk
                        rec.elevenlabs_agent.with_context(
                            skip_sip_trunk_sync=True, skip_elevenlabs=True
                        ).write({"sip_trunk": rec.id})
                        if prev_trunk and prev_trunk != rec:
                            prev_trunk.with_context(skip_agent_sync=True).write(
                                {"elevenlabs_agent": False}
                            )
        return recs

    def unlink(self):
        for rec in self:
            for num in rec.number_ids:
                if num.el_phone_number_uid:
                    num._delete_el_phone_number_safe()
        return super().unlink()

    def write(self, vals):
        el_fields = {"elevenlabs_agent", "el_inbound_allowed_ips"}
        needs_resync = bool(el_fields & set(vals.keys()))
        agent_removed = "elevenlabs_agent" in vals and not vals["elevenlabs_agent"]

        old_agents = {}
        if "elevenlabs_agent" in vals and not self.env.context.get("skip_agent_sync"):
            old_agents = {rec.id: rec.elevenlabs_agent for rec in self}

        res = super().write(vals)

        if needs_resync and not self.env.context.get("skip_el_sync"):
            for rec in self:
                if not agent_removed:
                    rec._ensure_el_origination_url()
                else:
                    rec._remove_el_origination_url()
                for num in rec.number_ids:
                    if agent_removed and not num.elevenlabs_agent:
                        if num.el_phone_number_uid:
                            num._delete_el_phone_number_safe()
                    else:
                        num._sync_el_phone_number_safe()

        if old_agents:
            for rec in self:
                old_agent = old_agents[rec.id]
                new_agent = rec.elevenlabs_agent
                if old_agent != new_agent:
                    if old_agent:
                        old_agent.with_context(skip_sip_trunk_sync=True, skip_elevenlabs=True).write({"sip_trunk": False})
                    if new_agent:
                        prev_trunk = new_agent.sip_trunk
                        new_agent.with_context(skip_sip_trunk_sync=True, skip_elevenlabs=True).write({"sip_trunk": rec.id})
                        if prev_trunk and prev_trunk != rec:
                            prev_trunk.with_context(skip_agent_sync=True).write({"elevenlabs_agent": False})

        return res

    def _el_origination_url(self):
        """Build the ElevenLabs origination SIP URL for this trunk.

        Returns None if the trunk has no phone numbers yet (URL requires the
        registered number so ElevenLabs can route to the correct agent).
        """
        self.ensure_one()
        number = self.number_ids[:1]
        if not number:
            return None
        return "sip:{}@sip.rtc.elevenlabs.io:5060;transport=tcp".format(
            number.phone_number)

    def _ensure_el_origination_url(self):
        """Add or update the ElevenLabs SIP origination URL on this trunk."""
        self.ensure_one()
        if not self.render_sip_url and self.elevenlabs_agent and self.elevenlabs_agent.agent_uid:
            self.with_context(skip_twilio_sync=True).render_sip_url = (
                "sip:{}@sip.rtc.elevenlabs.io:5060;transport=tcp".format(
                    self.elevenlabs_agent.agent_uid
                )
            )
        target_url = self._el_origination_url()
        if not target_url:
            return
        existing = self.origination_url_ids.filtered(
            lambda u: "elevenlabs.io" in (u.sip_url or "")
        )
        if existing:
            if existing[0].sip_url == target_url:
                return
            existing.with_context(skip_twilio_sync=True).unlink()
        new_url = self.env["connect.sip_trunk_origination_url"].with_context(
            skip_twilio_sync=True
        ).create({
            "sip_trunk": self.id,
            "friendly_name": "ElevenLabs SIP Ingress",
            "sip_url": target_url,
            "priority": 10,
            "weight": 10,
            "enabled": True,
        })
        if not _should_skip_twilio_sync(self.env) and self.sid:
            try:
                client = self.env["connect.settings"].get_client()
                ou = client.trunking.v1.trunks(self.sid).origination_urls.create(
                    sip_url=target_url,
                    friendly_name="ElevenLabs SIP Ingress",
                    priority=10,
                    weight=10,
                    enabled=True,
                )
                new_url.with_context(skip_twilio_sync=True).write(
                    {"origination_url_sid": ou.sid}
                )
            except Exception as e:
                logger.warning("EL origination URL Twilio create failed: %s", e)

    def _remove_el_origination_url(self):
        """Remove the ElevenLabs SIP origination URL from this trunk."""
        self.ensure_one()
        el_urls = self.origination_url_ids.filtered(
            lambda u: "elevenlabs.io" in (u.sip_url or "")
        )
        if not el_urls:
            return
        if not _should_skip_twilio_sync(self.env) and self.sid:
            try:
                client = self.env["connect.settings"].get_client()
                for url in el_urls:
                    if url.origination_url_sid:
                        client.trunking.v1.trunks(self.sid).origination_urls(
                            url.origination_url_sid
                        ).delete()
            except Exception as e:
                logger.warning("EL origination URL Twilio delete failed: %s", e)
        el_urls.with_context(skip_twilio_sync=True).unlink()

    def _ensure_el_virtual_number(self):
        """Register agent_uid as a virtual EL phone number for Exten-only routing.

        Called when the trunk has an ElevenLabs agent but no real phone numbers.
        ElevenLabs requires any SIP identifier to be registered before it will
        accept INVITEs for that identifier.
        """
        self.ensure_one()
        agent = self.elevenlabs_agent
        if not agent or not agent.agent_uid:
            return
        identifier = agent.agent_uid
        target_url = "sip:{}@sip.rtc.elevenlabs.io:5060;transport=tcp".format(identifier)

        try:
            client = self.env["connect.settings"].get_elevenlabs_client()
        except Exception as e:
            logger.warning("EL client unavailable for virtual number sync: %s", e)
            return

        if self.el_virtual_number_uid:
            try:
                client.conversational_ai.phone_numbers.update(
                    self.el_virtual_number_uid,
                    agent_id=agent.agent_uid,
                )
                if not self.render_sip_url:
                    self.with_context(skip_twilio_sync=True).render_sip_url = target_url
                return
            except ApiError as e:
                if e.status_code != 404:
                    logger.warning("EL virtual number update failed: %s", e)
                    return
                self.with_context(skip_twilio_sync=True).el_virtual_number_uid = False

        allowed_text = self.el_inbound_allowed_ips or ""
        allowed = [
            ip.strip()
            for ip in allowed_text.replace("\n", ",").split(",")
            if ip.strip()
        ]
        inbound_cfg = InboundSipTrunkConfigRequestModel(
            allowed_addresses=allowed if allowed else None,
        )

        try:
            result = client.conversational_ai.phone_numbers.create(
                request=PhoneNumbersCreateRequestBody_SipTrunk(
                    provider="sip_trunk",
                    phone_number=identifier,
                    label="ElevenLabs Exten Route ({})".format(identifier[:12]),
                    inbound_trunk_config=inbound_cfg,
                )
            )
            uid = result.phone_number_id
        except ApiError as e:
            if e.status_code == 409:
                uid = None
                try:
                    for pn in client.conversational_ai.phone_numbers.list():
                        if getattr(pn, "phone_number", None) == identifier:
                            uid = getattr(pn, "phone_number_id", None)
                            break
                except Exception as list_err:
                    logger.warning("EL phone number list failed: %s", list_err)
                if not uid:
                    logger.warning("EL virtual number conflict but could not find uid")
                    return
            else:
                logger.warning("EL virtual number create failed: %s", e)
                return

        try:
            client.conversational_ai.phone_numbers.update(uid, agent_id=agent.agent_uid)
        except Exception as e:
            logger.warning("EL virtual number agent assign failed: %s", e)

        self.with_context(skip_twilio_sync=True).write({
            "el_virtual_number_uid": uid,
            "render_sip_url": target_url if not self.render_sip_url else self.render_sip_url,
        })
        logger.info("EL virtual number registered: %s -> agent %s", identifier, agent.agent_uid)

    def _remove_el_virtual_number(self):
        """Delete the virtual EL phone number registration from ElevenLabs."""
        self.ensure_one()
        if not self.el_virtual_number_uid:
            return
        try:
            client = self.env["connect.settings"].get_elevenlabs_client()
            client.conversational_ai.phone_numbers.delete(self.el_virtual_number_uid)
            logger.info("EL virtual number deleted: %s", self.el_virtual_number_uid)
        except ApiError as e:
            if e.status_code != 404:
                logger.warning("EL virtual number delete failed: %s", e)
        except Exception as e:
            logger.warning("EL virtual number delete failed: %s", e)
        finally:
            vals = {"el_virtual_number_uid": False}
            if self.render_sip_url and "elevenlabs.io" in self.render_sip_url:
                vals["render_sip_url"] = False
            self.with_context(skip_twilio_sync=True).write(vals)
