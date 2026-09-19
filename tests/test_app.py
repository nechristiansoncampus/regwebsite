import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import email_service
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
        self.assertEqual(message['To'], 'student@example.com')
        self.assertEqual(message['Reply-To'], 'sender@example.com')
        self.assertIn('October 17-18', message.get_body(preferencelist=('plain',)).get_content())

    def test_scholarship_confirmation_explains_next_step(self):
        subject, body, _ = email_service.confirmation_content(
            registration_data(),
            'scholarship',
        )

        self.assertIn('scholarship', subject.lower())
        self.assertIn('application form', body)


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


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.late_fee_patcher = patch.dict(
            os.environ,
            {'RETREAT_LATE_FEE_START': '2999-10-10T00:00:00-04:00'},
        )
        self.late_fee_patcher.start()
        home.app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client = home.app.test_client()
        self.sheet_patcher = patch.object(home, 'record_registration')
        self.record_registration = self.sheet_patcher.start()

    def tearDown(self):
        self.sheet_patcher.stop()
        self.late_fee_patcher.stop()

    def test_public_pages_render(self):
        for path in ['/', '/spring-retreat', '/fall-retreat', '/register', '/check-in']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_flask_secret_key_is_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'FLASK_SECRET_KEY must be set'):
                home.required_setting('FLASK_SECRET_KEY')

    def test_home_page_defaults_to_fall_retreat(self):
        home_page = self.client.get('/').get_data(as_text=True)
        spring_page = self.client.get('/spring-retreat').get_data(as_text=True)

        self.assertIn('<title>Fall Retreat', home_page)
        self.assertIn('Spring Retreat</title>', spring_page)

    def test_retreat_pages_load_shared_interactions(self):
        for path in ['/', '/spring-retreat']:
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                self.assertIn('src="/static/js/retreat.js" defer', html)
        response = self.client.get('/static/js/retreat.js')
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_home_page_question_link_uses_browser_email_compose(self):
        home_page = self.client.get('/').get_data(as_text=True)
        self.assertIn('https://mail.google.com/mail/?view=cm&amp;fs=1', home_page)
        self.assertIn('to=nechristiansoncampus@gmail.com', home_page)
        self.assertNotIn('mailto:', home_page)

    def test_registration_page_contains_school_options(self):
        html = self.client.get('/register').get_data(as_text=True)
        schools = [
            'Berklee', 'Boston College', 'Boston University', 'Brandeis', 'Brown',
            'CCSU', 'Harvard', 'MIT', 'Northeastern', 'RISD', 'Tufts', 'UConn',
            'UMass Amherst', 'UMass Boston', 'UMass Lowell', 'Wellesley', 'Yale',
        ]
        positions = [html.index(f'value="{school}"') for school in schools]
        self.assertEqual(positions, sorted(positions))

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '149.50'}, clear=False)
    def test_registration_page_uses_configured_amount(self):
        html = self.client.get('/register').get_data(as_text=True)
        self.assertIn('<span class="costAmount">$149.50</span>', html)

    def test_contact_fields_expose_accessible_validation_contract(self):
        html = self.client.get('/register').get_data(as_text=True)
        self.assertIn('id="emailError" class="fieldError" role="alert" hidden', html)
        self.assertIn('id="phoneError" class="fieldError" role="alert" hidden', html)
        email_input = html.split('id="emailInput"', 1)[1].split('>', 1)[0]
        phone_input = html.split('id="phoneInput"', 1)[1].split('>', 1)[0]
        self.assertIn('type="email"', email_input)
        self.assertIn('aria-describedby="emailError"', email_input)
        self.assertIn('type="tel"', phone_input)
        self.assertIn('inputmode="numeric"', phone_input)
        self.assertIn('aria-describedby="phoneError"', phone_input)
        self.assertIn('pattern="[0-9]{10}"', phone_input)
        self.assertNotIn('maxlength=', phone_input)

    def test_fall_page_uses_seasonal_copy_and_consistent_headings(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('games, outdoor activities, and snacks.', html)
        self.assertNotIn('games, snow, and snacks.', html)
        self.assertIn('What to Expect', html)
        self.assertIn('What People Are Saying About Retreat', html)
        self.assertIn('class="btn btnPrimary" href="/register"', html)

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

    @patch.dict(os.environ, {'PAYPAL_CLIENT_ID': 'test-client-id'}, clear=False)
    def test_returning_attendee_reaches_checkout(self):
        response = self.client.post('/register', data=registration_data())
        self.assertIn(b'<h1>Checkout</h1>', response.data)
        self.assertIn(b'id="payment-processing"', response.data)
        self.assertIn(b'Finalizing your registration', response.data)
        self.assertIn(b'Please keep this page open.', response.data)
        self.record_registration.assert_not_called()

    @patch.object(home, 'queue_confirmation_email')
    def test_scholarship_choice_finishes_without_checkout(self, send_confirmation):
        response = self.client.post(
            '/register', data=registration_data(payment_option='scholarship')
        )
        self.assertIn(b'scholarship application form', response.data)
        self.assertIn(b'No payment is needed right now.', response.data)
        self.assertIn(b'href="/">Back to home</a>', response.data)
        self.assertIn(b'confirmation email shortly', response.data)
        self.assertIn(b'mailto:nechristiansoncampus@gmail.com', response.data)
        self.assertNotIn(b'Pay with PayPal', response.data)
        registration_id = self.record_registration.call_args.args[1]
        send_confirmation.assert_called_once_with(
            self.record_registration.call_args.args[0],
            registration_id,
            'scholarship',
        )

    def test_repeated_form_submission_reuses_registration_id(self):
        html = self.client.get('/register').get_data(as_text=True)
        token = html.split('name="registration_token" value="', 1)[1].split('"', 1)[0]
        form_data = registration_data(
            registration_token=token,
            payment_option='scholarship',
        )

        first_response = self.client.post('/register', data=form_data)
        second_response = self.client.post('/register', data=form_data)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        registration_ids = [call.args[1] for call in self.record_registration.call_args_list]
        self.assertEqual(registration_ids, [token, token])

    def test_expired_registration_form_is_rejected(self):
        self.client.get('/register')

        response = self.client.post(
            '/register',
            data=registration_data(registration_token='stale-token'),
        )

        self.assertIn(b'This registration form expired.', response.data)
        self.record_registration.assert_not_called()

    def test_eligible_state_full_timer_status_skips_payment(self):
        for state in ['Massachusetts', 'New Hampshire']:
            for status in ['full-timer', 'Full Timer', 'FT', 'F/T', 'fulltimer']:
                with self.subTest(state=state, status=status):
                    transportation = 'I need a ride' if state == 'Massachusetts' else ''
                    response = self.client.post(
                        '/register',
                        data=registration_data(
                            school_state=state,
                            status='Other',
                            status_other=status,
                            payment_option='',
                            attended_before='',
                            transportation=transportation,
                        ),
                    )
                    self.assertIn(b'No payment is required.', response.data)
                    self.assertIn(b'href="/">Back to home</a>', response.data)
                    recorded = self.record_registration.call_args.args[0]
                    self.assertEqual(recorded['payment_option'], 'not_required')
                    self.record_registration.reset_mock()

    def test_full_timer_outside_eligible_states_still_pays(self):
        for state in ['Connecticut', 'Rhode Island', 'Vermont']:
            with self.subTest(state=state):
                response = self.client.post(
                    '/register',
                    data=registration_data(
                        school_state=state,
                        status='Other',
                        status_other='FT',
                    ),
                )
                self.assertIn(b'<h1>Checkout</h1>', response.data)
                self.record_registration.assert_not_called()

    def test_stale_full_timer_text_does_not_exempt_a_student_status(self):
        response = self.client.post(
            '/register',
            data=registration_data(
                school_state='New Hampshire',
                status='Freshman',
                status_other='FT',
            ),
        )

        self.assertIn(b'<h1>Checkout</h1>', response.data)
        self.record_registration.assert_not_called()

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    def test_other_status_skips_attendance_question_without_discount(self):
        for attended_before in ['', 'no']:
            with self.subTest(attended_before=attended_before):
                response = self.client.post(
                    '/register',
                    data=registration_data(
                        status='Other',
                        status_other='Volunteer',
                        attended_before=attended_before,
                    ),
                )
                self.assertIn(b'<h1>Checkout</h1>', response.data)
                self.assertIn(b'$125.00', response.data)
                self.record_registration.assert_not_called()
                with self.client.session_transaction() as session:
                    self.assertEqual(session['registration']['attended_before'], '')

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
                self.assertIn(b'href="/">Back to home</a>', response.data)

    def test_other_school_is_normalized_before_recording(self):
        self.client.post(
            '/register',
            data=registration_data(
                campus='Other',
                campus_other='Emerson College',
                payment_option='scholarship',
            ),
        )
        recorded = self.record_registration.call_args.args[0]
        self.assertEqual(recorded['campus'], 'Emerson College')

    def test_sheet_failure_keeps_user_on_registration(self):
        self.record_registration.side_effect = RuntimeError('Google unavailable')
        with patch.object(home.app.logger, 'exception'):
            response = self.client.post(
                '/register',
                data=registration_data(payment_option='scholarship'),
            )
        self.assertIn(b'We could not save your registration.', response.data)
        self.assertIn(b'id="dismissRegistrationError"', response.data)

    def test_checkout_requires_registration_session(self):
        response = self.client.get('/checkout')
        self.assertIn(b'Please register before checking out.', response.data)


class RegistrationRuleTests(unittest.TestCase):
    def test_phone_formatting_is_rejected(self):
        parsed = registration.parse_registration(
            registration_data(phone='(555) 123-4567')
        )
        self.assertIn('10-digit phone number', registration.validate_registration(parsed))

    def test_phone_rejects_letters_and_country_codes(self):
        for phone in ['call5551234567', '+15551234567', '15551234567']:
            with self.subTest(phone=phone):
                parsed = registration.parse_registration(registration_data(phone=phone))
                self.assertIn('10-digit phone number', registration.validate_registration(parsed))

    def test_ccsu_matching_does_not_match_other_connecticut_schools(self):
        for campus in ['UConn', 'Connecticut College', 'Eastern Connecticut State University']:
            with self.subTest(campus=campus):
                self.assertFalse(registration.is_ccsu({'campus': campus}))

    def test_full_timer_status_matching_is_deliberately_narrow(self):
        for status in ['FT', 'F/T', 'full-time', 'full timer', 'fulltimer']:
            with self.subTest(status=status):
                self.assertTrue(registration.is_full_timer({
                    'status_is_other': True,
                    'status_other': status,
                }))
        self.assertFalse(registration.is_full_timer({
            'status_is_other': True,
            'status_other': 'full-time student',
        }))

    def test_full_timer_eligibility_values_have_stable_browser_order(self):
        self.assertEqual(
            sorted(registration.FULL_TIMER_STATES),
            ['Massachusetts', 'New Hampshire'],
        )
        self.assertEqual(
            sorted(registration.FULL_TIMER_STATUS_KEYS),
            ['ft', 'fulltime', 'fulltimer'],
        )

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    def test_registration_amount(self):
        before_cutoff = datetime(2026, 10, 10, 3, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(
            registration.registration_amount({'attended_before': 'yes'}, before_cutoff),
            '125.00',
        )
        self.assertEqual(
            registration.registration_amount({'attended_before': 'no'}, before_cutoff),
            '62.50',
        )

    @patch.dict(
        os.environ,
        {
            'RETREAT_REGISTRATION_AMOUNT': '125.00',
            'RETREAT_LATE_FEE_AMOUNT': '10.00',
            'RETREAT_LATE_FEE_START': '2026-10-10T00:00:00-04:00',
        },
        clear=False,
    )
    def test_late_fee_starts_at_midnight_eastern_after_discount(self):
        at_cutoff = datetime(2026, 10, 10, 4, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(registration.late_fee_amount(at_cutoff), 10)
        self.assertEqual(
            registration.registration_amount({'attended_before': 'yes'}, at_cutoff),
            '135.00',
        )
        self.assertEqual(
            registration.registration_amount({'attended_before': 'no'}, at_cutoff),
            '72.50',
        )

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': 'invalid'}, clear=False)
    def test_invalid_configured_amount_uses_default(self):
        before_cutoff = datetime(2026, 10, 10, 3, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(
            registration.registration_amount({'attended_before': 'yes'}, before_cutoff),
            '125.00',
        )

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
    def setUp(self):
        self.late_fee_patcher = patch.dict(
            os.environ,
            {'RETREAT_LATE_FEE_START': '2999-10-10T00:00:00-04:00'},
        )
        self.late_fee_patcher.start()

    def tearDown(self):
        self.late_fee_patcher.stop()

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    def test_record_registration_writes_every_column(self):
        worksheet = Mock()
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:]
        worksheet.get_col.return_value = ['Registration ID']
        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            google_sheets.record_registration(
                registration_data(
                    attended_before='no',
                    allergies='Peanuts',
                    comments='Arriving late',
                ),
                'registration-123',
            )

        row_number, row = worksheet.update_row.call_args.args
        values = dict(zip(google_sheets.REGISTRATION_HEADERS, row))
        self.assertEqual(row_number, 2)
        self.assertEqual(len(row), len(google_sheets.REGISTRATION_HEADERS))
        self.assertEqual(values['Registration ID'], 'registration-123')
        self.assertEqual(values['Allergies & Dietary Restrictions'], 'Peanuts')
        self.assertEqual(values['Comments'], 'Arriving late')
        self.assertEqual(values['First-Time Attendee'], 'Yes')
        self.assertEqual(values['Amount Due'], '62.50')

    def test_record_registration_does_not_duplicate_registration_id(self):
        worksheet = Mock()
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:]
        worksheet.get_col.return_value = ['Registration ID', 'registration-123']
        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            google_sheets.record_registration(registration_data(), 'registration-123')

        worksheet.update_row.assert_not_called()

    def test_payment_update_targets_registration_row(self):
        worksheet = Mock()
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:]
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
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:]
        worksheet.get_col.return_value = ['Registration ID']
        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            with self.assertRaisesRegex(RuntimeError, 'Registration row was not found'):
                google_sheets.update_registration_payment('missing-id', **{'Payment Status': 'Paid'})

    @patch.dict(os.environ, {'APP_ENV': 'development'}, clear=False)
    def test_non_production_opens_test_worksheet(self):
        os.environ.pop('REGISTRATION_SPREADSHEET_ID', None)
        os.environ.pop('REGISTRATION_SPREADSHEET', None)
        os.environ.pop('REGISTRATION_TEST_WORKSHEET', None)
        worksheet = Mock()
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:]
        spreadsheet = Mock()
        spreadsheet.worksheet_by_title.return_value = worksheet
        sheets_client = Mock()
        sheets_client.open.return_value = spreadsheet

        with patch.object(google_sheets.pygsheets, 'authorize', return_value=sheets_client):
            result = google_sheets.registration_worksheet()

        self.assertIs(result, worksheet)
        sheets_client.open.assert_called_once_with(
            '2026 Fall Retreat - Registration (Responses)'
        )
        spreadsheet.worksheet_by_title.assert_called_once_with('Test Registrations')

    @patch.dict(os.environ, {'APP_ENV': 'production'}, clear=False)
    def test_production_opens_live_spreadsheet(self):
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
            google_sheets.registration_worksheet()

        sheets_client.open.assert_called_once_with(
            '2026 Fall Retreat - Registration (Responses)'
        )

    @patch.dict(os.environ, {'RENDER': 'true'}, clear=False)
    def test_render_defaults_to_production_sheet(self):
        os.environ.pop('APP_ENV', None)
        os.environ.pop('REGISTRATION_SPREADSHEET_ID', None)
        os.environ.pop('REGISTRATION_SPREADSHEET', None)

        settings = google_sheets.registration_sheet_settings()

        self.assertEqual(
            settings['spreadsheet_title'],
            '2026 Fall Retreat - Registration (Responses)',
        )
        self.assertEqual(settings['worksheet_title'], 'Registrations')

    @patch.dict(
        os.environ,
        {
            'APP_ENV': 'staging',
            'REGISTRATION_SPREADSHEET_ID': 'shared-spreadsheet-id',
            'REGISTRATION_TEST_WORKSHEET': 'Staging Registrations',
        },
        clear=False,
    )
    def test_non_production_uses_shared_spreadsheet_id_and_test_worksheet(self):
        worksheet = Mock()
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:]
        spreadsheet = Mock()
        spreadsheet.worksheet_by_title.return_value = worksheet
        sheets_client = Mock()
        sheets_client.open_by_key.return_value = spreadsheet

        with patch.object(google_sheets.pygsheets, 'authorize', return_value=sheets_client):
            google_sheets.registration_worksheet()

        sheets_client.open_by_key.assert_called_once_with('shared-spreadsheet-id')
        spreadsheet.worksheet_by_title.assert_called_once_with('Staging Registrations')

    def test_sheet_adds_new_columns_to_existing_valid_headers(self):
        worksheet = Mock()
        worksheet.get_row.return_value = google_sheets.REGISTRATION_HEADERS[:-1]
        spreadsheet = Mock()
        spreadsheet.worksheet_by_title.return_value = worksheet
        sheets_client = Mock()
        sheets_client.open.return_value = spreadsheet

        with patch.object(google_sheets.pygsheets, 'authorize', return_value=sheets_client):
            google_sheets.registration_worksheet()

        worksheet.update_row.assert_called_once_with(1, google_sheets.REGISTRATION_HEADERS)

    def test_sheet_adds_new_columns_after_custom_columns(self):
        worksheet = Mock()
        existing_headers = google_sheets.REGISTRATION_HEADERS[:-2]
        existing_headers.insert(2, 'Followed Up')
        worksheet.get_row.return_value = existing_headers
        spreadsheet = Mock()
        spreadsheet.worksheet_by_title.return_value = worksheet
        sheets_client = Mock()
        sheets_client.open.return_value = spreadsheet

        with patch.object(google_sheets.pygsheets, 'authorize', return_value=sheets_client):
            google_sheets.registration_worksheet()

        worksheet.update_row.assert_called_once_with(
            1,
            existing_headers + google_sheets.REGISTRATION_HEADERS[-2:],
        )

    def test_sheet_rejects_missing_managed_column(self):
        worksheet = Mock()
        headers = google_sheets.REGISTRATION_HEADERS[:]
        headers.remove('Email')
        worksheet.get_row.return_value = headers
        spreadsheet = Mock()
        spreadsheet.worksheet_by_title.return_value = worksheet
        sheets_client = Mock()
        sheets_client.open.return_value = spreadsheet

        with patch.object(google_sheets.pygsheets, 'authorize', return_value=sheets_client):
            with self.assertRaisesRegex(RuntimeError, 'headers do not match'):
                google_sheets.registration_worksheet()

    def test_sheet_allows_custom_columns_among_registration_headers(self):
        worksheet = Mock()
        headers = google_sheets.REGISTRATION_HEADERS[:]
        headers.insert(2, 'Followed Up')
        headers.append('Internal Notes')
        worksheet.get_row.return_value = headers
        spreadsheet = Mock()
        spreadsheet.worksheet_by_title.return_value = worksheet
        sheets_client = Mock()
        sheets_client.open.return_value = spreadsheet

        with patch.object(google_sheets.pygsheets, 'authorize', return_value=sheets_client):
            result = google_sheets.registration_worksheet()

        self.assertIs(result, worksheet)
        worksheet.update_row.assert_not_called()

    @patch.dict(os.environ, {'RETREAT_REGISTRATION_AMOUNT': '125.00'}, clear=False)
    def test_record_registration_aligns_values_around_custom_columns(self):
        headers = google_sheets.REGISTRATION_HEADERS[:]
        headers.insert(2, 'Followed Up')
        worksheet = Mock()
        worksheet.get_row.return_value = headers
        worksheet.get_col.return_value = ['Registration ID', 'existing-registration']

        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            google_sheets.record_registration(registration_data(), 'registration-123')

        row_number, row = worksheet.update_row.call_args.args
        values = dict(zip(headers, row))
        self.assertEqual(row_number, 3)
        self.assertEqual(values['Registration ID'], 'registration-123')
        self.assertEqual(values['Followed Up'], '')
        self.assertEqual(values['Email'], 'student@example.com')

    def test_payment_update_uses_live_header_positions(self):
        headers = google_sheets.REGISTRATION_HEADERS[:]
        headers.insert(2, 'Followed Up')
        worksheet = Mock()
        worksheet.get_row.return_value = headers
        worksheet.get_col.return_value = ['Registration ID', 'registration-123']

        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            google_sheets.update_registration_payment(
                'registration-123',
                **{'Payment Status': 'Paid'},
            )

        payment_column = headers.index('Payment Status') + 1
        worksheet.update_value.assert_called_once_with((2, payment_column), 'Paid')

    def test_registration_field_uses_live_header_positions(self):
        headers = google_sheets.REGISTRATION_HEADERS[:]
        headers.insert(2, 'Followed Up')
        worksheet = Mock()
        worksheet.get_row.return_value = headers
        worksheet.get_col.return_value = ['Registration ID', 'registration-123']
        worksheet.get_value.return_value = 'Sent'

        with patch.object(google_sheets, 'registration_worksheet', return_value=worksheet):
            value = google_sheets.registration_field(
                'registration-123',
                'Confirmation Email Status',
            )

        self.assertEqual(value, 'Sent')
        status_column = headers.index('Confirmation Email Status') + 1
        worksheet.get_value.assert_called_once_with((2, status_column))


class PayPalTests(unittest.TestCase):
    def setUp(self):
        self.late_fee_patcher = patch.dict(
            os.environ,
            {'RETREAT_LATE_FEE_START': '2999-10-10T00:00:00-04:00'},
        )
        self.late_fee_patcher.start()
        home.app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client = home.app.test_client()

    def tearDown(self):
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
        self.assertEqual(
            payload['payment_source']['paypal']['experience_context']['shipping_preference'],
            'NO_SHIPPING',
        )

    @patch.object(paypal_service, 'get_paypal_access_token', return_value='access-token')
    @patch.object(paypal_service.requests, 'post')
    def test_capture_order_calls_expected_endpoint(self, requests_post, get_access_token):
        requests_post.return_value = FakeResponse({'id': 'ORDER-1', 'status': 'COMPLETED'})

        capture = paypal_service.capture_order('ORDER-1')

        self.assertEqual(capture['status'], 'COMPLETED')
        self.assertTrue(requests_post.call_args.args[0].endswith('/ORDER-1/capture'))


if __name__ == '__main__':
    unittest.main()
