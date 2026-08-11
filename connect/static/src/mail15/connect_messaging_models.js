/** @odoo-module **/

import {
    registerClassPatchModel,
    registerFieldPatchModel,
    registerIdentifyingFieldsPatch,
    registerInstancePatchModel,
} from '@mail/model/model_core';
import { attr, one2one } from '@mail/model/model_field';
import { insertAndReplace } from '@mail/model/model_field_command';

import { str_to_datetime } from 'web.time';


registerFieldPatchModel('mail.discuss', 'connect_messages', {
    categoryConnectMessages: one2one('mail.discuss_sidebar_category', {
        inverse: 'discussAsConnectMessages',
        isCausal: true,
    }),
});

registerFieldPatchModel('mail.discuss_sidebar_category', 'connect_messages', {
    discussAsConnectMessages: one2one('mail.discuss', {
        inverse: 'categoryConnectMessages',
        readonly: true,
    }),
});

registerIdentifyingFieldsPatch(
    'mail.discuss_sidebar_category',
    'connect_messages',
    identifyingFields => identifyingFields[0].push('discussAsConnectMessages'),
);

registerInstancePatchModel('mail.messaging_initializer', 'connect_messages', {
    _initResUsersSettings(settings) {
        this._super(settings);
        this.messaging.discuss.update({
            categoryConnectMessages: insertAndReplace({
                hasAddCommand: false,
                hasViewCommand: false,
                isServerOpen: settings.is_discuss_sidebar_category_connect_messages_open,
                name: this.env._t('Messages'),
                serverStateKey: 'is_discuss_sidebar_category_connect_messages_open',
                sortComputeMethod: 'last_action',
                supportedChannelTypes: ['connect_messages'],
            }),
        });
    },
});

registerInstancePatchModel('mail.messaging_notification_handler', 'connect_messages', {
    _handleNotificationResUsersSettings(settings) {
        const result = this._super(settings);
        if ('is_discuss_sidebar_category_connect_messages_open' in settings) {
            this.messaging.discuss.categoryConnectMessages.update({
                isServerOpen: settings.is_discuss_sidebar_category_connect_messages_open,
            });
        }
        return result;
    },
});

registerClassPatchModel('mail.thread', 'connect_messages', {
    convertData(data) {
        const converted = this._super(data);
        if ('connect_partner_id' in data) {
            converted.connectPartnerId = data.connect_partner_id || false;
        }
        if ('connect_number' in data) {
            converted.connectNumber = data.connect_number;
        }
        if ('connect_channel_provider' in data) {
            converted.connectChannelProvider = data.connect_channel_provider || 'sms';
        }
        if ('connect_whatsapp_window_open' in data) {
            converted.connectWhatsappWindowOpen = data.connect_whatsapp_window_open;
        }
        if ('connect_whatsapp_valid_until' in data) {
            converted.connectWhatsappValidUntil = data.connect_whatsapp_valid_until
                ? str_to_datetime(data.connect_whatsapp_valid_until)
                : false;
        }
        return converted;
    },
});

registerInstancePatchModel('mail.thread', 'connect_messages', {
    _getDiscussSidebarCategory() {
        if (this.channel_type === 'connect_messages') {
            return this.messaging.discuss.categoryConnectMessages;
        }
        return this._super();
    },
});

registerFieldPatchModel('mail.thread', 'connect_messages', {
    connectPartnerId: attr({ default: false }),
    connectNumber: attr(),
    connectChannelProvider: attr({ default: 'sms' }),
    connectWhatsappWindowOpen: attr({ default: false }),
    connectWhatsappValidUntil: attr(),
});

registerClassPatchModel('mail.message', 'connect_messages', {
    convertData(data) {
        const converted = this._super(data);
        if ('connectStatus' in data) {
            converted.connectStatus = data.connectStatus;
        }
        if ('connectMessageType' in data) {
            converted.connectMessageType = data.connectMessageType;
        }
        return converted;
    },
});

registerFieldPatchModel('mail.message', 'connect_messages', {
    connectStatus: attr(),
    connectMessageType: attr(),
});

registerInstancePatchModel('mail.composer', 'connect_messages', {
    _computeCanPostMessage() {
        const canPost = this._super();
        const thread = this.thread;
        if (
            thread &&
            thread.channel_type === 'connect_messages' &&
            thread.connectChannelProvider === 'whatsapp' &&
            !thread.connectWhatsappWindowOpen
        ) {
            return false;
        }
        return canPost;
    },
});

registerInstancePatchModel('mail.composer_view', 'connect_messages', {
    _created() {
        const result = this._super();
        this.onClickAiCompletion = this.onClickAiCompletion.bind(this);
        this.onClickConnectArchive = this.onClickConnectArchive.bind(this);
        this.onClickConnectCreatePartner = this.onClickConnectCreatePartner.bind(this);
        this.onClickConnectOpenPartner = this.onClickConnectOpenPartner.bind(this);
        return result;
    },
    _getMessageData() {
        const data = this._super();
        const thread = this.composer.thread;
        if (thread && thread.channel_type === 'connect_messages') {
            data.message_type = 'connect_message';
            data.connect_provider = thread.connectChannelProvider || 'sms';
        }
        return data;
    },
    async onClickAiCompletion() {
        const thread = this.composer.thread;
        const response = await this.env.services.rpc({
            route: '/connect/ai_completion',
            params: { model: thread.model, res_id: thread.id },
        });
        if (response.status === 'ok') {
            this.composer.update({ textInputContent: response.message });
        } else {
            this.env.services.notification.notify({
                message: response.error_message,
                type: 'warning',
            });
        }
    },
    async onClickConnectArchive() {
        const thread = this.composer.thread;
        await this.env.services.rpc({
            model: 'mail.channel',
            method: 'channel_pin',
            args: [thread.uuid],
            kwargs: { pinned: false },
        });
    },
    async onClickConnectCreatePartner() {
        const thread = this.composer.thread;
        const result = await this.env.services.rpc({
            model: 'mail.channel',
            method: 'connect_create_partner',
            args: [[thread.id]],
        });
        if (result && result.partner_id) {
            thread.update({ connectPartnerId: result.partner_id });
            this.env.services.notification.notify({
                message: _.str.sprintf(
                    this.env._t('Contact created: %s'), result.partner_name),
                type: 'success',
            });
        }
    },
    onClickConnectOpenPartner() {
        const thread = this.composer.thread;
        return this.env.bus.trigger('do-action', {
            action: {
                type: 'ir.actions.act_window',
                res_model: 'res.partner',
                res_id: thread.connectPartnerId,
                views: [[false, 'form']],
            },
        });
    },
});

registerInstancePatchModel('mail.discuss_sidebar_category_item', 'connect_messages', {
    _computeAvatarUrl() {
        if (this.channelType === 'connect_messages') {
            if (this.channel.connectPartnerId) {
                return `/web/image/res.partner/${this.channel.connectPartnerId}/avatar_128`;
            }
            return '/mail/static/src/img/smiley/avatar.jpg';
        }
        return this._super();
    },
    _computeCategoryCounterContribution() {
        if (this.channelType === 'connect_messages') {
            return this.channel.localMessageUnreadCounter > 0 ? 1 : 0;
        }
        return this._super();
    },
    _computeCounter() {
        if (this.channelType === 'connect_messages') {
            return this.channel.localMessageUnreadCounter;
        }
        return this._super();
    },
    _computeHasLeaveCommand() {
        if (this.channelType === 'connect_messages') {
            return false;
        }
        return this._super();
    },
    _computeHasSettingsCommand() {
        if (this.channelType === 'connect_messages') {
            return false;
        }
        return this._super();
    },
    _computeHasThreadIcon() {
        if (this.channelType === 'connect_messages') {
            return false;
        }
        return this._super();
    },
    _computeHasUnpinCommand() {
        if (this.channelType === 'connect_messages') {
            return !this.channel.localMessageUnreadCounter;
        }
        return this._super();
    },
});
