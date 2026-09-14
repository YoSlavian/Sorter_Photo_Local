"""Command line interface.

Three verbs, matching the three questions a modeller asks:

``build``     — give me the diagram;
``validate``  — is my description structurally sound?
``explain``   — how did you understand what I wrote?
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from bpmn_architect import __version__
from bpmn_architect.building.builder import BuildOptions
from bpmn_architect.errors import BpmnArchitectError
from bpmn_architect.parsing import ParserOptions
from bpmn_architect.pipeline import DiagramResult, PipelineOptions, generate
from bpmn_architect.validation.diagnostics import Severity

__all__ = ["main", "build_parser"]

_EXTENSIONS = {"bpmn": ".bpmn", "svg": ".svg", "json": ".json"}
_EXIT_OK = 0
_EXIT_DIAGNOSTICS = 1
_EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bpmn-architect",
        description="Build a BPMN 2.0 diagram from a textual process description.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "input",
        type=Path,
        help="description file; use '-' to read the description from stdin",
    )
    common.add_argument(
        "--syntax",
        choices=("auto", "text", "dsl"),
        default="auto",
        help="input front end (default: auto-detect)",
    )
    common.add_argument(
        "--no-lanes", action="store_true", help="do not derive swimlanes from the actors"
    )
    common.add_argument(
        "--verbatim-names",
        action="store_true",
        help="keep the original wording instead of rewriting activities in the infinitive",
    )
    common.add_argument(
        "--language",
        choices=("ru", "en"),
        help="force the input language instead of detecting it",
    )

    build = subparsers.add_parser(
        "build", parents=[common], help="generate a diagram from a description"
    )
    build.add_argument("-o", "--output", type=Path, help="output file (default: next to the input)")
    build.add_argument(
        "-f",
        "--format",
        choices=("bpmn", "svg", "json", "all"),
        default="bpmn",
        help="output format (default: bpmn)",
    )
    build.add_argument("--stdout", action="store_true", help="write the result to stdout")
    build.add_argument(
        "--executable", action="store_true", help="mark the process as executable"
    )
    build.add_argument(
        "--process-id", help="identifier of the generated bpmn:process element"
    )
    build.add_argument("--process-name", help="name of the generated process")
    build.add_argument(
        "--strict", action="store_true", help="fail if validation reports any error"
    )
    build.add_argument(
        "--no-documentation",
        action="store_true",
        help="do not copy source sentences into bpmn:documentation",
    )
    build.add_argument("-q", "--quiet", action="store_true", help="suppress diagnostics")

    subparsers.add_parser(
        "validate", parents=[common], help="check a description without writing files"
    )
    subparsers.add_parser(
        "explain", parents=[common], help="show how the description was interpreted"
    )
    return parser


def _read_input(path: Path) -> str:
    if str(path) == "-":
        return sys.stdin.read()
    return path.read_text(encoding="utf-8")


def _options(args: argparse.Namespace) -> PipelineOptions:
    options = PipelineOptions(syntax=args.syntax)
    options.parser = ParserOptions(
        infinitive_names=not args.verbatim_names,
        detect_lanes=not args.no_lanes,
        language=args.language,
    )
    options.build = BuildOptions(
        process_id=getattr(args, "process_id", "") or "",
        process_name=getattr(args, "process_name", "") or "",
        use_lanes=not args.no_lanes,
        executable=bool(getattr(args, "executable", False)),
    )
    options.strict = bool(getattr(args, "strict", False))
    if getattr(args, "no_documentation", False):
        options.render = replace(options.render, include_source_documentation=False)
    return options


def _report(result: DiagramResult, stream: TextIO) -> int:
    for diagnostic in result.diagnostics.sorted():
        print(diagnostic, file=stream)
    return _EXIT_DIAGNOSTICS if result.diagnostics.has_errors else _EXIT_OK


def _targets(args: argparse.Namespace) -> list[str]:
    return ["bpmn", "svg", "json"] if args.format == "all" else [args.format]


def _render(result: DiagramResult, fmt: str) -> str:
    return {"bpmn": result.to_bpmn, "svg": result.to_svg, "json": result.to_json}[fmt]()


def _output_path(args: argparse.Namespace, fmt: str) -> Path:
    output: Path | None = args.output
    if output is not None:
        return output.with_suffix(_EXTENSIONS[fmt]) if args.format == "all" else output
    stem = Path("process" if str(args.input) == "-" else args.input.stem)
    return stem.with_suffix(_EXTENSIONS[fmt])


def _command_build(args: argparse.Namespace) -> int:
    result = generate(_read_input(args.input), _options(args))
    for fmt in _targets(args):
        content = _render(result, fmt)
        if args.stdout:
            sys.stdout.write(content)
            continue
        destination = _output_path(args, fmt)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        if not args.quiet:
            print(f"{destination}  ({len(result.model)} elements, {len(result.model.flows)} flows)")
    if args.quiet:
        return _EXIT_DIAGNOSTICS if result.diagnostics.has_errors else _EXIT_OK
    return _report(result, sys.stderr)


def _command_validate(args: argparse.Namespace) -> int:
    result = generate(_read_input(args.input), _options(args))
    exit_code = _report(result, sys.stdout)
    counts = {
        severity.value: sum(1 for d in result.diagnostics if d.severity is severity)
        for severity in Severity
    }
    print(
        f"\n{len(result.model)} elements, {len(result.model.flows)} flows, "
        f"{len(result.model.lanes)} lanes - "
        f"{counts['error']} error(s), {counts['warning']} warning(s)"
    )
    return exit_code


def _command_explain(args: argparse.Namespace) -> int:
    result = generate(_read_input(args.input), _options(args))
    sys.stdout.write(result.explain())
    return _EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "build": _command_build,
        "validate": _command_validate,
        "explain": _command_explain,
    }
    try:
        return commands[args.command](args)
    except FileNotFoundError as error:
        print(f"error: {error.filename}: file not found", file=sys.stderr)
        return _EXIT_USAGE
    except BpmnArchitectError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_DIAGNOSTICS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
