/** @odoo-module **/

import {registry} from "@web/core/registry"
import {user} from "@web/core/user"

const {markup} = owl

var personal_channel = 'connect_actions_' + user.userId

export const pbxActionService = {
    dependencies: ["notification", 'bus_service'],

    start(env, {notification, bus_service}) {
        this.notification = notification

        bus_service.addChannel(personal_channel)
        bus_service.subscribe("connect_notify", (action) => this.connect_handle_notify(action))
    },

    connect_handle_notify: function ({title, message, sticky, warning}) {
        if (warning === true)
            this.notification.add(markup(message), {title, sticky, type: 'danger'})
        else
            this.notification.add(markup(message), {title, sticky, type: 'info'})
    },
}

registry.category("services").add("connectActionService", pbxActionService)