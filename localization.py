from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


LOCALIZATION_RE = re.compile(r'^\s*([A-Za-z0-9_.:-]+):\s*"(.*)"\s*$')
ALIAS_RE = re.compile(r"^\$([A-Za-z0-9_.:-]+)\$$")


def unescape_value(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def load_localization_file(path: Path) -> dict[str, str]:
    localizations: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = LOCALIZATION_RE.match(line)
        if match is None:
            continue
        key, value = match.groups()
        localizations[key] = unescape_value(value)
    return localizations


def load_localizations(localization_dir: Path) -> dict[str, str]:
    if not localization_dir.is_dir():
        raise NotADirectoryError(f"Localization directory does not exist: {localization_dir}")

    localizations: dict[str, str] = {}
    for path in sorted(localization_dir.glob("*.yml"), key=lambda item: item.name.lower()):
        localizations.update(load_localization_file(path))
    return resolve_aliases(localizations)


def resolve_aliases(localizations: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}

    def resolve_key(key: str, seen: set[str]) -> str:
        if key in resolved:
            return resolved[key]

        value = localizations.get(key)
        if value is None:
            return key

        match = ALIAS_RE.match(value)
        if match is None:
            resolved[key] = value
            return value

        target_key = match.group(1)
        if target_key in seen:
            resolved[key] = value
            return value

        resolved_value = resolve_key(target_key, seen | {target_key})
        resolved[key] = resolved_value
        return resolved_value

    for key in localizations:
        resolve_key(key, {key})

    return resolved


def localize_csv(input_path: Path, output_path: Path, localizations: dict[str, str]) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0

    with input_path.open("r", newline="", encoding="utf-8-sig") as input_file:
        reader = csv.reader(input_file)
        with output_path.open("w", newline="", encoding="utf-8-sig") as output_file:
            writer = csv.writer(output_file)
            for row in reader:
                writer.writerow([localizations.get(cell, cell) for cell in row])
                row_count += 1

    return row_count


def build_arg_parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Localize output.csv cells using localization/*.yml.")
    parser.add_argument(
        "--localization-dir",
        type=Path,
        default=script_dir / "localization",
        help="Directory containing Victoria-style .yml localization files.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=script_dir / "output.csv",
        help="Input CSV path. Default: output.csv beside this script.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "output_loc.csv",
        help="Output CSV path. Default: output_loc.csv beside this script.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        localizations = load_localizations(args.localization_dir)
        row_count = localize_csv(args.input, args.output, localizations)
    except (OSError, UnicodeError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Loaded {len(localizations)} localization entries from {args.localization_dir}.")
    print(f"Wrote {row_count} rows to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
