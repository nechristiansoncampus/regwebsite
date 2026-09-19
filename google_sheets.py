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
    'Confirmation Email Status',
    'Confirmation Email Sent At',
]


def registration_sheet_settings():
    app_env = os.environ.get('APP_ENV')
    is_production = (
        app_env.strip().casefold() == 'production'
        if app_env
        else bool(os.environ.get('RENDER'))
    )
    return {
        'spreadsheet_id': os.environ.get('REGISTRATION_SPREADSHEET_ID'),
        'spreadsheet_title': os.environ.get(
            'REGISTRATION_SPREADSHEET',
            '2026 Fall Retreat - Registration (Responses)',
        ),
        'worksheet_title': (
            os.environ.get('REGISTRATION_WORKSHEET', 'Registrations')
            if is_production
            else os.environ.get('REGISTRATION_TEST_WORKSHEET', 'Test Registrations')
        ),
    }


def registration_worksheet():
    settings = registration_sheet_settings()

    client = pygsheets.authorize(service_account_env_var='service_credentials')
    if settings['spreadsheet_id']:
        spreadsheet = client.open_by_key(settings['spreadsheet_id'])
    else:
        spreadsheet = client.open(settings['spreadsheet_title'])
    worksheet_title = settings['worksheet_title']

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
    else:
        missing_headers = [
            header for header in REGISTRATION_HEADERS if header not in current_headers
        ]
        duplicate_headers = [
            header for header in REGISTRATION_HEADERS if current_headers.count(header) > 1
        ]
        trailing_headers = REGISTRATION_HEADERS[len(REGISTRATION_HEADERS) - len(missing_headers):]
        if duplicate_headers or (missing_headers and missing_headers != trailing_headers):
            raise RuntimeError(
                f'The "{worksheet_title}" worksheet headers do not match the registration form.'
            )
        if missing_headers:
            worksheet.update_row(1, current_headers + missing_headers)

    return worksheet


def record_registration(registration, registration_id):
    worksheet = registration_worksheet()

    worksheet_headers = worksheet.get_row(1, include_tailing_empty=False)
    registration_id_column = worksheet_headers.index('Registration ID') + 1
    registration_ids = worksheet.get_col(
        registration_id_column,
        include_tailing_empty=False,
    )
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

    values_by_header = {
        'Registration ID': registration_id,
        'Submitted At': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'Email': registration.get('email', ''),
        'First Name': registration.get('first_name', ''),
        'Last Name': registration.get('last_name', ''),
        'Phone': registration.get('phone', ''),
        'Gender': registration.get('gender', ''),
        'College or University': registration.get('campus', ''),
        'Other College or University': registration.get('campus_other', ''),
        'School State': registration.get('school_state', ''),
        'Other School State': registration.get('school_state_other', ''),
        'Status': registration.get('status', ''),
        'Other Status': registration.get('status_other', ''),
        'Allergies & Dietary Restrictions': registration.get('allergies', ''),
        'Comments': registration.get('comments', ''),
        'Transportation': registration.get('transportation', ''),
        'Other Transportation': registration.get('transportation_other', ''),
        'Car Capacity': registration.get('car_capacity', ''),
        'Payment Option': registration.get('payment_option', ''),
        'First-Time Attendee': first_time,
        'Amount Due': amount_due,
        'Payment Status': (
            registration.get('payment_status') or initial_payment_status(registration)
        ),
        'PayPal Order ID': registration.get('paypal_order_id', ''),
        'PayPal Capture ID': registration.get('paypal_capture_id', ''),
        'Paid At': registration.get('paid_at', ''),
        'Late Fee': registration.get('late_fee', ''),
        'Confirmation Email Status': registration.get('confirmation_email_status', ''),
        'Confirmation Email Sent At': registration.get('confirmation_email_sent_at', ''),
    }
    worksheet.update_row(
        len(registration_ids) + 1,
        [values_by_header.get(header, '') for header in worksheet_headers],
    )


def registration_field(registration_id, header):
    worksheet = registration_worksheet()
    worksheet_headers = worksheet.get_row(1, include_tailing_empty=False)
    registration_id_column = worksheet_headers.index('Registration ID') + 1
    registration_ids = worksheet.get_col(
        registration_id_column,
        include_tailing_empty=False,
    )
    try:
        row_number = registration_ids.index(registration_id) + 1
    except ValueError as error:
        raise RuntimeError('Registration row was not found in Google Sheets.') from error
    return worksheet.get_value((row_number, worksheet_headers.index(header) + 1))


def update_registration(registration_id, **updates):
    worksheet = registration_worksheet()
    worksheet_headers = worksheet.get_row(1, include_tailing_empty=False)
    registration_id_column = worksheet_headers.index('Registration ID') + 1
    registration_ids = worksheet.get_col(
        registration_id_column,
        include_tailing_empty=False,
    )
    try:
        row_number = registration_ids.index(registration_id) + 1
    except ValueError as error:
        raise RuntimeError('Registration row was not found in Google Sheets.') from error

    header_columns = {header: index + 1 for index, header in enumerate(worksheet_headers)}
    for header, value in updates.items():
        worksheet.update_value((row_number, header_columns[header]), value)


update_registration_payment = update_registration
