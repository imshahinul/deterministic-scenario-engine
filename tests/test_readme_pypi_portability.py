from __future__ import annotations

from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from urllib.parse import urlsplit
import zipfile


ROOT = Path(__file__).parents[1]
MARKDOWN_TARGET = re.compile(r"!?\[[^]]*\]\((?:<)?([^)>\s]+)(?:>)?(?:\s+[^)]*)?\)")
ALLOWED_SCHEMES = {"http", "https", "mailto"}
MAINTAINER_LOCAL_PATH = re.compile(
    r"/Users/" + "smshahinulislam"
    + r"|/Users/[^/\s]+/Developer/scenario-engine|Developer/"
    + r"scenario-engine-audit|scenario-engine-audit/"
    + r"runtime-venv"
)


def packaged_documentation() -> list[Path]:
    return [
        ROOT / "README.md",
        ROOT / "pyproject.toml",
        ROOT / "MANIFEST.in",
        *(ROOT / "docs").glob("*.md"),
        *(path for path in (ROOT / "examples").iterdir() if path.is_file()),
    ]


def assert_portable(test: unittest.TestCase, description: str) -> None:
    for target in MARKDOWN_TARGET.findall(description):
        with test.subTest(target=target):
            if target.startswith("#"):
                test.fail(f"fragment-only README link requires explicit renderer proof: {target}")
            parsed = urlsplit(target)
            test.assertIn(parsed.scheme.lower(), ALLOWED_SCHEMES, f"repository-relative README link: {target}")


def metadata_description(payload: bytes) -> str:
    message = BytesParser(policy=compat32).parsebytes(payload)
    return message.get_payload()


class ReadmePyPIPortabilityTests(unittest.TestCase):
    def test_packaged_documentation_has_no_maintainer_local_paths(self):
        occurrences = []
        for path in packaged_documentation():
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if MAINTAINER_LOCAL_PATH.search(line):
                    occurrences.append(f"{path.relative_to(ROOT)}:{line_number}")
        self.assertEqual(occurrences, [], f"maintainer-local paths: {occurrences}")

    def test_source_readme_uses_portable_absolute_links(self):
        assert_portable(self, (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_built_wheel_and_sdist_descriptions_use_portable_absolute_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            subprocess.run(
                [sys.executable, "-m", "build", "--outdir", str(output), str(ROOT)],
                check=True,
                capture_output=True,
                text=True,
            )
            wheel, = output.glob("*.whl")
            sdist, = output.glob("*.tar.gz")
            with zipfile.ZipFile(wheel) as archive:
                name, = (name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
                assert_portable(self, metadata_description(archive.read(name)))
            with tarfile.open(sdist, "r:gz") as archive:
                member, = (member for member in archive.getmembers() if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO"))
                extracted = archive.extractfile(member)
                self.assertIsNotNone(extracted)
                assert_portable(self, metadata_description(extracted.read()))


if __name__ == "__main__":
    unittest.main()
