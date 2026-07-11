import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MemoryInbox(models.Model):
    """Questions to the memory engine and their answers. Odoo submits a
    `pending` request; the external service claims it, asks the engine and
    writes the answer back. Odoo UI then reads the answer from this table."""

    _name = "connect.memory.inbox"
    _description = "Memory Inbox Request/Answer"
    _order = "id desc"

    query_type = fields.Selection(
        [("reflect", "Reflect"), ("recall", "Recall")],
        default="reflect", required=True)
    query = fields.Text(required=True)
    request = fields.Text(help="Full JSON request for the memory service.")
    engine = fields.Char()
    state = fields.Selection(
        [("pending", "Pending"), ("processing", "Processing"),
         ("done", "Done"), ("failed", "Failed")],
        default="pending", required=True, index=True)
    answer = fields.Text(help="Raw JSON answer from the engine.")
    answer_text = fields.Text(help="Human-readable answer extracted from JSON.")
    res_model = fields.Char(index=True)
    res_id = fields.Integer(index=True)
    commercial_partner_id = fields.Many2one("res.partner", index=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company)
    requested_by = fields.Many2one(
        "res.users", default=lambda self: self.env.user)
    done_at = fields.Datetime()

    @api.model
    def submit(self, query, query_type="reflect", scope=None, res_model=None,
               res_id=None, engine=None):
        """Create a pending request for the memory service."""
        scope = scope or {}
        request_payload = {
            "query": query,
            "query_type": query_type,
            "scope": scope,
        }
        return self.sudo().create({
            "query": query,
            "query_type": query_type,
            "request": json.dumps(request_payload, ensure_ascii=False),
            "engine": engine,
            "res_model": res_model,
            "res_id": res_id,
            "commercial_partner_id": scope.get("commercial_partner_id"),
            "requested_by": self.env.user.id,
            "company_id": self.env.company.id,
        })

    # ------------------------------------------------------------------
    # Used by the HTTP endpoints (see controllers/main.py)
    # ------------------------------------------------------------------
    @api.model
    def claim_batch(self, limit=20, engine=None):
        criteria = [("state", "=", "pending")]
        if engine:
            criteria += ["|", ("engine", "=", engine), ("engine", "=", False)]
        rows = self.sudo().search(criteria, limit=limit, order="id asc")
        rows.write({"state": "processing"})
        result = []
        for row in rows:
            try:
                req = json.loads(row.request) if row.request else {}
            except (ValueError, TypeError):
                req = {}
            req.setdefault("query", row.query)
            result.append({"id": row.id, "request": req})
        return result

    @api.model
    def store_answer(self, inbox_id, answer, ok=True):
        rec = self.sudo().browse(int(inbox_id)).exists()
        if not rec:
            return False
        answer_text = ""
        if isinstance(answer, dict):
            answer_text = answer.get("text") or answer.get("answer") or ""
        elif isinstance(answer, str):
            answer_text = answer
        rec.write({
            "state": "done" if ok else "failed",
            "answer": json.dumps(answer, ensure_ascii=False)
            if answer is not None else False,
            "answer_text": answer_text,
            "done_at": fields.Datetime.now(),
        })
        return True
