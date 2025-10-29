# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ConnectWhatsappComposer(models.TransientModel):
    _name = 'connect.whatsapp_composer'
    _description = 'Send WhatsApp Message'

    # Context/target
    res_model = fields.Char('Related Model')
    res_id = fields.Integer('Related Record')

    # Inputs
    whatsapp_sender_id = fields.Many2one(
        'connect.whatsapp_sender',
        string='Sender',
        required=True,
        domain="[('no_sync', '=', False), ('status', '=', 'ONLINE')]"
    )
    phone = fields.Char(string='To', required=True)
    content_template_id = fields.Many2one('connect.message_content_template', string='Template',
                                          domain="[('status', '=', 'approved')]")
    content_variables = fields.Text(string='Content Variables (JSON)')
    body = fields.Text(string='Message')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        ctx = dict(self.env.context or {})
        res_model = ctx.get('active_model') or ctx.get('default_res_model')
        res_id = ctx.get('active_id') or ctx.get('default_res_id')
        vals.update({'res_model': res_model, 'res_id': res_id})

        # Default sender from model helper
        sender = self.env['connect.whatsapp_sender'].get_default_sender(self.env.user)
        if sender:
            vals['whatsapp_sender_id'] = sender.id

        # Default phone
        phone = ctx.get('default_phone')
        try:
            if not phone and res_model and res_id and res_model in self.env:
                rec = self.env[res_model].browse(res_id)
                # Prefer normalized fields then mobile then phone
                phone = rec.connect_mobile_normalized or rec.connect_phone_normalized or rec.mobile or rec.phone
            if phone:
                # Normalize to E.164 using partner helper
                phone = self.env['res.partner']._phone_format(number=phone)
        except Exception:
            pass
        if phone:
            vals['phone'] = phone

        return vals

    def _extract_template_variables(self, template_body):
        """Extract numeric placeholders from the template body and return a JSON-ready mapping.
        Our convention now is numeric variables only, e.g. {{1}}, {{2}}.
        Auto-filling from a record is not attempted, values default to empty strings.
        """
        import re
        indices = re.findall(r"{{\s*(\d+)\s*}}", template_body or "")
        # Keep order but ensure uniqueness by first occurrence
        seen = set()
        ordered_unique = []
        for idx in indices:
            if idx not in seen:
                seen.add(idx)
                ordered_unique.append(idx)
        return {i: "" for i in ordered_unique}

    @api.onchange('content_template_id')
    def _onchange_content_template(self):
        if self.content_template_id:
            # Prefer example variables defined on the template; fallback to numeric placeholders
            tmpl_vars_json = (self.content_template_id.variables or '').strip()
            parsed = None
            if tmpl_vars_json:
                try:
                    import json
                    parsed = json.loads(tmpl_vars_json)
                    if not isinstance(parsed, dict):
                        parsed = None
                except Exception:
                    parsed = None
            if parsed is None:
                parsed = self._extract_template_variables(self.content_template_id.body)
            try:
                import json
                self.content_variables = json.dumps(parsed) if parsed is not None else False
            except Exception:
                self.content_variables = str(parsed)
            # render preview
            self.body = self._render_preview(self.content_template_id.body, self.content_variables)
        else:
            # clear variables/body when deselecting
            self.content_variables = False
            self.body = False

    def _render_preview(self, template_body, variables_json):
        if not template_body:
            return False
        mapping = {}
        try:
            import json
            mapping = json.loads(variables_json) if variables_json else {}
        except Exception:
            mapping = {}
        # Replace only numeric placeholders {{1}}, {{2}}, ...
        import re
        def repl(match):
            key = match.group(1).strip()
            return str(mapping.get(key, match.group(0)))
        return re.sub(r"{{\s*(\d+)\s*}}", repl, template_body)

    @api.onchange('content_variables')
    def _onchange_content_variables(self):
        if self.content_template_id:
            self.body = self._render_preview(self.content_template_id.body, self.content_variables)

    def action_send_whatsapp(self):
        self.ensure_one()
        if not self.phone:
            raise ValidationError('Recipient number is required')
        # validate body if no template
        if not self.content_template_id and not (self.body and self.body.strip()):
            raise ValidationError('Message body is required')
        kwargs = {}
        body_to_send = self.body
        if self.content_template_id and self.content_template_id.sid:
            kwargs['content_sid'] = self.content_template_id.sid
            # use provided json or build automatically
            json_text = (self.content_variables or '').strip()
            if not json_text:
                # Prefer example variables from template; fallback to numeric placeholders
                tmpl_vars_json = (self.content_template_id.variables or '').strip()
                if tmpl_vars_json:
                    json_text = tmpl_vars_json
                else:
                    auto_vals = self._extract_template_variables(self.content_template_id.body)
                    if auto_vals is not None:
                        import json
                        json_text = json.dumps(auto_vals)
            if json_text:
                kwargs['content_variables'] = json_text
            body_to_send = self._render_preview(self.content_template_id.body, self.content_variables)
        self.whatsapp_sender_id.send_whatsapp(
            recipient=self.phone,
            body=body_to_send,
            res_model=self.res_model,
            res_id=self.res_id,
            **kwargs,
        )
        return {'type': 'ir.actions.act_window_close'}
