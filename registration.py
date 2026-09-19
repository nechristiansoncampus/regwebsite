import os
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone


EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def parse_registration(form):
    status_selection = form.get('status', '').strip()
    registration = {
        'email': form.get('email', '').strip(),
        'first_name': form.get('first_name', '').strip(),
        'last_name': form.get('last_name', '').strip(),
        'phone': form.get('phone', '').strip(),
        'gender': form.get('gender', '').strip(),
        'campus': form.get('campus', '').strip(),
        'campus_other': form.get('campus_other', '').strip(),
        'school_state': form.get('school_state', '').strip(),
        'school_state_other': form.get('school_state_other', '').strip(),
        'status': status_selection,
        'status_other': form.get('status_other', '').strip(),
        'status_is_other': status_selection == 'Other',
        'transportation': form.get('transportation', '').strip(),
        'transportation_other': form.get('transportation_other', '').strip(),
        'car_capacity': form.get('car_capacity', '').strip(),
        'payment_option': form.get('payment_option', '').strip(),
        'attended_before': form.get('attended_before', '').strip(),
        'allergies': form.get('allergies', '').strip(),
        'comments': form.get('comments', '').strip(),
    }

    if registration['school_state'] == 'Other':
        registration['school_state'] = registration['school_state_other']
    if registration['campus'] == 'Other':
        registration['campus'] = registration['campus_other']
    if registration['status_is_other']:
        registration['status'] = registration['status_other']

    return registration


def validate_registration(registration):
    required_fields = [
        'email', 'first_name', 'last_name', 'phone', 'gender', 'campus',
        'school_state', 'status',
    ]
    if any(not registration[field] for field in required_fields):
        return 'Please fill out every field.'

    if not EMAIL_PATTERN.match(registration['email']):
        return 'Please enter a valid email address.'

    if not re.fullmatch(r'\d{10}', registration['phone']):
        return 'Please enter a 10-digit phone number without a country code.'

    if registration['school_state'] == 'Massachusetts':
        if not registration['transportation']:
            return 'Please fill out every field.'
        if registration['transportation'] == 'Other' and not registration['transportation_other']:
            return 'Please fill out every field.'
        if (
            registration['transportation'] == 'I have a car and can give rides'
            and not registration['car_capacity']
        ):
            return 'Please fill out every field.'

    if not payment_not_required(registration):
        if registration['payment_option'] not in ['scholarship', 'pay_full']:
            return 'Please choose a payment option.'
        if not is_other_status(registration) and registration['attended_before'] not in ['yes', 'no']:
            return 'Please let us know if you have attended one of our retreats before.'

    return None


def late_fee_amount(now=None):
    cutoff_text = os.environ.get(
        'RETREAT_LATE_FEE_START',
        '2026-10-10T00:00:00-04:00',
    )
    if not cutoff_text:
        return Decimal('0.00')

    try:
        cutoff = datetime.fromisoformat(cutoff_text)
    except ValueError as error:
        raise RuntimeError('RETREAT_LATE_FEE_START must be an ISO 8601 timestamp.') from error
    if cutoff.tzinfo is None:
        raise RuntimeError('RETREAT_LATE_FEE_START must include a UTC offset.')

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError('The current time must include timezone information.')
    if current_time < cutoff:
        return Decimal('0.00')

    configured_fee = os.environ.get('RETREAT_LATE_FEE_AMOUNT', '10.00')
    try:
        return Decimal(configured_fee).quantize(Decimal('0.01'))
    except InvalidOperation:
        return Decimal('10.00')


def base_registration_amount():
    configured_amount = os.environ.get('RETREAT_REGISTRATION_AMOUNT', '125.00')
    try:
        return Decimal(configured_amount).quantize(Decimal('0.01'))
    except InvalidOperation:
        return Decimal('125.00')


def registration_amount_display():
    amount = base_registration_amount()
    if amount == amount.to_integral():
        return f'{amount:,.0f}'
    return f'{amount:,.2f}'


def registration_amount(registration, now=None):
    amount = base_registration_amount()

    if registration.get('attended_before') == 'no' and not is_other_status(registration):
        amount *= Decimal('0.50')

    amount += late_fee_amount(now)

    return f'{amount.quantize(Decimal("0.01"))}'


def is_other_status(registration):
    return registration.get('status_is_other', False) or registration.get('status') == 'Other'


def is_full_timer(registration):
    if not is_other_status(registration):
        return False
    status = registration.get('status_other') or registration.get('status', '')
    compact_status = re.sub(r'[^a-z0-9]+', '', status.casefold())
    return compact_status in {'ft', 'fulltime', 'fulltimer'}


def is_ccsu(registration):
    campus = re.sub(r'[^a-z0-9]+', ' ', registration.get('campus', '').casefold()).strip()
    compact_campus = campus.replace(' ', '')
    return compact_campus == 'ccsu' or bool(
        re.search(r'\bcentral (?:connecticut|conn|ct) state(?: university| univ| college)?\b', campus)
    )


def payment_not_required(registration):
    is_eligible_full_timer = (
        registration.get('school_state') in {'Massachusetts', 'New Hampshire'}
        and is_full_timer(registration)
    )
    return is_ccsu(registration) or is_eligible_full_timer


def initial_payment_status(registration):
    if payment_not_required(registration):
        return 'Not required'
    if registration.get('payment_option') == 'scholarship':
        return 'Scholarship application pending'
    return 'Pending'
