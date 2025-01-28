/** @odoo-module **/
import {registry} from "@web/core/registry"
import {ConnectActiveCallsTray} from "./active_calls_tray"
import {ConnectActiveCallsPopup} from "./active_calls_popup"
import {EventBus} from "@odoo/owl"


export const ConnectActiveCallsService = {
    async start(env, {}) {
        let bus = new EventBus()
        registry.category("systray").add('activeCallsTray', {Component: ConnectActiveCallsTray, props: {bus}})
        registry.category("main_components").add('activeCallsPopup', {Component: ConnectActiveCallsPopup, props: {bus}})
    }
}

registry.category('services').add("connect_active_calls", ConnectActiveCallsService)
