"""HTTPS GET for the Epicor BAQ host.

epicor.colonydisplay.com presents a Sectigo certificate that expired
2026-10-09 18:59. The chain and hostname are still valid, and that is
what makes the PO History scheduled tasks exit 0x1 before any data is
written. Skip only the expiry check, and only while the leaf is expired.
A renewed certificate is verified normally again.
"""
import socket
import ssl

import requests
from requests.adapters import HTTPAdapter

_HOST = "epicor.colonydisplay.com"
# OpenSSL X509_V_FLAG_NO_CHECK_TIME. Python does not expose this name.
_NO_CHECK_TIME = 0x200000
# X509_V_ERR_CERT_HAS_EXPIRED
_CERT_HAS_EXPIRED = 10

_session = None


def _ssl_context():
    strict = ssl.create_default_context()
    try:
        with socket.create_connection((_HOST, 443), timeout=20) as sock:
            with strict.wrap_socket(sock, server_hostname=_HOST):
                return strict
    except ssl.SSLCertVerificationError as exc:
        if exc.verify_code != _CERT_HAS_EXPIRED:
            raise
    loose = ssl.create_default_context()
    loose.verify_flags |= _NO_CHECK_TIME
    return loose


class _EpicorAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = _ssl_context()
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


def epicor_get(url, **kwargs):
    global _session
    if _session is None:
        _session = requests.Session()
        _session.mount("https://" + _HOST, _EpicorAdapter())
    kwargs.setdefault("timeout", 120)
    return _session.get(url, **kwargs)
