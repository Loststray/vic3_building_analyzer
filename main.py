from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

try:
    from merge_txt import merge_txt_files
    from localization import load_localizations, localize_csv
except ImportError:  # pragma: no cover - used when imported as a package
    from .merge_txt import merge_txt_files
    from .localization import load_localizations, localize_csv


TokenValue = str | int | float | list[Any] | dict[str, Any]
Numeric = int | float

INTEGER_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+)$")
GOODS_INPUT_RE = re.compile(r"^goods_input_(.+)_add$")
GOODS_OUTPUT_RE = re.compile(r"^goods_output_(.+)_add$")
EMPLOYMENT_RE = re.compile(r"^building_employment_(.+)_add$")
WORKFORCE_COLUMN = "workforce"
PRICE_COLUMNS = ["goods_input_price", "goods_output_prices", "profit", "profit_per_capita"]
MERGE_TARGETS = (
    ("buildings", "buildings.txt"),
    ("goods", "goods.txt"),
    ("production_methods", "pm.txt"),
    ("production_methods_groups", "pmg.txt"),
)


class ParseError(ValueError):
    pass


class DataError(ValueError):
    pass


class RepeatedKey(list[Any]):
    """Values for a repeated key in a Paradox-style object."""


@dataclass(frozen=True)
class Token:
    value: str
    line: int
    column: int
    quoted: bool = False


@dataclass(frozen=True)
class CombinationRow:
    building: str
    building_group: str
    production_methods: tuple[str, ...]
    totals: Counter[str]


@dataclass(frozen=True)
class AnalysisResult:
    buildings: int
    pmgs: int
    pms: int
    rows: int
    item_columns: int
    output_path: Path
    localized_output_path: Path
    localized_rows: int
    merged_files: tuple[Path, ...]
    warnings: tuple[str, ...]


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    line = 1
    column = 1

    def advance_char(char: str) -> None:
        nonlocal line, column
        if char == "\n":
            line += 1
            column = 1
        else:
            column += 1

    while index < len(text):
        char = text[index]

        if char.isspace():
            advance_char(char)
            index += 1
            continue

        if char == "#":
            while index < len(text) and text[index] != "\n":
                index += 1
                column += 1
            continue

        if char in "{}=":
            tokens.append(Token(char, line, column))
            advance_char(char)
            index += 1
            continue

        if char == '"':
            start_line = line
            start_column = column
            index += 1
            column += 1
            value_chars: list[str] = []

            while index < len(text):
                char = text[index]
                if char == '"':
                    index += 1
                    column += 1
                    tokens.append(Token("".join(value_chars), start_line, start_column, quoted=True))
                    break
                if char == "\\" and index + 1 < len(text):
                    next_char = text[index + 1]
                    value_chars.append(next_char)
                    advance_char(char)
                    advance_char(next_char)
                    index += 2
                    continue

                value_chars.append(char)
                advance_char(char)
                index += 1
            else:
                raise ParseError(f"Unterminated string at line {start_line}, column {start_column}")

            continue

        start = index
        start_line = line
        start_column = column
        while index < len(text):
            char = text[index]
            if char.isspace() or char in "{}=#\"":
                break
            advance_char(char)
            index += 1
        tokens.append(Token(text[start:index], start_line, start_column))

    return tokens


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def parse(self) -> dict[str, TokenValue]:
        result: dict[str, TokenValue] = {}
        while not self.is_at_end():
            key = self.expect_atom()
            self.expect("=")
            add_pair(result, key.value, self.parse_value())
        return result

    def parse_value(self) -> TokenValue:
        token = self.peek()
        if token is None:
            raise ParseError("Unexpected end of file while reading a value")
        if token.value == "{":
            return self.parse_braced_value()
        if token.value in {"}", "="}:
            raise ParseError(f"Unexpected token {token.value!r} at line {token.line}, column {token.column}")

        self.index += 1
        return atom_to_scalar(token)

    def parse_braced_value(self) -> TokenValue:
        self.expect("{")
        mapping: dict[str, TokenValue] = {}
        items: list[TokenValue] = []
        saw_pairs = False
        saw_items = False

        while True:
            token = self.peek()
            if token is None:
                raise ParseError("Unexpected end of file; missing '}'")
            if token.value == "}":
                self.index += 1
                break

            next_token = self.peek(1)
            if self.is_atom(token) and next_token is not None and next_token.value == "=":
                key = self.expect_atom()
                self.expect("=")
                add_pair(mapping, key.value, self.parse_value())
                saw_pairs = True
            else:
                items.append(self.parse_value())
                saw_items = True

        if saw_pairs and saw_items:
            mapping["_items"] = items
            return mapping
        if saw_pairs:
            return mapping
        return items

    def expect(self, value: str) -> Token:
        token = self.peek()
        if token is None:
            raise ParseError(f"Expected {value!r}, got end of file")
        if token.value != value:
            raise ParseError(
                f"Expected {value!r}, got {token.value!r} at line {token.line}, column {token.column}"
            )
        self.index += 1
        return token

    def expect_atom(self) -> Token:
        token = self.peek()
        if token is None:
            raise ParseError("Expected an identifier, got end of file")
        if not self.is_atom(token):
            raise ParseError(f"Expected an identifier at line {token.line}, column {token.column}")
        self.index += 1
        return token

    def peek(self, offset: int = 0) -> Token | None:
        position = self.index + offset
        if position >= len(self.tokens):
            return None
        return self.tokens[position]

    def is_at_end(self) -> bool:
        return self.index >= len(self.tokens)

    @staticmethod
    def is_atom(token: Token) -> bool:
        return token.value not in {"{", "}", "="}


def add_pair(mapping: dict[str, TokenValue], key: str, value: TokenValue) -> None:
    if key not in mapping:
        mapping[key] = value
        return

    existing = mapping[key]
    if isinstance(existing, RepeatedKey):
        existing.append(value)
    else:
        mapping[key] = RepeatedKey([existing, value])


def atom_to_scalar(token: Token) -> str | int | float:
    if token.quoted:
        return token.value
    if INTEGER_RE.match(token.value):
        return int(token.value)
    if FLOAT_RE.match(token.value):
        return float(token.value)
    return token.value


def parse_text(text: str) -> dict[str, TokenValue]:
    return Parser(tokenize(text)).parse()


def parse_file(path: Path) -> dict[str, TokenValue]:
    return parse_text(path.read_text(encoding="utf-8-sig"))


def merge_input_directories(data_dir: Path, encoding: str = "utf-8-sig") -> dict[str, Path]:
    merged_paths: dict[str, Path] = {}
    for source_name, output_name in MERGE_TARGETS:
        source_dir = data_dir / source_name
        output_path = data_dir / output_name
        merged_paths[output_name] = merge_txt_files(source_dir, str(output_path), encoding=encoding)
    return merged_paths


def get_dict_path(value: TokenValue | None, *path: str) -> dict[str, TokenValue]:
    current: TokenValue | None = value
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    if isinstance(current, dict):
        return current
    return {}


def as_string_list(value: TokenValue | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(as_string_list(item))
        return result
    if isinstance(value, dict):
        return []
    return [str(value)]


def number_value(value: TokenValue, context: str) -> Numeric:
    if isinstance(value, list):
        total: Numeric = 0
        for item in value:
            total += number_value(item, context)
        return total
    if isinstance(value, bool):
        raise DataError(f"{context} must be a number, got boolean {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str) and INTEGER_RE.match(value):
        return int(value)
    if isinstance(value, str) and FLOAT_RE.match(value):
        return float(value)
    raise DataError(f"{context} must be a number, got {value!r}")


def int_value(value: TokenValue, context: str) -> int:
    number = number_value(value, context)
    if isinstance(number, float) and number.is_integer():
        return int(number)
    if isinstance(number, int):
        return number
    raise DataError(f"{context} must be an integer, got {value!r}")


def extract_pm_modifiers(pm_name: str, pm_object: TokenValue) -> Counter[str]:
    modifiers: Counter[str] = Counter()
    if not isinstance(pm_object, dict):
        return modifiers

    workforce_scaled = get_dict_path(pm_object, "building_modifiers", "workforce_scaled")
    for key, value in workforce_scaled.items():
        input_match = GOODS_INPUT_RE.match(key)
        if input_match:
            modifiers[input_match.group(1)] -= number_value(value, f"{pm_name}.{key}")
            continue

        output_match = GOODS_OUTPUT_RE.match(key)
        if output_match:
            modifiers[output_match.group(1)] += number_value(value, f"{pm_name}.{key}")

    level_scaled = get_dict_path(pm_object, "building_modifiers", "level_scaled")
    workforce = 0
    for key, value in level_scaled.items():
        employment_match = EMPLOYMENT_RE.match(key)
        if employment_match:
            workforce += int_value(value, f"{pm_name}.{key}")
    if workforce != 0:
        modifiers[WORKFORCE_COLUMN] += workforce

    return Counter({key: value for key, value in modifiers.items() if value != 0})


def extract_all_pm_modifiers(pm_objects: dict[str, TokenValue]) -> dict[str, Counter[str]]:
    return {pm_name: extract_pm_modifiers(pm_name, pm_object) for pm_name, pm_object in pm_objects.items()}


def extract_goods_costs(goods_objects: dict[str, TokenValue]) -> dict[str, Numeric]:
    costs: dict[str, Numeric] = {}
    for item_name, item_object in goods_objects.items():
        if not isinstance(item_object, dict) or "cost" not in item_object:
            continue
        costs[item_name] = number_value(item_object["cost"], f"{item_name}.cost")
    return costs


def note_or_raise(
    warnings: set[str],
    strict: bool,
    message: str,
    strict_message: str | None = None,
) -> None:
    if strict:
        raise DataError(strict_message or message)
    warnings.add(message)


def get_pmg_choices(
    building_name: str,
    building_object: TokenValue,
    pmg_objects: dict[str, TokenValue],
    pm_objects: dict[str, TokenValue],
    warnings: set[str],
    strict: bool,
    missing_pm: str,
) -> list[tuple[str, list[str]]]:
    if not isinstance(building_object, dict):
        return []

    pmg_names = as_string_list(building_object.get("production_method_groups"))
    choices: list[tuple[str, list[str]]] = []

    for pmg_name in pmg_names:
        pmg_object = pmg_objects.get(pmg_name)
        if pmg_object is None:
            note_or_raise(
                warnings,
                strict,
                f"{building_name} references missing production method group {pmg_name!r}; skipped",
                f"{building_name} references missing production method group {pmg_name!r}",
            )
            continue
        if not isinstance(pmg_object, dict):
            note_or_raise(warnings, strict, f"{pmg_name!r} is not an object; skipped", f"{pmg_name!r} is not an object")
            continue

        pm_names = as_string_list(pmg_object.get("production_methods"))
        valid_pm_names: list[str] = []
        for pm_name in pm_names:
            if pm_name in pm_objects:
                valid_pm_names.append(pm_name)
                continue

            if missing_pm == "zero":
                note_or_raise(
                    warnings,
                    strict,
                    f"{pmg_name} references missing production method {pm_name!r}; kept with zero modifiers",
                    f"{pmg_name} references missing production method {pm_name!r}",
                )
                valid_pm_names.append(pm_name)
            else:
                note_or_raise(
                    warnings,
                    strict,
                    f"{pmg_name} references missing production method {pm_name!r}; skipped",
                    f"{pmg_name} references missing production method {pm_name!r}",
                )

        if valid_pm_names:
            choices.append((pmg_name, valid_pm_names))
        else:
            note_or_raise(warnings, strict, f"{pmg_name!r} has no usable production methods; skipped")

    return choices


def generate_combinations(
    building_objects: dict[str, TokenValue],
    pmg_objects: dict[str, TokenValue],
    pm_objects: dict[str, TokenValue],
    pm_modifiers: dict[str, Counter[str]],
    strict: bool = False,
    missing_pm: str = "zero",
) -> tuple[list[CombinationRow], int, set[str], set[str]]:
    rows: list[CombinationRow] = []
    warnings: set[str] = set()
    used_pm_names: set[str] = set()
    max_pmg_columns = 0

    for building_name, building_object in building_objects.items():
        if not isinstance(building_object, dict):
            continue
        building_group = str(building_object.get("building_group", ""))

        choices = get_pmg_choices(
            building_name,
            building_object,
            pmg_objects,
            pm_objects,
            warnings,
            strict,
            missing_pm,
        )
        if not choices:
            note_or_raise(warnings, strict, f"{building_name!r} has no usable production method groups; skipped")
            continue

        max_pmg_columns = max(max_pmg_columns, len(choices))
        method_lists = [method_names for _pmg_name, method_names in choices]
        for combination in product(*method_lists):
            totals: Counter[str] = Counter()
            for pm_name in combination:
                used_pm_names.add(pm_name)
                for item_name, amount in pm_modifiers.get(pm_name, {}).items():
                    totals[item_name] += amount
            rows.append(CombinationRow(building_name, building_group, tuple(combination), totals))

    return rows, max_pmg_columns, warnings, used_pm_names


def collect_item_names(pm_modifiers: dict[str, Counter[str]], used_pm_names: set[str]) -> list[str]:
    item_names: list[str] = [WORKFORCE_COLUMN]
    seen: set[str] = {WORKFORCE_COLUMN}

    for pm_name, modifiers in pm_modifiers.items():
        if pm_name not in used_pm_names:
            continue
        for item_name in modifiers:
            if item_name not in seen:
                seen.add(item_name)
                item_names.append(item_name)

    return item_names


def csv_number(value: Numeric) -> Numeric:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def calculate_price_columns(row: CombinationRow, goods_costs: dict[str, Numeric]) -> list[Numeric]:
    goods_input_price: Numeric = 0
    goods_output_prices: Numeric = 0

    for item_name, amount in row.totals.items():
        if item_name == WORKFORCE_COLUMN or amount == 0:
            continue
        cost = goods_costs.get(item_name)
        if cost is None:
            continue

        if amount < 0:
            goods_input_price += -amount * cost
        elif amount > 0:
            goods_output_prices += amount * cost

    profit = goods_output_prices - goods_input_price
    workforce = row.totals.get(WORKFORCE_COLUMN, 0)
    profit_per_capita: Numeric = profit / workforce * 52 if workforce else 0
    return [goods_input_price, goods_output_prices, profit, profit_per_capita]


def format_price_columns(values: list[Numeric]) -> list[Numeric | str]:
    return [csv_number(value) for value in values[:-1]] + [f"{values[-1]:.2f}"]


def write_csv(
    output_path: Path,
    rows: list[CombinationRow],
    max_pmg_columns: int,
    item_names: list[str],
    goods_costs: dict[str, Numeric],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["building_group", "building"]
    header.extend(f"pmg{index}" for index in range(1, max_pmg_columns + 1))
    header.extend(PRICE_COLUMNS)
    header.extend(item_names)

    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(header)
        for row in rows:
            method_cells = list(row.production_methods)
            method_cells.extend([""] * (max_pmg_columns - len(method_cells)))
            price_cells = format_price_columns(calculate_price_columns(row, goods_costs))
            writer.writerow(
                [row.building_group, row.building]
                + method_cells
                + price_cells
                + [csv_number(row.totals.get(item_name, 0)) for item_name in item_names]
            )


def default_localized_output_path(output_path: Path) -> Path:
    if output_path.name.lower() == "output.csv":
        return output_path.with_name("output_loc.csv")
    return output_path.with_name(f"{output_path.stem}_loc{output_path.suffix}")


def run_analysis(
    data_dir: Path,
    output_path: Path,
    localized_output_path: Path | None = None,
    strict: bool = False,
    missing_pm: str = "zero",
) -> AnalysisResult:
    merged_files = merge_input_directories(data_dir)
    building_objects = parse_file(merged_files["buildings.txt"])
    pmg_objects = parse_file(merged_files["pmg.txt"])
    pm_objects = parse_file(merged_files["pm.txt"])
    goods_objects = parse_file(merged_files["goods.txt"])
    pm_modifiers = extract_all_pm_modifiers(pm_objects)
    goods_costs = extract_goods_costs(goods_objects)

    rows, max_pmg_columns, warnings, used_pm_names = generate_combinations(
        building_objects,
        pmg_objects,
        pm_objects,
        pm_modifiers,
        strict=strict,
        missing_pm=missing_pm,
    )
    item_names = collect_item_names(pm_modifiers, used_pm_names)
    write_csv(output_path, rows, max_pmg_columns, item_names, goods_costs)
    localized_output_path = localized_output_path or default_localized_output_path(output_path)
    localizations = load_localizations(data_dir / "localization")
    localized_rows = localize_csv(output_path, localized_output_path, localizations)

    return AnalysisResult(
        buildings=len(building_objects),
        pmgs=len(pmg_objects),
        pms=len(pm_objects),
        rows=len(rows),
        item_columns=len(item_names),
        output_path=output_path,
        localized_output_path=localized_output_path,
        localized_rows=localized_rows,
        merged_files=tuple(merged_files[output_name] for _source_name, output_name in MERGE_TARGETS),
        warnings=tuple(sorted(warnings)),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse Vic3-style txt files and export building production method combinations to CSV."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help=(
            "Directory containing buildings, goods, production_methods, and "
            "production_methods_groups folders."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path. Defaults to <data-dir>/output.csv.",
    )
    parser.add_argument(
        "--localized-output",
        type=Path,
        default=None,
        help="Localized CSV output path. Defaults to output_loc.csv next to output.csv.",
    )
    parser.add_argument(
        "--missing-pm",
        choices=("zero", "skip"),
        default="zero",
        help="How to handle production methods referenced by pmg.txt but missing from pm.txt.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on missing production method groups or production methods instead of writing warnings.",
    )
    return parser


def print_warnings(warnings: tuple[str, ...], limit: int = 20) -> None:
    if not warnings:
        return

    print(f"Warnings: {len(warnings)}", file=sys.stderr)
    for warning in warnings[:limit]:
        print(f"  - {warning}", file=sys.stderr)
    if len(warnings) > limit:
        print(f"  - ... {len(warnings) - limit} more", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    data_dir = args.data_dir.resolve()
    output_path = args.output.resolve() if args.output is not None else data_dir / "output.csv"
    localized_output_path = args.localized_output.resolve() if args.localized_output is not None else None

    try:
        result = run_analysis(
            data_dir=data_dir,
            output_path=output_path,
            localized_output_path=localized_output_path,
            strict=args.strict,
            missing_pm=args.missing_pm,
        )
    except (OSError, UnicodeError, csv.Error, ParseError, DataError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print_warnings(result.warnings)
    print("Merged input folders into:")
    for merged_file in result.merged_files:
        print(f"  - {merged_file}")
    print(
        f"Parsed {result.buildings} buildings, {result.pmgs} production method groups, "
        f"and {result.pms} production methods."
    )
    print(f"Wrote {result.rows} combinations with {result.item_columns} item columns to {result.output_path}.")
    print(f"Wrote {result.localized_rows} localized CSV rows to {result.localized_output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
