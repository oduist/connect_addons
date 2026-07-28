/* @odoo-module */
import { Message } from "@mail/core/common/message";
import { markEventHandled } from "@web/core/utils/misc";
import { patch } from "@web/core/utils/patch";

// In connect_messages channels the customer is a plain contact with no linked
// internal user, so Odoo's author card (gated on author_id.main_user_id) never
// opens. Open the same AvatarCardPopover keyed on the partner instead — it
// already supports model "res.partner" (name/phone/email + View Profile), giving
// parity with the internal-user card shown for agents.
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
    onClickAuthor(ev) {
        if (this._isConnectCustomerAuthor()) {
            markEventHandled(ev, "Message.ClickAuthor");
            const target = ev.currentTarget;
            if (!this.avatarCard?.isOpen) {
                this.avatarCard.open(target, {
                    id: this.message.author_id.id,
                    model: "res.partner",
                });
            }
            return;
        }
        return super.onClickAuthor(ev);
    },
});
