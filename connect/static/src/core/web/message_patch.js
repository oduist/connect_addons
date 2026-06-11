/* @odoo-module */
import { Message } from "@mail/core/common/message";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

// In connect_messages channels the customer is a plain contact with no linked
// internal user, so Odoo's user-based author card (gated on author_id.main_user_id)
// never opens. Make such an author clickable and jump straight to their
// res.partner form — parity with the "Open Contact" thread action.
patch(Message.prototype, {
    _isConnectCustomerAuthor() {
        return (
            this.message.thread?.channel_type === "connect_messages" &&
            !!this.message.author_id &&
            !this.message.author_id.main_user_id
        );
    },
    hasAuthorClickable() {
        return (super.hasAuthorClickable?.() ?? false) || this._isConnectCustomerAuthor();
    },
    getAuthorText() {
        if (this._isConnectCustomerAuthor()) {
            return _t("Open contact");
        }
        return super.getAuthorText();
    },
    onClickAuthor(ev) {
        if (this._isConnectCustomerAuthor()) {
            this.env.services.action.doAction({
                type: "ir.actions.act_window",
                res_model: "res.partner",
                res_id: this.message.author_id.id,
                views: [[false, "form"]],
            });
            return;
        }
        return super.onClickAuthor(ev);
    },
});
