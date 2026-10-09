import os
import unittest
from unittest.mock import patch

import email_service

from tests.helpers import registration_data


class EmailConfirmationTests(unittest.TestCase):
    def test_confirmation_is_disabled_without_smtp_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(email_service.email_confirmation_configured())
            self.assertFalse(
                email_service.send_confirmation_email(registration_data(), 'paid')
            )

    @patch.dict(
        os.environ,
        {
            'SMTP_HOST': 'smtp.gmail.com',
            'SMTP_PORT': '587',
            'SMTP_USERNAME': 'sender@example.com',
            'SMTP_APP_PASSWORD': 'app-password',
            'SMTP_FROM_NAME': 'Retreat Team',
        },
        clear=True,
    )
    @patch.object(email_service.smtplib, 'SMTP')
    def test_confirmation_uses_tls_and_contains_retreat_details(self, smtp_class):
        smtp = smtp_class.return_value.__enter__.return_value

        sent = email_service.send_confirmation_email(registration_data(), 'paid')

        self.assertTrue(sent)
        smtp_class.assert_called_once_with('smtp.gmail.com', 587, timeout=10)
        smtp.starttls.assert_called_once_with()
        smtp.login.assert_called_once_with('sender@example.com', 'app-password')
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message['Subject'], 'Your Fall Retreat Registration Is Confirmed')
        self.assertEqual(message['To'], 'student@example.com')
        self.assertEqual(message['Reply-To'], 'sender@example.com')
        self.assertIn('October 17-18', message.get_body(preferencelist=('plain',)).get_content())

    def test_scholarship_confirmation_explains_next_step(self):
        subject, body, _ = email_service.confirmation_content(
            registration_data(),
            'scholarship',
        )

        self.assertEqual(subject, 'Retreat Scholarship Request Received')
        self.assertIn('application form', body)

    def test_ccsu_confirmation_explains_payment_contact(self):
        _, body, _ = email_service.confirmation_content(
            registration_data(campus='CCSU'),
            'ccsu',
        )

        self.assertIn('contact Charles Savona', body)
        self.assertIn('payment and other details regarding the retreat', body)

