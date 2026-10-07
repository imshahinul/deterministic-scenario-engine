"""Deterministic source-distribution archive support for the setuptools backend."""

from __future__ import annotations

import gzip
import os
from pathlib import Path
import tarfile

from setuptools import setup
from setuptools.command.sdist import sdist as _sdist


class ReproducibleSdist(_sdist):
    """Write canonical gzip/tar metadata when SOURCE_DATE_EPOCH is supplied."""

    def make_archive(self, base_name, format, root_dir=None, base_dir=None, owner=None, group=None):
        epoch_text = os.environ.get("SOURCE_DATE_EPOCH")
        if format != "gztar" or epoch_text is None:
            return super().make_archive(base_name, format, root_dir, base_dir, owner, group)
        epoch = int(epoch_text)
        root = Path(root_dir or ".")
        source = root / (base_dir or Path(base_name).name)
        destination = Path(f"{base_name}.tar.gz")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for path in (source, *sorted(source.rglob("*"), key=lambda item: item.as_posix())):
                        relative = path.relative_to(root).as_posix()
                        info = archive.gettarinfo(str(path), arcname=relative)
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mtime = epoch
                        if path.is_file():
                            with path.open("rb") as stream:
                                archive.addfile(info, stream)
                        else:
                            archive.addfile(info)
        return str(destination)


if __name__ == "__main__":
    setup(cmdclass={"sdist": ReproducibleSdist})
