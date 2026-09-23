from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
FORBIDDEN = (
    "/Users/" + "smshahinulislam",
    "Developer/" + "scenario-engine-audit",
    "scenario-engine-audit/" + "runtime-venv",
)


def test_executable_test_and_ci_surfaces_have_no_maintainer_local_paths():
    paths = list((ROOT / "tests").glob("**/*.py"))
    paths.extend((ROOT / ".github" / "workflows").glob("**/*.yml"))
    paths.extend((ROOT / ".github" / "workflows").glob("**/*.yaml"))

    occurrences = []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            if forbidden in content:
                occurrences.append(f"{path.relative_to(ROOT)}: {forbidden}")

    assert not occurrences, "maintainer-local paths found:\n" + "\n".join(occurrences)
