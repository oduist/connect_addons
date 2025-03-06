/** @odoo-module **/

import {registry} from "@web/core/registry"
import {routerBus} from "@web/core/browser/router"
import {user} from "@web/core/user"

const {markup} = owl

var personal_channel = 'connect_actions_' + user.userId
var common_channel = 'connect_actions'

export const pbxActionService = {
    dependencies: ["action", "notification", 'bus_service'],

    start(env, {action, notification, bus_service}) {
        this.action = action
        this.notification = notification

        bus_service.addChannel(personal_channel)
        bus_service.addChannel(common_channel)
        bus_service.subscribe("connect_notify", (action) => this.connect_handle_notify(action))
        bus_service.subscribe("reload_view", (action) => this.connect_handle_reload_view(action))
    },

    connect_handle_reload_view: function (message) {
        if (!this.action || !this.action.currentController) return
        const action = this.action.currentController.action
        if (action.res_model === message.model) {
            routerBus.trigger("ROUTE_CHANGE")
        }
    },

    connect_handle_notify: function ({title, message, sticky, warning}) {
        if (warning === true)
            this.notification.add(markup(message), {title, sticky, type: 'danger'})
        else
            this.notification.add(markup(message), {title, sticky, type: 'info'})
    },
}

registry.category("services").add("connectActionService", pbxActionService)