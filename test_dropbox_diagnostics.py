"""Useful Dropbox failures without provider-body or credential disclosure."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

from dropbox_auth import DropboxConnection,SCOPES
from dropbox_http import DropboxError,DropboxTransport,_provider_error


class DropboxDiagnosticTests(unittest.TestCase):
    def test_unknown_failure_returns_safe_http_details_in_message_and_json(self):
        body=json.dumps({'error_summary':'PRIVATE_ACCESS/secret-path','error':{'.tag':'PRIVATE_TOKEN'}}).encode()
        failure=_provider_error(400,body,{'X-Dropbox-Request-Id':'c1234-d5678'})
        self.assertEqual(failure.public_fields(),{'provider':'dropbox','http_status':400,'tag':'unavailable','request_id':'c1234-d5678'})
        self.assertIn('HTTP 400',str(failure));self.assertIn('request ID: c1234-d5678',str(failure))
        self.assertIn('namespace',str(failure));self.assertNotIn('App Folder',str(failure))
        self.assertNotIn('PRIVATE',str(failure));self.assertNotIn('secret-path',str(failure))
        self.assertNotIn('PRIVATE',json.dumps(failure.public_fields()))

    def test_mocked_http_error_retains_provider_request_id_without_request_headers(self):
        response=SimpleNamespace(status=400,headers={'x-dropbox-request-id':'safe_123'},
            read=lambda limit:b'PRIVATE_ACCESS PRIVATE_REFRESH /private/music.mp3',close=lambda:None)
        with patch('dropbox_http.http.client.HTTPSConnection') as create:
            create.return_value.getresponse.return_value=response
            with self.assertRaises(DropboxError) as caught:
                DropboxTransport().rpc('files/list_folder',{'path':''},'PRIVATE_ACCESS',{'.tag':'namespace_id','namespace_id':'123'})
        failure=caught.exception
        self.assertEqual(failure.status,400);self.assertEqual(failure.request_id,'safe_123')
        public=str(failure)+json.dumps(failure.public_fields())
        for private in ('PRIVATE','/private/','Bearer','Authorization','Dropbox-API-Path-Root'):self.assertNotIn(private,public)

    def test_request_id_is_strictly_bounded_ascii_and_case_insensitive(self):
        for invalid in ('id\nInjected: value','id\rvalue',' id','id ','id/secret','id:secret','é123','a'*129,'',None,42):
            with self.subTest(value=invalid):
                failure=_provider_error(500,b'PRIVATE_BODY',{'X-DROPBOX-REQUEST-ID':invalid})
                self.assertIsNone(failure.request_id);self.assertNotIn('request_id',failure.public_fields())
                self.assertNotIn('PRIVATE_BODY',str(failure))
        self.assertEqual(_provider_error(500,b'',{'x-dropbox-request-id':'a'*128}).request_id,'a'*128)

    def test_missing_scope_json_precedes_generic_unauthorized_classification(self):
        for tag in ('missing_scope','insufficient_scope','insufficient_scopes'):
            with self.subTest(tag=tag):
                failure=_provider_error(401,json.dumps({'error':{'.tag':tag,'required_scope':'PRIVATE_SCOPE'}}).encode(),{})
                self.assertEqual(failure.tag,tag);self.assertIn('App Console',str(failure))
                self.assertIn('files.metadata.read',str(failure));self.assertIn('files.content.read',str(failure))
                self.assertIn('disconnect and connect again',str(failure));self.assertNotIn('PRIVATE_SCOPE',str(failure))

    def test_known_plaintext_scope_rejection_is_actionable(self):
        body=b'Error in call to API function "files/list_folder": Your app is not permitted to access this endpoint because it is not configured with the required scope "files.metadata.read". PRIVATE_TOKEN'
        failure=_provider_error(400,body,{})
        self.assertEqual(failure.tag,'missing_scope');self.assertIn('App Console',str(failure))
        self.assertNotIn('PRIVATE_TOKEN',str(failure))

    def test_app_folder_message_requires_explicit_provider_evidence(self):
        for body in (
            b'Invalid Dropbox-API-Path-Root header: this header is not supported for app folder apps.',
            b'This API function requires full Dropbox access. PRIVATE_TOKEN',
        ):
            with self.subTest(body=body):
                failure=_provider_error(400,body,{})
                self.assertEqual(failure.tag,'app_folder_access');self.assertIn('Full Dropbox',str(failure))
                self.assertNotIn('PRIVATE_TOKEN',str(failure))
        for body in (b'An error occurred.',b'Invalid Dropbox-API-Path-Root header: invalid value.',
                     b'PRIVATE app folder path',b'HTTP 400 app folder'):
            with self.subTest(body=body):
                self.assertNotEqual(_provider_error(400,body,{}).tag,'app_folder_access')

    def test_invalid_namespace_header_is_distinct_from_app_access(self):
        for body in (b'Invalid Dropbox-API-Path-Root header: PRIVATE_VALUE',
                     b'Bad HTTP "Dropbox-API-Path-Root" header: PRIVATE_VALUE'):
            failure=_provider_error(400,body,{})
            self.assertEqual(failure.tag,'invalid_path_root')
            self.assertIn('Member home or Team root',str(failure));self.assertNotIn('PRIVATE_VALUE',str(failure))
            self.assertNotIn('Full Dropbox',str(failure))

    def test_documented_stale_root_and_forbidden_namespace_are_actionable(self):
        for tag in ('invalid_root','no_permission'):
            body={'error':{'.tag':tag,tag:{'.tag':'team','root_namespace_id':'PRIVATE_NAMESPACE'}}}
            failure=_provider_error(422,json.dumps(body).encode(),{})
            self.assertEqual(failure.tag,tag);self.assertEqual(failure.status,422)
            self.assertIn('Member home or Team root',str(failure));self.assertNotIn('PRIVATE_NAMESPACE',str(failure))

    def test_team_policy_is_only_claimed_for_an_explicit_known_tag(self):
        for tag in ('restricted_by_team','team_policy_disallows_member_policy'):
            failure=_provider_error(409,json.dumps({'error':{'.tag':tag}}).encode(),{})
            self.assertEqual(failure.tag,tag);self.assertIn('team policy blocks',str(failure))
        unknown=_provider_error(403,b'PRIVATE_TEAM_BODY',{})
        self.assertEqual(unknown.tag,'unavailable');self.assertNotIn('team policy blocks',str(unknown))

    def test_known_summary_prefix_is_safe_but_arbitrary_suffix_is_not_a_tag(self):
        failure=_provider_error(409,b'{"error_summary":"path/not_found/PRIVATE_PATH"}',{})
        self.assertEqual(failure.tag,'not_found');self.assertNotIn('PRIVATE_PATH',str(failure))
        unrelated=_provider_error(400,b'{"error_summary":"PRIVATE_PATH/not_found"}',{})
        self.assertEqual(unrelated.tag,'unavailable')

    def test_malformed_bodies_and_unknown_tags_do_not_escape(self):
        for body in (b'\xffPRIVATE',b'{"error":{".tag":["PRIVATE"]}}',b'{"error":"PRIVATE"}',b'[]',b'null',b'"PRIVATE"'):
            with self.subTest(body=body):
                failure=_provider_error(400,body,{})
                self.assertEqual(failure.tag,'unavailable');self.assertNotIn('PRIVATE',str(failure))

    def test_retry_header_and_public_fields_are_bounded(self):
        self.assertEqual(_provider_error(429,b'',{'retry-after':'30'}).public_fields()['retry_after'],30)
        for retry in ('nan','inf','-1','86401','PRIVATE'):
            with self.subTest(retry=retry):self.assertIsNone(_provider_error(429,b'',{'Retry-After':retry}).retry_after)
        failure=DropboxError(status=999,tag='PRIVATE\nBODY',request_id='\nPRIVATE',retry_after=10**10000)
        self.assertEqual(failure.public_fields(),{'provider':'dropbox','tag':'unavailable'})


class DropboxAccountMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.owner=SimpleNamespace(DATA=Path(temporary.name))
        self.account={'account_id':'dbid:invented-account','name':{'display_name':'Example member'},
            'email':'example@example.invalid','team':{'id':'dbtid:team','name':'Cloud Option DJ team'},
            'root_info':{'.tag':'team','root_namespace_id':'123','home_namespace_id':'456','home_path':'/Massimiliano Fantuzzi'}}
        self.vault=SimpleNamespace(available=False)
        self.transport=SimpleNamespace(
            token=lambda parameters:{'access_token':'PRIVATE_ACCESS','refresh_token':'PRIVATE_REFRESH','expires_in':14400,
                'scope':' '.join(SCOPES),'account_id':self.account['account_id']},
            rpc=lambda *args:deepcopy(self.account))
        self.connection=DropboxConnection(self.owner,self.transport,self.vault)

    def connect(self):
        self.connection.configure('PUBLIC_APP_KEY')
        begun=self.connection.begin('http://127.0.0.1:8765')
        state=parse_qs(urlsplit(begun['authorize_url']).query)['state'][0]
        self.connection.callback(state,'PRIVATE_CODE',callback_origin='http://127.0.0.1:8765')
        return self.connection.status()

    def test_team_home_path_and_name_survive_oauth_status(self):
        status=self.connect();account=status['account']
        self.assertEqual(account['home_path'],'/Massimiliano Fantuzzi')
        self.assertEqual(account['team_name'],'Cloud Option DJ team')
        self.assertEqual(account['root_namespace_id'],'123');self.assertEqual(account['home_namespace_id'],'456')
        self.assertEqual(status['required_scopes'],list(SCOPES));self.assertEqual(status['missing_scopes'],[])
        self.assertNotIn('PRIVATE',json.dumps(status))

    def test_only_account_info_grant_exposes_missing_file_permissions(self):
        original=self.transport.token
        def account_only(parameters):
            value=original(parameters);value['scope']='account_info.read';return value
        self.transport.token=account_only
        status=self.connect()
        self.assertTrue(status['connected'])
        self.assertEqual(status['missing_scopes'],['files.metadata.read','files.content.read'])

    def test_missing_oauth_scope_is_not_assumed_to_grant_all_permissions(self):
        original=self.transport.token
        def no_scope(parameters):
            value=original(parameters);value.pop('scope');return value
        self.transport.token=no_scope
        self.assertEqual(self.connect()['missing_scopes'],list(SCOPES))

    def test_unsafe_or_noncanonical_home_paths_are_not_published(self):
        for path in (None,42,'relative/member','//member','/member/../other','/member/./other',
                     '/member/','/member\\other','/member\nprivate','/member\u202esecret','/'+('x'*4096)):
            with self.subTest(path=path):
                account=deepcopy(self.account);account['root_info']['home_path']=path
                self.assertNotIn('home_path',self.connection._account_info(account))
        self.assertEqual(self.connection._account_info(self.account)['home_path'],'/Massimiliano Fantuzzi')

    def test_safe_unicode_names_are_preserved_and_unsafe_team_names_omitted(self):
        for team_name in (None,{},'','   ','team\nPRIVATE','team\u202ePRIVATE','x'*201):
            with self.subTest(team_name=team_name):
                account=deepcopy(self.account);account['team']['name']=team_name
                self.assertNotIn('team_name',self.connection._account_info(account))
        account=deepcopy(self.account);account['team']['name']='Équipe 音楽';account['root_info']['home_path']='/Équipe 音楽'
        public=self.connection._account_info(account)
        self.assertEqual(public['team_name'],'Équipe 音楽');self.assertEqual(public['home_path'],'/Équipe 音楽')


if __name__=='__main__':unittest.main()
