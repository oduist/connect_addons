/** @odoo-module **/

import {registry} from "@web/core/registry"
import {session} from "@web/session"

const {markup} = owl

var personal_channel = 'connect_actions_' + session.uid
var common_channel = 'connect_actions'

export const pbxActionService = {
    dependencies: ["action", "notification", 'bus_service'],

    start(env, {action, notification, bus_service}) {
        this.action = action
        this.notification = notification

        bus_service.addChannel(personal_channel)
        bus_service.addChannel(common_channel)
        bus_service.addEventListener('notification', (action) => this.on_connect_action(action))
    },

    on_connect_action: function (action) {
        for (var i = 0; i < action.detail.length; i++) {
            try {
                var {type, payload} = action.detail[i]
                if (typeof payload === 'string')
                    payload = JSON.parse(payload)
                if (type === 'connect_notify')
                    this.connect_handle_notify(payload);
                else if (type === 'open_record')
                    this.connect_handle_open_record(payload)
                else if (type === 'reload_view')
                    this.connect_handle_reload_view(payload)
            } catch (e) {
                console.log(e)
            }
        }
    },

    connect_handle_open_record: function (message) {
        // console.log('Opening record form')
        let action = this.action.currentController.action
        if (action.res_model === 'connect.call') {
            this.action.doAction({
                'type': 'ir.actions.act_window',
                'res_model': message.model,
                'target': 'current',
                'res_id': message.res_id,
                'views': [[message.view_id, 'form']],
                'view_mode': 'tree,form',
            })
        }
    },

    connect_handle_reload_view: function (message) {
        const action = this.action.currentController.action

        if (action.res_model !== message.model) {
            // console.log('Not message model view')
            return
        }

        this.bus.trigger("ROUTE_CHANGE")
    },

    connect_handle_notify: function ({title, message, sticky, warning}) {
        if (warning === true)
            this.notification.add(markup(message), {title, sticky, type: 'danger'})
        else
            this.notification.add(markup(message), {title, sticky, type: 'info'})
    },
}

registry.category("services").add("connectActionService", pbxActionService)