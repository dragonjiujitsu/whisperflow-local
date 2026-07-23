from __future__ import annotations

import unittest
from urllib import error, request

from whisperflow_local.local_endpoint import (
    NoRedirectHandler,
    validate_loopback_http_url,
)


class LocalEndpointTests(unittest.TestCase):
    def test_loopback_literals_are_normalized(self) -> None:
        self.assertEqual(
            validate_loopback_http_url("http://localhost:8888/v1/"),
            "http://127.0.0.1:8888/v1",
        )
        self.assertEqual(
            validate_loopback_http_url("http://[::1]:8888/v1"),
            "http://[::1]:8888/v1",
        )

    def test_redirects_are_rejected(self) -> None:
        req = request.Request("http://127.0.0.1:8888/v1/models")
        with self.assertRaises(error.HTTPError):
            NoRedirectHandler().redirect_request(
                req,
                None,
                302,
                "Found",
                {},
                "http://example.com/steal",
            )


if __name__ == "__main__":
    unittest.main()
