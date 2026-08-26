import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# correspondence candidate domain (same gate as live capture, minus the
# external-participant test which is applied per message via _memory_targets)
BASE_DOMAIN = [
    ("message_type", "in", ("email", "comment")),
    ("model", "!=", False),
    ("model", "not in", ("mail.channel",)),
]


class MemoryBackfill(models.Model):
    """Background job that enqueues historical correspondence of ALL partners
    (mail.message on any document, from `date_from`) into connect.memory.outbox, in
    batches driven by ir.cron. Idempotent (dedup_key + tombstones), resumable
    via a message-id cursor."""

    _name = "connect.memory.backfill"
    _description = "Memory Backfill Job"
    _order = "id desc"

    date_from = fields.Date(required=True)
    date_to = fields.Date()
    batch_size = fields.Integer(default=500, required=True)
    last_message_id = fields.Integer(
        default=0, help="Cursor: last processed mail.message id.")
    state = fields.Selection(
        [("running", "Running"), ("done", "Done"), ("cancelled", "Cancelled")],
        default="running", required=True, index=True)
    estimate = fields.Integer(help="Candidate messages at creation time.")
    processed = fields.Integer()
    enqueued = fields.Integer(help="Events sent to the outbox (incl. deduped).")
    skipped = fields.Integer(help="Messages without external correspondence.")

    def _message_domain(self):
        self.ensure_one()
        domain = list(BASE_DOMAIN) + [("date", ">=", self.date_from)]
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        return domain

    def _process_batch(self):
        self.ensure_one()
        if self.state != "running":
            return 0
        messages = self.env["mail.message"].search(
            self._message_domain() + [("id", ">", self.last_message_id)],
            order="id asc", limit=self.batch_size)
        if not messages:
            self.state = "done"
            return 0
        outbox = self.env["connect.memory.outbox"]
        enq = skip = 0
        for message in messages:
            record = self.env[message.model].browse(message.res_id) \
                if message.model in self.env else False
            if not record or not record.exists() \
                    or not hasattr(record, "_memory_targets") \
                    or not record._memory_should_capture(
                        message, enforce_enabled=False):
                skip += 1
                continue
            matched = False
            for target in record._memory_targets(message):
                envelope = record._memory_build_envelope(message, target)
                if envelope:
                    outbox.enqueue(envelope)
                    enq += 1
                    matched = True
            if not matched:
                skip += 1
        self.write({
            "last_message_id": messages[-1].id,
            "processed": self.processed + len(messages),
            "enqueued": self.enqueued + enq,
            "skipped": self.skipped + skip,
            "state": "done" if len(messages) < self.batch_size else "running",
        })
        return len(messages)

    @api.model
    def _cron_run(self, batches_per_job=10):
        for job in self.search([("state", "=", "running")], order="id"):
            for _i in range(batches_per_job):
                if job.state != "running" or not job._process_batch():
                    break
                self.env.cr.commit()  # persist progress, keep batches resumable

    def action_run_now(self):
        self.ensure_one()
        self._process_batch()
        return True

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_resume(self):
        self.write({"state": "running"})


class MemoryBackfillWizard(models.TransientModel):
    _name = "connect.memory.backfill.wizard"
    _description = "Backfill all partners"

    date_from = fields.Date(
        required=True, string="From date",
        default=lambda self: fields.Date.context_today(self)
        - relativedelta(months=6))
    date_to = fields.Date(string="To date (optional)")
    batch_size = fields.Integer(default=500, required=True)
    estimate = fields.Integer(string="Candidate messages", readonly=True)

    def _message_domain(self):
        domain = list(BASE_DOMAIN) + [("date", ">=", self.date_from)]
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        return domain

    def action_preview(self):
        self.ensure_one()
        self.estimate = self.env["mail.message"].search_count(
            self._message_domain())
        return {
            "type": "ir.actions.act_window",
            "res_model": "connect.memory.backfill.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_start(self):
        self.ensure_one()
        job = self.env["connect.memory.backfill"].create({
            "date_from": self.date_from,
            "date_to": self.date_to,
            "batch_size": self.batch_size,
            "estimate": self.env["mail.message"].search_count(
                self._message_domain()),
            "state": "running",
        })
        job._process_batch()   # first batch now for instant feedback; cron drains the rest
        return {
            "type": "ir.actions.act_window",
            "name": _("Backfill job"),
            "res_model": "connect.memory.backfill",
            "res_id": job.id,
            "view_mode": "form",
            "target": "current",
        }
