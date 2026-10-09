import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import home


home.record_registration = lambda registration, registration_id: None
home.queue_confirmation_email = lambda registration, registration_id, kind: None


if __name__ == '__main__':
    home.app.run(
        host='127.0.0.1',
        port=int(os.environ.get('E2E_PORT', '5010')),
        debug=False,
        use_reloader=False,
    )
