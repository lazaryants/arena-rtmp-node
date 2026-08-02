import unittest

from app.restream_manager import app
from app.wsgi import application


class WsgiTests(unittest.TestCase):
    def test_wsgi_exports_flask_application(self):
        self.assertIs(application, app)


if __name__ == "__main__":
    unittest.main()
