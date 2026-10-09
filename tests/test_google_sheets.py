import os
import unittest
from unittest.mock import Mock, patch

import google_sheets

from tests.helpers import registration_data


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

