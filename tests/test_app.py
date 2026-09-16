import os
import unittest
from unittest.mock import Mock, patch

import google_sheets
import home
import paypal_service
import registration


def registration_data(**overrides):
    data = {
        'email': 'student@example.com',
        'first_name': 'Jamie',
        'last_name': 'Student',
        'phone': '5551234567',
        'gender': 'Female',
        'campus': 'MIT',
        'campus_other': '',
        'school_state': 'Connecticut',
        'school_state_other': '',
        'status': 'Senior',
        'status_other': '',
        'transportation': '',
        'transportation_other': '',
        'car_capacity': '',
        'payment_option': 'pay_full',
        'attended_before': 'yes',
        'allergies': '',
        'comments': '',
    }
    data.update(overrides)
    return data


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class RouteTests(unittest.TestCase):
    def setUp(self):
        home.app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client = home.app.test_client()
        self.sheet_patcher = patch.object(home, 'record_registration')
        self.record_registration = self.sheet_patcher.start()

    def tearDown(self):
        self.sheet_patcher.stop()

    def test_public_pages_render(self):
        for path in ['/', '/spring-retreat', '/fall-retreat', '/register', '/check-in']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_registration_page_contains_school_options(self):
        html = self.client.get('/register').get_data(as_text=True)
        schools = [
            'Berklee', 'Boston College', 'Boston University', 'Brandeis', 'Brown',
            'CCSU', 'Harvard', 'MIT', 'Northeastern', 'RISD', 'Tufts', 'UConn',
            'UMass Amherst', 'UMass Boston', 'UMass Lowell', 'Wellesley', 'Yale',
        ]
        positions = [html.index(f'value="{school}"') for school in schools]
        self.assertEqual(positions, sorted(positions))

    def test_required_fields_are_validated(self):
        response = self.client.post('/register', data=registration_data(email=''))
        self.assertIn(b'Please fill out every field.', response.data)
        self.record_registration.assert_not_called()

    def test_email_is_validated(self):
        response = self.client.post('/register', data=registration_data(email='not-an-email'))
        self.assertIn(b'Please enter a valid email address.', response.data)

    def test_phone_is_validated(self):
        for phone in ['5551234', '+15551234567']:
            with self.subTest(phone=phone):
                response = self.client.post('/register', data=registration_data(phone=phone))
                self.assertIn(b'Please enter a 10-digit phone number', response.data)

    def test_massachusetts_requires_transportation(self):
        response = self.client.post(
            '/register',
            data=registration_data(school_state='Massachusetts'),
        )
        self.assertIn(b'Please fill out every field.', response.data)

    def test_car_option_requires_capacity(self):
        response = self.client.post(
            '/register',
            data=registration_data(
                school_state='Massachusetts',
                transportation='I have a car and can give rides',
            ),
        )
        self.assertIn(b'Please fill out every field.', response.data)

    def test_payment_option_and_attendance_are_required(self):
        no_payment_choice = self.client.post(
            '/register', data=registration_data(payment_option='')
        )
        self.assertIn(b'Please choose a payment option.', no_payment_choice.data)

        no_attendance = self.client.post(
            '/register', data=registration_data(attended_before='')
        )
        self.assertIn(b'Please let us know if you have attended', no_attendance.data)

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    def test_first_time_attendee_receives_half_price(self):
        response = self.client.post(
            '/register', data=registration_data(attended_before='no')
        )
        self.assertIn(b'$62.50', response.data)

    def test_returning_attendee_reaches_checkout(self):
        response = self.client.post('/register', data=registration_data())
        self.assertIn(b'<h1>Checkout</h1>', response.data)
        self.record_registration.assert_called_once()

    def test_scholarship_choice_finishes_without_checkout(self):
        response = self.client.post(
            '/register', data=registration_data(payment_option='scholarship')
        )
        self.assertIn(b'scholarship application form', response.data)
        self.assertIn(b'No payment is needed right now.', response.data)
        self.assertNotIn(b'Pay with PayPal', response.data)

    def test_full_timer_finishes_without_payment(self):
        for status in ['full-timer', 'Full Timer', 'fulltimer']:
            with self.subTest(status=status):
                response = self.client.post(
                    '/register',
                    data=registration_data(
                        status='Other',
                        status_other=status,
                        payment_option='',
                        attended_before='',
                    ),
                )
                self.assertIn(b'No payment is required.', response.data)

    def test_ccsu_variants_finish_with_contact_message(self):
        variants = [
            ('CCSU', ''),
            ('Other', 'C.C.S.U.'),
            ('Other', 'Central Connecticut State University'),
            ('Other', 'Central CT State Univ'),
        ]
        for campus, campus_other in variants:
            with self.subTest(campus=campus, campus_other=campus_other):
                response = self.client.post(
                    '/register',
                    data=registration_data(
                        campus=campus,
                        campus_other=campus_other,
                        payment_option='',
                        attended_before='',
                    ),
                )
                self.assertIn(b'Charles Savona', response.data)

    def test_other_school_is_normalized_before_recording(self):
        self.client.post(
            '/register',
            data=registration_data(campus='Other', campus_other='Emerson College'),
        )
        recorded = self.record_registration.call_args.args[0]
        self.assertEqual(recorded['campus'], 'Emerson College')

    def test_sheet_failure_keeps_user_on_registration(self):
        self.record_registration.side_effect = RuntimeError('Google unavailable')
        with patch.object(home.app.logger, 'exception'):
            response = self.client.post('/register', data=registration_data())
        self.assertIn(b'We could not save your registration.', response.data)

    def test_checkout_requires_registration_session(self):
        response = self.client.get('/checkout')
        self.assertIn(b'Please register before checking out.', response.data)


class RegistrationRuleTests(unittest.TestCase):
    def test_ccsu_matching_does_not_match_other_connecticut_schools(self):
        for campus in ['UConn', 'Connecticut College', 'Eastern Connecticut State University']:
            with self.subTest(campus=campus):
                self.assertFalse(registration.is_ccsu({'campus': campus}))

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    def test_registration_amount(self):
        self.assertEqual(registration.registration_amount({'attended_before': 'yes'}), '125.00')
        self.assertEqual(registration.registration_amount({'attended_before': 'no'}), '62.50')

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': 'invalid'}, clear=False)
    def test_invalid_configured_amount_uses_default(self):
        self.assertEqual(registration.registration_amount({'attended_before': 'yes'}), '125.00')

    def test_initial_payment_status(self):
        self.assertEqual(
            registration.initial_payment_status(registration_data(payment_option='pay_full')),
            'Pending',
        )
        self.assertEqual(
            registration.initial_payment_status(registration_data(payment_option='scholarship')),
            'Scholarship application pending',
        )
        self.assertEqual(
            registration.initial_payment_status(registration_data(campus='CCSU')),
            'Not required',
        )


class SheetTests(unittest.TestCase):
    def test_record_registration_writes_every_column(self):
        worksheet = Mock()
        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            google_sheets.record_registration(
                registration_data(
                    attended_before='no',
                    allergies='Peanuts',
                    comments='Arriving late',
                ),
                'registration-123',
            )

        row = worksheet.append_table.call_args.kwargs['values']
        values = dict(zip(google_sheets.REGISTRATION_HEADERS, row))
        self.assertEqual(len(row), len(google_sheets.REGISTRATION_HEADERS))
        self.assertEqual(values['Registration ID'], 'registration-123')
        self.assertEqual(values['Allergies & Dietary Restrictions'], 'Peanuts')
        self.assertEqual(values['Comments'], 'Arriving late')
        self.assertEqual(values['First-Time Attendee'], 'Yes')
        self.assertEqual(values['Amount Due'], '62.50')

    def test_payment_update_targets_registration_row(self):
        worksheet = Mock()
        worksheet.get_col.return_value = ['Registration ID', 'first-id', 'target-id']
        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            google_sheets.update_registration_payment(
                'target-id',
                **{'Payment Status': 'Paid', 'PayPal Capture ID': 'CAPTURE-1'},
            )

        status_col = google_sheets.REGISTRATION_HEADERS.index('Payment Status') + 1
        capture_col = google_sheets.REGISTRATION_HEADERS.index('PayPal Capture ID') + 1
        worksheet.update_value.assert_any_call((3, status_col), 'Paid')
        worksheet.update_value.assert_any_call((3, capture_col), 'CAPTURE-1')

    def test_missing_registration_row_raises(self):
        worksheet = Mock()
        worksheet.get_col.return_value = ['Registration ID']
        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            with self.assertRaisesRegex(RuntimeError, 'Registration row was not found'):
                google_sheets.update_registration_payment('missing-id', **{'Payment Status': 'Paid'})

    @patch.dict(os.environ, {}, clear=False)
    def test_sheet_opens_expected_spreadsheet_and_tab(self):
        os.environ.pop('REGISTRATION_SPREADSHEET_ID', None)
        os.environ.pop('REGISTRATION_SPREADSHEET', None)
        os.environ.pop('REGISTRATION_WORKSHEET', None)
        worksheet = Mock()
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:]
        spreadsheet = Mock()
        spreadsheet.worksheet_by_title.return_value = worksheet
        sheets_client = Mock()
        sheets_client.open.return_value = spreadsheet

        with patch.object(google_sheets.pygsheets, 'authorize', return_value=sheets_client):
            result = google_sheets.registration_worksheet()

        self.assertIs(result, worksheet)
        sheets_client.open.assert_called_once_with('2026 Fall Retreat - Registration (Responses)')
        spreadsheet.worksheet_by_title.assert_called_once_with('Registrations')


class PayPalTests(unittest.TestCase):
    def setUp(self):
        home.app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client = home.app.test_client()

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

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    @patch.object(home, 'update_registration_payment')
    @patch.object(home, 'create_order')
    def test_create_order_uses_registration_amount(
        self, create_order, update_payment
    ):
        create_order.return_value = {'id': 'ORDER-1', 'status': 'CREATED'}
        self.set_registration_session(registration_data(attended_before='no'))

        response = self.client.post('/api/paypal/orders')

        self.assertEqual(response.status_code, 200)
        create_order.assert_called_once_with('62.50', 'registration-123')
        with self.client.session_transaction() as session:
            self.assertEqual(session['paypal_order_id'], 'ORDER-1')
        update_payment.assert_called_once_with(
            'registration-123',
            **{
                'Payment Status': 'PayPal checkout started',
                'PayPal Order ID': 'ORDER-1',
            },
        )

    @patch.object(home, 'update_registration_payment')
    @patch.object(home, 'capture_order')
    def test_capture_marks_sheet_row_paid(
        self, capture_order, update_payment
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
        update_payment.assert_called_once_with(
            'registration-123',
            **{
                'Payment Status': 'Paid',
                'PayPal Order ID': 'ORDER-1',
                'PayPal Capture ID': 'CAPTURE-1',
                'Paid At': '2026-09-16T12:00:00Z',
            },
        )

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


class PayPalServiceTests(unittest.TestCase):
    @patch.object(paypal_service, 'get_paypal_access_token', return_value='access-token')
    @patch.object(paypal_service.requests, 'post')
    def test_create_order_builds_paypal_payload(self, requests_post, get_access_token):
        requests_post.return_value = FakeResponse({'id': 'ORDER-1'})

        order = paypal_service.create_order('62.50', 'registration-123')

        self.assertEqual(order['id'], 'ORDER-1')
        payload = requests_post.call_args.kwargs['json']
        self.assertEqual(payload['purchase_units'][0]['amount']['value'], '62.50')
        self.assertEqual(payload['purchase_units'][0]['custom_id'], 'registration-123')

    @patch.object(paypal_service, 'get_paypal_access_token', return_value='access-token')
    @patch.object(paypal_service.requests, 'post')
    def test_capture_order_calls_expected_endpoint(self, requests_post, get_access_token):
        requests_post.return_value = FakeResponse({'id': 'ORDER-1', 'status': 'COMPLETED'})

        capture = paypal_service.capture_order('ORDER-1')

        self.assertEqual(capture['status'], 'COMPLETED')
        self.assertTrue(requests_post.call_args.args[0].endswith('/ORDER-1/capture'))


if __name__ == '__main__':
    unittest.main()
