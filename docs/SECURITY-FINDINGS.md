# Reviewed findings

## CodeQL alert 1: user-selected local input paths

[Alert 1](https://github.com/fantuz/rekordbox-migration-helper/security/code-scanning/1) flagged `Path(value).expanduser()` in the intentional existing XML/ZIP input selector (`py/path-injection`). The local application intentionally permits full user-selected paths, including large backups outside its working directory.

The endpoint requires the per-process mutation token; the server binds to loopback, restricts trusted Host values, and does not grant cross-origin reads. The selector resolves an absolute existing regular nonempty XML/ZIP path and reads it without overwriting it. A same-user local process already has the same filesystem capability. For this supported local trust boundary, the finding was dismissed as a false positive with a comment on the alert; it was not described as patched and no rule was globally suppressed.

Reassess this classification before remote hosting, changing Host/token/CORS protection, or adding privileged access. Synthetic CI cases cover these local request guards. This review is limited to the reported path selection and does not establish that every parser or filesystem operation is free of vulnerabilities.
