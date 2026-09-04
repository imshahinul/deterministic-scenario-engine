from __future__ import annotations

from hashlib import sha256
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import scenario_engine
from scenario_engine._version import VERSION
from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.suite import (
    ArtifactBoundError,
    ArtifactOrigin,
    ArtifactReadError,
    ExecutionReplaySupport,
    MAX_ARTIFACT_BYTES,
    ReadSupport,
    UnsupportedReplayContractError,
    read_v1_manifest_bytes,
    read_v1_manifest_text,
    read_v1_result_bytes,
    read_v1_result_text,
)


ROOT = Path(__file__).parents[1]
CART_HASH = "cffc2e482f304ab18d39f96166e3e1be78b117a86bf0ce8ad0e22973677001b5"
FLOW_HASH = "86511d8c750272283eb1039a6e1039c8faa11cb5945c76aec41d9f5a71588e2b"
ORACLE_HASH = "5760aee1293d2d264d841621de08734358b3eb4ca54ef3e08e5a0b97f8f16cdd"


def run(name: str, inputs=None):
    text = (ROOT / "examples" / name).read_text()
    return run_scenario(compile_document(parse_yaml(text)), "docs-seed", inputs=inputs or {})


class V1ReadTests(unittest.TestCase):
    def test_v1_manifest_and_result_are_readable_but_not_execution_replay_supported(self):
        result = run("cart.yaml")
        manifest_bytes = json.dumps(result.manifest.normalized(), sort_keys=True, separators=(",", ":")).encode()
        manifest = read_v1_manifest_bytes(manifest_bytes)
        artifact = read_v1_result_text(result.to_json())
        self.assertEqual(manifest.origin, ArtifactOrigin.V1_MANIFEST)
        self.assertEqual(artifact.origin, ArtifactOrigin.V1_RESULT)
        self.assertEqual(manifest.read_support, ReadSupport.READABLE)
        self.assertEqual(artifact.execution_replay, ExecutionReplaySupport.UNSUPPORTED)
        with self.assertRaisesRegex(UnsupportedReplayContractError, "replay.engine_version_unsupported"):
            artifact.require_execution_replay()
        self.assertEqual(artifact.payload["manifest"]["engine_version"], "1.0.0")
        self.assertEqual(read_v1_manifest_text(manifest_bytes.decode()).payload, manifest.payload)
        self.assertEqual(read_v1_result_bytes(result.to_json_bytes()).payload, artifact.payload)

    def test_semantic_types_are_preserved(self):
        artifact = read_v1_result_bytes(run("cart.yaml").to_json_bytes())
        self.assertEqual(artifact.payload["state"]["cart_total"].as_tuple().exponent, -2)
        self.assertIs(type(artifact.payload["manifest"]["run_index"]), int)

    def test_malformed_unknown_duplicate_and_unsupported_artifacts_fail(self):
        result = run("cart.yaml")
        raw = json.loads(result.to_json())
        raw["unknown"] = True
        with self.assertRaises(ArtifactReadError):
            read_v1_result_text(json.dumps(raw))
        manifest = result.manifest.normalized()
        del manifest["locale"]
        with self.assertRaises(ArtifactReadError):
            read_v1_manifest_text(json.dumps(manifest))
        with self.assertRaises(ArtifactReadError):
            read_v1_manifest_text('{"engine_version":"1.0.0","engine_version":"1.0.0"}')
        manifest = result.manifest.normalized()
        manifest["engine_version"] = "2.0.0"
        with self.assertRaises(ArtifactReadError):
            read_v1_manifest_text(json.dumps(manifest))
        raw = json.loads(result.to_json())
        raw["state"] = {"bad": {"$type": "decimal", "value": "NaN"}}
        with self.assertRaises(ArtifactReadError):
            read_v1_result_text(json.dumps(raw))

    def test_size_and_depth_bounds(self):
        with self.assertRaises(ArtifactBoundError):
            read_v1_result_bytes(b" " * (MAX_ARTIFACT_BYTES + 1))
        nested = "null"
        for _ in range(66):
            nested = "[" + nested + "]"
        with self.assertRaises(ArtifactBoundError):
            read_v1_result_text(nested)

    def test_read_does_not_execute_discover_import_network_or_follow_paths(self):
        result = run("cart.yaml")
        raw = json.loads(result.to_json())
        raw["state"]["untrusted"] = {
            "plugin": "malicious.module", "domain_pack": "pack", "path": "/private/file", "url": "https://example.test"
        }
        with patch("builtins.__import__", side_effect=AssertionError("import attempted")), \
             patch("builtins.open", side_effect=AssertionError("file attempted")):
            artifact = read_v1_result_text(json.dumps(raw))
        self.assertEqual(artifact.payload["state"]["untrusted"]["path"], "/private/file")

    def test_suite_import_has_no_runtime_side_effects(self):
        import scenario_engine.suite as suite
        with patch("builtins.open", side_effect=AssertionError("file attempted")):
            self.assertIs(importlib.reload(suite), suite)

    def test_v1_api_version_and_three_result_goldens_remain_unchanged(self):
        expected = scenario_engine.__all__
        self.assertEqual(VERSION, "1.0.0")
        self.assertEqual(scenario_engine.__all__, expected)
        cart_source = (ROOT / "examples" / "phase0_1b_cart.yaml").read_text()
        cart = run_scenario(compile_document(parse_yaml(cart_source)), "s")
        flow_source = (ROOT / "examples" / "phase0_4_control_flow.yaml").read_text()
        flow = run_scenario(
            compile_document(parse_yaml(flow_source)), "s",
            inputs={"premium": True, "retry_count": 2, "customer_id": "customer-1"},
        )
        oracle_source = (ROOT / "examples" / "phase0_5_oracle_fault.yaml").read_text().replace(
            "enabled: true", "enabled: false"
        )
        oracle = run_scenario(
            compile_document(parse_yaml(oracle_source)), "phase1.0c"
        )
        self.assertEqual(sha256(cart.to_json_bytes()).hexdigest(), CART_HASH)
        self.assertEqual(sha256(flow.to_json_bytes()).hexdigest(), FLOW_HASH)
        self.assertEqual(sha256(oracle.to_json_bytes()).hexdigest(), ORACLE_HASH)


if __name__ == "__main__":
    unittest.main()
