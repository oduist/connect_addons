/** @odoo-module **/

import {registerPatch} from '@mail/model/model_core'

registerPatch({
    name: 'MessageView',
    fields: {
        failureNotificationIconClassName: {
            compute() {
                if (this.message && this.message.message_type === 'WhatsApp') {
                    return 'fa fa-whatsapp'
                }
                return this._super()
            },
        },
        failureNotificationIconLabel: {
            compute() {
                if (this.message && this.message.message_type === 'WhatsApp') {
                    return this.env._t("WhatsApp")
                }
                return this._super()
            },
        },
        notificationIconClassName: {
            compute() {
                if (this.message && this.message.message_type === 'WhatsApp') {
                    return 'fa fa-whatsapp'
                }
                return this._super()
            },
        },
        notificationIconLabel: {
            compute() {
                if (this.message && this.message.message_type === 'WhatsApp') {
                    return this.env._t("WhatsApp")
                }
                return this._super()
            },
        },
    },
})
