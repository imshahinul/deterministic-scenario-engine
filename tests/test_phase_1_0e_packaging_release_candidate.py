from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from importlib.metadata import EntryPoint
import json
from pathlib import Path
import sys
import tomllib
import unittest

import scenario_engine
from scenario_engine import ENGINE_VERSION, compile_document, parse_yaml, run_scenario
from scenario_engine._version import VERSION


ROOT = Path(__file__).parents[1]
HISTORICAL_ENGINE_VERSION = "0.2.0.dev0"
RC_HASHES = {
    "cart": "cffc2e482f304ab18d39f96166e3e1be78b117a86bf0ce8ad0e22973677001b5",
    "flow": "86511d8c750272283eb1039a6e1039c8faa11cb5945c76aec41d9f5a71588e2b",
    "oracle": "5760aee1293d2d264d841621de08734358b3eb4ca54ef3e08e5a0b97f8f16cdd",
}
HISTORICAL_HASHES = {
    "cart": "ea85ecfe3d6014f10481637db4e8a137d00ffab0bdcfe4ed070f0b1404ee123e",
    "flow": "73de01131fa12f904dee388a5ba04d11f8001ddde2a6d6b94e10b0ded0a75c61",
    "oracle": "cd28c9fdadef67267aa7f0dc950dd5d19331dc30c3d84636d0c678f481ac16b8",
}


def source(name: str) -> str:
    return (ROOT / "examples" / name).read_text(encoding="utf-8")


def result(name: str, seed: str, inputs=None, transform=None):
    text = source(name)
    if transform is not None:
        text = transform(text)
    return run_scenario(compile_document(parse_yaml(text)), seed, inputs=inputs)


class Phase10EPackagingReleaseCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        cls.project = cls.config["project"]

    def test_final_distribution_metadata_identity_and_version_source(self):
        self.assertEqual(self.project["name"], "deterministic-scenario-engine")
        self.assertEqual(self.project["dynamic"], ["version"])
        self.assertEqual(
            self.config["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "scenario_engine._version.VERSION",
        )
        self.assertEqual(VERSION, "1.0.0")
        self.assertEqual(ENGINE_VERSION, VERSION)

    def test_license_readme_and_build_backend_metadata(self):
        self.assertEqual(self.project["license"], "Apache-2.0")
        self.assertEqual(self.project["license-files"], ["LICENSE"])
        self.assertEqual(self.project["readme"], "README.md")
        self.assertIn("Apache License\n", (ROOT / "LICENSE").read_text(encoding="utf-8"))
        self.assertEqual(self.config["build-system"]["build-backend"], "setuptools.build_meta")
        self.assertEqual(self.config["build-system"]["requires"], ["setuptools>=77"])

    def test_src_package_discovery_and_pytest_entry_point_are_explicit(self):
        discovery = self.config["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(discovery, {"where": ["src"], "include": ["scenario_engine*"], "namespaces": False})
        target = self.config["project"]["entry-points"]["pytest11"]["scenario_engine"]
        self.assertEqual(target, "scenario_engine.pytest_plugin")
        entry_point = EntryPoint("scenario_engine", target, "pytest11")
        self.assertEqual(entry_point.load().__name__, "scenario_engine.pytest_plugin")

    def test_core_and_optional_dependencies_are_frozen(self):
        self.assertEqual(self.project["requires-python"], ">=3.11")
        self.assertEqual(self.project["dependencies"], ["PyYAML==6.0.3"])
        self.assertEqual(self.project["optional-dependencies"], {
            "pytest": ["pytest>=9.1,<10"],
            "sqlalchemy": ["SQLAlchemy>=2.0,<3"],
            "hypothesis": ["hypothesis>=6,<7"],
            "schemathesis": ["hypothesis>=6,<7", "schemathesis>=4,<5"],
        })

    def test_new_1_0_rc_golden_hashes(self):
        cart = result("cart.yaml", "s")
        flow = result("control_flow.yaml", "s", {
            "premium": True, "retry_count": 2, "customer_id": "customer-1",
        })
        oracle = result(
            "oracle_fault.yaml", "phase1.0c",
            transform=lambda text: text.replace("enabled: true", "enabled: false"),
        )
        for name, actual in (("cart", cart), ("flow", flow), ("oracle", oracle)):
            with self.subTest(name=name):
                self.assertEqual(actual.manifest.engine_version, "1.0.0")
                self.assertEqual(sha256(actual.to_json_bytes()).hexdigest(), RC_HASHES[name])

    def test_version_transition_changes_no_other_normalized_result_field(self):
        cases = (
            result("cart.yaml", "s"),
            result("control_flow.yaml", "s", {
                "premium": True, "retry_count": 2, "customer_id": "customer-1",
            }),
            result(
                "oracle_fault.yaml", "phase1.0c",
                transform=lambda text: text.replace("enabled: true", "enabled: false"),
            ),
        )
        for name, current in zip(("cart", "flow", "oracle"), cases, strict=True):
            historical = replace(current.manifest, engine_version=HISTORICAL_ENGINE_VERSION)
            current_payload = current.normalized()
            historical_payload = json.loads(json.dumps(current_payload))
            historical_payload["manifest"] = historical.normalized()
            historical_bytes = json.dumps(
                historical_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
            ).encode("utf-8")
            self.assertEqual(sha256(historical_bytes).hexdigest(), HISTORICAL_HASHES[name])
            current_payload["manifest"].pop("engine_version")
            historical_payload["manifest"].pop("engine_version")
            self.assertEqual(current_payload, historical_payload)

    def test_docs_state_future_install_without_false_publication_claim(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
        combined = f"{readme}\n{quickstart}".lower()
        self.assertIn("pip install deterministic-scenario-engine", combined)
        self.assertIn("not currently\navailable from pypi", combined)
        self.assertIn("only after a future\npublication", combined)

    def test_top_level_api_is_unchanged_by_version_authority_module(self):
        self.assertNotIn("VERSION", scenario_engine.__all__)
        self.assertNotIn("_version", scenario_engine.__all__)

    def test_no_typed_package_marker_is_advertised(self):
        self.assertFalse((ROOT / "src" / "scenario_engine" / "py.typed").exists())


if __name__ == "__main__":
    unittest.main()
