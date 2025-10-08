/** @odoo-module **/
import {ConnectActiveCallsPopup} from "@connect/services/active_calls/active_calls_popup"

import {patch} from "@web/core/utils/patch"

patch(ConnectActiveCallsPopup.prototype, {
    _onClickTicket(ev, ticket) {
        if (ticket === false) {
            return
        }
        ev.stopPropagation()
        this.action.doAction({
            res_id: ticket[0],
            res_model: 'helpdesk.ticket',
            target: 'current',
            type: 'ir.actions.act_window',
            views: [[false, 'form']],
        })
    }
})
