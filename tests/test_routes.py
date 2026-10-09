import os
import unittest
from datetime import datetime, timezone
from unittest.mock import mock_open, patch

import home
import registration

from tests.helpers import registration_data


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
        self.email_queue_patcher = patch.object(home, 'queue_confirmation_email')
        self.queue_confirmation_email = self.email_queue_patcher.start()

    def tearDown(self):
        self.email_queue_patcher.stop()
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

    @patch.object(home.os.path, 'exists', return_value=True)
    @patch(
        'builtins.open',
        new_callable=mock_open,
        read_data="\n# comment\nINVALID\nTEST_SETTING = 'from-file'\n",
    )
    def test_local_env_loader_ignores_non_settings_and_loads_values(
        self, open_file, path_exists
    ):
        with patch.dict(os.environ, {}, clear=True):
            home.load_local_env()

            self.assertEqual(os.environ['TEST_SETTING'], 'from-file')

        path_exists.assert_called_once()
        open_file.assert_called_once_with(os.path.join(home.app.root_path, '.env'))

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

    def test_registration_page_shows_deadline_and_late_fee_date(self):
        html = self.client.get('/register').get_data(as_text=True)

        self.assertEqual(html.count('class="registrationTimingItem deadline"'), 1)
        self.assertEqual(html.count('class="registrationTimingItem lateFee"'), 1)
        self.assertIn('Registration deadline</span>\n          October 11', html)
        self.assertIn('Late fee</span>\n          $10 beginning October 12', html)
        self.assertIn('I’ll pay for my registration now.', html)

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
        self.assertIn('class="registrationTimingItem deadline"', html)
        self.assertIn('class="registrationTimingItem lateFee"', html)
        self.assertIn('src="/static/img/fall_retreat_promo.mp4"', html)
        self.assertIn('data-src="/static/img/describe-retreat.mp4"', html)
        self.assertIn('preload="none"', html)
        testimonial_video = html.split('id="reel2"', 1)[1].split('>', 1)[0]
        self.assertNotIn('\n              src=', testimonial_video)

    def test_video_responses_are_cacheable_at_the_edge(self):
        response = self.client.get(
            '/static/img/fall_retreat_promo.mp4',
            headers={'Range': 'bytes=0-1023'},
        )

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers['Cache-Control'], 'public, max-age=86400')
        self.assertEqual(
            response.headers['CDN-Cache-Control'],
            'public, max-age=604800',
        )
        response.close()

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

    def test_scholarship_choice_finishes_without_checkout(self):
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
        self.queue_confirmation_email.assert_called_once_with(
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

    def test_ccsu_registration_queues_ccsu_confirmation(self):
        self.client.post(
            '/register',
            data=registration_data(
                campus='CCSU',
                payment_option='',
                attended_before='',
            ),
        )

        registration_id = self.record_registration.call_args.args[1]
        self.queue_confirmation_email.assert_called_once_with(
            self.record_registration.call_args.args[0],
            registration_id,
            'ccsu',
        )

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
