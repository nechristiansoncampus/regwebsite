import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from html import escape


REQUIRED_SMTP_SETTINGS = ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_APP_PASSWORD')


def email_confirmation_configured():
    return all(os.environ.get(name) for name in REQUIRED_SMTP_SETTINGS)


def confirmation_content(registration, confirmation_kind):
    first_name = registration.get('first_name', 'there')
    if confirmation_kind == 'scholarship':
        subject = 'Retreat scholarship request received'
        detail = (
            'We received your retreat registration and scholarship request. '
            'We will email you with the scholarship application form. No payment is needed right now.'
        )
    elif confirmation_kind == 'paid':
        subject = 'Your fall retreat registration is confirmed'
        detail = 'Your payment was received and your retreat registration is complete.'
    else:
        subject = 'Your fall retreat registration is confirmed'
        detail = 'Your retreat registration is complete. No payment is required.'

    body = (
        f'Hi {first_name},\n\n'
        f'{detail}\n\n'
        'Fall Retreat\n'
        'October 17-18\n'
        'Camp Incarnation\n'
        '253 Bushy Hill Rd, Ivoryton, CT 06442\n\n'
        'Questions? Reply to this email.\n\n'
        'NE Christians on Campus'
    )
    html = (
        f'<p>Hi {escape(first_name)},</p>'
        f'<p>{escape(detail)}</p>'
        '<p><strong>Fall Retreat</strong><br>'
        'October 17-18<br>'
        'Camp Incarnation<br>'
        '253 Bushy Hill Rd, Ivoryton, CT 06442</p>'
        '<p>Questions? Reply to this email.</p>'
        '<p>NE Christians on Campus</p>'
    )
    return subject, body, html


def send_confirmation_email(registration, confirmation_kind):
    if not email_confirmation_configured():
        return False

    host = os.environ['SMTP_HOST']
    port = int(os.environ.get('SMTP_PORT', '587'))
    username = os.environ['SMTP_USERNAME']
    password = os.environ['SMTP_APP_PASSWORD'].replace(' ', '')
    sender = os.environ.get('SMTP_FROM', username)
    sender_name = os.environ.get('SMTP_FROM_NAME', 'NE Christians on Campus')
    subject, body, html = confirmation_content(registration, confirmation_kind)

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = formataddr((sender_name, sender))
    message['To'] = registration['email']
    message['Reply-To'] = os.environ.get('SMTP_REPLY_TO', sender)
    message.set_content(body)
    message.add_alternative(html, subtype='html')

    smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with smtp_class(host, port, timeout=10) as smtp:
        if port != 465:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)
    return True
