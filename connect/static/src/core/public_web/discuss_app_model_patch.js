/* @odoo-module */
import { fields } from "@mail/core/common/record";
import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(DiscussApp.prototype, {
    setup() {
        super.setup(...arguments);
        this.connect_messages = fields.One("DiscussAppCategory", {
            compute() {
                return {
                    canAdd: false,
                    canView: false,
                    extraClass: "o-mail-DiscussSidebarCategory-connect",
                    icon: "fa fa-comments",
                    id: "connect_messages",
                    name: _t("Messages"),
                    sequence: 22,
                    serverStateKey: "is_discuss_sidebar_category_connect_messages_open",
                };
            },
            eager: true,
        });
    },
});
