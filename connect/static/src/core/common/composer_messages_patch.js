/* @odoo-module */
import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    get isConnectMessages() {
        return this.thread?.channel_type === "connect_messages";
    },
    get connectProvider() {
        // Explicit user selection overrides server default; fall back to channel provider.
        return this.thread?.connectProvider || this.thread?.connect_channel_provider || "sms";
    },
    setConnectProvider(provider) {
        if (this.thread) {
            this.thread.connectProvider = provider;
        }
    },
    get connectWhatsappBlocked() {
        // WhatsApp outside the 24h window needs a template (server enforces too).
        return (
            this.isConnectMessages &&
            this.connectProvider === "whatsapp" &&
            this.thread &&
            !this.thread.connect_whatsapp_window_open
        );
    },
    get placeholder() {
        if (this.connectWhatsappBlocked) {
            return _t("WhatsApp 24h window closed — send a template from the contact form.");
        }
        return super.placeholder;
    },
    get isSendButtonDisabled() {
        return super.isSendButtonDisabled || this.connectWhatsappBlocked;
    },
});
