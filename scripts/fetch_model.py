"""Download the embedding model of section 6 and verify its files by SHA-256.

The mosaic builder uses no network: it reads the model from a directory and checks each file
by its pinned hash (``mosaic_build.mosaic.vectors``). This script fills that directory from the
model's origin, the model repository at its pinned revision, and refuses a file whose hash is
not the pinned one, naming the file and both hashes; the refused download is removed.

    uv run python scripts/fetch_model.py [--dest DIR] [--origin URL]

The default directory is ``.cache/model/<name>@<revision>/`` in the repository (not committed).
A file already there with the pinned hash is not downloaded again.
"""

import argparse
import sys
import urllib.request
from pathlib import Path

from mosaic_build.mosaic.vectors import MODEL, ModelFileError, check_file

REPO = Path(__file__).resolve().parent.parent
DEST = REPO / ".cache" / "model" / f"{MODEL.name}@{MODEL.revision}"
ORIGIN = f"https://huggingface.co/{MODEL.repository}/resolve/{MODEL.revision}"
"""Where the files are fetched from: ``<origin>/<path>`` for each pinned file."""


def fetch(dest: Path = DEST, origin: str = ORIGIN) -> Path:
    """Every pinned file of the model in ``dest``, downloaded when missing or different."""
    for pinned in MODEL.files:
        target = dest / pinned.path
        try:
            check_file(target, pinned)
            continue
        except ModelFileError:
            pass
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        url = f"{origin.rstrip('/')}/{pinned.path}"
        print(f"fetch {pinned.path} <- {url}")
        urllib.request.urlretrieve(url, partial)
        try:
            check_file(partial, pinned)
        except ModelFileError as e:
            partial.unlink(missing_ok=True)
            raise ModelFileError(str(e).replace(str(partial), url, 1)) from None
        partial.replace(target)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=DEST, help=f"directory (default {DEST})")
    parser.add_argument("--origin", default=ORIGIN, help=f"base URL (default {ORIGIN})")
    args = parser.parse_args(argv)
    try:
        dest = fetch(args.dest, args.origin)
    except ModelFileError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for pinned in MODEL.files:
        print(f"ok   {pinned.path} {pinned.sha256}")
    print(f"model in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
