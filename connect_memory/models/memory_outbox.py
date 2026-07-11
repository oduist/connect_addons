import hashlib
import json
import logging
import uuid
from datetime import timedelta

from odoo import api, fields, models, release

_logger = logging.getLogger(__name__)


class MemoryOutbox(models.Model):
    """Engine-neutral domain events emitted by Odoo. An external per-engine
    service pulls pending rows over HTTP, loads them into its memory engine and
    acks them. Odoo never calls the engine itself."""

    _name = "connect.memory.outbox"
    _description = "Memory Outbox Event"
    _order = "id asc"

    event_id = fields.Char(
        required=True, index=True, copy=False,
        default=lambda self: str(uuid.uuid4()))
    dedup_key = fields.Char(
        index=True, help="Stable source id, e.g. 'mail.message-42'.")
    content_hash = fields.Char(help="Hash of the event text; detects edits.")
    domain = fields.Char(
        required=True, index=True, help="Data domain: partner, crm, sale, ...")
    kind = fields.Char(
        required=True, help="Event kind: message, observation, state_change, ...")
    payload = fields.Text(
        help="JSON envelope sent to the memory service. Cleared by the "
             "retention cron once the row is sent — a thin tombstone "
             "(dedup_key + content_hash) is kept for de-duplication.")
    state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        default="pending", required=True, index=True)
    engine = fields.Char(help="Optional target engine (hindsight, cognee).")
    company_id = fields.Many2one("res.company", index=True)
    commercial_partner_id = fields.Many2one("res.partner", index=True)
    res_model = fields.Char(index=True)
    res_id = fields.Integer(index=True)
    sent_at = fields.Datetime(copy=False)
    attempts = fields.Integer(default=0)
    last_error = fields.Text()

    if release.version_info[0] >= 19:
        _event_id_uniq = models.Constraint(
            "unique(event_id)",
            "event_id must be unique.",
        )
    else:
        _sql_constraints = [
            ("event_id_uniq", "unique(event_id)", "event_id must be unique."),
        ]

    @api.model
    def _memory_content_hash(self, text):
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        return "sha256:" + digest

    @api.model
    def enqueue(self, envelope):
        """Create one outbox row from an envelope dict. Idempotent on
        (dedup_key, content_hash): an identical event already pending/sent is
        skipped; a changed content_hash (edit) produces a new event."""
        if not envelope:
            return self.browse()
        dedup_key = envelope.get("dedup_key")
        content_hash = envelope.get("content_hash")
        if dedup_key and content_hash:
            existing = self.sudo().search([
                ("dedup_key", "=", dedup_key),
                ("content_hash", "=", content_hash),
                ("state", "in", ("pending", "sent")),
            ], limit=1)
            if existing:
                return existing
        scope = envelope.get("scope") or {}
        source = envelope.get("source") or {}
        vals = {
            "event_id": envelope.get("event_id") or str(uuid.uuid4()),
            "dedup_key": dedup_key,
            "content_hash": content_hash,
            "domain": envelope.get("domain") or "misc",
            "kind": envelope.get("kind") or "message",
            "payload": json.dumps(envelope, ensure_ascii=False, sort_keys=True),
            "engine": envelope.get("engine"),
            "company_id": source.get("company_id"),
            "commercial_partner_id": scope.get("commercial_partner_id"),
            "res_model": source.get("model"),
            "res_id": source.get("res_id"),
        }
        return self.sudo().create(vals)

    # ------------------------------------------------------------------
    # Used by the HTTP pull/ack endpoints (see controllers/main.py)
    # ------------------------------------------------------------------
    @api.model
    def fetch_batch(self, limit=100, domain=None, engine=None):
        criteria = [("state", "=", "pending")]
        if domain:
            criteria.append(("domain", "=", domain))
        if engine:
            criteria += ["|", ("engine", "=", engine), ("engine", "=", False)]
        rows = self.sudo().search(criteria, limit=limit, order="id asc")
        return [{
            "id": row.id,
            "event_id": row.event_id,
            "domain": row.domain,
            "kind": row.kind,
            "payload": json.loads(row.payload),
        } for row in rows]

    @api.model
    def ack(self, ids, ok=True, error=None):
        rows = self.sudo().browse(ids or []).exists()
        if not rows:
            return 0
        if ok:
            rows.write({"state": "sent", "sent_at": fields.Datetime.now()})
        else:
            for row in rows:
                row.write({
                    "state": "failed",
                    "attempts": row.attempts + 1,
                    "last_error": error or "",
                })
        return len(rows)

    # ------------------------------------------------------------------
    # Retention (ir.cron): keep dedup tombstones, drop bulky payloads
    # ------------------------------------------------------------------
    @api.model
    def _cron_vacuum_sent(self, days=None):
        """Drop the bulky `payload` of `sent` rows older than `days`, keeping a
        thin tombstone (dedup_key + content_hash + state) so `enqueue` keeps
        de-duplicating and never re-sends. The memory itself lives in the engine;
        the payload is only a transport buffer. `days=0` disables retention."""
        if days is None:
            days = int(self.env["ir.config_parameter"].sudo().get_param(
                "connect_memory.outbox_retention_days", "7") or 0)
        if not days:
            return 0
        cutoff = fields.Datetime.now() - timedelta(days=days)
        rows = self.sudo().search([
            ("state", "=", "sent"),
            ("sent_at", "<", cutoff),
            ("payload", "!=", False),
        ])
        if rows:
            rows.write({"payload": False})
            _logger.info(
                "memory: vacuumed payload of %s sent outbox rows (> %s days)",
                len(rows), days)
        return len(rows)
