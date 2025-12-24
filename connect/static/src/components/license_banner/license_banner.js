/** @odoo-module **/

/*
 * ODUIST PROPRIETARY LICENSE
 * Copyright (c) 2025 Oduist
 *
 * This file contains license validation logic.
 * Modification is prohibited under Oduist Proprietary License.
 * See LICENSE and COPYRIGHT files for full terms.
 */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class LicenseBanner extends Component {
    static template = "connect.LicenseBanner";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            visible: false,
            status: null,
            message: "",
            type: "info", // info, warning, danger
        });

        onWillStart(async () => {
            await this.loadLicenseStatus();
        });
    }

    async loadLicenseStatus() {
        try {
            const result = await this.orm.call(
                "connect.license",
                "get_license_status",
                ["connect"]
            );

            if (!result) {
                return;
            }

            // Show banner for trial, demo and expired states
            if (result.status === "demo") {
                this.state.visible = true;
                this.state.status = result.status;
                this.state.message = "Connect Module Demo";
                this.state.type = "warning";
            } else if (result.status === "trial_active") {
                this.state.visible = true;
                this.state.status = result.status;
                this.state.message = `Connect Module Trial: ${result.days_left} days remaining`;
                this.state.type = result.days_left <= 7 ? "warning" : "info";
            } else if (result.status === "trial_expired") {
                this.state.visible = true;
                this.state.status = result.status;
                this.state.message = "Connect Module Trial Expired";
                this.state.type = "danger";
            }
            // Don't show banner for licensed state
        } catch (error) {
            console.error("Failed to load license status:", error);
        }
    }

    get bannerClass() {
        const baseClass = "connect-license-banner";
        return `${baseClass} ${baseClass}-${this.state.type}`;
    }

    async openSettings() {
        const [res_id] = await this.orm.search("connect.settings",  [], {limit: 1})
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "connect.settings",
            res_id: res_id,
            action_id: "connect.connect_settings_action",
            views: [[false, "form"]],
        });
    }
}

// Register as a systray item to appear in navbar
export const systrayItem = {
    Component: LicenseBanner,
};

registry.category("systray").add("connect.LicenseBanner", systrayItem, { sequence: 1 });
