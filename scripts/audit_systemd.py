#!/usr/bin/env python3
"""Read-only systemd sandbox audit for packaged service units."""

import argparse
import os
import re
import subprocess
from pathlib import Path


UNIT_NAMES = (
    "cricket-restream-supervisor.service",
    "rtmp-auth.service",
    "restream-manager.service",
)
EXPOSURE_RE = re.compile(r"Overall exposure level .*: ([0-9]+(?:\.[0-9]+)?)")


class AuditError(RuntimeError):
    pass


def unit_exposure(path):
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    result = subprocess.run(
        [
            "systemd-analyze",
            "security",
            "--offline=yes",
            str(path),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise AuditError(f"systemd-analyze failed for {path.name}")
    match = EXPOSURE_RE.search(output)
    if match is None:
        raise AuditError(f"exposure score missing for {path.name}")
    return float(match.group(1))


def audit_units(unit_dir, maximum):
    results = {}
    for name in UNIT_NAMES:
        path = unit_dir / name
        if not path.is_file():
            raise AuditError(f"unit is missing: {path}")
        score = unit_exposure(path)
        results[name] = score
        if score > maximum:
            raise AuditError(
                f"{name} exposure {score:.1f} exceeds maximum {maximum:.1f}"
            )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--unit-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "systemd",
    )
    parser.add_argument("--max-exposure", type=float, default=3.0)
    arguments = parser.parse_args()
    if arguments.max_exposure < 0:
        raise SystemExit("ERROR: max exposure must be non-negative")

    try:
        results = audit_units(arguments.unit_dir.resolve(), arguments.max_exposure)
    except (AuditError, OSError) as error:
        raise SystemExit(f"ERROR: {error}") from error

    for name, score in results.items():
        print(f"PASS: {name}: exposure={score:.1f}")
    print(f"All units satisfy maximum exposure {arguments.max_exposure:.1f}.")


if __name__ == "__main__":
    main()
