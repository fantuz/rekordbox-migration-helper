"""Consistent native OAuth callback origin for both cloud providers."""
from urllib.parse import urlsplit

from flask import request
from file_health import local_request


def callback_errors(app,provider):
    """Profile-specific callback messages shared by the connector and setup screens."""
    return app.extensions.setdefault('workbench_cloud_callback_errors', {}).setdefault(provider, {})


def authorization_origin():
    """Use the canonical loopback host, retaining the actual Workbench port.

    Browser pages may be opened as localhost; the native clients register and
    validate 127.0.0.1 callbacks. Callback handlers must still verify their
    actual request origin against the pending OAuth state, not this helper.
    """
    if not local_request():raise ValueError('Connect cloud storage from the local Workbench application.')
    try:
        parsed=urlsplit(request.host_url)
        port=parsed.port or 80
        if (parsed.scheme!='http' or parsed.username or parsed.password
                or not 1<=port<=65535):raise ValueError()
    except (TypeError,ValueError):
        raise ValueError('Use the local HTTP Workbench address to connect cloud storage.') from None
    return 'http://127.0.0.1:'+str(port)
