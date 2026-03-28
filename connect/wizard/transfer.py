from odoo import models, fields, api
from twilio.twiml.voice_response import VoiceResponse, Dial
from urllib.parse import urljoin
import logging

logger = logging.getLogger(__name__)

class CallForwardHandler(models.TransientModel):
    _name = 'connect.transfer_wizard'
    _description = 'Transfer Wizard'

    phone_number = fields.Char(string='Phone Number', required=True)

    def action_confirm(self):
        # Legacy method for manual wizard usage
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def execute_transfer(self, phone_number, transfer_type, call_id=None, session_id=None):
        """
        Execute a call transfer using Twilio TwiML
        
        :param phone_number: Target phone number or extension
        :param transfer_type: 'blind' for immediate transfer, 'attended' for consultation
        :param call_id: Odoo call record ID (optional)
        :param session_id: Twilio Call SID for the active call
        :return: dict with success status and message
        """
        try:
            logger.info(
                'Transfer request: phone_number=%s transfer_type=%s call_id=%s session_id=%s',
                phone_number, transfer_type, call_id, session_id
            )
            if not session_id:
                return {
                    'success': False,
                    'error': 'No active call session found'
                }

            # Get Twilio client
            client = self.env['connect.settings'].get_client()
            if not client:
                return {
                    'success': False,
                    'error': 'Twilio client not configured'
                }

            # Determine if phone_number is an extension or external number
            target_number = self._resolve_phone_number(phone_number)
            logger.info('Resolved transfer target: %s -> %s', phone_number, target_number)
            
            if transfer_type == 'blind':
                success = self._execute_blind_transfer(client, session_id, target_number, call_id)
            elif transfer_type == 'attended':
                success = self._execute_attended_transfer(client, session_id, target_number, call_id)
            else:
                return {
                    'success': False,
                    'error': 'Invalid transfer type. Must be "blind" or "attended"'
                }

            if success:
                # Log the transfer attempt
                self._log_transfer_attempt(call_id, phone_number, transfer_type, session_id)
                
                return {
                    'success': True,
                    'message': f'{transfer_type.capitalize()} transfer initiated to {phone_number}'
                }
            else:
                return {
                    'success': False,
                    'error': 'Transfer failed - unable to update call'
                }

        except Exception as e:
            logger.exception(f'Transfer execution failed: {e}')
            return {
                'success': False,
                'error': f'Transfer failed: {str(e)}'
            }

    @api.model
    def debug_user_identity(self, extension_number):
        """
        Debug method to understand how client identities work in your system
        """
        try:
            # Look up the extension
            extension = self.env['connect.exten'].search([('number', '=', extension_number)], limit=1)
            if not extension or not extension.dst or extension.dst._name != 'connect.user':
                return {'error': f'Extension {extension_number} not found or not pointing to user'}
            
            user = extension.dst
            debug_info = {
                'extension_number': extension_number,
                'extension_name': extension.name,
                'user_name': user.name,
                'user_uri': user.uri,
                'user_username': getattr(user, 'username', 'N/A'),
                'user_client_enabled': user.client_enabled,
                'user_id': user.id,
            }
            
            # Check if there's an Odoo user linked
            if hasattr(user, 'user') and user.user:
                debug_info['odoo_user_name'] = user.user.name
                debug_info['odoo_user_login'] = user.user.login
            
            # Try different client identity formats
            uri_parts = user.uri.split('@') if user.uri else []
            debug_info['possible_identities'] = {
                'full_uri': user.uri,
                'username_part': uri_parts[0] if uri_parts else None,
                'username_field': getattr(user, 'username', None),
                'user_id_format': f'user{user.id}',
                'extension_format': f'ext{extension_number}',
            }
            
            return debug_info
            
        except Exception as e:
            logger.error(f'Debug user identity failed: {e}', exc_info=True)
            return {'error': str(e)}

    @api.model
    def debug_current_call_state(self, session_id):
        """
        Debug the current state of a call before and after transfer - fixed attributes
        """
        try:
            client = self.env['connect.settings'].get_client()
            call = client.calls(session_id).fetch()
            
            debug_info = {
                'call_sid': call.sid,
                'status': call.status,
                'direction': call.direction,
                'from_number': getattr(call, 'from_', getattr(call, 'from_formatted', 'Unknown')),
                'to_number': getattr(call, 'to', getattr(call, 'to_formatted', 'Unknown')),
                'start_time': str(call.start_time) if call.start_time else None,
                'end_time': str(call.end_time) if call.end_time else None,
                'duration': call.duration,
                'price': getattr(call, 'price', 'Unknown'),
                'answered_by': getattr(call, 'answered_by', 'N/A'),
                'parent_call_sid': getattr(call, 'parent_call_sid', 'N/A'),
                'queue_time': getattr(call, 'queue_time', 'N/A')
            }
            
            return debug_info
            
        except Exception as e:
            logger.error(f'Could not get call state: {e}')
            return {'error': str(e)}

    def _resolve_phone_number(self, phone_number):
        """
        Convert extension numbers to Twilio Client identities with enhanced debugging
        """
        if not phone_number:
            logger.warning('Transfer resolve: empty phone number')
            return phone_number
        # Check if it's a numeric extension (internal)
        if phone_number.isdigit() and len(phone_number) <= 4:
            # Get detailed debug info
            debug_info = self.debug_user_identity(phone_number)
            
            # Look up the extension in connect.exten
            extension = self.env['connect.exten'].search([('number', '=', phone_number)], limit=1)
            
            if extension and extension.dst and extension.dst._name == 'connect.user':
                user = extension.dst
                
                # Try multiple identity formats based on your system
                possible_identities = []
                
                if hasattr(user, 'username') and user.username:
                    possible_identities.append(f'client:{user.username}')
                
                if hasattr(user, 'uri') and user.uri:
                    # Extract client identity from URI (remove @domain part)
                    client_identity = user.uri.split('@')[0] if '@' in user.uri else user.uri
                    possible_identities.append(f'client:{client_identity}')
                
                # Try user ID format
                possible_identities.append(f'client:user{user.id}')
                
                # For now, let's use the URI-based one (what we were using before)
                if user.uri:
                    client_identity = user.uri.split('@')[0] if '@' in user.uri else user.uri
                    client_target = f'client:{client_identity}'
                    logger.info('Resolved extension %s to %s', phone_number, client_target)
                    return client_target
                else:
                    # Fallback client identity based on extension
                    client_target = f'client:user{phone_number}'
                    logger.info('Resolved extension %s to fallback %s', phone_number, client_target)
                    return client_target
            
            else:
                logger.warning(f'Extension {phone_number} not found or not pointing to user')
                # Still try as client identity - maybe it's a valid extension
                client_target = f'client:user{phone_number}'
                return client_target
        else:
            # External phone number - ensure it has proper formatting
            if not phone_number.startswith('+'):
                # Try to get default country code from settings, fallback to US
                try:
                    default_country = self.env['connect.settings'].sudo().get_param('default_country_code') or '1'
                    phone_number = f'+{default_country}{phone_number}'
                except:
                    phone_number = f'+1{phone_number}'  # Fallback to US
            
            logger.info('Resolved external number to %s', phone_number)
            return phone_number

    def _execute_blind_transfer(self, client, session_id, target_number, call_id=None):
        """
        Execute immediate blind transfer using extension render method (like ElevenLabs)
        """
        try:
            if target_number.startswith('client:'):
                # Extract extension number from client identity
                # We need to find which extension this client identity maps to
                extension_number = self._find_extension_by_client_identity(target_number)
                if extension_number:
                    return self._execute_extension_transfer(client, session_id, extension_number, 'blind', call_id)
                else:
                    logger.error(f'Could not find extension for client identity: {target_number}')
                    return False
            else:
                # External number - use our original TwiML approach
                response = VoiceResponse()
                dial = Dial(timeout=30)
                dial.number(target_number)
                response.append(dial)
                
                twiml_str = str(response)
                
                result = client.calls(session_id).update(twiml=twiml_str)
                return True
            
        except Exception as e:
            logger.error(f'Blind transfer failed: {e}', exc_info=True)
            return False

    def _execute_attended_transfer(self, client, session_id, target_number, call_id=None):
        """
        Execute attended transfer using extension render method
        """
        try:
            if target_number.startswith('client:'):
                # Extract extension number from client identity
                extension_number = self._find_extension_by_client_identity(target_number)
                if extension_number:
                    return self._execute_extension_transfer(client, session_id, extension_number, 'attended', call_id)
                else:
                    logger.error(f'Could not find extension for attended transfer: {target_number}')
                    return False
            else:
                # External number - use TwiML approach with announcement
                response = VoiceResponse()
                processed_text = self.env['connect.settings'].process_pronunciation('Transferring your call now.')
                response.say(processed_text)
                dial = Dial(timeout=30)
                dial.number(target_number)
                response.append(dial)
                
                twiml_str = str(response)
                
                result = client.calls(session_id).update(twiml=twiml_str)
                return True
                
        except Exception as e:
            logger.error(f'Attended transfer failed: {e}', exc_info=True)
            return False

    def _find_extension_by_client_identity(self, client_identity):
        """
        Find extension number from client identity (reverse lookup) - fixed search
        """
        try:
            # Remove 'client:' prefix
            identity = client_identity.replace('client:', '')
            identity = identity.split('@')[0] if identity else identity

            if not identity:
                logger.warning('Client identity missing for extension lookup: %s', client_identity)
                return None

            # Look for user with matching username (stored field only).
            user = self.env['connect.user'].search([
                ('username', '=', identity)
            ], limit=1)

            # Fallback: try extension number directly.
            if not user:
                extension = self.env['connect.exten'].search([
                    ('number', '=', identity)
                ], limit=1)
                if extension:
                    logger.info(
                        'Mapped client identity %s to extension %s via direct extension lookup',
                        client_identity, extension.number
                    )
                    return extension.number
                logger.warning('Could not find extension for client identity: %s', client_identity)
                return None

            # Find extension pointing to this user using stored fields.
            extension = self.env['connect.exten'].search([
                ('model', '=', 'connect.user'),
                ('res_id', '=', user.id)
            ], limit=1)

            if extension:
                logger.info(
                    'Mapped client identity %s to extension %s via user %s',
                    client_identity, extension.number, user.username
                )
                return extension.number

            logger.warning('Could not find extension for client identity: %s', client_identity)
            return None

        except Exception as e:
            logger.error(f'Error finding extension by client identity: {e}')
            return None

    def _execute_extension_transfer(self, client, session_id, extension_number, transfer_type, call_id=None):
        """
        Execute transfer with different behavior for blind vs attended transfers
        """
        try:
            logger.info(
                'Extension transfer start: extension=%s transfer_type=%s session_id=%s call_id=%s',
                extension_number, transfer_type, session_id, call_id
            )
            # Debug call state BEFORE transfer
            pre_transfer_state = self.debug_current_call_state(session_id)
            
            # Check if this is a child call with a parent
            parent_call_sid = pre_transfer_state.get('parent_call_sid')
            if parent_call_sid and parent_call_sid != 'N/A':
                target_call_sid = parent_call_sid
                
                # Debug the parent call state
                parent_state = self.debug_current_call_state(parent_call_sid)
            else:
                target_call_sid = session_id
            
            # Find the extension
            extension = self.env['connect.exten'].search([('number', '=', extension_number)], limit=1)
            if not extension:
                logger.error(f'Extension {extension_number} not found')
                return False
            
            # Get the user this extension points to
            if not extension.dst or extension.dst._name != 'connect.user':
                logger.error(f'Extension {extension_number} does not point to a connect.user')
                return False
                
            user = extension.dst
            
            # Track the transfer in the call record
            if user.user:
                try:
                    # Try to find the call record from the session_id
                    call = None
                    if call_id:
                        call = self.env['connect.call'].sudo().browse(call_id)
                    
                    if not call or not call.exists():
                        # Fallback: Find call by looking up channel with session_id
                        channel = self.env['connect.channel'].sudo().search([('sid', '=', session_id)], limit=1)
                        if channel and channel.call:
                            call = channel.call
                        else:
                            logger.warning(f'No call found for session {session_id}')
                            
                            # If parent call was detected, try looking up with target_call_sid (parent)
                            if parent_call_sid and parent_call_sid != session_id:
                                parent_channel = self.env['connect.channel'].sudo().search([('sid', '=', parent_call_sid)], limit=1)
                                if parent_channel and parent_channel.call:
                                    call = parent_channel.call
                                else:
                                    logger.warning(f'No call found for parent {parent_call_sid} either')
                    
                    if call and call.exists():
                        try:
                            call.add_transferred_user(user.user)
                        except Exception as e:
                            logger.warning(f'Could not add transfer user (concurrent update): {e}')
                        
                        try:
                            # Store transfer context for webhook processing (use target_call_sid as key)
                            call.store_transfer_context(target_call_sid, user.user)
                        except Exception as e:
                            logger.warning(f'Could not store transfer context: {e}')
                        
                        try:
                            # EXPLICIT PATTERN TAGGING: Ensure call pattern is set for transfers
                            if not call.call_pattern:
                                call.call_pattern = 'direct_call'  # Transfers only happen from direct calls
                        except Exception as e:
                            logger.warning(f'Could not set call pattern: {e}')
                    else:
                        logger.warning(f'Could not find call record to track transfer to {user.user.login}')
                except Exception as e:
                    logger.error(f'Failed to track transfer in call record: {e}', exc_info=True)
            
            # Determine if this is an outgoing call to use appropriate transfer method
            is_outgoing_call = False
            if call and call.exists():
                is_outgoing_call = call.direction == 'outgoing'
                
                # Log current user context for debugging user-specific issues
                current_user = self.env.user
                
                # See if we can identify which connect.user is involved
                connect_user = self.env['connect.user'].search([('user', '=', current_user.id)], limit=1)
            
            # Use unified direct extension redirect approach for ALL transfers
            if transfer_type == 'blind':
                # Use direct extension redirect - simpler and more reliable for both incoming and outgoing
                result = self._execute_extension_redirect(client, target_call_sid, user, call, is_outgoing_call)
                return result
            else:
                # Only use TwiML for attended transfers (which are rare)
                twiml_str = self._create_attended_transfer_twiml(user, target_call_sid)
                
                # Update the CORRECT call (parent if exists, otherwise current)
                result = client.calls(target_call_sid).update(twiml=twiml_str)
                
                return True
            
        except Exception as e:
            logger.error(f'=== TRANSFER FAILED WITH EXCEPTION ===')
            logger.error(f'Exception: {e}', exc_info=True)
            return False

    def _create_blind_transfer_twiml(self, user, outgoing_call=None):
        """
        For outgoing calls, use bridge transfer approach instead of TwiML modification
        This prevents external party disconnection by not modifying the original call flow
        """
        if outgoing_call and outgoing_call.direction == 'outgoing':
            # For outgoing calls, return minimal TwiML and handle via bridge method
            response = VoiceResponse()
            processed_text = self.env['connect.settings'].process_pronunciation('Transferring your call now.')
            response.say(processed_text)

            twiml_output = str(response)
            return twiml_output
        
        # For incoming calls, use the standard TwiML approach
        response = VoiceResponse()
        processed_text = self.env['connect.settings'].process_pronunciation('Transferring your call now.')
        response.say(processed_text)

        # Get the base URL for webhook callbacks
        api_url = self.env['connect.settings'].sudo().get_param('api_url')
        edge = self.env['connect.settings'].get_param('twilio_edge')
        
        # Create action URL with transfer context for continuation logic
        action_url = urljoin(api_url, f'twilio/webhook/transfer_continuation#e={edge}')
        
        # Create the transfer dial with action continuation
        dial = Dial(
            timeout=30,
            action=action_url,
            method='POST'
        )
        
        from twilio.twiml.voice_response import Client
        client_elem = Client()
        client_elem.identity(user.uri)
        dial.append(client_elem)
        
        response.append(dial)
        
        # Critical: Add continuation TwiML that executes AFTER the dial completes
        processed_text = self.env['connect.settings'].process_pronunciation('Call could not be completed. Please try again.')
        response.say(processed_text)
        response.hangup()
        
        twiml_output = str(response)
        
        return twiml_output

    def _execute_extension_redirect(self, client, call_sid, user, call, is_outgoing_call):
        """
        Execute outgoing call transfer by redirecting external caller directly to target's extension.
        This is simpler and provides better UX than conference transfers.
        """
        try:
            # Create the redirect URL
            api_url = self.env['connect.settings'].sudo().get_param('api_url')
            edge = self.env['connect.settings'].get_param('twilio_edge')
            extension_url = urljoin(api_url, f'connect/{user.exten.number}#e={edge}')
            
            if is_outgoing_call:
                # OUTGOING CALL: Redirect the external call leg, hang up the original caller
                
                external_call_sid = call.get_external_call_leg()
                if not external_call_sid:
                    logger.error('Could not find external call leg for outgoing transfer')
                    return False
                
                # Play transfer message to external caller, then redirect
                transfer_response = VoiceResponse()
                processed_text = self.env['connect.settings'].process_pronunciation('Transferring your call now.')
                transfer_response.say(processed_text)
                transfer_response.pause(length=1)
                transfer_response.redirect(extension_url, method='GET')
                
                # Update the external call with the transfer message + redirect
                redirect_result = client.calls(external_call_sid).update(
                    twiml=str(transfer_response)
                )
                
                # Check if original caller is still active before hanging up
                try:
                    original_call_status = client.calls(call_sid).fetch()
                    if original_call_status.status in ['in-progress', 'ringing']:
                        hangup_response = VoiceResponse()
                        hangup_response.hangup()
                        original_result = client.calls(call_sid).update(twiml=str(hangup_response))
                except Exception as e:
                    logger.warning(f'Could not check/update original caller status: {e}')
            else:
                # INCOMING CALL: Redirect the current call directly to extension
                
                # Play transfer message, then redirect to extension
                transfer_response = VoiceResponse()
                processed_text = self.env['connect.settings'].process_pronunciation('Transferring your call now.')
                transfer_response.say(processed_text)
                transfer_response.pause(length=1)
                transfer_response.redirect(extension_url, method='GET')
                
                # Update the current call with redirect
                redirect_result = client.calls(call_sid).update(
                    twiml=str(transfer_response)
                )
            
            return True
            
        except Exception as e:
            logger.error(f'Extension redirect failed: {e}', exc_info=True)
            return False

    def _get_original_caller_for_transfer(self, call):
        """
        Extract the original external caller information for outgoing call transfers
        This ensures the transfer recipient sees the external caller, not the internal user
        """
        try:
            if not call or call.direction != 'outgoing':
                return None
            
            # For outgoing calls, the external party info should be in the called field or channels
            if call.called and call.called.startswith('+'):
                return call.called
            
            # Look for external number in channels
            for channel in call.channels:
                if channel.technical_direction == 'outbound-dial' and channel.called and channel.called.startswith('+'):
                    return channel.called
            
            logger.warning('Could not extract original caller from outgoing call')
            return None
            
        except Exception as e:
            logger.error(f'Error extracting original caller: {e}')
            return None

    def _log_transfer_attempt(self, call_id, phone_number, transfer_type, session_id):
        """Log transfer attempt for debugging and tracking"""
        try:
            log_message = f'{transfer_type.capitalize()} transfer to {phone_number} for session {session_id}'
            if call_id:
                log_message += f' (Call ID: {call_id})'
            logger.info(log_message)
        except Exception as e:
            logger.warning(f'Could not log transfer attempt: {e}')

    def _create_attended_transfer_twiml(self, user, target_call_sid):
        """Create TwiML for attended transfer"""
        response = VoiceResponse()
        processed_text = self.env['connect.settings'].process_pronunciation('Setting up consultation call.')
        response.say(processed_text)
        
        dial = Dial(timeout=30)
        from twilio.twiml.voice_response import Client
        client_elem = Client()
        client_elem.identity(user.uri)
        dial.append(client_elem)
        response.append(dial)
        
        return str(response)

    def _get_caller_id_for_transfer(self, session_id):
        """
        Get appropriate caller ID for transfer call with multiple fallbacks
        """
        try:
            # Simple fallback caller ID
            default_caller_id = self.env['connect.settings'].sudo().get_param('default_caller_id')
            if default_caller_id:
                return default_caller_id
            
            # Ultimate fallback
            return '+15551234567'
            
        except Exception as e:
            logger.error(f'Error getting caller ID: {e}')
            return '+15551234567'

    def _redirect_to_transfer_target_extension(self, failed_call_sid, response):
        """Legacy method - not used with new direct redirect approach"""
        response.hangup()
        return response

    @api.model
    def handle_transfer_continuation(self, webhook_params):
        """
        Handle the action callback from transfer dial completion.
        For successful transfers, update completion status.
        For failed transfers, route the external caller to the transfer target's voicemail.
        """
        call_sid = webhook_params.get('CallSid')
        dial_call_status = webhook_params.get('DialCallStatus')
        dial_call_sid = webhook_params.get('DialCallSid')
        
        # Find the call record
        call_channel = self.env['connect.channel'].sudo().search([('sid', '=', call_sid)], limit=1)
        if not call_channel or not call_channel.call:
            logger.warning(f'Could not find call for transfer continuation: {call_sid}')
            response = VoiceResponse()
            response.hangup()
            return response
        
        call = call_channel.call
        
        # If transfer recipient answered (DialCallStatus: completed), update completion status
        if dial_call_status == 'completed' and call.transferred_users:
            # Find the transfer recipient who answered by looking at transfer context
            transfer_context = call.transfer_context or {}
            transfer_recipient_login = None
            
            # Look for the transfer recipient in the context using call SID or dial call SID
            for context_key, context_value in transfer_context.items():
                if context_key.startswith('_'):  # Skip internal keys like _external_leg
                    continue
                if context_key in (call_sid, dial_call_sid):
                    if isinstance(context_value, dict) and 'user_id' in context_value:
                        transfer_recipient_login = context_value.get('user_login')
                        break
            
            if transfer_recipient_login:
                # Find the user and set as completed_by_user
                transfer_recipient = self.env['res.users'].sudo().search([('login', '=', transfer_recipient_login)], limit=1)
                if transfer_recipient:
                    call.completed_by_user = transfer_recipient
                else:
                    logger.warning(f'Could not find user with login {transfer_recipient_login}')
            else:
                # Fallback: use the first transfer recipient
                if call.transferred_users:
                    call.completed_by_user = call.transferred_users[0]
        
        response = VoiceResponse()
        response.hangup()
        return response
