"""Regression coverage for clearing a remembered optional Google credential."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs,urlsplit

from google_drive_auth import GoogleDriveConnection
from test_google_drive_auth import CLIENT,ORIGIN,Transport,Vault


class GoogleClientSecretClearReviewTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.owner=SimpleNamespace(DATA=Path(temporary.name).resolve())
        self.transport=Transport();self.vault=Vault()
        original=GoogleDriveConnection(self.owner,self.transport,self.vault)
        original.configure(CLIENT,'invented-optional-secret-to-clear',remember=True)
        self.complete_login(original)
        self.restarted=GoogleDriveConnection(self.owner,self.transport,self.vault)

    def complete_login(self,connection):
        result=connection.begin(ORIGIN)
        state=parse_qs(urlsplit(result['authorize_url']).query)['state'][0]
        return connection.callback(state,'invented-review-code',callback_origin=ORIGIN)

    def test_explicit_clear_after_restart_updates_configured_status(self):
        self.restarted.configure(CLIENT,client_secret='',remember=True)
        self.assertFalse(self.restarted.status()['client_secret_configured'])

    def test_explicit_clear_after_restart_never_restores_or_sends_the_old_secret(self):
        self.restarted.configure(CLIENT,client_secret='',remember=True)
        self.complete_login(self.restarted)
        self.assertNotIn('client_secret',self.transport.tokens[-1])
        self.assertFalse(self.restarted.status()['client_secret_configured'])
        for value in self.vault.values.values():
            self.assertNotIn('client_secret',json.loads(value))


if __name__=='__main__':unittest.main()
