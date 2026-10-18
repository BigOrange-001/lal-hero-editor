"""Offline, Qt-free hero authoring model.

Drafts deliberately do not need to be valid game packages. Publishing always
uses the game's real importer and compiler, in an isolated temporary catalog.
Nothing in this module opens a player database or the game's installed Mods.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import stat
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from mod_schema import (CHANNELS, ENGINE_API, FORMAT, LIMITS, SCOPES, STATS,
                        ModError, canonical, fail, safe_path, strict_json,
                        validate_data, validate_hero, validate_manifest,
                        validate_patch, validate_skill, skill_extension_capabilities)
from mod_packages import ModCatalog, Package, _inspect_payload, inspect_package
from mod_compile import Compiler, target_digest

PROJECT_FORMAT = "lal-hero-project-v1"
PROJECT_JSON = "manifest/project.json"
PROJECT_JSON_LIMIT = LIMITS["combinedDataBytes"]
DATA_KINDS = ("heroes", "skills", "patches")


def _project_shape(manifest, data, metadata):
    """Render-safe JSON structure, deliberately weaker than the game schema."""
    def error(path, message):
        raise ModError("EditorInvalidProject", message, path)
    def object_value(value, path):
        if not isinstance(value, dict):
            error(path, "工程此字段必须为对象")
    def text_fields(row, keys, path, nullable=()):
        for key in keys:
            if key in row and not isinstance(row[key], str) and not (key in nullable and row[key] is None):
                error(path + "." + key, "工程此字段必须为文本")
    def numeric_fields(row, keys, path):
        for key in keys:
            if key in row and type(row[key]) not in (int, float):
                error(path + "." + key, "工程此字段必须为数值；可以暂时不填")
    def integer_fields(row, keys, path):
        for key in keys:
            if key in row and type(row[key]) is not int:
                error(path + "." + key, "工程此字段必须为整数；可以暂时不填")
    def rows_value(row, key, path):
        values = row.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
            error(path + "." + key, "工程此字段必须为对象数组")
        return values
    for value, path in ((manifest, "manifest"), (data, "data"), (metadata, "metadata")):
        object_value(value, path)
    text_fields(manifest, ("name", "author", "kind", "packageId", "version", "engineApi", "description"), "manifest")
    if "dependencies" in manifest:
        for index, dependency in enumerate(rows_value(manifest, "dependencies", "manifest")):
            text_fields(dependency, ("packageId", "version", "digest"), "manifest.dependencies[%d]" % index)
    if "integrationDefaults" in manifest:
        object_value(manifest["integrationDefaults"], "manifest.integrationDefaults")
        if any(type(value) is not bool for value in manifest["integrationDefaults"].values()):
            error("manifest.integrationDefaults", "开关值必须为布尔值")
    if isinstance(manifest.get("sourceNotes"), dict):
        text_fields(manifest["sourceNotes"], ("kind", "description"), "manifest.sourceNotes")
    if "offlineDependencyPaths" in metadata and (not isinstance(metadata["offlineDependencyPaths"], list)
            or any(not isinstance(value, str) for value in metadata["offlineDependencyPaths"])):
        error("metadata.offlineDependencyPaths", "离线依赖路径必须为文本数组")
    for kind in DATA_KINDS:
        if kind not in data:
            continue
        doc = data[kind]
        object_value(doc, "data." + kind)
        for index, row in enumerate(rows_value(doc, kind, "data." + kind)):
            path = "%s[%d]" % (kind, index)
            text_fields(row, ("id", "name", "variant", "description", "role", "target", "unitType", "signType", "actionType", "damageType", "timingUnit", "targetPolicy", "rankInfoTemplate"), path)
            for key in ("integrationDefaults", "patchScopes"):
                if key in row:
                    object_value(row[key], path + "." + key)
                    if any(type(value) is not bool for value in row[key].values()):
                        error(path + "." + key, "开关值必须为布尔值")
            if kind == "heroes":
                for key in ("baseStats", "growth", "skills", "presentation", "progression"):
                    if key in row:
                        object_value(row[key], path + "." + key)
                for key in ("baseStats", "growth"):
                    numeric_fields(row.get(key, {}), STATS, path + "." + key)
                integer_fields(row, ("quality", "speed", "attackRange", "leadership", "levelCap"), path)
                text_fields(row.get("progression", {}), ("preset", "starUp"), path + ".progression", ("starUp",))
                for key in ("skills", "presentation"):
                    for field_name, value in row.get(key, {}).items():
                        if value is not None and not isinstance(value, str):
                            error(path + "." + key + "." + field_name, "引用必须为文本或空值")
            elif kind == "skills":
                if row.get('model')=='native-template-v1':
                    object_value(row.get('nativeTemplate'),path+'.nativeTemplate')
                    object_value(row['nativeTemplate'].get('settings'),path+'.nativeTemplate.settings')
                    for action in rows_value(row,'actions',path):
                        if not isinstance(action.get('arguments'),list):error(path+'.actions','原生动作参数必须为数组')
                    continue
                integer_fields(row, ("warmup", "cooldown", "range", "maxLevel", "aoe"), path)
                if "banStand" in row and type(row["banStand"]) is not bool:
                    error(path + ".banStand", "开关值必须为布尔值")
                for action_index, action in enumerate(rows_value(row, "actions", path)):
                    action_path = path + ".actions[%d]" % action_index
                    text_fields(action, ("type", "damageType", "targetPolicy", "effect"), action_path, ("effect",))
                    numeric_fields(action, ("coefficient", "amount"), action_path)
                    integer_fields(action, ("duration", "maxTargets", "lockToAction", "distance"), action_path)
                    if "lockOnly" in action and type(action["lockOnly"]) is not bool:
                        error(action_path + ".lockOnly", "开关值必须为布尔值")
                for upgrade_index, upgrade in enumerate(rows_value(row, "upgrades", path)):
                    upgrade_path = path + ".upgrades[%d]" % upgrade_index
                    text_fields(upgrade, ("field",), upgrade_path)
                    integer_fields(upgrade, ("action",), upgrade_path)
                    numeric_fields(upgrade, ("perLevel",), upgrade_path)
            else:
                if "expect" in row:
                    object_value(row["expect"], path + ".expect")
                    text_fields(row["expect"], ("path", "sha256"), path + ".expect")
                for operation_index, operation in enumerate(rows_value(row, "operations", path)):
                    text_fields(operation, ("op", "path"), path + ".operations[%d]" % operation_index)


@lru_cache(maxsize=1)
def _default_base():
    from scripts.mod_tools import load_base
    return load_base(ROOT / "config/reconstruction/full-config.json")


def base_document(catalog=None):
    """Accept a UI catalog, a full document, or a raw cfg for headless use."""
    if catalog is None:
        return _default_base()
    value = catalog if isinstance(catalog, dict) else getattr(catalog, "base", None)
    if value is None:
        raise ModError("EditorCatalogMissing", "离线目录必须提供完整的 base 配置")
    if not isinstance(value, dict):
        raise ModError("EditorCatalogInvalid", "base 必须是配置对象")
    return value if "cfg" in value else {"cfg": value}


def _issue(error, severity="error"):
    if isinstance(error, ModError):
        return {"severity": severity, **error.as_dict()}
    return {"severity": severity, "code": "EditorFileError" if isinstance(error, OSError) else "EditorInvalidDraft",
            "path": "", "message": str(error)}


def _json_copy(value):
    # Besides detaching objects, this rejects NaN, cycles, and non-JSON values.
    return strict_json(canonical(value), PROJECT_JSON, max_bytes=PROJECT_JSON_LIMIT)


def _atomic_archive(path, payload, check):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ModError("EditorUnsafePath", "输出文件不能是符号链接", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "w+b") as stream:
            # Stored entries cannot trip the production compression-ratio guard
            # on legitimate repetitive JSON, and impose no decompression work.
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                for name, raw in sorted(payload.items()):
                    safe_path(name)
                    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    archive.writestr(info, raw)
            stream.flush()
            os.fsync(stream.fileno())
        if staged.stat().st_size > LIMITS["archiveBytes"]:
            raise ModError("ModTooLarge", "归档超过 64 MiB 限制", str(path))
        result = check(staged)
        os.replace(staged, path)
        return result
    finally:
        if staged.exists():
            staged.unlink()


def _read_project(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMITS["archiveBytes"]:
        raise ModError("EditorInvalidProject", "工程不存在、为符号链接或超过大小限制", str(path))
    contents = {}
    seen = set()
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > LIMITS["files"] + 1:
                raise ModError("EditorInvalidProject", "工程文件数量超限")
            for info in archive.infolist():
                safe_path(info.filename)
                if info.filename.casefold() in seen:
                    raise ModError("EditorInvalidProject", "工程存在重名文件", info.filename)
                seen.add(info.filename.casefold())
                mode = (info.external_attr >> 16) & 0o170000
                if info.is_dir() or mode not in (0, stat.S_IFREG) or info.flag_bits & 1:
                    raise ModError("EditorInvalidProject", "不允许目录、特殊文件或加密项", info.filename)
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ModError("EditorInvalidProject", "不支持此压缩格式", info.filename)
                if info.file_size > LIMITS["fileBytes"] or info.file_size > max(1, info.compress_size) * LIMITS["compressionRatio"]:
                    raise ModError("EditorInvalidProject", "工程文件大小或压缩比超限", info.filename)
                total += info.file_size
                if total > LIMITS["expandedBytes"]:
                    raise ModError("EditorInvalidProject", "工程展开大小超限")
                raw = archive.read(info)
                if len(raw) != info.file_size:
                    raise ModError("EditorInvalidProject", "工程文件长度错误", info.filename)
                contents[info.filename] = raw
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise ModError("EditorInvalidProject", "无法读取工程：" + str(error), str(path)) from error
    if PROJECT_JSON not in contents:
        raise ModError("EditorInvalidProject", "缺少 manifest/project.json")
    document = strict_json(contents.pop(PROJECT_JSON), PROJECT_JSON, max_bytes=PROJECT_JSON_LIMIT)
    if not isinstance(document, dict) or document.get("format") != PROJECT_FORMAT:
        raise ModError("EditorInvalidProject", "不支持的工程版本")
    required_keys = {"format", "manifest", "data", "metadata", "assets"}
    if not required_keys.issubset(document) or set(document) - required_keys - {"working"}:
        raise ModError("EditorInvalidProject", "工程结构错误")
    if not all(isinstance(document[key], dict) for key in ("manifest", "data", "metadata")) or not isinstance(document["assets"], list):
        raise ModError("EditorInvalidProject", "工程字段类型错误")
    if "working" in document and not isinstance(document["working"], list):
        raise ModError("EditorInvalidProject", "工程工作素材索引必须为数组")
    stores = {"assets": {}, "working": {}}
    used = set()
    for store in stores:
        for row in document.get(store, []):
            if (not isinstance(row, dict) or set(row) != {"path", "entry", "sha256"}
                    or not all(isinstance(row[key], str) for key in row)):
                raise ModError("EditorInvalidProject", "工程素材索引错误", store)
            # Draft names are not used as filesystem paths. Only actual archive
            # entries are used for I/O and independently validated above.
            name, entry = row["path"], row["entry"]
            if name in stores[store] or entry in used or entry not in contents or not entry.startswith(store + "/"):
                raise ModError("EditorInvalidProject", "工程素材重复或缺失", name)
            raw = contents[entry]
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ModError("EditorInvalidProject", "工程素材校验失败", name)
            stores[store][name] = raw
            used.add(entry)
    if used != set(contents):
        raise ModError("EditorInvalidProject", "工程包含未声明文件")
    _project_shape(document["manifest"], document["data"], document["metadata"])
    return document, stores["assets"], stores["working"]


def package_payloads(package):
    if package.payloads is not None:
        return dict(package.payloads)
    if package.path is None:
        raise ModError("EditorMissingDependency", "离线包缺少可读取的素材")
    root = Path(package.path)
    if root.is_file():
        return dict(inspect_package(root).payloads)
    result = {"manifest.json": canonical(package.manifest)}
    for row in package.manifest["files"]:
        safe_path(row["path"])
        source = root / row["path"]
        if source.is_symlink() or not source.resolve().is_relative_to(root.resolve()):
            raise ModError("EditorUnsafePath", "依赖包素材越出源目录", row["path"])
        result[row["path"]] = source.read_bytes()
    # Do not trust a cached Package if its files changed after selection.
    _inspect_payload(result)
    return result


def dependency_packages(catalog=None):
    """Read only explicit offline dependencies supplied by the editor catalog."""
    if catalog is None or isinstance(catalog, dict):
        return []
    sources = getattr(catalog, "package_paths", None)
    if sources is None:
        sources = getattr(catalog, "packages", ())
    if callable(sources):
        sources = sources()
    if isinstance(sources, dict):
        sources = sources.values()
    result = []
    for source in sources or ():
        if isinstance(source, Package):
            result.append(_inspect_payload(package_payloads(source)))
        else:
            result.append(inspect_package(source))
    return result


def compile_offline(packages, catalog=None, *, _capture_guard_base=False):
    """Compile explicit packages with only their required offline dependency closure."""
    selected = {package.package_id: package for package in packages}
    if len(selected) != len(packages):
        raise ModError("ModIdentityConflict", "同一 UUID 不能同时启用多个包")
    available = {}
    if any(package.manifest.get("dependencies") for package in packages):
        for package in dependency_packages(catalog):
            available.setdefault(package.package_id, []).append(package)
    visiting = set()
    done = set()
    def include(package, depth=0):
        from mod_schema import matches_version
        if depth > LIMITS["dependencyDepth"] or package.package_id in visiting:
            raise ModError("ModDependencyCycle", "离线依赖成环或超过深度限制", package.package_id)
        if package.package_id in done:
            return
        visiting.add(package.package_id)
        for dep in package.manifest.get("dependencies", []):
            other = selected.get(dep["packageId"])
            def matches(candidate):
                return matches_version(candidate.version, dep["version"]) and dep.get("digest", candidate.digest) == candidate.digest
            if other is None:
                options = {candidate.digest: candidate for candidate in available.get(dep["packageId"], []) if matches(candidate)}
                if len(options) != 1:
                    raise ModError("EditorMissingDependency", "请提供唯一匹配的离线依赖包：" + dep["packageId"], "manifest.dependencies")
                other = next(iter(options.values()))
                selected[other.package_id] = other
            if not matches(other):
                raise ModError("ModIncompatibleDependency", "离线依赖的版本或摘要不兼容", dep["packageId"])
            include(other, depth + 1)
        visiting.remove(package.package_id)
        done.add(package.package_id)
    for package in list(selected.values()):
        include(package)
    with tempfile.TemporaryDirectory(prefix="lal-editor-validate-") as directory:
        directory = Path(directory)
        storage = ModCatalog(directory / "catalog", base_document(catalog))
        settings = []
        for index, package in enumerate(sorted(selected.values(), key=lambda p: p.package_id)):
            archive = directory / ("package-%d.heropack" % index)
            payload = package_payloads(package)
            _atomic_archive(archive, payload, inspect_package)
            installed = storage.install(archive)
            settings.append({"packageId": package.package_id, "version": package.version,
                             "digest": installed["digest"], "enabled": True})
        roster = None if catalog is None or isinstance(catalog, dict) else getattr(catalog, "roster", None)
        if not _capture_guard_base:
            return storage.compile(base_document(catalog), {"packages": settings}, roster_side=roster, allow_missing=False)
        class GuardCompiler(Compiler):
            def patches(self):
                self.guard_base = copy.deepcopy(self.document)
                super().patches()
        compiler = GuardCompiler(storage, base_document(catalog), {"packages": settings}, roster, False)
        result = compiler.finish()
        result._guard_base = compiler.guard_base
        result._skill_identities = {sid: identity for identity, sid in storage.registry.get("skills", {}).items()
                                    if identity.startswith("mod:")}
        return result


def _unique_id(stem, existing):
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem)[:55]
    if not stem or not stem[0].isalpha() or not stem[0].isascii():
        stem = "item_" + stem
    candidate, index = stem, 2
    while candidate in existing:
        candidate = stem[:55] + "_" + str(index)
        index += 1
    return candidate


@dataclass
class Project:
    manifest: dict = field(default_factory=dict)
    data: dict = field(default_factory=lambda: {key: {key: []} for key in DATA_KINDS})
    assets: dict[str, bytes] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    working: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self):
        _project_shape(self.manifest, self.data, self.metadata)
        if not isinstance(self.working, dict) or any(not isinstance(key, str) or not isinstance(value, bytes)
                                                   for key, value in self.working.items()):
            raise ModError("EditorInvalidProject", "工程工作素材必须为文件名到 bytes 的映射", "working")
        for key in DATA_KINDS:
            self.data.setdefault(key, {key: []})
            self.data[key].setdefault(key, [])

    @property
    def kind(self):
        return "replace" if self.manifest.get("kind") == "patch" else "new"

    @classmethod
    def new(cls, kind="new", catalog=None):
        if kind not in ("new", "replace", "patch"):
            raise ModError("EditorInvalidKind", "请选择 new 或 replace 工程")
        manifest = {"format": FORMAT, "kind": "new" if kind == "new" else "patch",
                    "packageId": str(uuid.uuid4()), "name": "我的自制英雄" if kind == "new" else "我的英雄替换补丁",
                    "author": "", "version": "1.0.0", "engineApi": ENGINE_API,
                    "requiredCapabilities": [], "entrypoints": {}, "files": [], "dependencies": []}
        project = cls(manifest=manifest, metadata={"format": PROJECT_FORMAT})
        if kind == "new":
            project.add_hero(catalog=catalog)
        else:
            cfg = base_document(catalog)["cfg"]
            aid = "A_1001_5" if "A_1001_5" in cfg.get("avatar", {}) else next((key for key in sorted(cfg.get("avatar", {})) if key.startswith("A_1")), None)
            if aid is None:
                raise ModError("EditorMissingBuiltin", "离线目录中没有可替换的英雄")
            project.add_patch("builtin:avatar/" + aid, catalog=catalog)
        return project

    @classmethod
    def load(cls, path, catalog=None):
        if Path(path).suffix.lower() == ".heropack":
            return cls.import_package(path, catalog=catalog)
        document, assets, working = _read_project(path)
        return cls(document["manifest"], document["data"], assets, document["metadata"], working)

    @classmethod
    def import_package(cls, path, catalog=None):
        package = inspect_package(path, base_document(catalog))
        payload = package_payloads(package)
        excluded = {"manifest.json", *package.manifest["entrypoints"].values()}
        assets = {name: raw for name, raw in payload.items() if name not in excluded}
        return cls(copy.deepcopy(package.manifest), copy.deepcopy(package.data), assets,
                   {"format": PROJECT_FORMAT, "importedFrom": {"packageId": package.package_id,
                    "version": package.version, "digest": package.digest, "filename": Path(path).name}})

    def rows(self, kind):
        if kind not in DATA_KINDS:
            raise ModError("EditorInvalidEntity", "未知实体类型", str(kind))
        return self.data[kind][kind]

    def add_hero(self, catalog=None, source_aid=None):
        heroes = self.rows("heroes")
        hero = {"id": _unique_id("my_hero", {row.get("id") for row in heroes}), "variant": "quality5",
                "name": "我的自制英雄", "unitType": "hero", "quality": 5,
                "signType": "attack", "actionType": "forward", "damageType": "physical",
                "baseStats": {"health": 1200, "attack": 100, "physicalDefense": 60, "magicDefense": 40},
                "growth": {"health": 100, "attack": 8, "physicalDefense": 5, "magicDefense": 3},
                "speed": 245, "attackRange": 337, "leadership": 26, "levelCap": 99,
                "progression": {"preset": "builtin:progression/default-player-hero", "starUp": None},
                "skills": {"normal": "builtin:skill/S_201001_5", "captain": None, "passive": None},
                "presentation": {"portrait": "builtin:portrait/A_1001_5", "icon": "builtin:icon/A_1001_5",
                                 "basicAttackEffect": "builtin:effect/E_008", "voice": None}}
        if source_aid is not None:
            cfg = base_document(catalog)["cfg"]
            native = cfg.get("avatar", {}).get(source_aid)
            if not native or not str(source_aid).startswith("A_1"):
                raise ModError("EditorMissingBuiltin", "请选择已有的英雄作为模板", str(source_aid))
            pl, tl = native["pl"], native["tl"]
            hero.update(name=native.get("name", source_aid) + "（自制）", description=native.get("info", ""),
                        role=native.get("role", ""), quality=int(source_aid.rsplit("_", 1)[1]),
                        signType={1: "attack", 2: "tank", 3: "assist"}.get(tl[0], "attack"),
                        actionType={1: "forward", 2: "sly", 3: "stand", 4: "cunning"}.get(tl[1], "forward"),
                        damageType={1:'physical',2:'magic',3:'true'}[tl[2]], leadership=tl[3], levelCap=tl[4],
                        speed=pl[8], attackRange=pl[9])
            hero["variant"] = "quality" + str(hero["quality"])
            for index, key in enumerate(STATS):
                hero["baseStats"][key], hero["growth"][key] = pl[index * 2:index * 2 + 2]
            for key, index in (("normal", 10), ("captain", 11), ("passive", 13)):
                value = pl[index] if len(pl) > index else None
                hero["skills"][key] = "builtin:skill/" + value if value else None
            hero["presentation"].update(portrait="builtin:portrait/" + source_aid, icon="builtin:icon/" + source_aid,
                                        basicAttackEffect="builtin:effect/" + pl[12])
        heroes.append(hero)
        self.manifest["kind"] = "new"
        return hero

    def add_skill(self):
        skills = self.rows("skills")
        skill = {"id": _unique_id("my_skill", {row.get("id") for row in skills}), "name": "我的技能",
                 "description": "对前方一个敌人造成物理伤害。", "timingUnit": "ownerTurns", "warmup": 1,
                 "cooldown": 3, "range": 1500, "targetPolicy": "enemy_lane_frontmost", "maxLevel": 10,
                 "actions": [{"type": "damage", "coefficient": 1.2, "damageType": "physical", "effect": "builtin:effect/E_008"}],
                 "upgrades": [{"action": 0, "field": "coefficient", "perLevel": 0.1}]}
        skills.append(skill)
        return skill

    def add_patch(self, target, catalog=None):
        if isinstance(target, str) and target.startswith("A_"):
            target = "builtin:avatar/" + target
        if not isinstance(target, str):
            raise ModError("EditorInvalidTarget", "补丁目标必须是显式英雄引用")
        if target.startswith(("builtin:avatar/", "builtin:hero/")):
            aid = target.split("/", 1)[1]
            cfg = base_document(catalog)
            expected = {"path": "name", "sha256": target_digest(cfg, aid, "name")}
            name = cfg["cfg"]["avatar"][aid].get("name", aid)
        elif target.startswith("self:hero/"):
            local = target[len("self:hero/"):]
            source = next((row for row in self.rows("heroes") if row.get("id", "") + "/" + row.get("variant", "") == local), None)
            if source is None:
                raise ModError("EditorInvalidTarget", "找不到本工程目标英雄", target)
            name = source["name"]
            expected = {"path": "name", "value": name}
        else:
            raise ModError("EditorInvalidTarget", "新建补丁请选择内置或本工程英雄；外部补丁可通过导入编辑", target)
        patches = self.rows("patches")
        patch = {"id": _unique_id("replace_hero", {row.get("id") for row in patches}), "target": target,
                 "expect": expected, "operations": [{"op": "replace", "path": "name", "value": name}],
                 "patchScopes": {key: True for key in SCOPES}}
        patches.append(patch)
        return patch

    def _patch_view(self, patch, catalog=None):
        """Real prepatch scope definitions plus immutable production baseline."""
        target = patch.get("target", "")
        existing = self.rows("patches")
        position = next((index for index, row in enumerate(existing) if row is patch), None)
        if position is None:
            position = next((index for index, row in enumerate(existing) if row.get("id") == patch.get("id")), len(existing))
        prior = existing[:position]
        if not self.manifest.get("dependencies") and not prior and target.startswith(("builtin:avatar/", "builtin:hero/")):
            base = base_document(catalog)
            return {"document": base, "base": base, "aid": target.split("/", 1)[1],
                    "runtime": {}, "patches": [], "skills": {}}
        draft = Project(copy.deepcopy(self.manifest), copy.deepcopy(self.data), dict(self.assets), {})
        draft.data["patches"] = {"patches": copy.deepcopy(prior)}
        if draft.rows("heroes"):
            draft.manifest["kind"] = "new"
        elif not prior:
            # A structurally valid, all-scopes-disabled sentinel lets the real
            # compiler resolve dependencies/private skills without applying an
            # authored patch or weakening production schema rules.
            baseline = base_document(catalog)["cfg"]
            aid = next((key for key in sorted(baseline.get("avatar", {})) if key.startswith("A_1")), None)
            if aid is None:
                raise ModError("EditorMissingBuiltin", "没有可用于离线解析的内置英雄")
            draft.manifest["kind"] = "patch"
            draft.data["patches"]["patches"] = [{"id": "editor_guard_probe", "target": "builtin:avatar/" + aid,
                "expect": {"path": "name", "sha256": target_digest(base_document(catalog), aid, "name")},
                "operations": [{"op": "replace", "path": "name", "value": baseline["avatar"][aid].get("name", aid)}],
                "patchScopes": {scope: False for scope in SCOPES}}]
        _, _, payload = draft._payload()
        compiled = compile_offline([_inspect_payload(payload)], catalog, _capture_guard_base=True)
        if target.startswith(("builtin:avatar/", "builtin:hero/")):
            aid = target.split("/", 1)[1]
        else:
            if target.startswith(("self:hero/", "self:avatar/")):
                identity = "mod:" + self.manifest["packageId"] + "/hero/" + target.split("/", 1)[1]
            elif target.startswith("mod:"):
                parts = target[4:].split("/", 2)
                if len(parts) != 3 or parts[1] not in ("hero", "avatar"):
                    raise ModError("EditorInvalidTarget", "不支持的补丁目标", target)
                identity = "mod:" + parts[0] + "/hero/" + parts[2]
            else:
                raise ModError("EditorInvalidTarget", "请选择显式英雄引用", target)
            aid = next((key for key, row in compiled.runtime["heroes"].items() if row.get("identity") == identity), None)
            if aid is None:
                raise ModError("ModMissingReference", "找不到补丁目标英雄", target)
        return {"document": compiled.document, "base": compiled._guard_base, "aid": aid,
                "runtime": compiled.runtime, "patches": compiled.preview["patches"], "skills": compiled._skill_identities}

    def _patch_value(self, patch, path, context, *, primary=False):
        from mod_schema import PATCH_PATHS, boolean_map
        if path not in PATCH_PATHS:
            raise ModError("ModInvalidPackage", "此字段不支持补丁修改", str(path))
        boolean_map(patch.get("patchScopes", {}), SCOPES, "patch.patchScopes")
        scopes = [scope for scope in SCOPES if patch.get("patchScopes", {}).get(scope, True)]
        if not scopes:
            raise ModError("EditorPatchScopeDisabled", "请至少启用一个补丁作用域，再自动生成或刷新契约", path)
        values = []
        aid = context["aid"]
        for scope in scopes:
            # Production primary expectations use the immutable definition when
            # no dependency has written this target/scope; operation expectations
            # always use the actual intermediate definition.
            dependency_write = any(row["target"] == aid and row["scope"] == scope
                and row["packageId"] != self.manifest["packageId"] for row in context["patches"])
            immutable = primary and not dependency_write
            document = context["base"] if immutable else context["document"]
            cfg = document.get("cfg", document)
            definition = aid if immutable else context["runtime"].get("scopedAvatarIds", {}).get(scope, {}).get(aid, aid)
            if definition not in cfg.get("avatar", {}):
                raise ModError("ModMissingReference", "找不到补丁目标英雄", str(aid))
            compiler = Compiler.__new__(Compiler)
            compiler.cfg = cfg
            values.append(copy.deepcopy(compiler.logical(cfg["avatar"][definition], path)))
        if any(canonical(value) != canonical(values[0]) for value in values[1:]):
            raise ModError("EditorAmbiguousPatchScope", "所选作用域的原值不同，无法生成一个准确的公共契约；请分别创建单一作用域补丁", path)
        return values[0]

    @staticmethod
    def _whole_skill_path(path):
        return isinstance(path, str) and path.startswith("skills.") and path.count(".") == 1

    def _private_skill_reference(self, value, context, path, catalog=None):
        if not isinstance(value, dict) or value.get("id") in base_document(catalog)["cfg"].get("skill", {}):
            return None
        identity = context["skills"].get(value.get("id"))
        if identity is None:
            raise ModError("EditorNonportableGuard", "此技能由其他补丁派生，没有可移植的公开注册引用；请改用具体字段补丁或选择原始注册技能", path)
        owner, kind, local = identity[len("mod:"):].split("/", 2)
        if owner == self.manifest["packageId"]:
            return "self:skill/" + local
        if not any(dep["packageId"] == owner for dep in self.manifest.get("dependencies", [])):
            raise ModError("EditorGuardDependency", "此技能属于传递依赖；请先显式声明该包为直接依赖，才能使用其技能注册引用", path)
        return "mod:" + owner + "/skill/" + local

    def _finish_guards(self, updated, context, catalog=None, *, refresh=False, editing_path=None):
        from mod_schema import PATCH_PATHS, digest
        originals = {}
        private = {}
        for operation in updated.get("operations", []):
            path = operation.get("path")
            originals[path] = self._patch_value(updated, path, context)
            if self._whole_skill_path(path):
                reference = self._private_skill_reference(originals[path], context, path, catalog)
                if reference is not None:
                    private[path] = reference
            if refresh:
                operation["expect"] = copy.deepcopy(originals[path])
        old = updated.get("expect", {})
        old_path = old.get("path")
        if self._whole_skill_path(old_path):
            original = self._patch_value(updated, old_path, context, primary=True)
            reference = self._private_skill_reference(original, context, old_path, catalog)
            if reference is not None:
                private[old_path] = reference
        if len(private) > 1:
            raise ModError("EditorPrivateGuardLimit", "API 1 一个补丁只能表达一个私有整技能槽契约；请将多个私有槽拆成不同补丁", "patch.expect")
        if private:
            path, reference = next(iter(private.items()))
            primary_value = self._patch_value(updated, path, context, primary=True)
            primary_reference = self._private_skill_reference(primary_value, context, path, catalog)
            if primary_reference != reference:
                raise ModError("EditorNonportableGuard", "主契约和实际技能绑定不同，无法生成可移植的整槽补丁", path)
            if old_path and old_path != path:
                guarded_operation = next((operation for operation in updated["operations"] if operation["path"] == old_path), None)
                if guarded_operation is None:
                    raise ModError("EditorPrivateGuardLimit", "已有主契约保护了其他未修改字段，API 1 无法同时保留；请用 add_slot_patch 新建仅保护此私有技能槽的补丁", old_path)
                original = self._patch_value(updated, old_path, context, primary=True)
                if not refresh:
                    if "sha256" in old:
                        matches = digest(original) == old["sha256"]
                    elif self._whole_skill_path(old_path) and isinstance(old.get("value"), str) and isinstance(original, dict):
                        wanted = old["value"]
                        if wanted.startswith("builtin:skill/"):
                            matches = original.get("id") == wanted[len("builtin:skill/"):]
                        else:
                            identity = "mod:" + self.manifest["packageId"] + "/" + wanted[len("self:"):] if wanted.startswith("self:skill/") else wanted
                            matches = context["skills"].get(original.get("id")) == identity
                    else:
                        matches = canonical(original) == canonical(old.get("value"))
                    if not matches:
                        raise ModError("EditorStaleGuard", "已有契约与目标不符，已保留原补丁；请明确刷新契约后重试", old_path)
                if refresh or "expect" not in guarded_operation:
                    guarded_operation["expect"] = copy.deepcopy(original)
            if old_path == path and not refresh and "value" in old and isinstance(old["value"], str):
                # Preserve an imported semantic guard, including a stale one.
                primary_guard = copy.deepcopy(old)
            elif old_path == path and not refresh and old:
                raise ModError("EditorNonportableGuard", "此私有技能契约含旧运行时编号，请明确刷新契约以转换为注册引用", path)
            else:
                primary_guard = {"path": path, "value": reference}
            updated["expect"] = primary_guard
            for operation in updated["operations"]:
                if operation["path"] == path:
                    # Same logical unit remains guarded by the resolvable
                    # primary reference; never persist temporary native IDs.
                    operation.pop("expect", None)
        elif refresh or not old:
            path = old_path if old_path in PATCH_PATHS else editing_path or next((operation["path"] for operation in updated.get("operations", [])), "name")
            updated["expect"] = {"path": path, "sha256": digest(self._patch_value(updated, path, context, primary=True))}
        return updated

    def patch_original(self, patch, path, catalog=None):
        return self._patch_value(patch, path, self._patch_view(patch, catalog))

    def set_patch_field(self, patch, path, value=None, op="replace", catalog=None):
        from mod_schema import NULLABLE_PATHS, PATCH_PATHS
        if path not in PATCH_PATHS or op not in ("replace", "set", "clear"):
            raise ModError("ModInvalidPackage", "不支持的补丁字段或操作", str(path))
        if op == "clear" and path not in NULLABLE_PATHS:
            raise ModError("ModInvalidPackage", "只有可选技能与语音可以清除", path)
        if op != "clear" and value is None:
            raise ModError("ModInvalidPackage", "替换值不能为空；清除可选字段请使用 clear", path)
        existing = patch.get("operations", [])
        for operation in existing:
            other = operation.get("path", "")
            if other != path and (other.startswith(path + ".") or path.startswith(other + ".")):
                raise ModError("ModPatchConflict", "不能同时替换整个技能槽和其子字段", path)
        context = self._patch_view(patch, catalog)
        original = self._patch_value(patch, path, context)
        operation = {"op": op, "path": path, "expect": original}
        if op != "clear":
            operation["value"] = copy.deepcopy(value)
        changed = [copy.deepcopy(row) for row in existing]
        index = next((i for i, row in enumerate(changed) if row.get("path") == path), None)
        if index is None:
            changed.append(operation)
        else:
            if "expect" in changed[index]:
                operation["expect"] = copy.deepcopy(changed[index]["expect"])
            changed[index] = operation
        updated = copy.deepcopy(patch)
        updated["operations"] = changed
        updated = self._finish_guards(updated, context, catalog, editing_path=path)
        patch.clear()
        patch.update(updated)
        return patch["operations"][len(changed) - 1 if index is None else index]

    def refresh_patch_guards(self, patch, catalog=None):
        updated = self._finish_guards(copy.deepcopy(patch), self._patch_view(patch, catalog), catalog, refresh=True)
        patch.clear()
        patch.update(updated)
        return patch

    def add_slot_patch(self, target, slot, replacement=None, *, op="replace", patch_scopes=None, catalog=None):
        """Single-slot workflow with a portable guard for a registered skill."""
        if slot not in ("normal", "captain", "passive"):
            raise ModError("ModInvalidPackage", "请选择 normal/captain/passive 技能槽", str(slot))
        if isinstance(target, str) and target.startswith("A_"):
            target = "builtin:avatar/" + target
        patch = {"id": _unique_id("replace_slot", {row.get("id") for row in self.rows("patches")}),
                 "target": target, "operations": [],
                 "patchScopes": {scope: True for scope in SCOPES} if patch_scopes is None else copy.deepcopy(patch_scopes)}
        self.set_patch_field(patch, "skills." + slot, replacement, op=op, catalog=catalog)
        self.rows("patches").append(patch)
        return patch

    def remove(self, kind, index):
        """Remove an entity; dangling references remain visible validation errors."""
        return self.rows(kind).pop(index)

    def rename(self, kind, index, new_id, new_variant=None):
        """Rename an entity atomically, preserving row objects bound by the UI.

        A hero id identifies its whole progression family: changing it renames
        every quality in that family. ``new_variant`` affects only the selected
        row. Plain author text and source provenance are never rewritten.
        """
        from mod_schema import local_id
        kind = {"hero": "heroes", "skill": "skills", "patch": "patches"}.get(kind, kind)
        rows = self.rows(kind)
        if type(index) is not int or not 0 <= index < len(rows):
            raise ModError("EditorInvalidIndex", "实体位置越界")
        local_id(new_id, kind + ".id")
        if new_variant is not None:
            if kind != "heroes":
                raise ModError("EditorInvalidEntity", "只有英雄具有 variant")
            local_id(new_variant, "heroes.variant")
        selected = rows[index]
        if not isinstance(selected, dict):
            raise ModError("EditorInvalidDraft", "实体必须是对象", kind)
        old_id = selected.get("id")
        if kind == "heroes" and new_id != old_id and any(isinstance(row, dict) and row.get("id") == new_id for row in rows):
            raise ModError("EditorDuplicateId", "目标英雄家族 ID 已存在，不能通过重命名合并两个家族", new_id)
        candidate = copy.deepcopy(self.data)
        changed = candidate[kind][kind]
        hero_map = {}
        skill_map = {}
        if kind == "heroes":
            for position, row in enumerate(changed):
                if not isinstance(row, dict):
                    raise ModError("EditorInvalidDraft", "英雄必须是对象", "heroes[%d]" % position)
                if row.get("id") == old_id:
                    old_variant = row.get("variant")
                    row["id"] = new_id
                    if position == index and new_variant is not None:
                        row["variant"] = new_variant
                    if isinstance(old_id, str) and isinstance(old_variant, str):
                        hero_map[(old_id, old_variant)] = (new_id, row.get("variant"))
        else:
            changed[index]["id"] = new_id
            if kind == "skills" and isinstance(old_id, str):
                if sum(isinstance(row, dict) and row.get("id") == old_id for row in rows) != 1:
                    raise ModError("EditorDuplicateId", "旧技能 ID 已重名，不能确定引用指向哪个技能", str(old_id))
                skill_map[old_id] = new_id
        seen = set()
        for position, row in enumerate(changed):
            if not isinstance(row, dict):
                raise ModError("EditorInvalidDraft", "实体必须是对象", "%s[%d]" % (kind, position))
            key = (row.get("id"), row.get("variant")) if kind == "heroes" else row.get("id")
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError as error:
                raise ModError("EditorInvalidDraft", "实体 ID 必须是文本", kind) from error
            if duplicate:
                raise ModError("EditorDuplicateId", "重命名后 ID 或英雄变体重复", str(key))

        def reference(value):
            if not isinstance(value, str):
                return value
            if value.startswith("self:skill/"):
                local = value[len("self:skill/"):]
                return "self:skill/" + skill_map.get(local, local)
            for prefix in ("self:hero/", "self:avatar/"):
                if value.startswith(prefix):
                    parts = value[len(prefix):].split("/")
                    if len(parts) == 2 and tuple(parts) in hero_map:
                        identity = hero_map[tuple(parts)]
                        if all(isinstance(part, str) for part in identity):
                            return prefix + "/".join(identity)
            return value

        for hero in candidate.get("heroes", {}).get("heroes", []):
            if not isinstance(hero, dict):
                continue
            if isinstance(hero.get("skills"), dict):
                for key in hero["skills"]:
                    hero["skills"][key] = reference(hero["skills"][key])
            if isinstance(hero.get("progression"), dict):
                hero["progression"]["starUp"] = reference(hero["progression"].get("starUp"))
        for patch in candidate.get("patches", {}).get("patches", []):
            if not isinstance(patch, dict):
                continue
            patch["target"] = reference(patch.get("target"))
            expected = patch.get("expect")
            if isinstance(expected, dict) and isinstance(expected.get("path"), str) and expected["path"].startswith("skills.") and expected["path"].count(".") == 1 and "value" in expected:
                expected["value"] = reference(expected["value"])
            for operation in patch.get("operations", []):
                if not isinstance(operation, dict):
                    continue
                path = operation.get("path", "")
                if isinstance(path, str) and path.startswith("skills.") and path.count(".") == 1 and "value" in operation:
                    operation["value"] = reference(operation["value"])
        # All checks and rewrites succeeded. Retain every existing row dict and
        # row list so selections/forms do not keep detached stale objects.
        for entity_kind in DATA_KINDS:
            actual_rows = self.rows(entity_kind)
            for actual, updated in zip(actual_rows, candidate[entity_kind][entity_kind]):
                if isinstance(actual, dict) and isinstance(updated, dict):
                    actual.clear()
                    actual.update(updated)
        return rows[index]

    def reorder(self, kind, index, new_index):
        rows = self.rows(kind)
        if not 0 <= index < len(rows) or not 0 <= new_index < len(rows):
            raise ModError("EditorInvalidIndex", "实体位置越界")
        rows.insert(new_index, rows.pop(index))

    @staticmethod
    def reorder_actions(skill, index, new_index):
        actions = skill["actions"]
        if type(index) is not int or type(new_index) is not int or not 0 <= index < len(actions) or not 0 <= new_index < len(actions):
            raise ModError("EditorInvalidIndex", "动作位置越界")
        order = list(range(len(actions)))
        order.insert(new_index, order.pop(index))
        if skill.get('model')=='native-template-v1':
            from mod_native import reorder_actions
            return reorder_actions(skill,order)
        mapping = {old: new for new, old in enumerate(order)}
        changed = copy.deepcopy(skill)
        changed["actions"] = [changed["actions"][old] for old in order]
        for position, action in enumerate(changed["actions"]):
            if "lockToAction" in action:
                old = action["lockToAction"]
                if type(old) is not int or old not in mapping or mapping[old] >= position:
                    raise ModError("EditorActionOrder", "重排会导致动作锁定引用自身或后续动作；请先解除锁定")
                action["lockToAction"] = mapping[old]
        for upgrade in changed.get("upgrades", []):
            if type(upgrade.get("action")) is not int or upgrade["action"] not in mapping:
                raise ModError("EditorActionOrder", "升级路径引用了不存在的动作")
            upgrade["action"] = mapping[upgrade["action"]]
        if changed.get("rankInfoTemplate"):
            changed["rankInfoTemplate"] = re.sub(r"\{(rank|flat):(\d+):", lambda m:
                '{' + m[1] + ':' + str(mapping[int(m[2])]) + ':', changed["rankInfoTemplate"])
        skill.clear()
        skill.update(changed)

    @staticmethod
    def remove_action(skill, index):
        if skill.get('model')=='native-template-v1':
            from mod_native import remove_action
            return remove_action(skill,index)
        actions = skill["actions"]
        if type(index) is not int or not 0 <= index < len(actions):
            raise ModError("EditorInvalidIndex", "动作位置越界")
        if (any(action.get("lockToAction") == index for action in actions) or
            any(upgrade.get("action") == index for upgrade in skill.get("upgrades", [])) or
            re.search(r"\{(?:rank|flat):" + str(index) + ":", skill.get("rankInfoTemplate", ""))):
            raise ModError("EditorActionInUse", "动作仍被锁定、升级路径或说明模板引用，请先移除对应引用")
        changed = copy.deepcopy(skill)
        changed["actions"].pop(index)
        for action in changed["actions"]:
            if isinstance(action.get("lockToAction"), int) and action["lockToAction"] > index:
                action["lockToAction"] -= 1
        for upgrade in changed.get("upgrades", []):
            if isinstance(upgrade.get("action"), int) and upgrade["action"] > index:
                upgrade["action"] -= 1
        if changed.get("rankInfoTemplate"):
            changed["rankInfoTemplate"] = re.sub(r"\{(rank|flat):(\d+):", lambda m:
                '{' + m[1] + ':' + str(int(m[2]) - (int(m[2]) > index)) + ':', changed["rankInfoTemplate"])
        skill.clear()
        skill.update(changed)

    def save(self, path):
        # No game schema checks here: incomplete names, references, actions and
        # properties must survive an ordinary Save/Load editing cycle.
        payload = {}
        descriptors = {"assets": [], "working": []}
        for store, mapping in (("assets", self.assets), ("working", self.working)):
            if not isinstance(mapping, dict) or not all(isinstance(name, str) and isinstance(raw, bytes) for name, raw in mapping.items()):
                raise ModError("EditorInvalidDraft", "素材必须为文件名到 bytes 的映射")
            for index, (name, raw) in enumerate(sorted(mapping.items())):
                if len(raw) > LIMITS["fileBytes"]:
                    raise ModError("ModTooLarge", "工程素材超过单文件大小限制", name)
                entry = store + "/%04d.bin" % index
                descriptors[store].append({"path": name, "entry": entry, "sha256": hashlib.sha256(raw).hexdigest()})
                payload[entry] = raw
        doc = {"format": PROJECT_FORMAT, "manifest": self.manifest, "data": self.data,
               "metadata": self.metadata, "assets": descriptors["assets"]}
        if descriptors["working"]:
            doc["working"] = descriptors["working"]
        payload[PROJECT_JSON] = canonical(_json_copy(doc))
        _atomic_archive(path, payload, _read_project)
        return Path(path)

    @staticmethod
    def _image_edit_keys(record):
        if not isinstance(record, dict):
            return set()
        return {record[key] for key in ("sourceKey", "foregroundKey", "clipKey")
                if isinstance(record.get(key), str)}

    def store_image_edit(self, asset_path, source, recipe, foreground=None, clip=None):
        """Atomically retain original image, optional layers and editable recipe.

        All bytes live in ``working`` and are intentionally ignored by game
        validation/export. Only the caller's rendered result belongs in assets.
        """
        if not isinstance(asset_path, str) or not asset_path:
            raise ModError("EditorImageEditInvalid", "图片编辑目标必须是非空素材名")
        for role, value in (("source", source), ("foreground", foreground), ("clip", clip)):
            if value is None and role != "source":
                continue
            if not isinstance(value, bytes):
                raise ModError("EditorImageEditInvalid", "图片工作素材必须为 bytes", role)
            if len(value) > LIMITS["fileBytes"]:
                raise ModError("ModTooLarge", "图片工作素材超过 32 MiB 单文件限制", role)
        if not isinstance(recipe, dict):
            raise ModError("EditorImageEditInvalid", "图片编辑配方必须为对象", "recipe")
        # Prepare every validation/copy before publishing either metadata or
        # work bytes; a bad recipe cannot leave half an editable image behind.
        try:
            saved_recipe = _json_copy(recipe)
            metadata = _json_copy(self.metadata)
        except (TypeError, ValueError, RecursionError) as error:
            if isinstance(error, ModError):
                raise
            raise ModError("EditorImageEditInvalid", "图片编辑配方必须为有限、可序列化的 JSON", "recipe") from error
        edits = metadata.get("imageEdits", {})
        if not isinstance(edits, dict):
            raise ModError("EditorImageEditInvalid", "图片编辑记录必须为对象", "metadata.imageEdits")
        if not isinstance(self.working, dict) or any(not isinstance(key, str) or not isinstance(value, bytes) for key, value in self.working.items()):
            raise ModError("EditorImageEditInvalid", "工程工作素材必须为文件名到 bytes 的映射", "working")
        prefix = "image-edits/" + hashlib.sha256(asset_path.encode("utf-8")).hexdigest() + "/"
        record = {"version": 1, "sourceKey": prefix + "source.bin", "recipe": saved_recipe,
                  "foregroundKey": prefix + "foreground.bin" if foreground is not None else None,
                  "clipKey": prefix + "clip.bin" if clip is not None else None}
        other_keys = set().union(*(self._image_edit_keys(value) for key, value in edits.items() if key != asset_path))
        working = dict(self.working)
        for key in self._image_edit_keys(edits.get(asset_path)) - other_keys:
            working.pop(key, None)
        for role, raw, key in (("source", source, prefix + "source.bin"),
                              ("foreground", foreground, prefix + "foreground.bin"),
                              ("clip", clip, prefix + "clip.bin")):
            if key in other_keys:
                raise ModError("EditorImageEditInvalid", "工作素材被其他图片编辑记录共用，不能覆盖", key)
            if raw is None:
                working.pop(key, None)
            else:
                working[key] = raw
        if len(self.assets) + len(working) > LIMITS["files"]:
            raise ModError("ModTooLarge", "工程素材总文件数超过限制")
        if sum(len(raw) for raw in working.values()) + sum(len(raw) for raw in self.assets.values()) > LIMITS["expandedBytes"]:
            raise ModError("ModTooLarge", "工程素材总大小超过限制")
        edits[asset_path] = record
        metadata["imageEdits"] = edits
        _json_copy(metadata)
        self.metadata.clear()
        self.metadata.update(metadata)
        self.working.clear()
        self.working.update(working)
        return copy.deepcopy(record)

    def image_edit(self, asset_path):
        """Return detached recipe plus original/layer bytes, or None if absent."""
        edits = self.metadata.get("imageEdits", {})
        if not isinstance(edits, dict):
            raise ModError("EditorImageEditInvalid", "图片编辑记录必须为对象", "metadata.imageEdits")
        if asset_path not in edits:
            return None
        record = edits[asset_path]
        if (not isinstance(record, dict) or type(record.get("version")) is not int
                or record["version"] != 1 or not isinstance(record.get("recipe"), dict)):
            raise ModError("EditorImageEditInvalid", "不支持或损坏的图片编辑记录", str(asset_path))
        def read(key, optional=False):
            name = record.get(key)
            if name is None and optional:
                return None
            if not isinstance(name, str) or not isinstance(self.working.get(name), bytes):
                raise ModError("EditorImageEditInvalid", "图片编辑工作素材缺失", key)
            return self.working[name]
        return {"source": read("sourceKey"), "recipe": _json_copy(record["recipe"]),
                "foreground": read("foregroundKey", True), "clip": read("clipKey", True)}

    def remove_image_edit(self, asset_path):
        """Remove an edit record and its unshared working bytes; keep its asset."""
        edits = self.metadata.get("imageEdits", {})
        if not isinstance(edits, dict):
            raise ModError("EditorImageEditInvalid", "图片编辑记录必须为对象", "metadata.imageEdits")
        if asset_path not in edits:
            return False
        removed = self._image_edit_keys(edits[asset_path])
        remaining = {key: value for key, value in edits.items() if key != asset_path}
        other_keys = set().union(*(self._image_edit_keys(value) for value in remaining.values()))
        if remaining:
            self.metadata["imageEdits"] = remaining
        else:
            self.metadata.pop("imageEdits", None)
        for key in removed - other_keys:
            self.working.pop(key, None)
        return True

    def _payload(self):
        manifest = _json_copy(self.manifest)
        data = _json_copy(self.data)
        if not isinstance(manifest, dict) or not isinstance(data, dict):
            raise ModError("EditorInvalidDraft", "manifest 与 data 必须是对象")
        manifest.pop("signature", None)
        entrypoints = {}
        payload = {}
        asset_names = {name.casefold() for name in self.assets if isinstance(name, str)}
        main = "heroes" if manifest.get("kind") == "new" else "patches"
        for key, doc in data.items():
            if key not in DATA_KINDS:
                raise ModError("EditorInvalidDraft", "不支持的实体文档", str(key))
            if key == main or doc != {key: []}:
                name = key + ".json"
                index = 1
                while name.casefold() in asset_names:
                    name = "data/editor_" + key + "_%d.json" % index
                    index += 1
                payload[name] = canonical(doc)
                entrypoints[key] = name
        for name, raw in self.assets.items():
            safe_path(name)
            if name.casefold() in {key.casefold() for key in payload} | {"manifest.json"}:
                raise ModError("EditorPayloadCollision", "素材名与数据文件冲突", name)
            if not isinstance(raw, bytes):
                raise ModError("EditorInvalidDraft", "素材内容必须为 bytes", name)
            payload[name] = raw
        manifest["entrypoints"] = entrypoints
        manifest["files"] = [{"path": name, "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sorted(payload.items())]
        caps = set()
        if data.get("heroes", {}).get("heroes"):
            caps.update(("hero.register", "progression.default-player-hero"))
        if any(hero.get('damageType')=='true' for hero in data.get('heroes',{}).get('heroes',[])):
            caps.add('hero.damage.true')
        for patch in data.get("patches", {}).get("patches", []):
            for op in patch.get("operations", []):
                path = op.get("path", "")
                if path == 'damageType':caps.add('hero.patch.damage-type')
                caps.add("hero.patch." + ("skill" if path.startswith("skills.") else "presentation" if path.startswith("presentation.") else "text" if path in ("name", "description", "role") else "stats"))
            if patch.get("patchScopes"):
                caps.add("patch.scopes")
        for skill in data.get("skills", {}).get("skills", []):
            caps.update(skill_extension_capabilities(skill))
            if skill.get('model')=='native-template-v1':continue
            for action in skill.get("actions", []):
                if isinstance(action, dict) and isinstance(action.get("type"), str):
                    caps.add("skill." + action["type"])
        def references(value):
            if isinstance(value, str):
                if value.startswith("builtin:skill/"):
                    caps.add("skill.reference.builtin")
                if value.startswith("builtin:effect/"):
                    caps.add("effect.reference.builtin")
            elif isinstance(value, dict):
                for child in value.values():
                    references(child)
            elif isinstance(value, list):
                for child in value:
                    references(child)
        references(data)
        for name in self.assets:
            suffix = Path(name).suffix.lower()
            if suffix in (".png", ".jpg", ".jpeg"):
                caps.add("asset.image")
                from mod_packages import validate_media
                if validate_media(self.assets[name],name).get('cardFrame'):
                    caps.add('asset.image.card-frame')
            elif suffix in (".mp3", ".wav"):
                caps.add("asset.sound")
        manifest["requiredCapabilities"] = sorted(caps)
        payload["manifest.json"] = canonical(manifest)
        if len(payload) > LIMITS["files"] + 1 or sum(map(len, payload.values())) > LIMITS["expandedBytes"]:
            raise ModError("ModTooLarge", "包的文件数量或展开大小超过游戏限制")
        if any(len(raw) > LIMITS["fileBytes"] for raw in payload.values()):
            raise ModError("ModTooLarge", "包内单文件超过游戏限制")
        return manifest, data, payload

    def validate(self, catalog=None):
        issues = []
        def record(error):
            row = _issue(error)
            if row not in issues:
                issues.append(row)
        try:
            manifest, data, payload = self._payload()
        except (ModError, OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
            return [_issue(error)]
        try:
            validate_manifest(manifest)
        except ModError as error:
            record(error)
        for kind, validator in (("heroes", validate_hero), ("skills", validate_skill), ("patches", validate_patch)):
            rows = data.get(kind, {}).get(kind, []) if isinstance(data.get(kind, {}), dict) else None
            if not isinstance(rows, list):
                record(ModError("ModInvalidPackage", "实体表必须是数组", kind))
                continue
            for index, row in enumerate(rows):
                try:
                    validator(row, "%s[%d]" % (kind, index))
                except (ModError, TypeError, KeyError, AttributeError) as error:
                    record(error)
        try:
            validate_data(manifest, data)
        except (ModError, TypeError, KeyError, AttributeError) as error:
            record(error)
        if not issues:
            try:
                package = _inspect_payload(payload)
                compile_offline([package], catalog)
            except (ModError, OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
                record(error)
        return issues

    def export(self, path, catalog=None):
        errors = self.validate(catalog)
        if any(row["severity"] == "error" for row in errors):
            first = next(row for row in errors if row["severity"] == "error")
            error = ModError(first["code"], first["message"], first["path"])
            error.issues = errors
            raise error
        manifest, _, payload = self._payload()
        def check(staged):
            package = inspect_package(staged, base_document(catalog))
            result = package.metadata()
            result["validation"] = {"compiled": True, "engineApi": ENGINE_API}
            return result
        result = _atomic_archive(path, payload, check)
        # Commit generated fields only after successful publication.
        self.manifest.clear()
        self.manifest.update(manifest)
        return result
