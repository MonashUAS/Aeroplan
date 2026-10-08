"""aeroplan command line. P0 commands: schema, validate, compile-config."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import REGISTRY
from .config import compile_yaml, roundtrip_ok
from .muas.node import validate_node
from .schema_export import export_schemas


def _validate(args) -> int:
    failed = 0
    for path in args.files:
        try:
            validate_node(json.loads(Path(path).read_text(encoding="utf-8")))
            print(f"ok    {path}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {path}: {e}", file=sys.stderr)
    return 1 if failed else 0


def _compile_config(args) -> int:
    dst = compile_yaml(Path(args.src), Path(args.dst))
    if not roundtrip_ok(Path(args.src), dst):
        print("round-trip failed", file=sys.stderr)
        return 1
    print(f"wrote {dst}")
    return 0


def _schema(args) -> int:
    for p in export_schemas(Path(args.out)):
        print(f"wrote {p}")
    return 0


def _pkg_synthetic(args) -> int:
    from .synthetic import make_placeholder_package

    m = make_placeholder_package(Path(args.out_dir))
    print(f"wrote {args.out_dir} ({m.package_id}, sha256 {m.sha256[:12]})")
    return 0


def _pkg_verify(args) -> int:
    from .package import verify_package

    m = verify_package(Path(args.pkg_dir))
    print(f"ok {m.package_id} sha256 {m.sha256[:12]}")
    return 0


def _pkg_pack(args) -> int:
    from .package import pack_h5

    print(f"wrote {pack_h5(Path(args.pkg_dir), Path(args.h5))}")
    return 0


def _pkg_unpack(args) -> int:
    from .package import unpack_h5

    m = unpack_h5(Path(args.h5), Path(args.out_dir))
    print(f"ok {m.package_id}")
    return 0


def _pkg_build(args) -> int:
    import subprocess

    from .export_aircraft import build_aircraft_package
    from .package import Source

    def head(repo: Path) -> tuple[str, bool]:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True)
        if sha.returncode or dirty.returncode:
            raise SystemExit(f"{repo} is not a git repository with a commit")
        return sha.stdout.strip(), bool(dirty.stdout.strip())

    here = Path(__file__).resolve().parents[2]
    code, code_dirty = head(here)
    data, data_dirty = head(Path(args.aircraft_dir))
    if code_dirty or data_dirty:
        print(f"refused: uncommitted changes in {'AeroPlan' if code_dirty else ''} {'the aircraft data' if data_dirty else ''}. "
              "A package comes from committed files only (exchange rule).", file=sys.stderr)
        return 1
    m, rep = build_aircraft_package(Path(args.aircraft_dir), Path(args.out_dir), author=args.author, org=args.org,
                                    version=args.version, source=Source(repo="aeroplan", commit=code, data_repo="muas-fleet-data",
                                                                        data_commit=data))
    print(rep.text())
    print(f"wrote {args.out_dir} ({m.package_id}, sha256 {m.sha256[:12]})")
    return 0


def _integrate(args) -> int:
    from .integrate import integrate_currawong

    r = integrate_currawong(Path(args.aircraft_dir), force_config=args.force_config)
    print(json.dumps(r, indent=2))
    return 1 if r["unclassified"] else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="aeroplan")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate ADH node JSON files")
    v.add_argument("files", nargs="+")
    v.set_defaults(fn=_validate)
    c = sub.add_parser("compile-config", help="compile hand YAML to canonical JSON")
    c.add_argument("src")
    c.add_argument("dst")
    c.set_defaults(fn=_compile_config)
    s = sub.add_parser("schema", help="export JSON Schema files")
    s.add_argument("--out", default="schema")
    s.set_defaults(fn=_schema)
    ig = sub.add_parser("integrate", help="integrate raw artefacts of an aircraft folder (fleet-data repo)")
    ig.add_argument("aircraft", choices=["currawong"])
    ig.add_argument("aircraft_dir", help="the aircraft folder, e.g. <fleet-data>/aircraft/currawong")
    ig.add_argument("--force-config", action="store_true", help="overwrite config/<aircraft>.yaml")
    ig.set_defaults(fn=_integrate)
    pk = sub.add_parser("package", help="export package tools")
    pks = pk.add_subparsers(dest="pcmd", required=True)
    for name, nargs, fn in (
        ("synthetic", ["out_dir"], _pkg_synthetic),
        ("verify", ["pkg_dir"], _pkg_verify),
        ("pack", ["pkg_dir", "h5"], _pkg_pack),
        ("unpack", ["h5", "out_dir"], _pkg_unpack),
    ):
        sp = pks.add_parser(name)
        for n in nargs:
            sp.add_argument(n)
        sp.set_defaults(fn=fn)
    b = pks.add_parser("build", help="build the export package of an aircraft folder (contract C)")
    b.add_argument("aircraft", choices=["currawong"])
    b.add_argument("aircraft_dir")
    b.add_argument("out_dir")
    b.add_argument("--author", required=True, help="the person who makes the package")
    b.add_argument("--org", default="MUAS")
    b.add_argument("--version", required=True, help="package version, for example 0.1.0 (a package is never edited)")
    b.set_defaults(fn=_pkg_build)
    a = sub.add_parser("adapters", help="list ingestion adapters")
    a.set_defaults(fn=lambda _: print("\n".join(f"{n}: {c.produces}" for n, c in REGISTRY.items())) or 0)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
