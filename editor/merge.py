"""Conservative, identity-explicit merging of declarative hero packages."""
from __future__ import annotations

import copy
import hashlib
import re
import uuid
from pathlib import Path

from .core import (CHANNELS, ENGINE_API, FORMAT, SCOPES, Project, ModError,
                   _inspect_payload, base_document, compile_offline,
                   inspect_package, package_payloads)
from mod_schema import matches_version, safe_path, version


def _local_name(package_id, local):
    # Full UUID prefix prevents accidental reuse even when users deliberately
    # selected similar IDs. The suffix remains within the production 64 chars.
    prefix = "p" + package_id.replace("-", "") + "_"
    room = 64 - len(prefix)
    if len(local) > room:
        local = local[:room - 13] + "_" + hashlib.sha256(local.encode("utf-8")).hexdigest()[:12]
    return prefix + local


def _asset_name(package_id, local):
    name = "assets/p" + package_id.replace("-", "") + "/" + (local[7:] if local.startswith("assets/") else local)
    if len(name) > 240:
        name = "assets/p" + package_id.replace("-", "") + "/" + hashlib.sha256(local.encode("utf-8")).hexdigest() + Path(local).suffix.lower()
    safe_path(name)
    return name


def _terms(constraint):
    """Intersect the production version grammar without inventing a new one."""
    if constraint == "*":
        return []
    if constraint.startswith(("^", "~")):
        low = version(constraint[1:])
        if constraint[0] == "~":
            high = (low[0], low[1] + 1, 0)
        elif low[0]:
            high = (low[0] + 1, 0, 0)
        elif low[1]:
            high = (0, low[1] + 1, 0)
        else:
            high = (0, 0, low[2] + 1)
        return [">=" + ".".join(map(str, low)), "<" + ".".join(map(str, high))]
    return [term.strip() for term in constraint.split(",")]


def _ordered_sources(packages):
    by_id = {package.package_id: package for package in packages}
    result = []
    done = set()
    visiting = set()
    def visit(package):
        if package.package_id in done:
            return
        if package.package_id in visiting:
            raise ModError("ModDependencyCycle", "合并源的内部依赖成环", package.package_id)
        visiting.add(package.package_id)
        for dep in sorted(package.manifest.get("dependencies", []), key=lambda row: row["packageId"]):
            if dep["packageId"] in by_id:
                other = by_id[dep["packageId"]]
                if not matches_version(other.version, dep["version"]) or dep.get("digest", other.digest) != other.digest:
                    raise ModError("ModIncompatibleDependency", "所选源包不满足内部依赖的版本或摘要", package.package_id + " → " + other.package_id)
                visit(other)
        visiting.remove(package.package_id)
        done.add(package.package_id)
        result.append(package)
    for package in sorted(packages, key=lambda p: p.package_id):
        visit(package)
    return result


def _reject_overlapping_patches(patches):
    writes = []
    for patch in patches:
        scopes = {key: True for key in SCOPES}
        scopes.update(patch.get("patchScopes", {}))
        target = patch["target"].replace("builtin:hero/", "builtin:avatar/").replace("self:avatar/", "self:hero/")
        for operation in patch["operations"]:
            path = operation["path"]
            for other_target, other_path, other_scopes, other_id in writes:
                overlap = path == other_path or path.startswith(other_path + ".") or other_path.startswith(path + ".")
                if target == other_target and overlap and any(scopes[key] and other_scopes[key] for key in SCOPES):
                    error = ModError("ModMergePatchConflict", "补丁 %s 与 %s 在相同作用域重叠修改 %s；API 1 的单包不支持补丁覆盖链，请先整理成单个明确补丁" % (other_id, patch["id"], path), target)
                    error.conflict = {"target": target, "path": path, "patches": [other_id, patch["id"]]}
                    raise error
            writes.append((target, path, scopes, patch["id"]))


def merge_packages(paths, catalog=None, name="合并英雄包", author=""):
    """Merge only combinations verified against the real offline compiler.

    The new UUID is intentionally a different game identity. Source hero IDs,
    variants, skills, patch IDs and assets are all namespaced, all internal
    references are rewritten, and defaults are lowered to individual entities.
    Existing saves are not migrated by a merge.
    """
    paths = list(paths)
    if not paths:
        raise ModError("ModMergeEmpty", "请至少选择一个英雄包")
    if len(paths) > 128:
        raise ModError("ModQuotaExceeded", "一次最多选择 128 个英雄包")
    sources = {}
    duplicates = []
    for path in paths:
        package = inspect_package(path, base_document(catalog))
        old = sources.get(package.package_id)
        if old is not None:
            if old.version != package.version or old.digest != package.digest:
                raise ModError("ModMergeIdentityConflict", "同一个注册 UUID 出现不同版本或内容，请只选择明确的一版", package.package_id)
            duplicates.append({"filename": Path(path).name, "packageId": package.package_id, "digest": package.digest})
            continue
        sources[package.package_id] = package
    ordered = _ordered_sources(list(sources.values()))
    # This proves every original expectation, direct dependency, version/digest
    # contract, resource and overlap is valid *before* namespacing or absorption.
    compile_offline(ordered, catalog)

    mappings = {}
    assets = {}
    for package in ordered:
        payload = package_payloads(package)
        excluded = {"manifest.json", *package.manifest["entrypoints"].values()}
        mapping = {"heroes": {}, "variants": {}, "skills": {}, "patches": {}, "assets": {}}
        for hero in package.data.get("heroes", {}).get("heroes", []):
            mapping["heroes"][hero["id"]] = _local_name(package.package_id, hero["id"])
            mapping["variants"][hero["variant"]] = _local_name(package.package_id, hero["variant"])
        for kind in ("skills", "patches"):
            for entity in package.data.get(kind, {}).get(kind, []):
                mapping[kind][entity["id"]] = _local_name(package.package_id, entity["id"])
        for kind in ("heroes", "variants", "skills", "patches"):
            values = list(mapping[kind].values())
            if len(values) != len(set(values)):
                raise ModError("ModMergeNameCollision", "命名空间产生冲突，请先缩短本地 ID", package.package_id)
        for local, raw in payload.items():
            if local in excluded:
                continue
            target = _asset_name(package.package_id, local)
            if target.casefold() in {key.casefold() for key in assets}:
                raise ModError("ModMergeNameCollision", "素材命名空间冲突", target)
            mapping["assets"][local] = target
            assets[target] = raw
        mappings[package.package_id] = mapping

    def rewrite(value, owner):
        if not isinstance(value, str):
            return value
        match = re.fullmatch(r"self:([A-Za-z]+)/(.+)|mod:([0-9a-f-]+)/([A-Za-z]+)/(.+)", value)
        if match is None:
            return value
        if match.group(1):
            pid, kind, local = owner, match.group(1), match.group(2)
        else:
            pid, kind, local = match.group(3), match.group(4), match.group(5)
        if pid not in mappings:
            return value
        mapping = mappings[pid]
        if kind in ("hero", "avatar"):
            parts = local.split("/")
            if len(parts) != 2 or parts[0] not in mapping["heroes"] or parts[1] not in mapping["variants"]:
                raise ModError("ModMissingReference", "合并源中不存在此英雄变体", value)
            return "self:" + kind + "/" + mapping["heroes"][parts[0]] + "/" + mapping["variants"][parts[1]]
        if kind == "skill":
            if local not in mapping["skills"]:
                raise ModError("ModMissingReference", "合并源中不存在此技能", value)
            return "self:skill/" + mapping["skills"][local]
        if kind == "asset":
            local = local if local in mapping["assets"] else "assets/" + local
            if local not in mapping["assets"]:
                raise ModError("ModMissingReference", "合并源中不存在此素材", value)
            return "self:asset/" + mapping["assets"][local]
        raise ModError("ModMissingReference", "合并源使用未开放的私有引用类型", value)

    def rewrite_entity(original, kind, owner):
        # Rewrite only schema-defined references. Text that happens to equal a
        # reference (a skill description/name, for example) is still author text.
        entity = copy.deepcopy(original)
        if kind == "heroes":
            for key, value in entity["skills"].items():
                entity["skills"][key] = rewrite(value, owner)
            for key, value in entity["presentation"].items():
                entity["presentation"][key] = rewrite(value, owner)
            entity["progression"]["starUp"] = rewrite(entity["progression"]["starUp"], owner)
        elif kind == "skills":
            if entity.get('model') == 'effect-sequence-v1':
                for action in entity["actions"]:
                    for field in ("effect", "unit"):
                        if field in action:
                            action[field] = rewrite(action[field], owner)
            elif entity.get('model') != 'native-template-v1':
                for action in entity["actions"]:
                    action["effect"] = rewrite(action["effect"], owner)
        else:
            entity["target"] = rewrite(entity["target"], owner)
            expected = entity["expect"]
            if expected["path"].startswith("skills.") and expected["path"].count(".") == 1 and isinstance(expected.get("value"), str):
                expected["value"] = rewrite(expected["value"], owner)
            for operation in entity["operations"]:
                path = operation["path"]
                if "value" in operation and (path.startswith("presentation.") or (path.startswith("skills.") and path.count(".") == 1)):
                    operation["value"] = rewrite(operation["value"], owner)
        return entity

    data = {key: {key: []} for key in ("heroes", "skills", "patches")}
    dependencies = {}
    absorbed = []
    for package in ordered:
        mapping = mappings[package.package_id]
        for kind in data:
            for original in package.data.get(kind, {}).get(kind, []):
                entity = rewrite_entity(original, kind, package.package_id)
                entity["id"] = mapping[kind][original["id"]]
                if kind == "heroes":
                    entity["variant"] = mapping["variants"][original["variant"]]
                if kind in ("heroes", "patches"):
                    defaults = {key: True for key in CHANNELS}
                    defaults.update(package.manifest.get("integrationDefaults", {}))
                    defaults.update(original.get("integrationDefaults", {}))
                    entity["integrationDefaults"] = defaults
                if kind == "patches":
                    scopes = {key: True for key in SCOPES}
                    scopes.update(original.get("patchScopes", {}))
                    entity["patchScopes"] = scopes
                data[kind][kind].append(entity)
        for dep in package.manifest.get("dependencies", []):
            if dep["packageId"] in sources:
                absorbed.append({"from": package.package_id, **copy.deepcopy(dep)})
                continue
            prior = dependencies.get(dep["packageId"])
            if prior is None:
                dependencies[dep["packageId"]] = copy.deepcopy(dep)
            else:
                if prior.get("digest") and dep.get("digest") and prior["digest"] != dep["digest"]:
                    raise ModError("ModIncompatibleDependency", "源包需要同一外部依赖的不同内容", dep["packageId"])
                terms = list(dict.fromkeys(_terms(prior["version"]) + _terms(dep["version"])))
                prior["version"] = ",".join(terms) or "*"
                if "digest" in dep:
                    prior["digest"] = dep["digest"]
    _reject_overlapping_patches(data["patches"]["patches"])
    identity = str(uuid.uuid4())
    source_rows = [{"packageId": package.package_id, "version": package.version, "digest": package.digest,
                    "name": package.manifest["name"], "author": package.manifest["author"],
                    "sourceNotes": copy.deepcopy(package.manifest.get("sourceNotes"))} for package in ordered]
    identity_notice = "合并包使用新的注册 UUID 和英雄身份；不会继承原包英雄的存档身份，请保留原包以继续使用旧存档中的角色。"
    source_authors = list(dict.fromkeys(package.manifest["author"] for package in ordered))
    merged_author = author.strip() or "；".join(source_authors)
    if not author.strip() and len(merged_author) > 200:
        merged_author = "原包作者（完整名单见来源记录）"
    manifest = {"format": FORMAT, "kind": "new" if data["heroes"]["heroes"] else "patch", "packageId": identity,
                "name": name, "author": merged_author, "version": "1.0.0", "engineApi": ENGINE_API,
                "requiredCapabilities": [], "entrypoints": {}, "files": [],
                "dependencies": [dependencies[key] for key in sorted(dependencies)],
                "sourceNotes": {"kind": "merged-package", "identityNotice": identity_notice, "sources": copy.deepcopy(source_rows)}}
    report = {"packageId": identity, "sources": source_rows, "duplicates": duplicates,
              "absorbedDependencies": absorbed, "externalDependencies": copy.deepcopy(manifest["dependencies"]),
              "renamed": copy.deepcopy(mappings), "identityNotice": identity_notice,
              "counts": {key: len(doc[key]) for key, doc in data.items()}, "assetCount": len(assets), "warnings": []}
    project = Project(manifest, data, assets, {"merge": copy.deepcopy(report)})
    try:
        _, _, payload = project._payload()
        compile_offline([_inspect_payload(payload)], catalog)
    except ModError as error:
        wrapped = ModError("ModMergeIncompatible", "源包组合可启用，但合并为单包后无法保留当前补丁契约：" + error.message,
                           error.path)
        wrapped.cause = error.as_dict()
        wrapped.report = report
        raise wrapped from error
    report["compiled"] = True
    project.metadata["merge"]["compiled"] = True
    return project, report
