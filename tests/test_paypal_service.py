import unittest
from unittest.mock import Mock, patch

import paypal_service

from tests.helpers import FakeResponse


class PayPalServiceTests(unittest.TestCase):
    @patch.object(paypal_service.requests, 'post')
    def test_paypal_error_retains_safe_api_diagnostics(self, requests_post):
        response = Mock(status_code=422)
        response.json.return_value = {
            'name': 'UNPROCESSABLE_ENTITY',
            'message': 'The requested action could not be performed.',
            'debug_id': 'debug-123',
            'details': [{
                'issue': 'INSTRUMENT_DECLINED',
                'description': 'The instrument presented was declined.',
                'field': '/payment_source/card',
            }],
        }
        requests_post.return_value = response
        response.raise_for_status.side_effect = paypal_service.requests.HTTPError(
            response=response,
        )

        with self.assertRaises(paypal_service.PayPalError) as raised:
            paypal_service.paypal_post('/v2/checkout/orders')

        self.assertEqual(raised.exception.diagnostics['http_status'], 422)
        self.assertEqual(raised.exception.diagnostics['debug_id'], 'debug-123')
        self.assertEqual(
            raised.exception.diagnostics['details'][0]['issue'],
            'INSTRUMENT_DECLINED',
        )

    def test_paypal_diagnostics_tolerates_non_object_json(self):
        response = Mock(status_code=500)
        response.json.return_value = ['unexpected payload']

        diagnostics = paypal_service.paypal_diagnostics(response)

        self.assertEqual(diagnostics, {'http_status': 500})

    @patch.object(paypal_service, 'get_paypal_access_token', return_value='access-token')
    @patch.object(paypal_service.requests, 'post')
    def test_create_order_builds_paypal_payload(self, requests_post, get_access_token):
        requests_post.return_value = FakeResponse({'id': 'ORDER-1'})

        order = paypal_service.create_order('62.50', 'registration-123')

        self.assertEqual(order['id'], 'ORDER-1')
        payload = requests_post.call_args.kwargs['json']
        self.assertEqual(payload['purchase_units'][0]['amount']['value'], '62.50')
        self.assertEqual(payload['purchase_units'][0]['custom_id'], 'registration-123')
        self.assertEqual(
            payload['payment_source']['paypal']['experience_context']['shipping_preference'],
            'NO_SHIPPING',
        )

    @patch.object(paypal_service, 'get_paypal_access_token', return_value='access-token')
    @patch.object(paypal_service.requests, 'post')
    def test_capture_order_calls_expected_endpoint(self, requests_post, get_access_token):
        requests_post.return_value = FakeResponse({'id': 'ORDER-1', 'status': 'COMPLETED'})

        capture = paypal_service.capture_order('ORDER-1')

        self.assertEqual(capture['status'], 'COMPLETED')
        self.assertTrue(requests_post.call_args.args[0].endswith('/ORDER-1/capture'))


if __name__ == '__main__':
    unittest.main()
