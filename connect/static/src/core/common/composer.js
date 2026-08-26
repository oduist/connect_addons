/** @odoo-module **/
"use strict"

import { patch } from "@web/core/utils/patch";
import { Composer } from "@mail/core/common/composer";
import { rpc } from "@web/core/network/rpc";


patch(Composer.prototype, {
    async _onClickAiCompletion() {
        const response = await rpc("/connect/ai_completion", {
            model: this.thread.model,
            res_id: this.thread.id,
        })
        if (response.status === 'ok') {
            this.props.composer.textInputContent = response.message
        } else {
            this.env.services.notification.add(response.error_message, {type: "warning",})
        }
    }
})
