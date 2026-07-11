import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    _MEMORY_SALE_TRACKED_SCALARS = (
        "amount_total", "amount_untaxed", "currency_id",
        "date_order", "validity_date", "commitment_date", "partner_shipping_id",
    )
    _MEMORY_SALE_TRACKED_LINE_FIELDS = (
        "product_uom_qty", "price_unit", "discount", "price_subtotal",
    )

    # ------------------------------------------------------------------
    # create -> "created" event
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        if self.env["connect.memory.mixin"]._memory_enabled():
            try:  # capture must never break the business operation (ADR-009)
                orders._memory_sale_capture_created()
            except Exception:
                _logger.exception("memory_sale: sale create capture failed")
        return orders

    def _memory_sale_capture_created(self):
        mixin = self.env["connect.memory.sale.mixin"]
        for order in self:
            partner = order.partner_id
            if not mixin._memory_sale_should_capture(partner):
                continue
            lines = self._memory_sale_line_summary(order)
            scope = mixin._memory_sale_scope(order, partner)
            source = mixin._memory_sale_source(order)
            text = "%s created for %s: %s" % (
                order.name or "Draft order", partner.display_name,
                ", ".join("%g x %s" % (ln["qty"], ln["product"]) for ln in lines) or "no lines")
            tags = mixin._memory_sale_base_tags("sale", "customer", partner.commercial_partner_id.id) \
                + ["stage:draft", "via:sale.order", "res:sale.order-%s" % order.id]
            envelope = mixin._memory_sale_build(
                domain="sale", kind="created", scope=scope, source=source,
                text=text, tags=tags, sensitivity="financial",
                dedup_key="sale.order-%s@created" % order.id,
                data={"amount_total": order.amount_total,
                      "currency": order.currency_id.name,
                      "lines": lines})
            self.env["connect.memory.mixin"]._memory_emit(envelope, module="connect_memory_sale")

    @api.model
    def _memory_sale_line_summary(self, order):
        lines = []
        for ln in order.order_line:
            lines.append({
                "product": ln.product_id.display_name or "",
                "qty": ln.product_uom_qty,
                "uom": ln.product_uom_id.name or "",
                "price_unit": ln.price_unit,
                "discount": ln.discount,
                "subtotal": ln.price_subtotal,
            })
        return lines

    # ------------------------------------------------------------------
    # write -> lifecycle (confirm/cancel/lock) + state_change
    # ------------------------------------------------------------------
    def write(self, vals):
        # snapshot tracked scalars + line values BEFORE super().write()
        # overwrites them (capture must never break the write — ADR-009)
        capture = self.env["connect.memory.mixin"]._memory_enabled()
        before_scalars, before_lines = {}, {}
        if capture:
            try:
                if any(f in vals for f in self._MEMORY_SALE_TRACKED_SCALARS):
                    for rec in self:
                        if rec.state == "sale":
                            before_scalars[rec.id] = {
                                f: rec[f] for f in self._MEMORY_SALE_TRACKED_SCALARS if f in vals}
                before_lines = self._memory_sale_snapshot_lines(vals.get("order_line"))
            except Exception:
                _logger.exception("memory_sale: sale write snapshot failed")
        result = super().write(vals)
        if capture:
            try:
                if vals.get("state") == "sale":
                    self._memory_sale_lifecycle("confirmed", "outcome:confirmed")
                elif vals.get("state") == "cancel":
                    self._memory_sale_lifecycle("cancelled", "outcome:cancelled")
                elif vals.get("locked") is True:
                    self._memory_sale_lifecycle("locked", "outcome:locked")
                else:
                    self._memory_sale_state_change(vals, before_scalars, before_lines)
            except Exception:
                _logger.exception("memory_sale: sale write capture failed")
        return result

    def _memory_sale_snapshot_lines(self, commands):
        """Read tracked line fields BEFORE super().write() so an op==1 update
        can report the real old value (after write the line already holds the
        new one). Keyed by line_id; '__product__' carries the display name."""
        snapshot = {}
        if not commands:
            return snapshot
        Line = self.env["sale.order.line"]
        for cmd in commands:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                continue
            if cmd[0] == 1:  # update
                line = Line.browse(cmd[1])
                snap = {f: line[f] for f in self._MEMORY_SALE_TRACKED_LINE_FIELDS}
                snap["__product__"] = line.product_id.display_name
                snapshot[cmd[1]] = snap
        return snapshot

    def _memory_sale_lifecycle(self, label, outcome_tag):
        mixin = self.env["connect.memory.sale.mixin"]
        for order in self:
            partner = order.partner_id
            if not mixin._memory_sale_should_capture(partner):
                continue
            incoterm = ""
            if "incoterm" in order._fields and order.incoterm:
                incoterm = ", %s" % order.incoterm.display_name
            text = "Sale order %s %s for %s: %g %s%s." % (
                order.name or "", label, partner.display_name,
                order.amount_total, order.currency_id.name, incoterm)
            tags = mixin._memory_sale_base_tags(
                "sale", "customer", partner.commercial_partner_id.id) \
                + [outcome_tag, "via:sale.order", "res:sale.order-%s" % order.id]
            envelope = mixin._memory_sale_build(
                domain="sale", kind="lifecycle",
                scope=mixin._memory_sale_scope(order, partner),
                source=mixin._memory_sale_source(order),
                text=text, tags=tags, sensitivity="financial",
                dedup_key="sale.order-%s@%s" % (order.id, label),
                data={"amount_total": order.amount_total,
                      "currency": order.currency_id.name})
            self.env["connect.memory.mixin"]._memory_emit(envelope, module="connect_memory_sale")

    def _memory_sale_state_change(self, vals, before_scalars, before_lines):
        mixin = self.env["connect.memory.sale.mixin"]
        for order in self:
            if order.state != "sale":
                continue
            if not mixin._memory_sale_should_capture(order.partner_id):
                continue
            diff = {}
            old_map = before_scalars.get(order.id, {})
            for fname in self._MEMORY_SALE_TRACKED_SCALARS:
                if fname in vals:
                    old = old_map.get(fname)
                    new = order[fname]
                    old_str = old.display_name if hasattr(old, "display_name") else (str(old) if old else None)
                    new_str = new.display_name if hasattr(new, "display_name") else str(new)
                    if old_str != new_str:
                        diff[fname] = [old_str, new_str]
            line_diff = self._memory_sale_parse_o2m(vals.get("order_line"), before_lines)
            if line_diff:
                diff["order_line"] = line_diff
            if not diff:
                continue
            self._memory_sale_emit_state_change(order, diff)

    def _memory_sale_parse_o2m(self, commands, before_lines):
        if not commands:
            return []
        out = []
        Line = self.env["sale.order.line"]
        for cmd in commands:
            if not isinstance(cmd, (list, tuple)) or not cmd:
                continue
            op = cmd[0]
            if op == 1:  # update
                line_id = cmd[1]
                new_vals = cmd[2] or {}
                old_snap = before_lines.get(line_id, {})
                changes = {}
                for fname in self._MEMORY_SALE_TRACKED_LINE_FIELDS:
                    if fname in new_vals:
                        changes[fname] = [old_snap.get(fname), new_vals[fname]]
                if changes:
                    out.append({"line_id": line_id,
                                "product": old_snap.get("__product__")
                                or Line.browse(line_id).product_id.display_name,
                                "changes": changes})
            elif op == 0:  # create
                out.append({"action": "line_added", "vals": cmd[2] or {}})
            elif op == 2:  # delete
                out.append({"action": "line_deleted", "line_id": cmd[1]})
        return out

    def _memory_sale_emit_state_change(self, order, diff):
        mixin = self.env["connect.memory.sale.mixin"]
        partner = order.partner_id
        text_parts = []
        for fname, val in diff.items():
            if fname == "order_line":
                continue
            text_parts.append("%s: %s -> %s" % (fname, val[0], val[1]))
        if "order_line" in diff:
            for ld in diff["order_line"]:
                if "changes" in ld:
                    for f, (old, new) in ld["changes"].items():
                        text_parts.append("%s.%s: %s -> %s" % (ld["product"], f, old, new))
                elif ld.get("action") == "line_added":
                    text_parts.append("line added")
                elif ld.get("action") == "line_deleted":
                    text_parts.append("line deleted")
        text = "Sale order %s (%s) edited: %s" % (
            order.name or "", partner.display_name,
            "; ".join(text_parts) or "structural change")
        tags = mixin._memory_sale_base_tags("sale", "customer", partner.commercial_partner_id.id) \
            + ["signal:renegotiation", "via:sale.order", "res:sale.order-%s" % order.id]
        envelope = mixin._memory_sale_build(
            domain="sale", kind="state_change",
            scope=mixin._memory_sale_scope(order, partner),
            source=mixin._memory_sale_source(order),
            text=text, tags=tags, sensitivity="financial",
            dedup_key="sale.order-%s@edit-%s" % (
                order.id, fields.Datetime.now().strftime("%Y%m%dT%H%M%S")),
            data={"changes": diff})
        self.env["connect.memory.mixin"]._memory_emit(envelope, module="connect_memory_sale")
