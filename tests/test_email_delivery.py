import unittest
from unittest.mock import patch

import home

from tests.helpers import registration_data


class EmailDeliveryFlowTests(unittest.TestCase):
    def setUp(self):
        home.app.config.update(TESTING=True, SECRET_KEY='test-secret')

    @patch.object(home.email_executor, 'submit')
    @patch.object(home, 'update_registration')
    @patch.object(home, 'registration_field', return_value='')
    @patch.object(home, 'email_confirmation_configured', return_value=True)
    def test_email_is_marked_queued_before_background_submission(
        self, configured, registration_field, update_registration, submit
    ):
        with home.app.test_request_context('/'):
            home.queue_confirmation_email(registration_data(), 'registration-123', 'paid')

        update_registration.assert_called_once_with(
            'registration-123',
            **{'Confirmation Email Status': 'Queued'},
        )
        submit.assert_called_once()
        self.assertIs(submit.call_args.args[0], home.deliver_confirmation_email)

    @patch.object(home.email_executor, 'submit')
    @patch.object(home, 'update_registration')
    @patch.object(home, 'registration_field', return_value='Sent')
    @patch.object(home, 'email_confirmation_configured', return_value=True)
    def test_sent_registration_is_not_queued_again(
        self, configured, registration_field, update_registration, submit
    ):
        with home.app.test_request_context('/'):
            home.queue_confirmation_email(registration_data(), 'registration-123', 'paid')

        submit.assert_not_called()
        update_registration.assert_not_called()

    @patch.object(home, 'update_registration')
    @patch.object(home, 'send_confirmation_email', side_effect=RuntimeError('SMTP unavailable'))
    @patch.object(home, 'registration_field', return_value='')
    @patch.object(home, 'email_confirmation_configured', return_value=True)
    def test_email_failure_does_not_raise_and_is_recorded(
        self, configured, registration_field, send_email, update_registration
    ):
        with patch.object(home.app.logger, 'exception'):
            home.deliver_confirmation_email(registration_data(), 'registration-123', 'paid')

        update_registration.assert_called_once_with(
            'registration-123',
            **{'Confirmation Email Status': 'Failed'},
        )

    @patch.object(home, 'update_registration')
    @patch.object(home, 'send_confirmation_email')
    def test_successful_background_email_is_recorded(self, send_email, update_registration):
        home.deliver_confirmation_email(registration_data(), 'registration-123', 'paid')

        updates = update_registration.call_args.kwargs
        self.assertEqual(updates['Confirmation Email Status'], 'Sent')
        self.assertTrue(updates['Confirmation Email Sent At'])

