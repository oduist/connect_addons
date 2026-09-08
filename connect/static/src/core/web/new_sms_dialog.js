/* @odoo-module */
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { Component, onMounted, useState, useRef } from "@odoo/owl";

export class NewSmsDialog extends Component {
    static template = "connect.NewSmsDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onSubmit: Function,
        // Lines this database can send from, and the one to preselect. With a
        // single line there is nothing to choose, so the picker stays hidden.
        senders: { type: Array, optional: true },
        defaultSender: { type: [String, Boolean], optional: true },
    };
    static defaultProps = { senders: [], defaultSender: false };

    setup() {
        this.title = _t("New SMS Conversation");
        this.state = useState({
            number: "",
            sender: this.props.defaultSender || this.props.senders[0]?.number || "",
        });
        this.inputRef = useRef("autofocus");
        onMounted(() => this.inputRef.el?.focus());
    }

    get hasSenderChoice() {
        return this.props.senders.length > 1;
    }

    get isValid() {
        return this.state.number.trim().length > 0;
    }

    async onConfirm() {
        if (!this.isValid) return;
        await this.props.onSubmit(this.state.number.trim(), this.state.sender);
        this.props.close();
    }
}
