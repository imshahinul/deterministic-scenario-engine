"""Export, verify, and copy the deterministic ecommerce reference evidence."""

from __future__ import annotations

import argparse

from scenario_engine.cli import main
from scenario_engine.reference_packs import export_ecommerce_evidence


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", help="absent destination for the generated bundle")
    parser.add_argument("copy", help="absent destination for the CLI-exported copy")
    arguments = parser.parse_args()
    workflow = export_ecommerce_evidence(arguments.bundle)
    print(f"domain_pack={workflow.domain_pack.coordinate}")
    print(f"domain_pack_sha256={workflow.domain_pack.content_hash}")
    print(f"bundle_id={workflow.bundle.bundle_id}")
    verified = main(["--json", "verify", arguments.bundle])
    if verified:
        return verified
    return main(["--json", "export", arguments.bundle, arguments.copy])


if __name__ == "__main__":
    raise SystemExit(run())
