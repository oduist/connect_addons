/** @odoo-module **/
import {Component} from "@odoo/owl"

export class ConnectActiveCallsTray extends Component {
    static template = 'connect.active_calls_tray'
    static props = {
        bus: Object,
    }

    _onClick() {
        this.props.bus.trigger('connect_active_calls_toggle_display')
    }
}

