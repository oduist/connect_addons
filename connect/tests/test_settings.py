# -*- coding: utf-8 -*-
"""
Tests for connect.settings model

Module contains comprehensive tests for functionality verification
of Connect telecommunications system settings model.
"""
import json
import uuid
from unittest.mock import patch, MagicMock, Mock
from urllib.parse import urljoin

import odoo.tests.common as common
from odoo.exceptions import ValidationError, UserError


class TestConnectSettings(common.TransactionCase):
    """Test class for connect.settings model"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.settings_model = self.env['connect.settings']
        
        # Create test data
        self.test_settings = self.settings_model.create({
            'debug_mode': False,
            'twilio_auto_sync': True,
            'twilio_region': 'us1',
            'twilio_edge': 'ashburn',
            'account_sid': 'ACtest123456789',
            'auth_token': 'test_auth_token',
            'twilio_api_key': 'SKtest123456789',
            'twilio_api_secret': 'test_secret',
            'openai_api_key': 'sk-test-openai-key',
            'number_search_operation': '=',
            'proxy_recordings': True,
            'transcript_calls': False,
            'transcript_provider': 'openai',
            'summary_prompt': 'Test summary prompt',
            'register_summary': True,
            'fetch_call_prices': False,
            'twilio_verify_requests': True,
            'customer_code': 'TEST123',
            'is_registered': False,
            'i_agree_to_register': True,
            'i_agree_to_contact': True,
            'i_agree_to_receive': True,
            'company_name': 'Test Company',
            'admin_name': 'Test Admin',
            'admin_email': 'admin@test.com',
            'admin_phone': '+1234567890',
        })

    def test_settings_model_creation(self):
        """Test settings model creation"""
        self.assertTrue(self.test_settings)
        self.assertEqual(self.test_settings.name, 'General Settings')
        self.assertTrue(self.test_settings.twilio_auto_sync)
        self.assertEqual(self.test_settings.twilio_region, 'us1')
        self.assertEqual(self.test_settings.twilio_edge, 'ashburn')

    def test_get_set_param_methods(self):
        """Test get_param and set_param methods"""
        # Test get_param
        self.assertEqual(self.test_settings.get_param('debug_mode'), False)
        self.assertEqual(self.test_settings.get_param('twilio_region'), 'us1')
        
        # Test set_param
        self.test_settings.set_param('debug_mode', True)
        self.assertEqual(self.test_settings.get_param('debug_mode'), True)
        
        # Test with default parameter
        self.assertEqual(self.test_settings.get_param('nonexistent_param', 'default'), 'default')

    def test_open_settings_form(self):
        """Test opening settings form"""
        action = self.test_settings.open_settings_form()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'connect.settings')
        self.assertEqual(action['view_mode'], 'form')

    def test_set_defaults(self):
        """Test setting default values"""
        # Remove parameters to test default setting
        self.env['ir.config_parameter'].sudo().search([
            ('key', 'like', 'connect.%')
        ]).unlink()
        
        self.settings_model.set_defaults()
        
        api_url = self.env['ir.config_parameter'].sudo().get_param('connect.api_url')
        installation_date = self.env['ir.config_parameter'].sudo().get_param('connect.installation_date')
        
        self.assertTrue(api_url)
        self.assertTrue(installation_date)

    def test_set_instance_uid(self):
        """Test instance UID setting"""
        self.settings_model.set_instance_uid()
        instance_uid = self.env['ir.config_parameter'].sudo().get_param('connect.instance_uid')
        self.assertTrue(instance_uid)
        
        # Second call should not change UID
        old_uid = instance_uid
        self.settings_model.set_instance_uid()
        new_uid = self.env['ir.config_parameter'].sudo().get_param('connect.instance_uid')
        self.assertEqual(old_uid, new_uid)

    def test_set_default_admin_and_company(self):
        """Test setting default admin and company data"""
        self.test_settings.admin_name = False
        self.test_settings.company_name = False
        self.test_settings.set_default_admin_and_company()
        
        self.assertEqual(self.test_settings.company_name, self.env.user.company_id.name)
        self.assertEqual(self.test_settings.admin_name, self.env.user.partner_id.name)

    def test_connect_notify(self):
        """Test notifications"""
        with patch('odoo.addons.connect.models.settings.release') as mock_release:
            mock_release.version_info = [15, 0, 0]
            with patch.object(self.env['bus.bus'], '_sendone') as mock_send:
                result = self.settings_model.connect_notify(
                    'Test message', 
                    title='Test Title',
                    notify_uid=self.env.uid
                )
                self.assertTrue(result)
                mock_send.assert_called_once()

    def test_prepare_registration_data(self):
        """Test registration data preparation"""
        # Set required data
        self.test_settings.company_country_id = self.env.ref('base.us')
        
        data = self.test_settings.prepare_registration_data()
        
        self.assertIn('instance_uid', data)
        self.assertIn('company_name', data)
        self.assertIn('admin_email', data)
        self.assertEqual(data['module_name'], 'connect')
        self.assertEqual(data['customer_code'], 'TEST123')

    def test_register_instance_validation(self):
        """Test instance registration validation"""
        # Test without admin rights
        with self.assertRaises(ValidationError) as context:
            self.test_settings.with_user(self.env.ref('base.user_demo')).register_instance()
        self.assertIn('Only Odoo admin can do it', str(context.exception))

    def test_register_instance_missing_fields(self):
        """Test registration with missing fields"""
        self.test_settings.customer_code = False
        with self.assertRaises(ValidationError) as context:
            self.test_settings.register_instance()
        self.assertIn('customer code', str(context.exception))

    @patch('requests.post')
    def test_register_instance_success(self, mock_post):
        """Test successful instance registration"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'registration_key': 'test_key',
            'registration_number': 'test_number'
        }
        mock_post.return_value = mock_response
        
        # Set required data
        self.test_settings.company_country_id = self.env.ref('base.us')
        self.test_settings.web_base_url = 'https://test.example.com'
        
        # Emulate admin rights
        with patch.object(self.env.user, 'has_group', return_value=True):
            self.test_settings.register_instance()
            
        self.assertTrue(self.test_settings.get_param('is_registered'))

    @patch('requests.post')
    def test_make_usage_request(self, mock_post):
        """Test usage API request execution"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'success': True}
        mock_post.return_value = mock_response
        
        result = self.test_settings.make_usage_request(
            'test_endpoint', 
            mock_post, 
            data={'test': 'data'}
        )
        
        self.assertEqual(result, {'success': True})

    def test_make_usage_request_error(self):
        """Test API request error handling"""
        with patch('requests.post') as mock_post:
            mock_post.side_effect = Exception('Connection error')
            
            with self.assertRaises(ValidationError):
                self.test_settings.make_usage_request(
                    'test_endpoint', 
                    mock_post, 
                    raise_on_error=True
                )

    def test_protected_fields_write(self):
        """Test protected fields write"""
        test_values = {
            'display_auth_token': 'new_token',
            'display_twilio_api_secret': 'new_secret',
            'display_openai_api_key': 'new_openai_key',
        }
        
        self.test_settings.write(test_values)
        
        # Verify that real fields are set
        self.assertEqual(self.test_settings.auth_token, 'new_token')
        self.assertEqual(self.test_settings.twilio_api_secret, 'new_secret')
        self.assertEqual(self.test_settings.openai_api_key, 'new_openai_key')
        
        # Verify that display fields are masked
        self.assertEqual(self.test_settings.display_auth_token, '*' * len('new_token'))

    def test_get_module_version(self):
        """Test module version retrieval"""
        version = self.test_settings.get_module_version('connect')
        self.assertIsInstance(version, str)

    def test_get_module_list(self):
        """Test module list retrieval"""
        module_list = self.settings_model.get_module_list()
        self.assertIsInstance(module_list, list)
        self.assertIn('connect', module_list)

    @patch('requests.post')
    def test_check_latest_versions(self, mock_post):
        """Test latest versions checking"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'connect': '1.0.0'}
        mock_post.return_value = mock_response
        
        with patch.object(self.env['ir.ui.view'], '_render_template') as mock_render:
            mock_render.return_value = '<div>Test HTML</div>'
            self.test_settings.check_latest_versions()
            
            self.assertTrue(self.test_settings.latest_versions)

    def test_get_usage_model_list(self):
        """Test usage statistics model list retrieval"""
        model_list = self.test_settings.get_usage_model_list()
        self.assertIsInstance(model_list, list)
        expected_models = [
            'call', 'callflow', 'domain', 'exten', 'message', 
            'number', 'outgoing_callerid', 'recording', 'twiml', 'user'
        ]
        for model in expected_models:
            self.assertIn(model, model_list)

    def test_sync_validation(self):
        """Test synchronization validation"""
        # Test without credentials
        self.test_settings.account_sid = False
        with self.assertRaises(ValidationError) as context:
            self.test_settings.sync()
        self.assertIn('account SID and Auth token', str(context.exception))

    def test_check_api_url(self):
        """Test API URL validation"""
        # Test HTTP URL
        with patch.object(self.test_settings, 'get_param', return_value='http://example.com'):
            message = self.test_settings.check_api_url()
            self.assertIn('HTTPS instead of HTTP', message)
        
        # Test localhost
        with patch.object(self.test_settings, 'get_param', return_value='https://localhost'):
            message = self.test_settings.check_api_url()
            self.assertIn('localhost is not allowed', message)
        
        # Test correct URL
        with patch.object(self.test_settings, 'get_param', return_value='https://example.com'):
            message = self.test_settings.check_api_url()
            self.assertIsNone(message)

    def test_get_external_call_route(self):
        """Test TwiML generation for external call"""
        user = self.env.user
        status_url = 'https://example.com/status'
        number = '+1234567890'
        caller_id = '+0987654321'
        
        with patch.object(self.test_settings, 'sudo', return_value=self.test_settings):
            with patch.object(self.test_settings, 'get_param', return_value='240'):
                twiml = self.test_settings.get_external_call_route(
                    number, caller_id, status_url
                )
                self.assertIn('<Response>', twiml)
                self.assertIn('<Dial', twiml)
                self.assertIn(number, twiml)
                self.assertIn(caller_id, twiml)

    def test_twilio_region_edge_onchange(self):
        """Test Twilio region and edge change"""
        # Test for us1 region
        self.test_settings.twilio_region = 'us1'
        self.test_settings._reset_twilio_edge()
        self.assertEqual(self.test_settings.twilio_edge, 'ashburn')
        
        # Test for ie1 region
        self.test_settings.twilio_region = 'ie1'
        self.test_settings._reset_twilio_edge()
        self.assertEqual(self.test_settings.twilio_edge, 'dublin')
        
        # Test for au1 region
        self.test_settings.twilio_region = 'au1'
        self.test_settings._reset_twilio_edge()
        self.assertEqual(self.test_settings.twilio_edge, 'sydney')

    def test_action_open_system_parameters(self):
        """Test opening system parameters"""
        with patch('odoo.addons.connect.models.settings.release') as mock_release:
            mock_release.version_info = [18, 0, 0]
            action = self.test_settings.action_open_system_parameters()
            
            self.assertEqual(action['type'], 'ir.actions.act_window')
            self.assertEqual(action['res_model'], 'ir.config_parameter')
            self.assertEqual(action['view_mode'], 'list,form')

    @patch('openai.OpenAI')
    def test_get_openai_client(self, mock_openai):
        """Test OpenAI client retrieval"""
        # Test with API key
        with patch.object(self.test_settings, 'sudo', return_value=self.test_settings):
            with patch.object(self.test_settings, 'get_param', return_value='test-key'):
                client = self.settings_model.get_openai_client()
                self.assertTrue(client)
                mock_openai.assert_called_once()
        
        # Test without API key
        with patch.object(self.test_settings, 'sudo', return_value=self.test_settings):
            with patch.object(self.test_settings, 'get_param', return_value=False):
                client = self.settings_model.get_openai_client()
                self.assertFalse(client)

    def test_twilio_balance_fetch(self):
        """Test Twilio balance fetching"""
        with patch.object(self.test_settings, 'get_client') as mock_get_client:
            mock_client = Mock()
            mock_balance = Mock()
            mock_balance.currency = 'USD'
            mock_balance.balance = '10.50'
            mock_client.api.v2010.account.balance.fetch.return_value = mock_balance
            mock_get_client.return_value = mock_client
            
            with patch.object(self.test_settings, 'set_param') as mock_set_param:
                with patch.object(self.test_settings, 'connect_notify') as mock_notify:
                    balance = self.test_settings.get_twilio_balance()
                    
                    self.assertEqual(balance, '$10.50 USD')
                    mock_set_param.assert_called_once()
                    mock_notify.assert_called_once()

    def test_twilio_balance_api_not_available(self):
        """Test handling of Twilio balance API unavailability"""
        with patch.object(self.test_settings, 'get_client') as mock_get_client:
            mock_client = Mock()
            mock_client.api.v2010.account.balance.fetch.side_effect = Exception('20404')
            mock_get_client.return_value = mock_client
            
            with patch.object(self.test_settings, 'set_param') as mock_set_param:
                with patch.object(self.test_settings, 'connect_notify') as mock_notify:
                    balance = self.test_settings.get_twilio_balance()
                    
                    self.assertEqual(balance, "Balance API not available for this account")
                    mock_set_param.assert_called_once()
                    mock_notify.assert_called_once()

    def test_compute_sip_uri(self):
        """Test SIP URI computation"""
        # Create test user with URI
        test_user = self.env['res.users'].create({
            'name': 'Test User',
            'login': 'testuser',
        })
        
        # Create related connect user
        connect_user = self.env['connect.user'].create({
            'user': test_user.id,
            'uri': 'test_user_sip',
        })
        
        with patch.object(self.env.user, 'connect_user', connect_user):
            sip_uri = self.test_settings.compute_sip_uri(test_user)
            self.assertEqual(sip_uri, 'sip:test_user_sip')

    def test_update_usage_stats(self):
        """Test usage statistics update"""
        with patch.object(self.test_settings, 'prepare_registration_data', return_value={}):
            with patch.object(self.test_settings, 'make_usage_request') as mock_request:
                self.test_settings.update_usage()
                
                # Verify that request was made
                mock_request.assert_called_once()
                
                # Verify data structure
                call_args = mock_request.call_args
                self.assertEqual(call_args[0][0], 'usage')
                self.assertIn('usage', call_args[1]['data'])

    def test_transcript_calls_openai_key_requirement(self):
        """Test OpenAI key requirement for transcription"""
        # Remove OpenAI key
        self.test_settings.openai_api_key = False
        
        # Try to enable transcription
        with self.assertRaises(ValidationError) as context:
            self.test_settings._require_openai_key()
        
        self.assertIn('OpenAI key', str(context.exception))

    def test_read_method_sets_defaults(self):
        """Test read method sets default values"""
        # Reset values
        self.test_settings.admin_name = False
        self.test_settings.company_name = False
        
        # Call read
        result = self.test_settings.read(['admin_name', 'company_name'])
        
        # Verify that values are set
        self.test_settings.refresh()
        self.assertTrue(self.test_settings.admin_name)
        self.assertTrue(self.test_settings.company_name)


class TestConnectSettingsIntegration(common.HttpCase):
    """Integration test class for connect.settings"""

    def test_settings_model_access(self):
        """Test settings model access via ORM"""
        settings = self.env['connect.settings'].search([])
        if not settings:
            settings = self.env['connect.settings'].create({})
        
        self.assertTrue(settings.exists())
        
    def test_settings_parameter_persistence(self):
        """Test settings parameter persistence"""
        settings_model = self.env['connect.settings']
        
        # Set parameter
        settings_model.set_param('test_param', 'test_value')
        
        # Get parameter
        value = settings_model.get_param('test_param')
        self.assertEqual(value, 'test_value')

    def test_concurrent_parameter_access(self):
        """Test concurrent parameter access"""
        settings_model = self.env['connect.settings']
        
        # Set parameter
        settings_model.set_param('concurrent_test', 'initial')
        
        # Check value through different model instances
        settings1 = self.env['connect.settings']
        settings2 = self.env['connect.settings']
        
        value1 = settings1.get_param('concurrent_test')
        value2 = settings2.get_param('concurrent_test')
        
        self.assertEqual(value1, 'initial')
        self.assertEqual(value2, 'initial')


if __name__ == '__main__':
    common.run_test(TestConnectSettings)
    common.run_test(TestConnectSettingsIntegration)