/* @odoo-module */
import { registerThreadAction } from "@mail/core/common/thread_actions";
import { _t } from "@web/core/l10n/translation";

registerThreadAction("connect-create-contact", {
    condition: ({ thread }) =>
        thread?.channel_type === "connect_messages" && !thread.connect_partner_id,
    icon: "fa fa-fw fa-user-plus",
    name: _t("Create Contact"),
    open: async ({ store, thread }) => {
        try {
            const result = await store.env.services.orm.call(
                "discuss.channel",
                "connect_create_partner",
                [[thread.id]],
                {}
            );
            if (result?.partner_id) {
                thread.connect_partner_id = result.partner_id;
                store.env.services.notification.add(
                    _t("Contact created: %s", result.partner_name),
                    { type: "success" }
                );
            }
        } catch (e) {
            console.error("connect_create_partner failed:", e);
            store.env.services.notification.add(
                _t("Failed to create contact"),
                { type: "warning" }
            );
        }
    },
    // sequence 15 puts it right above "Invite People" (sequence 20) in the same group.
    sequence: 15,
    sequenceGroup: 20,
});

registerThreadAction("connect-leave-channel", {
    condition: ({ owner, thread }) =>
        thread?.channel_type === "connect_messages" && owner.isDiscussSidebarChannelActions,
    icon: "fa fa-fw fa-sign-out",
    name: _t("Leave Channel"),
    open: async ({ store, thread }) => {
        try {
            await store.env.services.orm.call(
                "discuss.channel",
                "execute_command_leave",
                [[thread.id]],
                {}
            );
        } catch (e) {
            console.error("connect leave channel failed:", e);
        }
    },
    sequence: 10,
    sequenceGroup: 30,
});
