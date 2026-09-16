import os

import requests


PAYPAL_API_BASE = {
    'sandbox': 'https://api-m.sandbox.paypal.com',
    'live': 'https://api-m.paypal.com',
}


class PayPalError(RuntimeError):
    pass


def paypal_base_url():
    paypal_env = os.environ.get('PAYPAL_ENV', 'sandbox').lower()
    return PAYPAL_API_BASE.get(paypal_env, PAYPAL_API_BASE['sandbox'])


def get_paypal_access_token():
    client_id = os.environ.get('PAYPAL_CLIENT_ID')
    client_secret = os.environ.get('PAYPAL_CLIENT_SECRET')

    if not client_id or not client_secret:
        raise PayPalError('PayPal credentials are not configured.')

    try:
        response = requests.post(
            f'{paypal_base_url()}/v1/oauth2/token',
            auth=(client_id, client_secret),
            data={'grant_type': 'client_credentials'},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise PayPalError(str(error)) from error

    return response.json()['access_token']


def create_order(amount, registration_id):
    access_token = get_paypal_access_token()
    try:
        response = requests.post(
            f'{paypal_base_url()}/v2/checkout/orders',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            json={
                'intent': 'CAPTURE',
                'purchase_units': [{
                    'description': 'Retreat registration',
                    'custom_id': registration_id,
                    'amount': {
                        'currency_code': 'USD',
                        'value': amount,
                    },
                }],
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise PayPalError(str(error)) from error

    return response.json()


def capture_order(order_id):
    access_token = get_paypal_access_token()
    try:
        response = requests.post(
            f'{paypal_base_url()}/v2/checkout/orders/{order_id}/capture',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise PayPalError(str(error)) from error

    return response.json()
