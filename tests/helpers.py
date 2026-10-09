def registration_data(**overrides):
    data = {
        'email': 'student@example.com',
        'first_name': 'Jamie',
        'last_name': 'Student',
        'phone': '5551234567',
        'gender': 'Female',
        'campus': 'MIT',
        'campus_other': '',
        'school_state': 'Connecticut',
        'school_state_other': '',
        'status': 'Senior',
        'status_other': '',
        'transportation': '',
        'transportation_other': '',
        'car_capacity': '',
        'payment_option': 'pay_full',
        'attended_before': 'yes',
        'allergies': '',
        'comments': '',
    }
    data.update(overrides)
    return data


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

