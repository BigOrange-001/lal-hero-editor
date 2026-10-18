"""Build the offline Windows editor, without rebuilding or launching the game."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from editor.app import APP_VERSION


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def icon(destination):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PIL import Image
    from io import BytesIO
    application = QGuiApplication.instance() or QGuiApplication(["editor-icon"])
    renderer = QSvgRenderer(str(ROOT / "editor/resources/app-icon.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid application SVG")
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, 256, 256))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    with Image.open(BytesIO(bytes(buffer.data()))) as picture:
        picture.save(destination, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def collect_licenses(destination):
    """Copy reviewed upstream texts and the actual installed dependency notices.

    Packaging is deliberately offline. Source URLs and hashes travel with the
    release, alongside the full texts; a missing or changed notice fails the
    build instead of silently producing a link-only attribution directory.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    bundled = ROOT / "editor/resources/licenses"
    sources = json.loads((bundled / "SOURCES.json").read_text(encoding="utf-8"))
    if sources.get("unresolved"):
        raise ValueError("Unresolved upstream license sources")
    for row in sources["files"]:
        source = bundled / row["file"]
        if not source.resolve().is_relative_to(bundled.resolve()) or not source.is_file() or sha(source) != row["sha256"]:
            raise ValueError("Missing or changed bundled license: " + row["file"])
    required = ("PROJECT-LICENSE-AND-ASSET-NOTICE.txt", "README.txt",
                "CPython/LICENSE-" + sources["pythonVersion"] + ".txt",
                "Qt-PySide/qtbase/LICENSES/LGPL-3.0-only.txt",
                "Qt-PySide/qtbase/LICENSES/GPL-2.0-only.txt",
                "Qt-PySide/qtbase/LICENSES/GPL-3.0-only.txt",
                "Qt-PySide/qtbase/LICENSES/Qt-GPL-exception-1.0.txt",
                "Qt-PySide/COMPONENT-ATTRIBUTIONS.json", "FFmpeg/COPYING.LGPLv2.1")
    if any(not (bundled / name).is_file() for name in required):
        raise ValueError("Incomplete editor license resources")
    shutil.copytree(bundled, destination, dirs_exist_ok=True)

    distributions = ("PySide6-Essentials", "PySide6-Addons", "shiboken6", "Pillow", "PyInstaller", "tzdata")
    versions = {}
    origins = {row["file"]: row["source"] for row in sources["files"]}
    for name in distributions:
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        if name in ("PySide6-Essentials", "PySide6-Addons", "shiboken6") and distribution.version != sources["qtPySideVersion"]:
            raise ValueError("Update bundled Qt/PySide license sources for " + name + " " + distribution.version)
        copied = 0
        for record in distribution.files or ():
            normalized = str(record).replace("\\", "/")
            if ".dist-info/" not in normalized:
                continue
            local = normalized.split(".dist-info/", 1)[-1]
            if local != "METADATA" and not any(term in local.lower() for term in ("license", "copying", "notice", "copyright", "authors")):
                continue
            source = Path(distribution.locate_file(record))
            if source.is_file():
                target = destination / name / local
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                origins[target.relative_to(destination).as_posix()] = "installed distribution " + name + "==" + distribution.version + ": " + normalized
                if local != "METADATA":
                    copied += 1
        if not copied:
            raise ValueError("No installed license text found for " + name)

    if sys.version.split()[0] != sources["pythonVersion"]:
        raise ValueError("Update bundled CPython license sources for Python " + sys.version.split()[0])
    # Retain the installation's notice verbatim, without assuming it is the PSF
    # license. The independently sourced, versioned CPython text is above.
    runtime_notice = Path(sys.base_prefix) / "LICENSE.txt"
    if runtime_notice.is_file():
        target = destination / "Installed-runtime/LICENSE.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime_notice, target)
        origins[target.relative_to(destination).as_posix()] = "build interpreter installation: LICENSE.txt (verbatim, separate from CPython official license)"
    pyside = Path(importlib.metadata.distribution("PySide6-Essentials").locate_file("PySide6"))
    for source in (pyside / "Qt/licenses", pyside / "licenses"):
        if source.is_dir():
            target_root = destination / "Qt-installed" / source.relative_to(pyside)
            shutil.copytree(source, target_root, dirs_exist_ok=True)
            for item in target_root.rglob("*"):
                if item.is_file():
                    origins[item.relative_to(destination).as_posix()] = "installed PySide6 Qt notices: " + source.name + "/" + item.relative_to(target_root).as_posix()
    inventory = [{"path": path.relative_to(destination.parent).as_posix(), "bytes": path.stat().st_size}
                 for path in sorted(destination.parent.rglob("*")) if path.is_file() and path.suffix.lower() in (".dll", ".pyd")]
    (destination / "BUNDLED-FILES.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    origins["BUNDLED-FILES.json"] = "generated from this release's actual DLL/PYD files (relative paths and byte sizes)"
    records = [{"path": path.relative_to(destination).as_posix(), "sha256": sha(path),
                "source": origins.get(path.relative_to(destination).as_posix(), "editor/resources/licenses/" + path.relative_to(destination).as_posix())}
               for path in sorted(destination.rglob("*")) if path.is_file() and path.name != "INSTALLED-LICENSES.json"]
    (destination / "INSTALLED-LICENSES.json").write_text(json.dumps(
        {"python": sys.version.split()[0], "dependencies": versions, "files": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return versions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / f"build/hero-editor-release-{APP_VERSION}")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    # Build paths always stay under this checkout; no user directory is removed.
    if not output.is_relative_to(ROOT / "build"):
        raise ValueError("Build output must be a dedicated subdirectory of this repository's build/")
    output.mkdir(parents=True, exist_ok=True)
    work = output / "work"
    work.mkdir(exist_ok=True)
    app_icon = work / "HeroPackEditor.ico"
    icon(app_icon)
    executable_name = "HeroPackEditor"
    command = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir", "--windowed",
               "--name", executable_name, "--icon", str(app_icon), "--distpath", str(output / "dist"),
               "--workpath", str(work / "pyinstaller"), "--specpath", str(work),
               "--paths", str(ROOT), "--paths", str(ROOT / "server"),
               "--hidden-import", "PySide6.QtSvg", "--hidden-import", "scripts.mod_tools",
               "--collect-data", "tzdata"]
    for module in ("PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
                   "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtQuick", "PySide6.QtQml",
                   "tkinter", "matplotlib", "numpy", "pandas", "pytest", "unittest"):
        command += ["--exclude-module", module]
    for source, target in (("editor/resources", "editor/resources"), ("config", "config"),
                           ("schemas", "schemas"), ("examples/mods", "examples/mods"),
                           ("client/resources/app/assets", "client/resources/app/assets")):
        command += ["--add-data", str(ROOT / source) + os.pathsep + target]
    # The game modules are imported unqualified from server/ and use sibling
    # data files; frozen modules therefore need those siblings at bundle root.
    for source in sorted((ROOT / "server").glob("*.json")):
        command += ["--add-data", str(source) + os.pathsep + "."]
    command.append(str(ROOT / "scripts/hero_editor.py"))
    # DLL discovery must not inspect unrelated tools on the host PATH. In
    # particular Poppler's ICU has the same filename as Windows' native ICU
    # but incompatible exports, and image tools can supply foreign UCRT stubs.
    # Qt/Pillow hooks provide their own package-local dependency directories.
    environment = os.environ.copy()
    windows = Path(environment.get("SystemRoot", "C:/Windows"))
    search_paths = [Path(sys.prefix) / "Scripts", Path(sys.base_prefix),
                    Path(sys.base_prefix) / "DLLs", windows / "System32", windows]
    environment["PATH"] = os.pathsep.join(str(path) for path in search_paths if path.is_dir())
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "server")))
    print("Building Windows editor (no game build or runtime)", flush=True)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    package = output / "dist" / executable_name
    internal = package / "_internal"
    foreign_system = [path.name for path in internal.glob("*.dll")
                      if path.name.lower().startswith("api-ms-win-")
                      or path.name.lower() in ("ucrtbase.dll", "icuuc.dll")]
    if foreign_system:
        raise ValueError("Unexpected bundled Windows system libraries: " + ", ".join(sorted(foreign_system)))
    documents = {"hero-pack-editor-guide.md": "使用说明.md",
                 "hero-pack-editor-requirements.md": "需求与范围.md",
                 "hero-pack-editor-implementation.md": "实现与验证.md",
                 "battle-mechanism-editor-catalog.md": "战斗机制目录.md",
                 "mod-authoring.md": "英雄包作者规范.md"}
    for source_name, destination_name in documents.items():
        body = (ROOT / "docs" / source_name).read_text(encoding="utf-8")
        for original, translated in documents.items():
            body = body.replace("](" + original + ")", "](" + translated + ")")
        body = body.replace("](../schemas/", "](_internal/schemas/")
        body = body.replace("](../server/native_ability_parameters.json)", "](_internal/native_ability_parameters.json)")
        (package / destination_name).write_text(body, encoding="utf-8")
    (package / "启动英雄工坊.cmd").write_text('@echo off\r\ncd /d "%~dp0"\r\nstart "" "HeroPackEditor.exe"\r\n', encoding="utf-8")
    versions = collect_licenses(package / "licenses")
    sources = sorted(list((ROOT / "editor").rglob("*.py")) + list((ROOT / "server").glob("*.py")) +
                     list((ROOT / "server").glob("*.json")) + list((ROOT / "schemas").glob("*.json")) +
                     [ROOT / "scripts/hero_editor.py", ROOT / "scripts/build_hero_editor.py", ROOT / "scripts/mod_tools.py"])
    record = {"version": APP_VERSION, "gameVersion": (ROOT / "GAME_VERSION").read_text("utf-8").strip(),
              "python": sys.version.split()[0], "dependencies": versions,
              "sources": {path.relative_to(ROOT).as_posix(): sha(path) for path in sources},
              "executableSha256": sha(package / "HeroPackEditor.exe"), "personalSavesIncluded": False}
    (package / "build-record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = output / f"HeroPackEditor-{APP_VERSION}-win-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(package.parent).as_posix())
    result = {"executable": str(package / "HeroPackEditor.exe"), "archive": str(archive),
              "archiveSha256": sha(archive), "bytes": archive.stat().st_size}
    (output / "release.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
