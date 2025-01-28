/** @odoo-module **/
import {registry} from "@web/core/registry"

// TODO: Update event List
const eventList = [
    {model: "connect.server", post_id: 8927457},
    {model: "connect.recording", post_id: 8989865},
]

const serviceRegistry = registry.category("services")

export const intercomStart = (support_data, {show = false}) => {
    const {user_id, user_hash, name, email, created_at} = support_data
    window.intercomSettings = {
        api_base: "https://api-iam.intercom.io",
        app_id: "qijhupkn",
        name, // Full name
        user_id, // a UUID for your user
        email, // the email for your user
        created_at, // Signup date as a Unix timestamp
        user_hash,
    };

    // We pre-filled your app ID in the widget URL: 'https://widget.intercom.io/widget/qijhupkn'
    (function () {
        var w = window;
        var ic = w.Intercom;
        if (typeof ic === "function") {
            ic('reattach_activator');
            ic('update', w.intercomSettings);
            if (show) w.Intercom('show')
        } else {
            var d = document;
            var i = function () {
                i.c(arguments);
            };
            i.q = [];
            i.c = function (args) {
                i.q.push(args);
            };
            w.Intercom = i;
            var l = function () {
                var s = d.createElement('script');
                s.type = 'text/javascript';
                s.async = true;
                s.src = 'https://widget.intercom.io/widget/qijhupkn';
                var x = d.getElementsByTagName('script')[0];
                x.parentNode.insertBefore(s, x)
                if (show) w.Intercom('show')
            };
            if (document.readyState === 'complete') {
                l();
            } else if (w.attachEvent) {
                w.attachEvent('onload', l);
            } else {
                w.addEventListener('load', l, false);
            }
        }
    })();
}

export const intercomStop = () => {
    window.Intercom('shutdown')
}


window.intercomStatus = false;
export const intercomService = {
    dependencies: ["user", "orm"],

    async start(env, {user, orm}) {
        let url = location.href
        const isAsteriskAdmin = await user.hasGroup('connect.group_asterisk_admin')

        if (isAsteriskAdmin) {
            const self = this
            self.support_data = await orm.call('connect.settings', 'get_instance_support_data')
            if (self.support_data == false) return // Intercom is not enabled.
            self.manageIntercom(location.href)
            if (window.navigation) {
                navigation.addEventListener("navigate", (event) => {
                    self.manageIntercom(event.destination.url)
                })
            } else {
                setInterval(() => {
                    if (url !== location.href) {
                        url = location.href
                        self.manageIntercom(location.href)
                    }
                }, 1000)
            }
        }
    },

    manageIntercom(url) {

        eventList.forEach((event) => {
            if (url.includes(event.model)) {
                let connect_setup = localStorage.getItem('connect_setup')
                connect_setup = connect_setup ? JSON.parse(connect_setup) : []
                if (!connect_setup.includes(event.post_id)) {
                    connect_setup.push(event.post_id)
                    localStorage.setItem('connect_setup', JSON.stringify(connect_setup))
                    window.Intercom('showArticle', event.post_id)
                }
            }
        })

        if (url.includes('model=connect')) {
            if (!window.intercomStatus) {
                window.intercomStatus = true
                intercomStart(this.support_data, {show: false})
            }
        } else {
            setTimeout(() => {
                if (window.ConnectSupport) return
                if (window.intercomStatus && typeof window.Intercom === "function") {
                    window.intercomStatus = false
                    intercomStop()
                }
            }, 500)

        }
    },
}

serviceRegistry.add("intercomService", intercomService)