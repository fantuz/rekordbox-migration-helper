# Dropbox connector

The Dropbox connector checks saved library references against an authorized
Dropbox account. Checking existence is a metadata operation: it does not open
audio, request content downloads, change selective-sync settings or start a
folder resynchronization. [Google Drive](GOOGLE-DRIVE-CONNECTOR.md) has its own
connection and folder evidence; both can coexist through
[Cloud connections](CLOUD-CONNECTIONS.md).

## Connect an account

Open **Dropbox connector**, enter the public Dropbox **app key** and follow
**Connect Dropbox**. The page shows the callback URL that must be registered
for this installation. Workbench and the browser completing authorization must
run on the same computer; use the exact loopback address and port shown there.

Dropbox handles the sign-in, password, MFA or SSO and permission screen in the
browser. Workbench uses OAuth 2.0 Authorization Code with PKCE. It does not ask
for a Dropbox password or an app secret, and a running Dropbox desktop client
does not automatically authorize Workbench's API access.

Access tokens expire and are renewed through a refresh token. If a supported
operating-system credential store is available, **Remember connection** keeps
that refresh token there. Otherwise use a session-only connection and authorize
again after restarting Workbench. Tokens are not written to the library
sidecar, exported reports, source snapshots or application logs. Disconnect
removes the locally held authorization and requests its revocation at Dropbox.

### Register an app key

The project maintainer can register an app in the
[Dropbox developer console](https://www.dropbox.com/developers/apps). An
installation using its own developer app can supply that app's public key.

1. Create a scoped Dropbox API app with **Full Dropbox** access. App Folder
   access covers only a new application-owned folder and cannot inspect an
   existing DJ library elsewhere in the account.
2. Enable `account_info.read`, `files.metadata.read` and `files.content.read`.
   These permit identifying the account, checking metadata and reading an
   individually requested file. No cloud-write or deletion permission is
   requested. Content-read permission alone does not start downloads.
3. Register the exact callback URL displayed by Workbench, including its port
   and `/api/dropbox/callback` path. Enable public-client/PKCE authorization as
   required by Dropbox's console.
4. Copy the **app key**, not the app secret, into Workbench. Each user then
   authorizes their own account through Dropbox's browser screen.

Dropbox's development/production access rules still apply when distributing an
app to other users. See the [OAuth guide](https://developers.dropbox.com/oauth-guide)
and [developer guide](https://www.dropbox.com/developers/reference/developer-guide).

### Fix an invalid redirect URI

Before choosing **Connect Dropbox**, copy the callback URL displayed by
Workbench. Add that exact string to the app's **OAuth 2 / Redirect URIs** in
the Dropbox developer console and save the console setting. Workbench cannot
inspect that developer-console list or register the value on your behalf.

Match the complete address: `127.0.0.1` and `localhost` are different hosts;
the current Workbench port and `/api/dropbox/callback` path must match; an
extra trailing slash changes the URI. Recopy the value if Workbench starts on
another port, and make sure its app key belongs to the console app you edited.
Then start **Connect Dropbox** again. Do not substitute the Google callback
or a public cloud-preview address.

This console-registration step is specific to Dropbox's configured redirect
list. Google's Desktop OAuth loopback procedure is described in its separate
[setup guide](GOOGLE-DRIVE-CONNECTOR.md).

## Map the library folder

Use **Cloud connections** to select the saved collection, account arrangement
and Rekordbox synchronization method. Keep detected desktop roots as
candidates. In selected-file mode you can instead review an ordinary existing
download destination outside those roots, including when Dropbox desktop is
not installed. All-files mode retains the verified Dropbox desktop-root
requirement.

For a team account, review **Member home folder** and **Team root folder** in
the namespace choices. These use the signed-in account's reported home and
root identities. The first starts in the member's personal area; the second
starts at the team-space root. Choose the base containing the remote music
folder and verify the resulting relative paths in the preview. Some accounts
report the same identity for both choices, so they are not necessarily two
different locations. Choosing a namespace does not change team membership,
app access settings, callback registration or cloud permissions, and it does
not attach a folder automatically.

Choose the corresponding remote folder and preview complete relative-path
matches before attaching. If the captured paths use an old prefix, an explicit
recorded root can propose a source-scoped Audio folders mapping without
rewriting the snapshot or replacing a conflicting mapping. The remote path is
relative to the authorized account's selected namespace; team folders may use
a team root namespace rather than a member's home namespace. A team/customer
folder name or matching suffix alone does not establish that it is the same
folder.

Use the narrow folder that contains the selected music. Workbench checks the
current library path first, then uses XML or original-path evidence as a
fallback, with source-scoped audio-folder mappings when configured. An updated
current path takes precedence over a stale original path after relocation.
Invalid or ambiguous audio-folder mappings are held for review. References
outside the selected root remain unmapped. Workbench does not rewrite paths in
the captured library or infer an arbitrary cloud location from a filename.

## Check existence without downloading

Choose a saved collection and start the explicit metadata check. Results apply
to the entire checked collection before filtering and pagination.

| Result | Meaning |
| --- | --- |
| Present | Dropbox returned a file at the mapped path in the authorized namespace. |
| Not found | Dropbox did not find that mapped path in the checked namespace; this alone is not proof of deletion. |
| Unmapped | No verified selected-folder mapping applies to the recorded reference. |
| Unverified | A bounded metadata listing ended before this mapped path could be conclusively checked. |

The account, mapping and checked path determine the result. A wrong account,
renamed file or different team namespace can produce an unavailable path even
when another copy exists. Recheck after reconnecting, changing mappings or
moving cloud files. Logical size and file identity are metadata; they do not
prove local residency or decodable audio.

A failed authorization, permission or network request reports a failed check
and preserves earlier evidence with its original timestamp. It does not turn
unchecked paths into missing files.

## Download one file deliberately

Remote validation never calls the content-download endpoint. To fetch a file,
choose its individual download action and review the filename, destination and
size in the confirmation. Cancel or Escape leaves the file untouched. Approval
applies to that one current file and does not enable a download queue, bulk
hydration or a remembered blanket consent.

The connector writes an absent file only into the explicitly attached local
destination. Selected-file destinations can be outside the normal Dropbox
desktop folder. It does not replace an existing local file, write through a symbolic
link or turn an arbitrary filename into a destination. Failed or incomplete
transfers do not publish a partial final file. A changed mapping or remote
revision requires a new confirmation.

Parent folders must already exist locally as ordinary directories. Transfers
are limited to 8 GiB per file and need sufficient free space. A private staging
folder outside Dropbox must be on the same filesystem as the destination;
the filesystem must support atomic hard links. If these checks fail, use the
Dropbox client to make that one file available instead. Workbench verifies
both the advertised byte count and Dropbox content hash before publishing the
complete file, so interrupted transfers never appear in the sync folder.

If the filesystem already contains an online-only placeholder, use the
existing individual **Play** flow so the provider can hydrate that one file.
The connector does not overwrite a placeholder with a separate API transfer.
Dropbox itself controls how its desktop client handles newly local files;
Workbench does not change sync policy or promise that the client will perform
no additional metadata reconciliation.

After a successful download, the file is an ordinary local file at its mapped
Dropbox path. Refresh local File health or playback evidence to observe its
current state. Native library references remain unchanged.

## Validation limits

Automated checks use invented library records, synthetic provider responses and
temporary files. They check path boundaries, scope isolation, metadata-only
validation, single-file consent and transfer failure handling. They do not use
personal credentials, contact a live account or demonstrate the behavior of an
installed Windows/macOS Dropbox client. Live account, team-namespace and
selective-sync validation is still required before claiming those layouts are
fully verified.
