#!/usr/bin/env python3
"""Opt-in separate-prefix pinned FFmpeg build. Never installs dependencies/drivers.

Default is a plan. --execute creates fresh source/build/prefix roots, builds and
writes a local provenance receipt; it does not replace /usr/bin or execute media.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

PIN = "946fcce07b6dcd0331c8cc609192aeff5e1924f8"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha(path)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "build", "prefix"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--cc", default="cc")
    p.add_argument("--glslc", default="glslc")
    p.add_argument("--jobs", type=int, default=len(os.sched_getaffinity(0)))
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    roots = [a.source.resolve(), a.build.resolve(), a.prefix.resolve()]
    if (
        a.jobs < 1
        or len(set(roots)) != 3
        or any(x.is_relative_to(y) for x in roots for y in roots if x != y)
    ):
        p.error("positive jobs and three disjoint fresh roots required")
    for root in roots:
        if root.exists() or any((d / ".git").exists() for d in root.parents):
            p.error("all build destinations must be fresh and outside any checkout")
    configure = [
        str(a.source.resolve() / "configure"),
        "--prefix=" + str(a.prefix.resolve()),
        "--disable-autodetect",
        "--enable-gpl",
        "--enable-libx264",
        "--enable-vulkan",
        "--disable-doc",
        "--disable-debug",
        "--disable-shared",
        "--enable-static",
        "--cc=" + a.cc,
        "--glslc=" + a.glslc,
        "--extra-version=ewp-" + PIN[:12],
    ]
    if not a.execute:
        print(
            json.dumps(
                {
                    "status": "NOT_RUN",
                    "source_commit": PIN,
                    "configure_argv": configure,
                    "jobs": a.jobs,
                    "prerequisites": [
                        "git",
                        "make",
                        "nasm",
                        "pkg-config",
                        a.cc,
                        a.glslc,
                        "Vulkan headers >=1.3.277 (1.4.317 capability checked)",
                        "glslc supporting Vulkan1.4/SPIR-V1.6",
                        "libx264 development files",
                    ],
                    "note": (
                        "no apt/driver/global installation; target operator supplies prerequisites"
                    ),
                },
                indent=2,
            )
        )
        return 0
    required = {
        key: shutil.which(key) for key in ("git", "make", "nasm", "pkg-config", a.cc, a.glslc)
    }
    if not all(required.values()):
        p.error("missing prerequisites: " + str([k for k, v in required.items() if v is None]))
    a.source, a.build, a.prefix = roots
    for root in roots:
        root.mkdir(parents=True, exist_ok=False)
    tmp = a.build / "tmp"
    tmp.mkdir()
    env = {**os.environ, "TMPDIR": str(tmp), "LC_ALL": "C"}
    commands = []

    def run(label: str, argv: list[str], cwd: Path = a.build) -> str:
        entry = {"label": label, "argv": argv, "cwd": str(cwd), "event": "STARTED"}
        with (a.build / "commands.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False)
        stdout, stderr = a.build / (label + ".stdout"), a.build / (label + ".stderr")
        stdout.write_bytes(proc.stdout)
        stderr.write_bytes(proc.stderr)
        commands.append(
            {
                **entry,
                "event": "FINISHED",
                "returncode": proc.returncode,
                "stdout": artifact(stdout),
                "stderr": artifact(stderr),
            }
        )
        with (a.build / "commands.jsonl").open("a") as f:
            f.write(json.dumps(commands[-1]) + "\n")
        if proc.returncode:
            raise RuntimeError(label + " failed; preserve build logs, no retry in this namespace")
        return proc.stdout.decode(errors="replace").strip()

    try:
        compiler = run("compiler", [str(required[a.cc]), "--version"])
        spirv = run("spirv-compiler", [str(required[a.glslc]), "--version"])
        pkg = run("pkg-versions", ["pkg-config", "--modversion", "vulkan", "x264"])
        run("git-init", ["git", "init", str(a.source)])
        run(
            "git-fetch",
            [
                "git",
                "-C",
                str(a.source),
                "fetch",
                "--depth",
                "1",
                "https://github.com/FFmpeg/FFmpeg.git",
                PIN,
            ],
        )
        run("git-checkout", ["git", "-C", str(a.source), "checkout", "--detach", "FETCH_HEAD"])
        observed = run("git-pin", ["git", "-C", str(a.source), "rev-parse", "HEAD"])
        if observed != PIN:
            raise ValueError("fetched source commit mismatch")
        configure[-3] = "--cc=" + str(Path(str(required[a.cc])).resolve())
        configure[-2] = "--glslc=" + str(Path(str(required[a.glslc])).resolve())
        run("configure", configure)
        run("make", ["make", "-j", str(a.jobs)])
        run("install-prefix", ["make", "install"])
        dirty = run("git-status", ["git", "-C", str(a.source), "status", "--porcelain"])
        if dirty:
            raise ValueError("pinned source unexpectedly dirty")
        tools = {k: artifact(a.prefix / "bin" / k) for k in ("ffmpeg", "ffprobe")}
        run("buildconf", [str(a.prefix / "bin/ffmpeg"), "-buildconf"])
        run("encoders", [str(a.prefix / "bin/ffmpeg"), "-encoders"])
        run("filters", [str(a.prefix / "bin/ffmpeg"), "-filters"])
        for name in ("ffmpeg", "ffprobe"):
            run("ldd-" + name, ["ldd", str(a.prefix / "bin" / name)])
        evidence = [artifact(path) for path in sorted(a.build.iterdir()) if path.is_file()]
        evidence += [
            artifact(a.build / "ffbuild/config.log"),
            artifact(a.build / "config.h"),
            artifact(a.build / "ffbuild/config.mak"),
            artifact(a.source / "configure"),
        ]
        receipt = {
            "schema_version": 1,
            "source_commit": PIN,
            "source_dirty": False,
            "compiler": compiler,
            "compiler_binary": artifact(Path(str(required[a.cc])).resolve()),
            "spirv_compiler": spirv,
            "spirv_compiler_binary": artifact(Path(str(required[a.glslc])).resolve()),
            "pkg_config_versions_vulkan_x264": pkg,
            "configure_argv": configure,
            "tools": tools,
            "evidence": evidence,
            "commands": commands,
            "linked_libraries": (
                "ldd records retained; driver/ICD observed separately by suite preflight"
            ),
        }
        # Hash actual dynamic libraries, not merely their textual names.
        libraries = {}
        import re

        for name in ("ffmpeg", "ffprobe"):
            text = (a.build / ("ldd-" + name + ".stdout")).read_text()
            for value in re.findall(r"(?:=>\s+)?(/\S+)", text):
                path = Path(value)
                if path.is_file():
                    libraries[str(path.resolve())] = artifact(path.resolve())
        receipt["library_identities"] = libraries
        with (a.build / "build-receipt.json").open("x") as f:
            json.dump(receipt, f, indent=2)
        print(str(a.build / "build-receipt.json"))
    except Exception as exc:
        with (a.build / "FAILED.json").open("x") as f:
            json.dump({"error": str(exc), "commands": commands, "status": "FAILED"}, f, indent=2)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
