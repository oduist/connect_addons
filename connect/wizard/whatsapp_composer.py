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

        # Default sender: user preference -> default sender -> any sender
        sender = False
        connect_user = self.env.user.connect_user
        if connect_user and connect_user.whatsapp_sender_id:
            sender = connect_user.whatsapp_sender_id
        if not sender:
            sender = self.env['connect.whatsapp_sender'].search([('is_default', '=', True)], limit=1)
        if not sender:
            sender = self.env['connect.whatsapp_sender'].search([], limit=1)
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
        import re
        names = set(re.findall(r"{{\s*([\w\.]+)\s*}}", template_body or ""))
        values = {}
        rec = False
        if self.res_model and self.res_id and self.res_model in self.env:
            rec = self.env[self.res_model].browse(self.res_id)
        for name in names:
            val = ''
            if rec:
                try:
                    # support simple field or dot path
                    parts = name.split('.')
                    cur = rec
                    for p in parts:
                        cur = getattr(cur, p)
                    if hasattr(cur, 'display_name') and getattr(cur, 'id', False):
                        val = cur.display_name
                    else:
                        val = str(cur) if cur is not None else ''
                except Exception:
                    val = ''
            values[name] = val
        return values

    @api.onchange('content_template_id')
    def _onchange_content_template(self):
        if self.content_template_id:
            # prefill variables from current record
            auto_vals = self._extract_template_variables(self.content_template_id.body)
            if auto_vals:
                try:
                    import json
                    self.content_variables = json.dumps(auto_vals)
                except Exception:
                    self.content_variables = str(auto_vals)
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
        preview = template_body
        # simple placeholder replacement for {{var}}
        import re
        def repl(match):
            key = match.group(1).strip()
            return str(mapping.get(key, match.group(0)))
        preview = re.sub(r"{{\s*([\w\.]+)\s*}}", repl, template_body)
        return preview

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
                auto_vals = self._extract_template_variables(self.content_template_id.body)
                if auto_vals:
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
