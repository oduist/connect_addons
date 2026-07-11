from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    memory_event_count = fields.Integer(
        string="Memory events", compute="_compute_memory_event_count")

    def _compute_memory_event_count(self):
        outbox = self.env["connect.memory.outbox"].sudo()
        for partner in self:
            commercial = partner.commercial_partner_id or partner
            partner.memory_event_count = outbox.search_count(
                [("commercial_partner_id", "=", commercial.id)]) \
                if commercial.id else 0

    def action_memory_events(self):
        self.ensure_one()
        commercial = self.commercial_partner_id or self
        return {
            "type": "ir.actions.act_window",
            "name": _("Memory events"),
            "res_model": "connect.memory.outbox",
            "view_mode": "list,form",
            "domain": [("commercial_partner_id", "=", commercial.id)],
            "context": {"create": False},
        }

    def action_memory_backfill(self):
        """Enqueue this customer's existing correspondence into connect.memory.outbox:
        mail.message on ANY document where the company (or its contacts) is the
        external author or a recipient. Synchronous, idempotent (dedup_key per
        message+bank). No cron — meant for a per-partner backfill from the form."""
        self.ensure_one()
        commercial = self.commercial_partner_id or self
        family = self.env["res.partner"].search(
            [("commercial_partner_id", "=", commercial.id)])
        limit = 5000
        messages = self.env["mail.message"].search(
            [("message_type", "in", ("email", "comment")),
             ("model", "!=", False),
             ("model", "not in", ("mail.channel",)),
             "|", ("author_id", "in", family.ids),
             ("partner_ids", "in", family.ids)],
            order="id", limit=limit)
        outbox = self.env["connect.memory.outbox"]
        # already in the queue (or already shipped) -> not re-created (enqueue is
        # idempotent on dedup_key+content_hash); count them separately so a second
        # click reports "0 new" instead of misleading "all queued".
        existing = set(outbox.sudo().search([
            ("commercial_partner_id", "=", commercial.id),
            ("state", "in", ("pending", "sent")),
        ]).mapped(lambda r: (r.dedup_key, r.content_hash)))
        new = already = skipped = 0
        for message in messages:
            record = self.env[message.model].browse(message.res_id) \
                if message.model in self.env else False
            if not record or not record.exists() \
                    or not hasattr(record, "_memory_targets") \
                    or not record._memory_should_capture(
                        message, enforce_enabled=False):
                skipped += 1
                continue
            matched = False
            for target in record._memory_targets(message):
                if target["commercial"].id != commercial.id:
                    continue
                envelope = record._memory_build_envelope(message, target)
                if not envelope:
                    continue
                matched = True
                key = (envelope["dedup_key"], envelope["content_hash"])
                if key in existing:
                    already += 1
                else:
                    outbox.enqueue(envelope)
                    existing.add(key)
                    new += 1
            if not matched:
                skipped += 1
        note = _("%(n)s new queued, %(a)s already in memory, %(s)s skipped.") % {
            "n": new, "a": already, "s": skipped}
        if len(messages) == limit:
            note += _(" (limited to %s per run)") % limit
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Memory backfill"), "message": note,
                       "type": "success", "sticky": False},
        }

    def action_memory_summary(self):
        """Queue a 'reflect' request about this customer. The external memory
        service answers asynchronously into connect.memory.inbox."""
        self.ensure_one()
        commercial = self.commercial_partner_id or self
        engine = self.env["connect.settings"].sudo().get_param(
            "memory_default_engine") or False
        inbox = self.env["connect.memory.inbox"].submit(
            query=_("Give a concise summary of what we know about %s.")
            % commercial.display_name,
            query_type="reflect",
            scope={
                "commercial_partner_id": commercial.id,
                "commercial_partner_name": commercial.display_name,
            },
            res_model="res.partner",
            res_id=self.id,
            engine=engine,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "connect.memory.inbox",
            "res_id": inbox.id,
            "view_mode": "form",
            "target": "new",
        }
