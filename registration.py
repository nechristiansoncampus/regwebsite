import os
import re
from decimal import Decimal, InvalidOperation


EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def parse_registration(form):
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
        'status': form.get('status', '').strip(),
        'status_other': form.get('status_other', '').strip(),
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
    if registration['status'] == 'Other':
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

    phone_digits = re.sub(r'\D', '', registration['phone'])
    if registration['phone'].startswith('+') or len(phone_digits) != 10:
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
        if registration['attended_before'] not in ['yes', 'no']:
            return 'Please let us know if you have attended one of our retreats before.'

    return None


def registration_amount(registration):
    configured_amount = os.environ.get('RETREAT_REGISTRATION_AMOUNT', '125.00')
    try:
        amount = Decimal(configured_amount)
    except InvalidOperation:
        amount = Decimal('125.00')

    if registration.get('attended_before') == 'no':
        amount *= Decimal('0.50')

    return f'{amount.quantize(Decimal("0.01"))}'


def is_full_timer(registration):
    status = registration.get('status', '')
    return bool(re.search(r'full[\s-]*timer', status, re.IGNORECASE))


def is_ccsu(registration):
    campus = re.sub(r'[^a-z0-9]+', ' ', registration.get('campus', '').casefold()).strip()
    compact_campus = campus.replace(' ', '')
    return compact_campus == 'ccsu' or bool(
        re.search(r'\bcentral (?:connecticut|conn|ct) state(?: university| univ| college)?\b', campus)
    )


def payment_not_required(registration):
    return is_ccsu(registration) or is_full_timer(registration)


def initial_payment_status(registration):
    if payment_not_required(registration):
        return 'Not required'
    if registration.get('payment_option') == 'scholarship':
        return 'Scholarship application pending'
    return 'Pending'
