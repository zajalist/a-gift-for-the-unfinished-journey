"""Offline lease guard fixtures. No editor or socket is contacted."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bounded_pie_profile as profile


class ProfileLeaseGuardTests(unittest.TestCase):
    def status(self, token="[REDACTED:token]"):
        return {"caller_owner": "fixture", "leases": [{
            "owner": "fixture", "mine": True, "token": token,
            "expires_in_s": 900,
            "resources": [{"resource": "global", "mode": "exclusive"}],
        }]}

    def construct(self, status, token="[REDACTED:token]"):
        mirror = {"holders": {"fixture": {"expires_at": profile.time.time() + 900}}}
        with patch.object(profile.editor_gate, "mirrored_token", return_value=token), \
             patch.object(profile.editor_gate, "read_lock", return_value=mirror), \
             patch.object(profile, "hayba_deadline", return_value=status) as rpc:
            bridge = profile.Bridge("fixture")
            return bridge, rpc.call_args

    def test_redacted_own_claim_uses_owner_only(self):
        bridge, call = self.construct(self.status())
        self.assertIsNone(bridge.token)
        self.assertEqual(call.args[2:4], ("fixture", None))

    def test_actual_token_retained_with_redacted_or_matching_status(self):
        for live in ("actual-token", "[REDACTED:token]"):
            bridge, call = self.construct(self.status(live), "actual-token")
            self.assertEqual(bridge.token, "actual-token")
            self.assertEqual(call.args[3], "actual-token")

    def test_actual_token_mismatch_rejected(self):
        for live in ("different-token", None):
            with self.subTest(live=live), self.assertRaises(RuntimeError):
                self.construct(self.status(live), "actual-token")

    def test_owner_scope_expiry_and_uniqueness_are_required(self):
        changes = (
            lambda s: s.update(caller_owner="other"),
            lambda s: s["leases"][0].update(owner="other"),
            lambda s: s["leases"][0].update(mine=False),
            lambda s: s["leases"][0].update(expires_in_s=149.9),
            lambda s: s["leases"][0].update(expires_in_s=float("nan")),
            lambda s: s["leases"][0].update(resources=[{"resource": "global", "mode": "shared"}]),
            lambda s: s["leases"][0].update(resources=[{"resource": "world:/Game/level/Saskarta_WP", "mode": "exclusive"}]),
            lambda s: s["leases"].append(copy.deepcopy(s["leases"][0])),
            lambda s: s.update(leases=[]),
        )
        for index, change in enumerate(changes):
            status = self.status()
            change(status)
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                self.construct(status)


if __name__ == "__main__":
    unittest.main()
