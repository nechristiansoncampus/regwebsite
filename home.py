from flask import Flask
from flask import jsonify, redirect, render_template, request, session, url_for

import os
import re
import secrets
from datetime import datetime, timezone

import pygsheets

from google_sheets import record_registration
from paypal_service import PayPalError, capture_order, create_order
from registration import (
    FULL_TIMER_STATES,
    FULL_TIMER_STATUS_KEYS,
    is_ccsu,
    is_other_status,
    late_fee_amount,
    parse_registration,
    payment_not_required,
    registration_amount,
    registration_amount_display,
    validate_registration,
)

app = Flask(__name__)


def required_setting(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f'{name} must be set.')
    return value


def load_local_env():
    env_path = os.path.join(app.root_path, '.env')
    if not os.path.exists(env_path):
        return

    with open(env_path) as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue

            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


load_local_env()

app.secret_key = required_setting('FLASK_SECRET_KEY')


@app.context_processor
def registration_config():
    return {
        'registration_amount_display': registration_amount_display(),
        'full_timer_states': sorted(FULL_TIMER_STATES),
        'full_timer_status_keys': sorted(FULL_TIMER_STATUS_KEYS),
    }


@app.route("/", methods=['post', 'get'])
def home():
    return render_template('fall_retreat.html')

@app.route("/spring-retreat", methods=['get'])
def spring_retreat():
    return render_template('spring_retreat.html')

@app.route("/fall-retreat", methods=['get'])
def fall_retreat():
    return render_template('fall_retreat.html')

@app.route("/register", methods=['get', 'post'])
def register():
    if request.method == 'POST':
        registration = parse_registration(request.form)
        validation_error = validate_registration(registration)
        if validation_error:
            return render_template(
                'register.html',
                error=validation_error,
                registration=registration,
            )

        no_payment = payment_not_required(registration)
        if no_payment or is_other_status(registration):
            registration['attended_before'] = ''
        if no_payment:
            registration['payment_option'] = 'not_required'

        if registration['payment_option'] == 'pay_full':
            submitted_at = datetime.now(timezone.utc)
            registration['late_fee'] = f'{late_fee_amount(submitted_at):.2f}'
            registration['amount_due'] = registration_amount(registration, submitted_at)
        else:
            registration['late_fee'] = ''
            registration['amount_due'] = ''

        registration_token = secrets.token_urlsafe(16)
        session['registration'] = registration
        session['registration_token'] = registration_token
        if no_payment or registration['payment_option'] == 'scholarship':
            try:
                record_registration(registration, registration_token)
            except Exception:
                app.logger.exception('Unable to save registration to Google Sheets.')
                return render_template(
                    'register.html',
                    error='We could not save your registration. Please try again.',
                    registration=registration,
                )

        if no_payment:
            return render_template(
                'registration_confirmation.html',
                registration=registration,
                ccsu_registration=is_ccsu(registration),
            )

        if registration['payment_option'] == 'scholarship':
            return render_template('scholarship_confirmation.html', registration=registration)

        return render_template(
            'checkout.html',
            registration=registration,
            paypal_client_id=os.environ.get('PAYPAL_CLIENT_ID'),
            amount=registration['amount_due'],
            late_fee=registration['late_fee'],
        )

    return render_template('register.html')

@app.route("/checkout", methods=['get'])
def checkout():
    registration = session.get('registration')
    if not registration:
        return render_template('register.html', error='Please register before checking out.')

    if payment_not_required(registration):
        return render_template(
            'registration_confirmation.html',
            registration=registration,
            ccsu_registration=is_ccsu(registration),
        )

    return render_template(
        'checkout.html',
        registration=registration,
        paypal_client_id=os.environ.get('PAYPAL_CLIENT_ID'),
        amount=registration.get('amount_due') or registration_amount(registration),
        late_fee=registration.get('late_fee', ''),
    )


@app.route("/api/paypal/orders", methods=['post'])
def create_paypal_order():
    registration = session.get('registration')
    if not registration:
        return jsonify({'error': 'Registration is required before checkout.'}), 400

    if payment_not_required(registration):
        return jsonify({'error': 'Payment is not required for this registration.'}), 400

    amount = registration.get('amount_due') or registration_amount(registration)

    try:
        order = create_order(amount, session.get('registration_token'))
    except PayPalError as error:
        return jsonify({'error': str(error)}), 500

    session['paypal_order_id'] = order.get('id')
    return jsonify(order)

@app.route("/api/paypal/orders/<order_id>/capture", methods=['post'])
def capture_paypal_order(order_id):
    registration = session.get('registration')
    if not registration:
        return jsonify({'error': 'Registration is required before checkout.'}), 400

    if payment_not_required(registration):
        return jsonify({'error': 'Payment is not required for this registration.'}), 400

    if not session.get('paypal_order_id') or order_id != session.get('paypal_order_id'):
        return jsonify({'error': 'PayPal order does not match this registration.'}), 400

    if session.get('payment_completed'):
        return save_paid_registration(registration)

    try:
        capture = capture_order(order_id)
    except PayPalError as error:
        return jsonify({'error': str(error)}), 500

    capture_details = (
        capture.get('purchase_units', [{}])[0]
        .get('payments', {})
        .get('captures', [{}])[0]
    )
    if capture_details.get('status') != 'COMPLETED':
        return jsonify(capture)

    registration.update({
        'payment_status': 'Paid',
        'paypal_order_id': capture.get('id', order_id),
        'paypal_capture_id': capture_details.get('id', ''),
        'paid_at': capture_details.get('create_time', ''),
    })
    session['registration'] = registration
    session['payment_completed'] = True
    return save_paid_registration(registration)


def save_paid_registration(registration):
    try:
        record_registration(registration, session.get('registration_token'))
    except Exception:
        app.logger.exception('Payment completed but registration could not be saved.')
        return jsonify({
            'error': (
                'Your payment was received, but we could not save your registration. '
                'Please contact us and do not submit another payment.'
            ),
            'payment_completed': True,
        }), 500

    session['completed_registration'] = {
        'first_name': registration.get('first_name', ''),
    }
    session.pop('registration', None)
    session.pop('registration_token', None)
    session.pop('paypal_order_id', None)
    session.pop('payment_completed', None)
    return jsonify({
        'status': 'COMPLETED',
        'redirect_url': url_for('registration_complete'),
    })


@app.route('/registration-complete', methods=['get'])
def registration_complete():
    completed_registration = session.get('completed_registration')
    if not completed_registration:
        return redirect(url_for('register'))
    return render_template(
        'payment_confirmation.html',
        registration=completed_registration,
    )

@app.route("/info", methods=['post', 'get'])
def info():
    gc = pygsheets.authorize(service_account_env_var='service_credentials')
    # add regwebsite@reg-website-341515.iam.gserviceaccount.com as editor to sheet
    sh = gc.open('2026 Fall Retreat - Registration (Responses)')
    wks = sh.worksheet_by_title('Responses')

    if request.method == 'POST':
        i = 0
        for row in wks:
            i += 1
            sheet_pn = re.sub(r"\D", "", row[11]) #removes anything that's not a number
            form_pn = request.form['phone']
            print(sheet_pn, form_pn)
            if sheet_pn == form_pn:
                if (row[6].strip() == ''):
                    return render_template('not_paid.html', name=row[3] + ' ' + row[4])
                else:
                    wks.update_value('B' + str(i), True)
                    return render_template('info.html', name=row[3] + ' ' + row[4], group=row[13], housing=row[14])
                break
    return render_template('home.html', error="Phone number not registered")

@app.route("/check-in", methods=['get'])
def check_in():
    return render_template('check_in.html')

# @app.route("/announcements", methods=['get'])
# def announcements():
#     gc = pygsheets.authorize(service_account_env_var='service_credentials')
#     sh = gc.open('2022 Spring Retreat - Registration & Planning')
#     wks = sh.worksheet_by_title('Announcements')

#     announcements = []
#     i = 0
#     for row in wks:
#         if i == 0:
#             i += 1
#             continue
#         announcements.append(row[0])
#         i += 1
#     return render_template('announcements.html', announcements=announcements)
