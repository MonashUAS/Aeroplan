"""aeroplan command line.

    aeroplan build <aircraft> --author NAME    run the spokes and write the source tree aircraft/<aircraft>/
    aeroplan check <aircraft>                  every check: ADH tree, datasets (DAVE-ML), datums, consumers
    aeroplan show <aircraft>                   print the ADH tree and the asset register
    aeroplan pack <aircraft> --profile P       write dist/<aircraft>-<version>-<P>.muas (a ZIP package)
    aeroplan unpack <file.muas> <folder>       check a package and write its source tree into <folder>
    aeroplan verify <file.muas>                check a package: mimetype, every hash, the package hash
    aeroplan generate <spoke> <aircraft>       write the tool input files of a spoke from the source tree
    aeroplan sweep <spoke> <aircraft>          run the tool sweep of a spoke (flow5: writes work/<aircraft>/sweeps/<name>)
    aeroplan export <spoke> <aircraft> <out>  write the tool files of a spoke (Aerolink: the aerolink package)
    aeroplan spokes [<aircraft>]               list the spokes and the input in their work folders
    aeroplan setup <spoke> [<aircraft>]        make the tool runtime of a spoke on this machine (OpenVSP)
    aeroplan schema --out schema               export the JSON Schema of the MUAS types
"""
from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path


def _build(args) -> int:
    from .build import build

    res = build(args.aircraft, author=args.author, version=args.version, new=args.new, only=args.only,
                dry_run=args.dry_run, consumers=args.consumers)
    for name, changes in res.changes.items():
        print(f"{name}:")
        for c in changes:
            print(f"  {c}")
    if res.skipped:
        print(f"no input: {', '.join(res.skipped)}")
    print("\nDatum checks:\n" + res.datum.text())
    print(f"\n{len(res.placeholders)} values are marked placeholder (aeroplan show {args.aircraft} --placeholders).")
    if res.missing_for_flight:
        print("Not flight ready for Aerolink. Missing:\n  " + "\n  ".join(res.missing_for_flight))
    else:
        print("Flight ready: Aerolink has every item it needs.")
    print(("dry run, nothing written" if args.dry_run else f"wrote {res.path}") + f" (version {res.version})")
    return 0


def _check(args) -> int:
    from .build import load_aircraft
    from .checks import run
    from .spokes import repo_root

    rep = run(load_aircraft(args.aircraft), repo_root())
    print(rep.text())
    print("\nAll checks pass." if rep.passed else f"\n{len(rep.failures)} checks fail.")
    return 0 if rep.passed else 1


def _show(args) -> int:
    from . import adh_doc, assets
    from .build import load_aircraft, placeholders

    acft = load_aircraft(args.aircraft)
    doc = acft.doc
    if args.placeholders:
        for p in placeholders(doc):
            print(p)
        return 0
    for path, item, parent in adh_doc.iter_nodes(doc):
        depth = path.count(".") + path.count("subcomponents")
        m = item.get("muas") or {}
        keys = [k for k in m if k not in ("ext_version", "instance")]
        label = f"{item.get('wbs_no', '')} {item.get('name', '')}".strip() if parent is None else f"- {item.get('name')}"
        extra = []
        if item.get("geometry"):
            extra.append("geometry: " + ", ".join(item["geometry"]))
        if item.get("requirements"):
            extra.append(f"{len(item['requirements'])} requirements")
        if item.get("performance"):
            extra.append("performance: " + ", ".join(d.get("name", "?") for d in item["performance"]))
        if m.get("datasets"):
            extra.append("datasets: " + ", ".join(d["role"] for d in m["datasets"]))
        print(f"{'  ' * depth}{label} [{m.get('instance', '')}]  {' '.join(keys)}  {'; '.join(extra)}")
    print("\nAsset register (1.10.2):")
    for e in assets.register(doc, create=False):
        print(f"  {e['kind']:7s} {e['name']:45s} {e['size']:>9d} B  {e['id'][13:25]}  {e['role']}")
    b = (doc.get("muas") or {}).get("build")
    if b:
        print(f"\nversion {b['version']}, built {b['built']} by {b['author']}, AeroPlan {b['aeroplan_commit'][:10]}"
              f"{' (dirty)' if b['aeroplan_dirty'] else ''}")
    return 0


def _pack(args) -> int:
    from .build import load_aircraft
    from .package import open_package, pack
    from .spokes import repo_root

    acft = load_aircraft(args.aircraft)
    for profile in args.profile:
        out = pack(acft, profile, repo_root(), Path(args.out))
        m = open_package(out).manifest
        print(f"wrote {out} ({len(m['files'])} files, package hash {m['package_hash'][:16]})")
    return 0


def _unpack(args) -> int:
    from .package import unpack
    from .spokes import repo_root

    for n in unpack(Path(args.file), Path(args.folder), repo_root()):
        print(n)
    print(f"wrote the source tree {args.folder}")
    return 0


def _verify(args) -> int:
    from . import assets
    from .package import open_package
    from .spokes import repo_root

    pkg = open_package(Path(args.file))
    m = pkg.manifest
    print(f"{Path(args.file).name}: {m['kind']} {m['aircraft']} {m['version']}, profile {m['profile']}, "
          f"format {m['format']} {m['format_version']}")
    print(f"pass  mimetype, {len(m['files'])} file hashes, package hash {m['package_hash']}")
    tiers = {}
    for e in assets.register(pkg.doc, create=False):
        tiers.setdefault(e.get("storage", "?"), []).append(e)
    for t, es in sorted(tiers.items()):
        print(f"      {t}: {len(es)} assets")
    missing = []
    for e in tiers.get("linked", []):
        if e["kind"] == "file":
            if assets.local_path(e, repo_root()) is None:
                missing.append(e["name"])
    if missing:
        print(f"      {len(missing)} linked files are not on this machine (the package stays valid): "
              + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    return 0


def _generate(args) -> int:
    from .build import generate

    for p in generate(args.spoke, args.aircraft):
        print(f"wrote {p}")
    return 0


def _sweep(args) -> int:
    from .build import sweep
    from .spokes import load

    res = sweep(args.spoke, args.aircraft, name=args.name, only=args.only, dry_run=args.dry_run, keep=args.keep,
                timeout=args.timeout, flow5=args.flow5)
    fmt = getattr(load(args.spoke), "format_sweep", None)
    print(fmt(res) if fmt else res)
    if not res.get("dry_run") and args.spoke == "flow5":
        print(f"\nNext: set `sweep: {res['name']}` and `sweep_date: '{res['created_utc'][:10]}'` in "
              f"{args.spoke}/settings/{args.aircraft}.yaml, then run `aeroplan build {args.aircraft} --author NAME`.")
    return 0 if res.get("dry_run") or (res.get("validation") or {}).get("ok") else 1


def _export(args) -> int:
    from .build import export

    for p in export(args.spoke, args.aircraft, Path(args.out)):
        print(f"wrote {p}")
    return 0


def _spokes(args) -> int:
    from .spokes import SPOKES, context, load

    for name in SPOKES:
        mod = load(name)
        steps = [s for s in ("ingest", "generate", "export") if hasattr(mod, s)]
        line = f"{name:12s} {', '.join(steps)}"
        if args.aircraft:
            w = context(name, args.aircraft).work
            n = sum(1 for p in w.rglob("*") if p.is_file()) if w.is_dir() else 0
            line += f"   work/{args.aircraft}: {n} files"
        if hasattr(mod, "describe"):
            line += f"   ({mod.describe()})"
        print(line)
    return 0


def _setup(args) -> int:
    from .spokes import context, load

    mod = load(args.spoke)
    if not hasattr(mod, "setup"):
        raise ValueError(f"the spoke {args.spoke} has no setup step")
    options = {"vsp": args.vsp, "proptimiser": args.proptimiser}
    accepted = inspect.signature(mod.setup).parameters
    res = mod.setup(context(args.spoke, args.aircraft), **{k: v for k, v in options.items() if k in accepted})
    print(f"{args.spoke} is ready: {res['version']} ({res['folder']})")
    return 0


def _schema(args) -> int:
    from .schema_export import export_schemas

    for p in export_schemas(Path(args.out)):
        print(f"wrote {p}")
    return 0


def main(argv=None) -> int:
    from .consumers import PROFILES

    p = argparse.ArgumentParser(prog="aeroplan", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="run the spokes and write the source tree aircraft/<aircraft>/")
    b.add_argument("aircraft")
    b.add_argument("--author", required=True, help="the person who builds the source tree")
    b.add_argument("--version", help="version of the aircraft (default: the last version, patch + 1)")
    b.add_argument("--new", action="store_true", help="start a new aircraft (an empty ADH document)")
    b.add_argument("--only", nargs="+", help="run only these spokes")
    b.add_argument("--consumers", nargs="+", choices=PROFILES, help="the packing profiles the aircraft serves")
    b.add_argument("--dry-run", action="store_true", help="check only, write nothing")
    b.set_defaults(fn=_build)
    for name, fn, helptext in (("check", _check, "every check of the source tree"),
                               ("show", _show, "print the ADH tree and the asset register")):
        c = sub.add_parser(name, help=helptext)
        c.add_argument("aircraft", nargs="?", default="currawong")
        if name == "show":
            c.add_argument("--placeholders", action="store_true", help="list every value marked placeholder")
        c.set_defaults(fn=fn)
    pk = sub.add_parser("pack", help="write a .muas package of the source tree")
    pk.add_argument("aircraft")
    pk.add_argument("--profile", nargs="+", required=True, choices=PROFILES)
    pk.add_argument("--out", default="dist")
    pk.set_defaults(fn=_pack)
    up = sub.add_parser("unpack", help="check a .muas package and write its source tree")
    up.add_argument("file")
    up.add_argument("folder")
    up.set_defaults(fn=_unpack)
    vf = sub.add_parser("verify", help="check a .muas package")
    vf.add_argument("file")
    vf.set_defaults(fn=_verify)
    g = sub.add_parser("generate", help="write the tool input files of a spoke")
    g.add_argument("spoke")
    g.add_argument("aircraft")
    g.set_defaults(fn=_generate)
    sw = sub.add_parser("sweep", help="run the tool sweep of a spoke (flow5: T7, alpha, beta and control runs)")
    sw.add_argument("spoke")
    sw.add_argument("aircraft")
    sw.add_argument("--name", help="the sweep folder name (default <aircraft>_<date>)")
    sw.add_argument("--only", nargs="+", help="run only these runs")
    sw.add_argument("--dry-run", action="store_true", help="write the XML files, do not start the tool")
    sw.add_argument("--keep", action="store_true", help="keep the tool output of the passes")
    sw.add_argument("--timeout", type=float, default=3600.0, help="seconds for each pass")
    sw.add_argument("--flow5", help="the path of flow5.exe, when the search does not find it")
    sw.set_defaults(fn=_sweep)
    e = sub.add_parser("export", help="write the tool files of a spoke into a folder")
    e.add_argument("spoke")
    e.add_argument("aircraft")
    e.add_argument("out")
    e.set_defaults(fn=_export)
    s = sub.add_parser("spokes", help="list the spokes")
    s.add_argument("aircraft", nargs="?")
    s.set_defaults(fn=_spokes)
    su = sub.add_parser("setup", help="make the tool runtime of a spoke on this machine (OpenVSP, AeroSandbox)")
    su.add_argument("spoke")
    su.add_argument("aircraft", nargs="?", default="currawong")
    su.add_argument("--vsp", help="the OpenVSP folder (the folder of vsp.exe), when the search does not find it")
    su.add_argument("--proptimiser", help="AeroSandbox: a Proptimiser checkout to install, instead of the git source")
    su.set_defaults(fn=_setup)
    sc = sub.add_parser("schema", help="export the JSON Schema of the MUAS types")
    sc.add_argument("--out", default="schema")
    sc.set_defaults(fn=_schema)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, KeyError, OSError, RuntimeError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
