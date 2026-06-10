/* @odoo-module */
import { Store } from "@mail/core/common/store_service";
import { patch } from "@web/core/utils/patch";

patch(Store.prototype, {
    async getMessagePostParams({ thread }) {
        const params = await super.getMessagePostParams(...arguments);
        if (thread.channel_type === "connect_messages"
                && params.post_data.subtype_xmlid !== "mail.mt_note") {
            params.post_data.message_type = "connect_message";
            params.post_data.connect_provider = thread.connect_channel_provider || "sms";
            if (thread.connectSenderId) {
                params.post_data.connect_sender_id = thread.connectSenderId;
            }
        }
        return params;
    },
});
