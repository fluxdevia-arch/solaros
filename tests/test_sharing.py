import unittest

from solar_crm.sharing import resolve_share_base_url


class ShareUrlTests(unittest.TestCase):
    def test_hosted_app_replaces_stale_localhost_setting(self):
        self.assertEqual(
            resolve_share_base_url(
                "http://localhost:8501",
                "https://solaros.streamlit.app/inspections?inspection=abc",
            ),
            "https://solaros.streamlit.app",
        )

    def test_configured_public_url_is_kept_during_local_development(self):
        self.assertEqual(
            resolve_share_base_url(
                "https://portal.ongrid.com.br/solaros/",
                "http://localhost:8501/inspections",
            ),
            "https://portal.ongrid.com.br/solaros",
        )

    def test_public_route_is_removed_from_browser_base(self):
        self.assertEqual(
            resolve_share_base_url("", "https://solaros.streamlit.app/service-orders"),
            "https://solaros.streamlit.app",
        )


if __name__ == "__main__":
    unittest.main()
