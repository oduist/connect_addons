/* @odoo-module */
import { Thread } from "@mail/core/common/thread_model";
import { fields } from "@mail/model/misc";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        // Server-provided WhatsApp 24h window state (connect_messages channels).
        this.connect_whatsapp_window_open = fields.Attr(false);
        this.connect_whatsapp_valid_until = fields.Attr(undefined, { type: "datetime" });
        // Per-agent composer selection (client-only).
        this.connectProvider = fields.Attr("sms");
        this.connectSenderId = fields.Attr(undefined);
        // Partner ID (or false) and raw phone number for connect_messages channels.
        this.connect_partner_id = fields.Attr(undefined);
        this.connect_number = fields.Attr(undefined);
    },
    _computeDiscussAppCategory() {
        if (this.channel_type === "connect_messages") {
            return this.store.discuss.connect_messages;
        }
        return super._computeDiscussAppCategory(...arguments);
    },
});
