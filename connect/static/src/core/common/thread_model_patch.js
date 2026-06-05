/* @odoo-module */
import { Thread } from "@mail/core/common/thread_model";
import { Record } from "@mail/core/common/record";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    setup() {
        super.setup();
        // Server-provided WhatsApp 24h window state (connect_messages channels).
        this.connect_whatsapp_window_open = false;
        this.connect_whatsapp_valid_until = Record.attr(undefined, { type: "datetime" });
        // Per-agent composer selection (client-only).
        this.connectProvider = "sms";
        this.connectSenderId = undefined;
    },
});
