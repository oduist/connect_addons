# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import api, fields, models


class CallAttempt(models.Model):
    _name = "connect.call.attempt"
    _description = "Call Runtime Attempt"
    _order = "id desc"
    _rec_name = "parent_sid"

    kind = fields.Selection(
        [
            ("direct_call", "Direct Call"),
            ("ring_group", "Ring Group"),
            ("transfer", "Transfer"),
            ("external_leg", "External Leg"),
            ("external_termination", "External Termination"),
        ],
        required=True,
        index=True,
    )
    call_id = fields.Many2one(
        "connect.call", required=True, ondelete="cascade", index=True
    )
    parent_sid = fields.Char(index=True)
    expected_count = fields.Integer(default=1, required=True)
    target_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    dial_call_sid = fields.Char(index=True)
    external_sid = fields.Char(index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("resolved", "Resolved"),
            ("expired", "Expired"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    expires_at = fields.Datetime(required=True, index=True)
    resolved_at = fields.Datetime(index=True)
    context = fields.Json()

    @api.model_create_multi
    def create(self, vals_list):
        default_expiry = fields.Datetime.now() + timedelta(hours=1)
        for vals in vals_list:
            vals.setdefault("expires_at", default_expiry)
        return super().create(vals_list)

    def mark_resolved(self):
        pending = self.filtered(lambda attempt: attempt.state == "pending")
        if pending:
            pending.write(
                {
                    "state": "resolved",
                    "resolved_at": fields.Datetime.now(),
                }
            )

    @api.autovacuum
    def _vacuum(self):
        now = fields.Datetime.now()
        expired = self.search(
            [("state", "=", "pending"), ("expires_at", "<=", now)]
        )
        if expired:
            expired.write({"state": "expired", "resolved_at": now})

        terminal = self.search(
            [
                ("state", "in", ["resolved", "expired"]),
                ("resolved_at", "<=", now - timedelta(hours=1)),
            ]
        )
        if terminal:
            terminal.unlink()
