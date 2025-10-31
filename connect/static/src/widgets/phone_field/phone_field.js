/** @odoo-module **/
"use strict"

import {patch} from "@web/core/utils/patch"
import {PhoneField} from "@web/views/fields/phone/phone_field"

patch(PhoneField.prototype, "connect.PhoneField", {
    _onClickCallButton(e) {
        e.preventDefault()
        const {resModel, data} = this.props.record
        const args = [this.props.value, resModel, data.id]
        this.env.model.orm.call("connect.settings", "originate_call", args, {})
    },

    _onClickWhatsappCallButton(e) {
        e.preventDefault()
        const {resModel, data} = this.props.record
        const args = [this.props.value, resModel, data.id]
        // Pass whatsapp_call flag via kwargs to avoid breaking positional args
        this.env.model.orm.call("connect.settings", "originate_call", args, {whatsapp_call: true})
    },

    async _onClickWhatsappMessageButton(e) {
        e.preventDefault()
        await this.props.record.save()
        this.env.model.actionService.doAction(
            {
                type: "ir.actions.act_window",
                target: "new",
                name: "WhatsApp",
                res_model: "connect.whatsapp_composer",
                views: [[false, "form"]],
                context: {
                    active_model: this.props.record.resModel,
                    active_id: this.props.record.data.id,
                    default_phone: this.props.value,
                },
            },
            {
                onClose: () => {
                    this.props.record.load()
                    this.props.record.model.notify()
                },
            }
        )
    }
})
