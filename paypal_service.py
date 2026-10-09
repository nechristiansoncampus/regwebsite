import os

import requests


PAYPAL_API_BASE = {
    'sandbox': 'https://api-m.sandbox.paypal.com',
    'live': 'https://api-m.paypal.com',
}


class PayPalError(RuntimeError):
    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def paypal_base_url():
    paypal_env = os.environ.get('PAYPAL_ENV', 'sandbox').lower()
    return PAYPAL_API_BASE.get(paypal_env, PAYPAL_API_BASE['sandbox'])


def paypal_diagnostics(response):
    if response is None:
        return {}

    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}

    diagnostics = {
        'http_status': getattr(response, 'status_code', None),
        'name': payload.get('name'),
        'message': payload.get('message'),
        'debug_id': payload.get('debug_id'),
    }
    details = []
    for detail in payload.get('details', [])[:5]:
        details.append({
            key: detail.get(key)
            for key in ('issue', 'description', 'field', 'location')
            if detail.get(key)
        })
    if details:
        diagnostics['details'] = details
    return {key: value for key, value in diagnostics.items() if value is not None}


def paypal_post(path, **kwargs):
    try:
        response = requests.post(
            f'{paypal_base_url()}{path}',
            timeout=15,
            **kwargs,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        diagnostics = paypal_diagnostics(getattr(error, 'response', None))
        message = diagnostics.get('message') or str(error)
        raise PayPalError(message, diagnostics) from error
    return response.json()


def get_paypal_access_token():
    client_id = os.environ.get('PAYPAL_CLIENT_ID')
    client_secret = os.environ.get('PAYPAL_CLIENT_SECRET')

    if not client_id or not client_secret:
        raise PayPalError('PayPal credentials are not configured.')

    response = paypal_post(
        '/v1/oauth2/token',
        auth=(client_id, client_secret),
        data={'grant_type': 'client_credentials'},
    )
    return response['access_token']


def create_order(amount, registration_id):
    access_token = get_paypal_access_token()
    return paypal_post(
        '/v2/checkout/orders',
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        },
        json={
            'intent': 'CAPTURE',
            'payment_source': {
                'paypal': {
                    'experience_context': {
                        'shipping_preference': 'NO_SHIPPING',
                    },
                },
            },
            'purchase_units': [{
                'description': 'Retreat registration',
                'custom_id': registration_id,
                'amount': {
                    'currency_code': 'USD',
                    'value': amount,
                },
            }],
        },
    )


def capture_order(order_id):
    access_token = get_paypal_access_token()
    return paypal_post(
        f'/v2/checkout/orders/{order_id}/capture',
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        },
    )
