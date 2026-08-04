/* @odoo-module */
import { DiscussSearch } from "@mail/core/public_web/discuss_search";
import { NewSmsDialog } from "@connect/core/web/new_sms_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useHover } from "@mail/utils/common/hooks";
import { useDropdownState } from "@web/core/dropdown/dropdown_hooks";

patch(DiscussSearch.prototype, {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.smsHover = useHover(["sms-btn", "sms-floating"], {
            onHover: () => {
                if (this.store.discuss.isSidebarCompact) {
                    this.newSmsFloating.isOpen = true;
                }
            },
            onAway: () => {
                if (this.store.discuss.isSidebarCompact) {
                    this.newSmsFloating.isOpen = false;
                }
            },
        });
        this.newSmsFloating = useDropdownState();
    },

    get newSmsText() {
        return _t("New SMS");
    },

    async onClickNewSms() {
        let senders = { options: [], default: false };
        try {
            senders = await this.orm.call(
                "discuss.channel",
                "connect_sms_sender_options",
                [],
            );
        } catch {
            // Offering no choice still lets the server pick the default line.
        }
        this.dialogService.add(NewSmsDialog, {
            senders: senders.options,
            defaultSender: senders.default,
            onSubmit: async (number, senderNumber) => {
                await this._startSmsChannel(number, senderNumber);
            },
        });
    },

    async _startSmsChannel(number, senderNumber) {
        try {
            const result = await this.orm.call(
                "discuss.channel",
                "connect_start_sms_channel",
                [number, senderNumber || false],
            );
            if (result?.channel_id) {
                const thread = await this.store.Thread.getOrFetch({
                    model: "discuss.channel",
                    id: result.channel_id,
                });
                if (thread) {
                    thread.setAsDiscussThread();
                }
            }
        } catch (e) {
            // Show what the server said (invalid number, no default outgoing
            // number, ...) — a generic message leaves the agent with nothing
            // to act on.
            this.notification.add(
                e?.data?.message || _t("Failed to start SMS conversation."),
                { type: "warning" },
            );
        }
    },
});
