#!/usr/bin/env python3
"""
Patches a `flet build apk` generated Flutter/Android project so it includes
NotificationCaptureService.kt and the manifest entries it needs.

Why this exists: `flet build apk` regenerates the Flutter shell project from
your pyproject.toml + assets on every run, so hand-edits to build/flutter get
wiped out. Run this script AFTER `flet build apk` (or after Flet has
generated build/flutter, if your workflow separates those steps), then build
the APK from build/flutter yourself (see README) so the patch is included.

Usage:
    python patch_android_project.py --project-root build/flutter [--package com.example.nairafinancehub]

If --package is omitted, the script tries to read `applicationId` out of
android/app/build.gradle(.kts) in the project root.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SERVICE_CLASS = "NotificationCaptureService"
SERVICE_SOURCE = Path(__file__).parent / f"{SERVICE_CLASS}.kt"

MANIFEST_SERVICE_TEMPLATE = """        <service
            android:name=".{cls}"
            android:label="Transaction capture"
            android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.service.notification.NotificationListenerService" />
            </intent-filter>
        </service>
"""


def find_application_id(project_root: Path) -> str | None:
    for name in ("build.gradle", "build.gradle.kts"):
        gradle_file = project_root / "android" / "app" / name
        if gradle_file.exists():
            text = gradle_file.read_text()
            m = re.search(r'applicationId\s*[=]?\s*"([\w.]+)"', text)
            if m:
                return m.group(1)
    return None


def patch_kotlin_source(project_root: Path, package: str) -> Path:
    kotlin_root = project_root / "android" / "app" / "src" / "main" / "kotlin"
    package_dir = kotlin_root.joinpath(*package.split("."))
    package_dir.mkdir(parents=True, exist_ok=True)

    content = SERVICE_SOURCE.read_text()
    # Rewrite the placeholder package declaration to match the real app id.
    content = re.sub(r"^package .+$", f"package {package}", content, count=1, flags=re.M)

    dest = package_dir / f"{SERVICE_CLASS}.kt"
    dest.write_text(content)
    return dest


def patch_manifest(project_root: Path) -> None:
    manifest_path = project_root / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    if not manifest_path.exists():
        sys.exit(f"AndroidManifest.xml not found at {manifest_path}")

    text = manifest_path.read_text()

    if f".{SERVICE_CLASS}" in text:
        print("Manifest already contains the service entry — skipping manifest edit.")
        return

    # Insert the <service> block just before the closing </application> tag.
    if "</application>" not in text:
        sys.exit("Could not find </application> in AndroidManifest.xml — patch manually.")

    service_xml = MANIFEST_SERVICE_TEMPLATE.format(cls=SERVICE_CLASS)
    text = text.replace("</application>", service_xml + "    </application>")
    manifest_path.write_text(text)
    print(f"Patched {manifest_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, help="Path to the generated Flutter project, e.g. build/flutter")
    parser.add_argument("--package", help="Your app's applicationId, e.g. com.example.nairafinancehub")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        sys.exit(f"Project root not found: {project_root}")

    package = args.package or find_application_id(project_root)
    if not package:
        sys.exit(
            "Could not determine your applicationId. Pass it explicitly with "
            "--package com.example.nairafinancehub"
        )

    dest = patch_kotlin_source(project_root, package)
    print(f"Wrote {dest}")
    patch_manifest(project_root)

    print(
        "\nDone. Now build the APK from this patched project, e.g.:\n"
        f"  cd {project_root} && flutter build apk --release\n"
        "(In CI, run this script right after `flet build apk`, then run "
        "`flutter build apk` again inside build/flutter and use that APK.)"
    )


if __name__ == "__main__":
    main()
