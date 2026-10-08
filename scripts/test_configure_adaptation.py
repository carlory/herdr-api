"""Credential transfer must be restricted and must not expose tokens in output."""

import subprocess
import unittest
from unittest.mock import call, patch

import configure_adaptation


class ConfigurationTests(unittest.TestCase):
    def test_one_hidden_prompt_configures_both_secrets_before_dispatch(self):
        token = "github_pat_fixture_not_a_real_token"
        results = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, '[{"name":"COPILOT_GITHUB_TOKEN"},{"name":"GH_AW_CI_TRIGGER_TOKEN"}]'),
            subprocess.CompletedProcess([], 0),
        ]
        with patch.object(configure_adaptation.getpass, "getpass", return_value=token) as prompt, \
                patch.object(configure_adaptation, "store_secret") as store, \
                patch.object(configure_adaptation.subprocess, "run", side_effect=results) as run, \
                patch("builtins.print") as output:
            configure_adaptation.main()
            prompt.assert_called_once()
            self.assertEqual(store.call_args_list, [call(name, token) for name in configure_adaptation.SECRETS])
            self.assertEqual(run.call_args.args[0], [
                "gh", "workflow", "run", "adapt-herdr.lock.yml", "--repo", "carlory/herdr-api", "--ref", "main",
            ])
            self.assertNotIn(token, str(output.call_args_list))

    def test_secret_is_passed_only_through_stdin_to_the_fixed_repository(self):
        token = "github_pat_fixture_not_a_real_token"
        with patch.object(configure_adaptation.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            configure_adaptation.store_secret("COPILOT_GITHUB_TOKEN", token)
            self.assertEqual(run.call_args.args[0], [
                "gh", "secret", "set", "COPILOT_GITHUB_TOKEN", "--repo", "carlory/herdr-api",
            ])
            self.assertEqual(run.call_args.kwargs["input"], token)
            self.assertNotIn(token, run.call_args.args[0])
            self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_unknown_destinations_and_classic_credentials_are_rejected(self):
        for name, token in [
            ("OTHER_SECRET", "github_pat_fixture"),
            ("COPILOT_GITHUB_TOKEN", "ghp_broad_fixture"),
            ("GH_AW_CI_TRIGGER_TOKEN", "github_pat_fixture\n"),
        ]:
            with self.subTest(name=name), patch.object(configure_adaptation.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    configure_adaptation.store_secret(name, token)
                run.assert_not_called()

    def test_failed_transfer_never_relays_subprocess_credential_output(self):
        token = "github_pat_fixture_not_a_real_token"
        with patch.object(configure_adaptation.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, token, token)):
            with self.assertRaises(RuntimeError) as failure:
                configure_adaptation.store_secret("COPILOT_GITHUB_TOKEN", token)
            self.assertNotIn(token, str(failure.exception))


if __name__ == "__main__":
    unittest.main()
