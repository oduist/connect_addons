import logging
import uuid

from odoo import api, models, tools

_logger = logging.getLogger(__name__)

# The base `memory` module is the COMMUNICATIONS layer: it captures real
# correspondence between an external partner and the company, on the chatter of
# ANY document (lead, order, shipment, invoice, ...), recording just the source
# record. Business EVENTS (order confirmed, shipment, ticket) are emitted by the
# domain modules (memory_sale, memory_crm, ...), not here.
EXCLUDED_MODELS = ("mail.channel",)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        try:
            self._memory_capture_message(message)
        except Exception:  # capture must never break the business operation
            _logger.exception(
                "memory: capture failed for message %s",
                getattr(message, "id", False))
        return message

    @api.model
    def _memory_enabled(self):
        return self.env["connect.memory.mixin"]._memory_enabled()

    @api.model
    @tools.ormcache()
    def _memory_company_partner_ids(self):
        """Partners that represent our OWN companies — never a memory target."""
        companies = self.env["res.company"].sudo().search([])
        partners = companies.partner_id | companies.partner_id.commercial_partner_id
        return set(partners.ids)

    def _memory_is_external(self, partner):
        """External = a real partner that is neither an internal employee
        (linked to a non-share user) nor one of our own companies."""
        if not partner:
            return False
        if partner.user_ids.filtered(lambda u: not u.share):
            return False
        if partner.commercial_partner_id.id in self._memory_company_partner_ids():
            return False
        return True

    def _memory_targets(self, message):
        """Which customer bank(s) this message belongs to, and the direction.

        - external author        -> ['in']  to the author's company
        - external recipient(s)  -> ['out'] to each recipient's company
        - neither (internal note)-> []  (skip)
        Returns a list of dicts: {commercial, direction, contacts}.
        """
        author = message.author_id
        if self._memory_is_external(author):
            return [{"commercial": author.commercial_partner_id,
                     "direction": "in", "contacts": author}]
        targets, seen = [], {}
        for partner in message.partner_ids:
            if not self._memory_is_external(partner):
                continue
            cid = partner.commercial_partner_id.id
            if cid not in seen:
                seen[cid] = {"commercial": partner.commercial_partner_id,
                             "direction": "out",
                             "contacts": self.env["res.partner"]}
                targets.append(seen[cid])
            seen[cid]["contacts"] |= partner
        return targets

    def _memory_should_capture(self, message, enforce_enabled=True):
        if not message or self._name in EXCLUDED_MODELS:
            return False
        if enforce_enabled and not self._memory_enabled():
            return False
        # real mail correspondence only — emails / chatter messages, never
        # field-tracking, system notifications or internal log notes
        if message.message_type not in ("email", "comment"):
            return False
        if not message.body:
            return False
        note = self.env.ref("mail.mt_note", raise_if_not_found=False)
        if note and message.subtype_id == note:
            return False
        # ... and there must be an external partner on either end
        return bool(self._memory_targets(message))

    def _memory_capture_message(self, message):
        if not self._memory_should_capture(message):
            return
        for target in self._memory_targets(message):
            envelope = self._memory_build_envelope(message, target)
            if envelope:
                self.env["connect.memory.mixin"]._memory_emit(envelope)

    def _memory_build_envelope(self, message, target):
        self.ensure_one()
        mixin = self.env["connect.memory.mixin"]
        commercial = target["commercial"]
        direction = target["direction"]
        contacts = target["contacts"]            # company-side external contacts
        author = message.author_id

        scope = {"commercial_partner_id": commercial.id,
                 "commercial_partner_name": commercial.display_name}
        if len(contacts) == 1 and contacts != commercial:
            scope["partner_id"] = contacts.id
            scope["partner_name"] = contacts.display_name
        internal_users = author.user_ids.filtered(
            lambda u: not u.share) if author else author
        is_internal = bool(internal_users)
        if is_internal:
            scope["user_id"] = internal_users[0].id
            scope["user_name"] = internal_users[0].name

        record_name = message.record_name or self.display_name or ""
        body = mixin._memory_clean_body(message.body)
        subject = (message.subject or "").strip()
        core = ("%s\n%s" % (subject, body)).strip() if subject else body
        if not core:
            return False
        text = ("[%s] %s" % (record_name, core)) if record_name else core
        lang = (contacts[:1].lang or commercial.lang) if contacts else commercial.lang

        outbox = self.env["connect.memory.outbox"]
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url") or ""
        occurred = message.date.isoformat() + "Z" if message.date else False
        actor_ref = ("user:%s" % internal_users[0].id) if is_internal \
            else ("partner:%s" % (author.id if author else 0))

        tags = ["domain:partner", "kind:message", "dir:%s" % direction,
                "commercial:%s" % commercial.id,
                "via:%s" % self._name, "res:%s-%s" % (self._name, self.id)]
        participants = set()
        if direction == "in" and author:
            tags.append("from:%s" % author.id)
            participants.add(author.id)
        for contact in contacts:
            if direction == "out":
                tags.append("to:%s" % contact.id)
            participants.add(contact.id)
        for pid in sorted(participants):
            tags.append("contact:%s" % pid)
        if lang:
            tags.append("lang:%s" % lang)

        return {
            "event_id": str(uuid.uuid4()),
            "event_version": 1,
            "occurred_at": occurred,
            "source": {
                "system": "odoo",
                "db": self.env.cr.dbname,
                "company_id": self.company_id.id if "company_id" in self._fields
                and self.company_id else self.env.company.id,
                "model": self._name,
                "res_id": self.id,
                "record_name": record_name,
                "url": "%s/web#id=%s&model=%s" % (base_url, self.id, self._name),
            },
            "domain": "partner",
            "kind": "message",
            "scope": scope,
            "actor": {
                "type": "user" if is_internal else "contact",
                "ref": actor_ref,
                "direction": direction,
            },
            "text": text,
            "tags": tags,
            "lang": lang or False,
            "sensitivity": "personal",
            "dedup_key": "mail.message-%s-c%s" % (message.id, commercial.id),
            "content_hash": outbox._memory_content_hash(text),
        }
