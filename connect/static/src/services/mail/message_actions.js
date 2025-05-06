/** @odoo-module */

import {_t} from "@web/core/l10n/translation"
import {registry} from "@web/core/registry"

export const messageActionsRegistry = registry.category("mail.message/actions")

messageActionsRegistry
    .add("sms-reply", {
        condition: (component) =>
            component.message.message_type !== null,
        icon: "fa fa-mail-reply",
        title: _t("Connect Reply"),
        onClick: async (component) => {
            const orm = component.message.Model.env.services.orm
            const numbers = await orm.call("mail.message", 'get_message_numbers', [component.message.id])

            if (!numbers) {
                const notification = component.message.Model.env.services.notification
                notification.add(_t("You can't replay to this message!"), {type: 'danger'})
                return
            }

            component.action.doAction(
                {
                    type: "ir.actions.act_window",
                    target: "new",
                    name: _t("Send Message"),
                    res_model: "sms.composer",
                    views: [[false, "form"]],
                    context: {
                        default_res_model: component.message.model,
                        default_res_id: component.message.res_id,
                        default_number_field_name: component.message.record_name,
                        default_recipient_single_number_itf: numbers.from_number,
                        default_recipient_single_number: numbers.from_number,
                        default_outgoing_callerid: numbers.to_number,
                        default_composition_mode: "comment",
                    },
                },
            )
        },
        sequence: 120,
    })