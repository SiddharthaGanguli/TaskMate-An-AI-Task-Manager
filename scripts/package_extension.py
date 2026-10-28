"""Bundle the browser extension with its manifest at the ZIP root."""

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/taskmate-extension.zip")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "browser-extension"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    files = {"manifest.json", "popup.html", "popup.js", "popup.css", *manifest["icons"].values()}
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in files:
        if not (root / name).is_file():
            raise FileNotFoundError(f"Extension resource is missing: {name}")
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(root / name, name)
    print(f"Packaged TaskMate extension: {output}")


if __name__ == "__main__":
    main()
