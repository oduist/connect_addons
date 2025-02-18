from odoo import models, fields
from odoo.exceptions import ValidationError


class CancelSubscription(models.TransientModel):
    _name = 'connect.cancel_subscription_wizard'
    _description = 'Cancel Subscription'

    is_confirmed = fields.Boolean('Please confirm')

    def submit(self):
        if self.is_confirmed:
            context = self.env.context
            self.env[context["active_model"]].browse(context["active_id"]).unsubscribe_product()
        else:
            raise ValidationError('Please check the confirm box!')

