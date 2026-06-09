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
        // Per-agent composer selection; undefined = fall back to server default.
        this.connectProvider = fields.Attr(undefined);
        this.connectSenderId = fields.Attr(undefined);
        // Server-provided fields for connect_messages channels.
        this.connect_partner_id = fields.Attr(undefined);
        this.connect_number = fields.Attr(undefined);
        this.connect_channel_provider = fields.Attr("sms");
    },
    _computeDiscussAppCategory() {
        if (this.channel_type === "connect_messages") {
            return this.store.discuss.connect_messages;
        }
        return super._computeDiscussAppCategory(...arguments);
    },
});
