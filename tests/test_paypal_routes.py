import os
import unittest
from unittest.mock import Mock, patch

import home

from tests.helpers import registration_data


class PayPalTests(unittest.TestCase):
    def setUp(self):
        self.late_fee_patcher = patch.dict(
            os.environ,
            {'RETREAT_LATE_FEE_START': '2999-10-10T00:00:00-04:00'},
        )
        self.late_fee_patcher.start()
        home.app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client = home.app.test_client()
        self.email_queue_patcher = patch.object(home, 'queue_confirmation_email')
        self.queue_confirmation_email = self.email_queue_patcher.start()

    def tearDown(self):
        self.email_queue_patcher.stop()
        self.late_fee_patcher.stop()

    def set_registration_session(self, registration=None, paypal_order_id=None):
        with self.client.session_transaction() as session:
            session['registration'] = registration or registration_data()
            session['registration_token'] = 'registration-123'
            if paypal_order_id:
                session['paypal_order_id'] = paypal_order_id

    def test_order_requires_registration(self):
        response = self.client.post('/api/paypal/orders')
        self.assertEqual(response.status_code, 400)

    def test_payment_exempt_registration_cannot_create_order(self):
        self.set_registration_session(registration_data(campus='CCSU'))
        response = self.client.post('/api/paypal/orders')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Payment is not required', response.get_json()['error'])

    @patch.object(home.app.logger, 'warning')
    def test_paypal_client_event_logs_only_allowlisted_fields(self, logger):
        self.set_registration_session(paypal_order_id='ORDER-1')

        response = self.client.post('/api/paypal/client-events', json={
            'event': 'sdk_error',
            'error_name': 'INSTRUMENT_DECLINED',
            'message': 'Payment method declined',
            'order_id': 'ORDER-1',
            'card_number': '4111111111111111',
        })

        self.assertEqual(response.status_code, 204)
        logged_payload = logger.call_args.args[1]
        self.assertIn('INSTRUMENT_DECLINED', logged_payload)
        self.assertIn('ORDER-1', logged_payload)
        self.assertIn('Jamie Student', logged_payload)
        self.assertNotIn('student@example.com', logged_payload)
        self.assertNotIn('4111111111111111', logged_payload)

    @patch.object(home.app.logger, 'warning')
    def test_paypal_log_normalizes_registrant_name(self, logger):
        with home.app.test_request_context('/'):
            home.paypal_log(
                'order_created',
                registration_data(first_name=' Jamie\n', last_name=' Student '),
                order_id='ORDER-1',
            )

        logged_payload = logger.call_args.args[1]
        self.assertIn('"registrant": "Jamie Student"', logged_payload)

    def test_paypal_client_event_rejects_unknown_events(self):
        self.set_registration_session()

        response = self.client.post('/api/paypal/client-events', json={
            'event': 'arbitrary_event',
        })

        self.assertEqual(response.status_code, 400)

    def test_paypal_client_event_rejects_non_object_json(self):
        self.set_registration_session()

        response = self.client.post('/api/paypal/client-events', json=['sdk_error'])

        self.assertEqual(response.status_code, 400)

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    @patch.object(home, 'create_order')
    def test_create_order_uses_registration_amount(self, create_order):
        create_order.return_value = {'id': 'ORDER-1', 'status': 'CREATED'}
        self.set_registration_session(registration_data(attended_before='no'))

        response = self.client.post('/api/paypal/orders')

        self.assertEqual(response.status_code, 200)
        create_order.assert_called_once_with('62.50', 'registration-123')
        with self.client.session_transaction() as session:
            self.assertEqual(session['paypal_order_id'], 'ORDER-1')

    @patch.object(home, 'record_registration')
    @patch.object(home, 'capture_order')
    def test_completed_capture_records_registration_and_returns_redirect(
        self, capture_order, record_registration
    ):
        capture = {
            'id': 'ORDER-1',
            'purchase_units': [{
                'payments': {'captures': [{
                    'id': 'CAPTURE-1',
                    'status': 'COMPLETED',
                    'create_time': '2026-09-16T12:00:00Z',
                }]},
            }],
        }
        capture_order.return_value = capture
        self.set_registration_session(paypal_order_id='ORDER-1')

        response = self.client.post('/api/paypal/orders/ORDER-1/capture')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['redirect_url'], '/registration-complete')
        recorded, registration_id = record_registration.call_args.args
        self.assertEqual(registration_id, 'registration-123')
        self.assertEqual(recorded['payment_status'], 'Paid')
        self.assertEqual(recorded['paypal_order_id'], 'ORDER-1')
        self.assertEqual(recorded['paypal_capture_id'], 'CAPTURE-1')
        self.assertEqual(recorded['paid_at'], '2026-09-16T12:00:00Z')
        with self.client.session_transaction() as session:
            self.assertNotIn('registration', session)
            self.assertEqual(session['completed_registration']['first_name'], 'Jamie')

        confirmation = self.client.get('/registration-complete')
        self.assertIn(b'You\xe2\x80\x99re registered', confirmation.data)
        self.assertIn(b'See you there, Jamie!', confirmation.data)
        self.assertIn(b'confirmation email shortly', confirmation.data)
        self.assertIn(b'mailto:nechristiansoncampus@gmail.com', confirmation.data)
        self.assertIn(b'Jamie Student', confirmation.data)
        self.assertIn(b'student@example.com', confirmation.data)
        self.assertIn(b'MIT', confirmation.data)
        self.assertIn(b'Senior', confirmation.data)
        self.assertIn(b'href="/"', confirmation.data)

    @patch.object(home, 'record_registration')
    @patch.object(home, 'capture_order')
    def test_sheet_failure_after_capture_warns_not_to_pay_again(
        self, capture_order, record_registration
    ):
        capture_order.return_value = {
            'id': 'ORDER-1',
            'purchase_units': [{
                'payments': {'captures': [{
                    'id': 'CAPTURE-1',
                    'status': 'COMPLETED',
                    'create_time': '2026-09-16T12:00:00Z',
                }]},
            }],
        }
        record_registration.side_effect = RuntimeError('Google unavailable')
        self.set_registration_session(paypal_order_id='ORDER-1')

        with patch.object(home.app.logger, 'exception'):
            response = self.client.post('/api/paypal/orders/ORDER-1/capture')

        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.get_json()['payment_completed'])
        self.assertIn('do not submit another payment', response.get_json()['error'])

        record_registration.side_effect = None
        retry = self.client.post('/api/paypal/orders/ORDER-1/capture')
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.get_json()['redirect_url'], '/registration-complete')
        capture_order.assert_called_once_with('ORDER-1')

    def test_completion_page_requires_completed_payment(self):
        response = self.client.get('/registration-complete')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/register'))

    @patch.object(home, 'capture_order')
    def test_capture_rejects_order_from_another_registration(self, capture_order):
        self.set_registration_session(paypal_order_id='EXPECTED-ORDER')

        response = self.client.post('/api/paypal/orders/OTHER-ORDER/capture')

        self.assertEqual(response.status_code, 400)
        self.assertIn('does not match', response.get_json()['error'])
        capture_order.assert_not_called()

    @patch.object(home, 'capture_order')
    def test_payment_exempt_registration_cannot_capture_order(self, capture_order):
        self.set_registration_session(
            registration_data(campus='CCSU'),
            paypal_order_id='ORDER-1',
        )

        response = self.client.post('/api/paypal/orders/ORDER-1/capture')

        self.assertEqual(response.status_code, 400)
        self.assertIn('Payment is not required', response.get_json()['error'])
        capture_order.assert_not_called()
