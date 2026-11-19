"""Cross-collection integrity regression identified during cloud review."""
from copy import deepcopy
import unittest

import test_cloud_setup as fixtures


class CloudAttachmentStatusReviewTests(unittest.TestCase):
    def test_status_does_not_report_other_collection_attachment_as_active(self):
        fixture=fixtures.CloudSetupTests('test_status_is_local_only_and_does_not_call_remote_provider')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        attached=fixture.attach(fixture.preview())
        self.assertEqual(attached.status_code,200,attached.json)
        other=fixture.saved.save_snapshot({'scope_key':'invented:other-cloud-collection',
            'tracks':deepcopy(fixture.before['tracks']),'playlists':[]},'Other invented collection')
        for client in fixture.clients.values():client.rpc.reset_mock()
        response=fixture.client.get('/api/cloud-setup/status',query_string={'source':'snapshot:'+other['id']})
        self.assertEqual(response.status_code,200,response.json)
        self.assertFalse(response.json['providers']['dropbox']['attachment_active'])
        self.assertIsNone(response.json['providers']['dropbox']['mapping'])
        # Keep the configured attachment available as a candidate to re-preview.
        self.assertIsNotNone(response.json['attachments']['dropbox'])
        for client in fixture.clients.values():client.rpc.assert_not_called()


if __name__=='__main__':unittest.main()
