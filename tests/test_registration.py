import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import registration

from tests.helpers import registration_data


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
            'RETREAT_LATE_FEE_START': '2026-10-12T00:00:00-04:00',
        },
        clear=False,
    )
    def test_late_fee_starts_at_midnight_eastern_after_discount(self):
        before_cutoff = datetime(2026, 10, 12, 3, 59, 59, tzinfo=timezone.utc)
        at_cutoff = datetime(2026, 10, 12, 4, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(registration.late_fee_amount(before_cutoff), 0)
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
