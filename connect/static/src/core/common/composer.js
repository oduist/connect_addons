/** @odoo-module **/
"use strict"

import {patch} from "@web/core/utils/patch"
import {Composer} from "@mail/core/common/composer"


patch(Composer.prototype, {
    async _onClickAiCompletion() {
        const response = await this.rpc("/connect/ai_completion", {
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
