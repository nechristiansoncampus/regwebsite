import os
from datetime import datetime, timezone

import pygsheets

from registration import initial_payment_status, registration_amount


REGISTRATION_HEADERS = [
    'Registration ID',
    'Submitted At',
    'Email',
    'First Name',
    'Last Name',
    'Phone',
    'Gender',
    'College or University',
    'Other College or University',
    'School State',
    'Other School State',
    'Status',
    'Other Status',
    'Allergies & Dietary Restrictions',
    'Comments',
    'Transportation',
    'Other Transportation',
    'Car Capacity',
    'Payment Option',
    'First-Time Attendee',
    'Amount Due',
    'Payment Status',
    'PayPal Order ID',
    'PayPal Capture ID',
    'Paid At',
    'Late Fee',
]


def registration_worksheet():
    spreadsheet_id = os.environ.get('REGISTRATION_SPREADSHEET_ID')
    spreadsheet_title = os.environ.get(
        'REGISTRATION_SPREADSHEET',
        '2026 Fall Retreat - Registration (Responses)',
    )

    client = pygsheets.authorize(service_account_env_var='service_credentials')
    if spreadsheet_id:
        spreadsheet = client.open_by_key(spreadsheet_id)
    else:
        spreadsheet = client.open(spreadsheet_title)
    worksheet_title = os.environ.get('REGISTRATION_WORKSHEET', 'Registrations')

    try:
        worksheet = spreadsheet.worksheet_by_title(worksheet_title)
    except pygsheets.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            worksheet_title,
            rows=1000,
            cols=len(REGISTRATION_HEADERS),
        )

    current_headers = worksheet.get_row(1, include_tailing_empty=False)
    if not current_headers:
        worksheet.update_row(1, REGISTRATION_HEADERS)
    elif current_headers == REGISTRATION_HEADERS[:len(current_headers)]:
        if len(current_headers) < len(REGISTRATION_HEADERS):
            worksheet.update_row(1, REGISTRATION_HEADERS)
    else:
        raise RuntimeError(
            f'The "{worksheet_title}" worksheet headers do not match the registration form.'
        )

    return worksheet


def record_registration(registration, registration_id):
    worksheet = registration_worksheet()

    registration_ids = worksheet.get_col(1, include_tailing_empty=False)
    if registration_id in registration_ids:
        return

    first_time = ''
    if registration.get('attended_before') == 'no':
        first_time = 'Yes'
    elif registration.get('attended_before') == 'yes':
        first_time = 'No'

    amount_due = registration.get('amount_due', '')
    if registration.get('payment_option') == 'pay_full' and not amount_due:
        amount_due = registration_amount(registration)

    worksheet.append_table(values=[
        registration_id,
        datetime.now(timezone.utc).isoformat(timespec='seconds'),
        registration.get('email', ''),
        registration.get('first_name', ''),
        registration.get('last_name', ''),
        registration.get('phone', ''),
        registration.get('gender', ''),
        registration.get('campus', ''),
        registration.get('campus_other', ''),
        registration.get('school_state', ''),
        registration.get('school_state_other', ''),
        registration.get('status', ''),
        registration.get('status_other', ''),
        registration.get('allergies', ''),
        registration.get('comments', ''),
        registration.get('transportation', ''),
        registration.get('transportation_other', ''),
        registration.get('car_capacity', ''),
        registration.get('payment_option', ''),
        first_time,
        amount_due,
        registration.get('payment_status') or initial_payment_status(registration),
        registration.get('paypal_order_id', ''),
        registration.get('paypal_capture_id', ''),
        registration.get('paid_at', ''),
        registration.get('late_fee', ''),
    ], start='A1')


def update_registration_payment(registration_id, **updates):
    worksheet = registration_worksheet()
    registration_ids = worksheet.get_col(1, include_tailing_empty=False)
    try:
        row_number = registration_ids.index(registration_id) + 1
    except ValueError as error:
        raise RuntimeError('Registration row was not found in Google Sheets.') from error

    header_columns = {header: index + 1 for index, header in enumerate(REGISTRATION_HEADERS)}
    for header, value in updates.items():
        worksheet.update_value((row_number, header_columns[header]), value)
