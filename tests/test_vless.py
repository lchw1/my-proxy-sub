import sys
from unittest.mock import MagicMock

# Mock dependencies before importing main
sys.modules['aiohttp'] = MagicMock()
sys.modules['ruamel'] = MagicMock()
sys.modules['ruamel.yaml'] = MagicMock()
sys.modules['requests'] = MagicMock()

import unittest
from main import parse_vless_link

class TestVlessParsing(unittest.TestCase):
    def test_flow_inclusion_case_insensitivity(self):
        # Test that flow is included when security is TLS (uppercase)
        link = "vless://uuid@host:443?security=TLS&flow=vision#test"
        proxy = parse_vless_link(link)
        self.assertEqual(proxy.get("flow"), "vision", "Should include flow for security=TLS")
        self.assertTrue(proxy.get("tls"), "TLS should be enabled")

    def test_flow_inclusion_reality(self):
        # Test that flow is included when security is reality
        link = "vless://uuid@host:443?security=Reality&flow=vision#test"
        proxy = parse_vless_link(link)
        self.assertEqual(proxy.get("flow"), "vision", "Should include flow for security=Reality")

    def test_flow_exclusion_no_security(self):
        # Test that flow is excluded when no security is specified
        link = "vless://uuid@host:443?flow=vision#test"
        proxy = parse_vless_link(link)
        self.assertNotIn("flow", proxy, "Should NOT include flow when no security is specified")

    def test_network_normalization(self):
        # Test that network 'WS' is normalized to 'ws' and ws-opts are added
        link = "vless://uuid@host:443?type=WS&path=/ws#test"
        proxy = parse_vless_link(link)
        self.assertEqual(proxy.get("network"), "ws")
        self.assertIn("ws-opts", proxy)

if __name__ == "__main__":
    unittest.main()
