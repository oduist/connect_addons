# -*- coding: utf-8 -*
import json
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.addons.connect.models.settings import debug


logger = logging.getLogger(__name__)


class ElevenlabsSaleCall(models.Model):
    _inherit = 'connect.call'

    def elevenlabs_agent_get_call_data(self):
        if not self.env["oduist.license"].check_license('connect_elevenlabs_sale'):
            return super(ElevenlabsSaleCall, self).elevenlabs_agent_get_call_data()
        res = super(ElevenlabsSaleCall, self).elevenlabs_agent_get_call_data()
        res['sale_module_extra_prompt'] = ''
        return res
