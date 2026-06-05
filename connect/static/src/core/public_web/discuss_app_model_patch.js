/* @odoo-module */
import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { Record } from "@mail/core/common/record";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(DiscussApp, {
    new(data) {
        const res = super.new(data);
        res.connect_messages = {
            extraClass: "o-mail-DiscussSidebarCategory-connect",
            icon: "fa fa-comments",
            id: "connect_messages",
            name: _t("Messages"),
            hideWhenEmpty: true,
            canView: false,
            canAdd: false,
            serverStateKey: "is_discuss_sidebar_category_connect_messages_open",
            sequence: 22,
        };
        return res;
    },
});

patch(DiscussApp.prototype, {
    setup(env) {
        super.setup(env);
        this.connect_messages = Record.one("DiscussAppCategory");
    },
});
