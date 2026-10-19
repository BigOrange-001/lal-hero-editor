"""Desktop entry point and small offline command-line companion."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pathlib import Path

APP_VERSION = "1.2.0-dev"
APP_NAME = "英雄工坊"
ROOT = Path(__file__).resolve().parents[1]


def _emit(value, report=None):
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if report:
        path = Path(report).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(text)


def _data_directory():
    override = os.environ.get("HERO_EDITOR_DATA_DIR")
    base = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LALHeroEditor"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _logging():
    try:
        handler = RotatingFileHandler(_data_directory() / "editor.log", maxBytes=1_048_576, backupCount=2, encoding="utf-8")
        logging.basicConfig(handlers=[handler], level=logging.WARNING,
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.WARNING)


def _gui(catalog, project=None, check_report=None):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QFont, QFontDatabase, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .ui import MainWindow

    # Qt 6 handles high DPI automatically; use a predictable Chinese UI face.
    QCoreApplication.setOrganizationName("LALRebuild")
    QCoreApplication.setApplicationName("HeroPackEditor")
    QCoreApplication.setApplicationVersion(APP_VERSION)
    application = QApplication.instance() or QApplication([sys.argv[0]])
    # The offscreen plugin does not enumerate Windows fonts. Load the local
    # installed face for diagnostics without redistributing system fonts.
    if application.platformName() == "offscreen" and not QFontDatabase.families():
        face = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/msyh.ttc"
        if face.is_file():
            QFontDatabase.addApplicationFont(str(face))
    application.setFont(QFont("Microsoft YaHei UI", 10))
    icon = ROOT / "editor/resources/app-icon.svg"
    if icon.is_file():
        application.setWindowIcon(QIcon(str(icon)))

    def exception_hook(kind, value, tb):
        logging.error("Unhandled editor error", exc_info=(kind, value, tb))
        QMessageBox.critical(None, "操作未完成", "操作遇到异常，已保留当前工程。\n请先另存工程，再检查日志。\n\n" + str(value))

    sys.excepthook = exception_hook
    window = MainWindow(catalog=catalog)
    if project:
        path = Path(project)
        if path.suffix.lower() == ".heropack":
            window.import_package(str(path))
        else:
            window.open_project(str(path))
    if check_report is not None:
        # One launch check for the shipped executable, also useful in support.
        # It opens no game, account, save, network endpoint or native dialogs.
        window.resize(1440, 960)
        window.show()
        application.processEvents()
        screenshot = Path(check_report).with_suffix(".png")
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(screenshot)):
            raise OSError("无法保存安装诊断截图")
        _emit({"ok": True, "version": APP_VERSION, "gameDataVersion": catalog.base.get("cfg_version"),
               "heroes": len(catalog.heroes), "skills": len(catalog.skills), "effects": len(catalog.effects),
               "screenshot": str(screenshot.resolve()), "frozen": bool(getattr(sys, "frozen", False))}, check_report)
        window.hide()
        window.deleteLater()
        application.processEvents()
        return 0
    window.show()
    return application.exec()


def main(argv=None):
    parser = argparse.ArgumentParser(description="英雄工坊：离线英雄包编辑、校验、合并与导出")
    parser.add_argument("project", nargs="?", help="打开 .lalhero 工程或 .heropack 英雄包")
    parser.add_argument("--config", help="使用指定的游戏完整配置")
    parser.add_argument("--report", help="将命令行结果保存为 JSON")
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument("--validate", metavar="FILE", help="离线校验工程或英雄包")
    operations.add_argument("--merge", nargs="+", metavar="PACKAGE", help="将多个英雄包合并为新包")
    operations.add_argument("--coverage", action="store_true", help="导出当前游戏技能机制覆盖清单")
    operations.add_argument("--check-install", action="store_true", help="离屏打开主界面并输出一次安装诊断")
    parser.add_argument("--output", help="合并后的 .heropack 输出位置")
    parser.add_argument("--name", default="合并英雄包", help="合并后包名称")
    parser.add_argument("--author", default="", help="合并后作者；省略时保留来源作者组合")
    args = parser.parse_args(argv)
    _logging()
    try:
        from .catalog import Catalog
        from .core import Project
        catalog = Catalog(base_path=args.config)
        if args.validate:
            path = Path(args.validate)
            project = Project.import_package(path, catalog=catalog) if path.suffix.lower() == ".heropack" else Project.load(path, catalog=catalog)
            issues = project.validate(catalog=catalog)
            valid = not any(item.get("severity") == "error" for item in issues)
            _emit({"ok": valid, "issues": issues}, args.report)
            return 0 if valid else 2
        if args.merge:
            if not args.output:
                parser.error("--merge 需要 --output 指定导出位置")
            from .merge import merge_packages
            project, summary = merge_packages(args.merge, catalog=catalog, name=args.name, author=args.author)
            package = project.export(args.output, catalog=catalog)
            _emit({"ok": True, "package": package, "merge": summary}, args.report)
            return 0
        if args.coverage:
            _emit(catalog.coverage(), args.report)
            return 0
        if args.check_install:
            if not args.report:
                parser.error("--check-install 需要 --report 指定诊断文件")
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            return _gui(catalog, args.project, args.report)
        return _gui(catalog, args.project)
    except Exception as error:
        logging.exception("Editor operation failed")
        result = {"ok": False, "code": getattr(error, "code", "EditorError"),
                  "path": getattr(error, "path", ""), "message": str(error)}
        _emit(result, args.report)
        if not any((args.validate, args.merge, args.coverage, args.check_install)):
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox
                application = QApplication.instance() or QApplication([sys.argv[0]])
                QMessageBox.critical(None, "无法启动英雄工坊", "请使用完整的解压目录启动程序。\n\n" + str(error))
            except ImportError:
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
