"""The displayed callback and OAuth request must use the same loopback origin."""
from flask import Flask
import unittest

from cloud_oauth import authorization_origin


class CloudOAuthOriginTests(unittest.TestCase):
    def test_localhost_and_loopback_display_identical_callback_origin(self):
        app=Flask(__name__)
        for base in ('http://localhost:8765','http://127.0.0.1:8765'):
            with self.subTest(base=base),app.test_request_context('/',base_url=base,environ_base={'REMOTE_ADDR':'127.0.0.1'}):
                self.assertEqual(authorization_origin(),'http://127.0.0.1:8765')

    def test_fallback_port_is_preserved(self):
        app=Flask(__name__)
        with app.test_request_context('/',base_url='http://127.0.0.1:8766',environ_base={'REMOTE_ADDR':'127.0.0.1'}):
            self.assertEqual(authorization_origin(),'http://127.0.0.1:8766')

    def test_remote_host_peer_and_https_are_rejected(self):
        app=Flask(__name__)
        for base,peer in (('http://workbench.example:8765','127.0.0.1'),
                          ('http://127.0.0.1:8765','198.51.100.7'),
                          ('https://127.0.0.1:8765','127.0.0.1')):
            with self.subTest(base=base,peer=peer),app.test_request_context('/',base_url=base,environ_base={'REMOTE_ADDR':peer}):
                with self.assertRaises(ValueError):authorization_origin()


if __name__=='__main__':unittest.main()
