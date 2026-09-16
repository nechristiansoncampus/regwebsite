from flask import Flask
from flask import jsonify, render_template, request, session

import os
import re
import secrets

import pygsheets

from google_sheets import record_registration, update_registration_payment
from paypal_service import PayPalError, capture_order, create_order
from registration import (
    is_ccsu,
    parse_registration,
    payment_not_required,
    registration_amount,
    validate_registration,
)

app = Flask(__name__)


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

app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-me')


@app.route("/", methods=['post', 'get'])
def home():
    return render_template('spring_retreat.html')

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
        if no_payment:
            registration['payment_option'] = 'not_required'
            registration['attended_before'] = ''

        registration_token = secrets.token_urlsafe(16)
        try:
            record_registration(registration, registration_token)
        except Exception:
            app.logger.exception('Unable to save registration to Google Sheets.')
            return render_template(
                'register.html',
                error='We could not save your registration. Please try again.',
                registration=registration,
            )

        session['registration'] = registration
        session['registration_token'] = registration_token
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
            amount=registration_amount(registration),
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
        amount=registration_amount(registration),
    )

@app.route("/api/paypal/orders", methods=['post'])
def create_paypal_order():
    registration = session.get('registration')
    if not registration:
        return jsonify({'error': 'Registration is required before checkout.'}), 400

    if payment_not_required(registration):
        return jsonify({'error': 'Payment is not required for this registration.'}), 400

    amount = registration_amount(registration)

    try:
        order = create_order(amount, session.get('registration_token'))
    except PayPalError as error:
        return jsonify({'error': str(error)}), 500

    try:
        update_registration_payment(
            session.get('registration_token'),
            **{
                'Payment Status': 'PayPal checkout started',
                'PayPal Order ID': order.get('id', ''),
            },
        )
    except Exception:
        app.logger.exception('Unable to update the PayPal order in Google Sheets.')

    return jsonify(order)

@app.route("/api/paypal/orders/<order_id>/capture", methods=['post'])
def capture_paypal_order(order_id):
    registration = session.get('registration')
    if not registration:
        return jsonify({'error': 'Registration is required before checkout.'}), 400

    try:
        capture = capture_order(order_id)
    except PayPalError as error:
        return jsonify({'error': str(error)}), 500

    session['payment'] = capture
    capture_details = (
        capture.get('purchase_units', [{}])[0]
        .get('payments', {})
        .get('captures', [{}])[0]
    )
    payment_status = 'Paid' if capture_details.get('status') == 'COMPLETED' else capture_details.get('status', 'Captured')
    try:
        update_registration_payment(
            session.get('registration_token'),
            **{
                'Payment Status': payment_status,
                'PayPal Order ID': capture.get('id', order_id),
                'PayPal Capture ID': capture_details.get('id', ''),
                'Paid At': capture_details.get('create_time', ''),
            },
        )
    except Exception:
        app.logger.exception('Unable to update the completed payment in Google Sheets.')

    return jsonify(capture)

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
