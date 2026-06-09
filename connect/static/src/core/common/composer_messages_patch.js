/* @odoo-module */
import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(Composer.prototype, {
    get isConnectMessages() {
        return this.thread?.channel_type === "connect_messages";
    },
    get connectProvider() {
        return this.thread?.connectProvider || "sms";
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
    get isConnectUnknownContact() {
        return this.isConnectMessages && !this.thread?.connect_partner_id;
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
    async onCreateContact() {
        const thread = this.thread;
        if (!thread) return;
        try {
            const result = await this.env.services.orm.call(
                "discuss.channel",
                "connect_create_partner",
                [[thread.id]],
                {}
            );
            if (result && result.partner_id) {
                thread.connect_partner_id = result.partner_id;
                this.env.services.notification.add(
                    _t("Contact created: %s", result.partner_name),
                    { type: "success" }
                );
            }
        } catch {
            this.env.services.notification.add(
                _t("Failed to create contact"),
                { type: "warning" }
            );
        }
    },
});
