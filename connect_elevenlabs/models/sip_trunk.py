# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

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
                        old_agent.with_context(skip_sip_trunk_sync=True).write({"sip_trunk": False})
                    if new_agent:
                        prev_trunk = new_agent.sip_trunk
                        new_agent.with_context(skip_sip_trunk_sync=True).write({"sip_trunk": rec.id})
                        if prev_trunk and prev_trunk != rec:
                            prev_trunk.with_context(skip_agent_sync=True).write({"elevenlabs_agent": False})

        return res

    def _ensure_el_origination_url(self):
        """Add the ElevenLabs SIP origination URL to this trunk if not present."""
        self.ensure_one()
        EL_ORIGIN_URL = "sip:sip.rtc.elevenlabs.io;transport=tls"
        existing = self.origination_url_ids.filtered(
            lambda u: "elevenlabs.io" in (u.sip_url or "")
        )
        if existing:
            return
        self.env["connect.sip_trunk_origination_url"].create({
            "sip_trunk": self.id,
            "friendly_name": "ElevenLabs SIP Ingress (TLS)",
            "sip_url": EL_ORIGIN_URL,
            "priority": 10,
            "weight": 10,
            "enabled": True,
        })

    def _remove_el_origination_url(self):
        """Remove the ElevenLabs SIP origination URL from this trunk."""
        self.ensure_one()
        el_urls = self.origination_url_ids.filtered(
            lambda u: "elevenlabs.io" in (u.sip_url or "")
        )
        if el_urls:
            el_urls.unlink()
