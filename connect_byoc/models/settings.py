from odoo import fields, models, api, release
from odoo.exceptions import ValidationError, UserError
from odoo.addons.connect.models.settings import CONNECT_MODULES


CONNECT_MODULES.append('connect_byoc')

class Settings(models.Model):
    _inherit = "connect.settings"

    def get_usage_model_list(self):
        res = super(Settings, self).get_usage_model_list()
        res.extend(["byoc", "outgoing_rule"])
        res.sort()
        return res

    def sync(self):
        super().sync()
        self.env["connect.byoc"].sync()

    def get_external_call_route(self, number, callerId, status_url):
        # External call to PSTN. Find outgoing rule.
        rule = self.env["connect.outgoing_rule"].find_rule(number)
        if not rule:
            raise ValidationError("No outgoing rule found for this destination!")
        callerId = self.env['connect.domain'].get_byoc_caller_id_number(rule.byoc, number, callerId)
        twiml = """
        <Response>
            <Dial callerId="{}"><Number {} statusCallback='{}' statusCallbackEvent='initiated answered completed'>{}</Number></Dial>
        </Response>
        """.format(
            callerId,
            'byoc="{}"'.format(rule.byoc.sid) if rule.byoc else "",
            status_url,
            number,
        )
        return twiml
