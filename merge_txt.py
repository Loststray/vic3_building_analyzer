from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TOP_LEVEL_OPERATION_RE = re.compile(r"^\s*(REPLACE|TRY_REPLACE|INJECT|TRY_INJECT|TRT_INJECT):", re.MULTILINE)


def normalize_output_path(source_dir: Path, output_name: str) -> Path:
    output_path = Path(output_name)
    if output_path.suffix.lower() != ".txt":
        output_path = output_path.with_suffix(".txt")
    if not output_path.is_absolute():
        output_path = source_dir / output_path
    return output_path


def collect_txt_files(source_dir: Path, output_path: Path) -> list[Path]:
    output_path = output_path.resolve()
    txt_files: list[Path] = []

    for path in sorted(source_dir.glob("*.txt"), key=txt_sort_key):
        if path.resolve() == output_path:
            continue
        txt_files.append(path)

    return txt_files


def txt_sort_key(path: Path) -> tuple[int, str]:
    try:
        has_operation_prefix = bool(TOP_LEVEL_OPERATION_RE.search(path.read_text(encoding="utf-8-sig")))
    except OSError:
        has_operation_prefix = False
    return (1 if has_operation_prefix else 0, path.name.lower())


def merge_txt_files(source_dir: Path, output_name: str, encoding: str = "utf-8-sig") -> Path:
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source directory does not exist: {source_dir}")

    output_path = normalize_output_path(source_dir, output_name)
    txt_files = collect_txt_files(source_dir, output_path)
    if not txt_files:
        raise FileNotFoundError(f"No .txt files found in: {source_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding=encoding, newline="") as output_file:
        for index, txt_file in enumerate(txt_files):
            if index > 0:
                output_file.write("\n")
            output_file.write(txt_file.read_text(encoding=encoding))

    return output_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge all .txt files in a directory into one .txt file.")
    parser.add_argument("source_dir", type=Path, help="Directory containing .txt files.")
    parser.add_argument("output_name", help="Output file name, such as merged.txt. The .txt suffix is optional.")
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="Text encoding used for reading and writing files. Default: utf-8-sig.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        output_path = merge_txt_files(args.source_dir, args.output_name, args.encoding)
    except (OSError, UnicodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Wrote merged file to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
