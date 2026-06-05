/* @odoo-module */
import { patch } from "@web/core/utils/patch";
import { DiscussAppCategory } from "@mail/discuss/core/public_web/discuss_app_category_model";
import { compareDatetime } from "@mail/utils/common/misc";

patch(DiscussAppCategory.prototype, {
    sortThreads(t1, t2) {
        if (this.id === "connect_messages") {
            return compareDatetime(t2.lastInterestDt, t1.lastInterestDt) || t2.id - t1.id;
        }
        return super.sortThreads(t1, t2);
    },
});
