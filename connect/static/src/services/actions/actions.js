/** @odoo-module **/

import {registry} from "@web/core/registry"
import {uid} from "web.session"

const {markup} = owl

var personal_channel = 'connect_actions_' + uid
var common_channel = 'connect_actions'

export const connectActionService = {
    dependencies: ["action", "notification"],

    start(env, {action, notification, bus_service}) {
        this.bus = env.bus
        this.action = action
        this.notification = notification

        const legacyEnv = owl.Component.env
        legacyEnv.services.bus_service.addChannel(personal_channel)
        legacyEnv.services.bus_service.addChannel(common_channel)
        legacyEnv.services.bus_service.onNotification(this, this.on_connect_action)
        legacyEnv.services.bus_service.startPolling()
    },

    on_connect_action: function (action) {
        for (var i = 0; i < action.length; i++) {
            try {
                var {type, payload} = action[i]
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
        if (!this.action || !this.action.currentController) return
        const action = this.action.currentController.action
        if (action.res_model === message.model) {
            this.bus.trigger("ROUTE_CHANGE")
        }
    },

    connect_handle_notify: function ({title, message, sticky, warning}) {
        if (warning === true)
            this.notification.add(message, {title, sticky, type: 'danger', messageIsHtml: true})
        else
            this.notification.add(message, {title, sticky, type: 'info', messageIsHtml: true})
    },
}

registry.category("services").add("connectActionService", connectActionService)