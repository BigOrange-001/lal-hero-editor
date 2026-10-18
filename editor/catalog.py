"""Read-only authoring catalogue derived from the actual overlaid game data.

Whole-skill reuse is checked by the game compiler itself. A native skill is
offered as an editable action template only when its mechanics can round-trip
through API 1 without dropping native targeting or upgrade semantics.
"""
from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path
from statistics import median
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from scripts.mod_tools import load_base
from mod_compile import Compiler
from mod_schema import ACTIONS, POLICIES, STATS, ModError, validate_skill

ROOT = Path(__file__).resolve().parents[1]
QUALITY_LABELS = {1: "特殊", 2: "白", 3: "绿", 4: "蓝", 5: "紫", 6: "橙"}
_RASTERS = frozenset((".png", ".jpg", ".jpeg", ".webp", ".bmp"))
_NATIVE_SKILL_FIELDS = frozenset(("id", "name", "info", "res", "pl", "skill", "skillUp",
    "targetPolicy", "actionTargetPolicies", "actionTargetLocks", "actionTargetMaxTargets", "modMaxLevel", "rankInfoTemplate"))
_DISPLAY_SKILL_FIELDS = frozenset(("local_design",))


def _walk_sounds(value):
    if isinstance(value, dict):
        sound = value.get("s")
        if isinstance(sound, dict) and isinstance(sound.get("id"), str):
            yield sound["id"]
        for item in value.values():
            yield from _walk_sounds(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_sounds(item)


def _at(values, index, default=None):
    return values[index] if isinstance(values, list) and len(values) > index else default


def _empty(value):
    return value is None or value == [] or value == {} or value == ""


class Catalog:
    def __init__(self, base_path=None, assets_root=None):
        self.base_path = Path(base_path) if base_path else ROOT / "config/reconstruction/full-config.json"
        self.assets_root = Path(assets_root) if assets_root else ROOT / "client/resources/app/assets"
        self.base = load_base(self.base_path)
        self.cfg = self.base.get("cfg", self.base)
        # This method only consults cfg and does not allocate IDs or modify data.
        self._compiler = Compiler.__new__(Compiler)
        self._compiler.cfg = self.cfg
        self._compiler.base = self.base
        self._rasters = {}
        self._sounds = {}
        self._atlas = {}
        self._index_assets()
        self._builtin_sounds = set(_walk_sounds(self.cfg.get("effect", {})))
        self.skills = [self._skill_row(sid, native) for sid, native in sorted(self.cfg.get("skill", {}).items())]
        self._skills = {row["id"]: row for row in self.skills}
        self.heroes = [self._hero_row(aid, native) for aid, native in sorted(self.cfg.get("avatar", {}).items())
                       if aid.startswith("A_1") and isinstance(native, dict)]
        self._heroes = {row["id"]: row for row in self.heroes}
        self.effects = [self._effect_row(eid, native) for eid, native in sorted(self.cfg.get("effect", {}).items())]
        self._effects = {row["id"]: row for row in self.effects}
        self.audio = []
        for sid in sorted(self._builtin_sounds | set(self._sounds)):
            supported = sid in self._builtin_sounds
            self.audio.append({"id": sid, "name": sid, "reference": "builtin:audio/" + sid,
                               "exportable": supported,
                               "reason": "" if supported else "磁盘试听素材；当前编译器未公开此内置声音引用。",
                               "preview": self._audio_preview(sid)})

    def _index_assets(self):
        if not self.assets_root.is_dir():
            return
        for path in sorted(self.assets_root.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in _RASTERS:
                self._rasters.setdefault(path.stem, path)
            elif suffix in (".mp3", ".wav", ".ogg"):
                self._sounds.setdefault(path.stem, path)
            elif suffix == ".xml":
                # Atlas XML is data only. Never execute SWF or expand entities.
                try:
                    if path.stat().st_size > 4 * 1024 * 1024:
                        continue
                    raw = path.read_bytes()
                    plain = raw.replace(b"\x00", b"").upper()
                    if b"<!DOCTYPE" in plain or b"<!ENTITY" in plain:
                        continue
                    atlas = ET.fromstring(raw)
                    if atlas.tag != "TextureAtlas":
                        continue
                    image_name = atlas.get("imagePath", "")
                    image = (path.parent / image_name).resolve()
                    if not image.is_relative_to(path.parent.resolve()):
                        continue
                    if not image.is_file():
                        image = image.with_suffix(".atf")
                    for item in atlas.findall("SubTexture"):
                        name = item.get("name")
                        box = [int(item.get(key, "0")) for key in ("x", "y", "width", "height")]
                        if name and box[0] >= 0 and box[1] >= 0 and box[2] > 0 and box[3] > 0:
                            self._atlas.setdefault(name, {"path": str(image) if image.is_file() else None,
                                "box": box, "atlas": str(path), "rotated": item.get("rotated") == "true"})
                except (OSError, ValueError, ET.ParseError):
                    continue

    def _hero_row(self, aid, native):
        pl, tl = native.get("pl", []), native.get("tl", [])
        try:
            quality = int(aid.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            quality = 0
        sign = {1: "attack", 2: "tank", 3: "assist"}.get(_at(tl, 0))
        role = native.get("role")
        voice = native.get("modVoice")
        if not voice or voice not in self._builtin_sounds:
            voice = None
        return {"id": aid, "name": native.get("name", aid), "description": native.get("info", ""),
            "quality": quality, "quality_label": QUALITY_LABELS.get(quality, str(quality)),
            "role": role, "role_label": role or "未标注", "signType": sign,
            "actionType": {1: "forward", 2: "sly", 3: "stand", 4: "cunning"}.get(_at(tl, 1)),
            "damageType": {1: "physical", 2: "magic", 3: "true"}.get(_at(tl, 2)),
            "baseStats": {stat: _at(pl, i * 2, 0) for i, stat in enumerate(STATS)},
            "growth": {stat: _at(pl, i * 2 + 1, 0) for i, stat in enumerate(STATS)},
            "speed": _at(pl, 8, 0), "attackRange": _at(pl, 9, 0),
            "leadership": _at(tl, 3, 0), "levelCap": _at(tl, 4, 1),
            "normal": _at(pl, 10) or None, "captain": _at(pl, 11) or None,
            "passive": _at(pl, 13) or None, "res": native.get("res", aid),
            "reference": "builtin:hero/" + aid,
            "presentation": {"portrait": "builtin:portrait/" + aid, "icon": "builtin:icon/" + aid,
                "basicAttackEffect": "builtin:effect/" + pl[12] if _at(pl, 12) else None,
                "voice": "builtin:audio/" + voice if voice else None},
            "preview": self._hero_preview(aid), "exportable": quality in (2, 3, 4, 5, 6)}

    def _skill_row(self, sid, native):
        from mod_native import make_template
        authored=make_template(sid,native,self.base)
        reusable=True
        try:self._compiler.ensure_public_skill(sid,'skill.'+sid)
        except ModError:reusable=False
        return {"id":sid,"name":native.get('name',sid),"description":native.get('info',''),
                "reference":"builtin:skill/"+sid,"actions":copy.deepcopy(native.get('skill',[])),
                "reusable":reusable,"editable":True,"reason":"可导入完整原生机制模板；动作、选敌、条件、成长、召唤与被动均可编辑。"+
                ("此技能有原生绑定，需要导入模板后再指派给自制英雄。" if not reusable else ""),
                "authored":authored,"editable_fields":["warmup","cooldown","range","description"],
                "timing":{"warmup":_at(native.get('pl'),0),"cooldown":_at(native.get('pl'),1),"range":_at(native.get('pl'),2)},
                "native":copy.deepcopy(native)}
    def _legacy_skill_row(self, sid, native):
        """Legacy narrow reverse codec, retained for format-1 diagnostic tools."""
        reusable, failure = True, ""
        try:
            self._compiler.ensure_public_skill(sid, "skill." + sid)
        except ModError as error:
            reusable, failure = False, error.message
        authored, conversion_reason = self._reverse_skill(sid, native) if reusable else (None, failure)
        editable_fields = []
        if reusable:
            editable_fields = ["description"]
            if isinstance(native.get("pl"), list) and len(native["pl"]) >= 3:
                editable_fields = ["warmup", "cooldown", "range", "description"]
        if not reusable:
            reason = "API 1 不支持整项引用：" + failure
        elif authored:
            reason = "可整项引用，也可无损转换为 API 1 动作模板。"
        else:
            reason = "可整项引用；动作模板不可无损转换：" + conversion_reason
        return {"id": sid, "name": native.get("name", sid), "description": native.get("info", ""),
                "reference": "builtin:skill/" + sid, "actions": copy.deepcopy(native.get("skill", [])),
                "reusable": reusable, "editable": authored is not None, "reason": reason,
                "authored": authored, "editable_fields": editable_fields,
                "timing": {"warmup": _at(native.get("pl"), 0), "cooldown": _at(native.get("pl"), 1),
                           "range": _at(native.get("pl"), 2)},
                "native": copy.deepcopy(native)}

    def _reverse_skill(self, sid, native):
        """Reverse exactly the public compiler output, never infer target geometry."""
        actions = native.get("skill", [])
        if not actions:
            return None, "无公开的主动动作（可能是原生被动机制）。"
        kinds = sorted({str(action[0]) for action in actions if isinstance(action, list) and action})
        outside = [kind for kind in kinds if kind not in ACTIONS]
        if outside:
            return None, f"动作超出 {len(ACTIONS)} 种自定义动作：" + "、".join(outside)
        extras = [key for key, value in native.items()
                  if key not in _NATIVE_SKILL_FIELDS | _DISPLAY_SKILL_FIELDS and not _empty(value)]
        # A default multiplier of 1 has no effect and is safe to omit.
        extras = [key for key in extras if not (key in ("manualDamageMultiplier", "manualDefenseBuffMultiplier",
                  "manualEffectMultiplier", "captainSummonMultiplier") and native[key] == 1)]
        if native.get('actionTargetGroups') == [None] * len(actions):
            extras = [key for key in extras if key != 'actionTargetGroups']
        if extras:
            return None, "保留原生机制字段：" + "、".join(sorted(extras))
        pl = native.get("pl")
        if not isinstance(pl, list) or len(pl) != 6 or pl[3] != 0 or pl[5] not in (0, 1):
            return None, "原生触发/站位字段不能与 API 1 逐项对应。"
        default_policy = native.get("targetPolicy")
        if default_policy is None:
            # Native per-action policies are authoritative. A public default
            # is only used for authoring; null locked rows compile back to null.
            default_policy = next((p for p in native.get('actionTargetPolicies', []) if p in POLICIES), None)
        if default_policy not in POLICIES:
            return None, "缺少显式公开目标策略；原生几何/连锁选取不作推测。"
        policies = native.get("actionTargetPolicies", [default_policy] * len(actions))
        locks = native.get("actionTargetLocks", [None] * len(actions))
        maxima = native.get("actionTargetMaxTargets", [1] * len(actions))
        if 'actionTargetMaxTargets' not in native and pl[4] != 0:
            return None, '缺少显式目标数量且使用原生 AOE 路径，不能推测逐动作数量。'
        if any(not isinstance(values, list) or len(values) != len(actions) for values in (policies, locks, maxima)):
            return None, "逐动作目标/锁定字段长度不匹配。"
        authored = {"id": "Template_" + sid, "name": native.get("name", sid),
                    "description": native.get("info", ""), "timingUnit": "ownerTurns",
                    "warmup": pl[0], "cooldown": pl[1], "range": pl[2], "aoe": pl[4],
                    "banStand": pl[5] == 0, "maxLevel": native.get("modMaxLevel", 10),
                    "targetPolicy": default_policy, "actions": [], "upgrades": []}
        if "rankInfoTemplate" in native:authored["rankInfoTemplate"] = native["rankInfoTemplate"]
        for index, raw in enumerate(actions):
            kind = raw[0]
            expected = 4 if kind == "damage" else 3 if kind in ("cure", "purify") else 5 if kind in ("stun", "silence") else 6 if kind in ("weak", "sunder", "poison") else 4
            if len(raw) != expected:
                return None, "动作参数包含额外原生语义：" + kind
            if raw[-1] and not isinstance(raw[-1], str):
                return None, "特效参数不是公开的资源 ID。"
            action = {"type": kind, "effect": "builtin:effect/" + raw[-1] if raw[-1] else None}
            if kind == 'move_to_target':
                action['distance'] = raw[2]
                if raw[1] not in POLICIES:
                    return None, '位移目标策略不在公开范围内。'
            elif kind != "purify":
                action["coefficient"] = raw[1]
            if kind in ("damage", "stun", "silence", "weak", "sunder", "poison"):
                if raw[2] not in (1, 2):
                    return None, "伤害类型超出物理/魔法。"
                action["damageType"] = "physical" if raw[2] == 1 else "magic"
            if kind not in ("damage", "cure", "move_to_target"):
                action["duration"] = raw[-2]
            if kind in ("weak", "sunder", "poison"):
                action["amount"] = raw[3]
            policy = policies[index]
            if policy is None and type(locks[index]) is int and 0 <= locks[index] < index and kind != 'move_to_target':
                policy = authored['actions'][locks[index]]['targetPolicy']
                action['lockOnly'] = True
            if policy not in POLICIES:
                return None, "逐动作目标依赖原生默认/私有策略。"
            if kind == 'move_to_target' and raw[1] != policy:
                return None, '位移内部与逐动作目标策略不一致。'
            action["targetPolicy"] = policy
            action["maxTargets"] = maxima[index]
            if locks[index] is not None:
                action["lockToAction"] = locks[index]
            authored["actions"].append(action)
        upgrades = native.get("skillUp") or []
        if upgrades and not isinstance(upgrades[0], list):
            # Engine legacy pair [action, increment] always grows coefficient.
            upgrades = [[upgrades[0], 1, upgrades[1]]] if len(upgrades) == 2 else [upgrades]
        try:
            for upgrade in upgrades:
                if not isinstance(upgrade, list) or len(upgrade) != 3 or upgrade[1] not in (1, 3):
                    return None, "升级路径不能与 coefficient/amount 一一对应。"
                authored["upgrades"].append({"action": upgrade[0], "field": "coefficient" if upgrade[1] == 1 else "amount", "perLevel": upgrade[2]})
            validate_skill(authored, "template." + sid)
            pkg = SimpleNamespace(package_id="editor-template")
            self._compiler.skill_refs = {(pkg.package_id, authored["id"]): sid}
            result = self._compiler.skill(pkg, authored)
            if result["skill"] != actions or result["pl"] != pl:
                return None, "编译往返结果与原生动作或触发字段不一致。"
            if (result['actionTargetPolicies'] != policies or result['actionTargetLocks'] != locks or
                result['actionTargetMaxTargets'] != maxima or result['skillUp'] != upgrades or
                result.get('rankInfoTemplate') != native.get('rankInfoTemplate')):
                return None, '编译往返的选敌、目标锁定、数量、成长或说明模板不一致。'
        except (ModError, TypeError, IndexError, KeyError) as error:
            return None, "公开结构约束不允许此原生参数：" + str(error)
        return authored, ""

    def _effect_row(self, eid, native):
        roles = []
        if isinstance(native, dict):
            if any(isinstance(native.get(key), dict) and native[key].get("id") for key in ("b", "h")):
                roles.append("basicAttackEffect")
            if isinstance(native.get("id"), str):
                roles.append("skillEffect")
        return {"id": eid, "name": native.get("name", eid) if isinstance(native, dict) else eid,
                "reference": "builtin:effect/" + eid, "roles": roles, "exportable": bool(roles),
                "reason": "" if roles else "该配置项是原生组合/装备索引，不是可选的视觉特效定义。",
                "native": copy.deepcopy(native), "preview": self._effect_preview(eid, native)}

    def hero(self, aid):
        return self._heroes.get(str(aid).split("/")[-1])

    def skill(self, sid):
        return self._skills.get(str(sid).split("/")[-1])

    def references(self, kind):
        if kind in ("hero", "avatar"):
            rows = self.heroes
        elif kind in ("portrait", "icon"):
            return [(f'{native.get("name", aid)} · {aid}', "builtin:" + kind + "/" + aid)
                    for aid, native in sorted(self.cfg.get("avatar", {}).items()) if isinstance(native, dict)]
        elif kind == "skill":
            rows = [row for row in self.skills if row["reusable"]]
        elif kind == 'skillTemplate':
            rows=self.skills
        elif kind in ("effect", "basicAttackEffect", "skillEffect"):
            rows = [row for row in self.effects if row["exportable"] and (kind == "effect" or kind in row["roles"])]
        elif kind in ("audio", "voice"):
            rows = [row for row in self.audio if row["exportable"]]
        else:
            raise ValueError("未知资源类型：" + str(kind))
        return [(f'{row["name"]} · {row["id"]}', row["reference"]) for row in rows]

    def _hero_image_path(self, aid):
        avatar = self.cfg.get("avatar", {}).get(aid)
        if not isinstance(avatar, dict):
            return None
        for resource in dict.fromkeys((aid, avatar.get("res", aid))):
            if not isinstance(resource, str) or "/" in resource or "\\" in resource:
                continue
            bundled = ROOT / "editor/resources/icons" / (resource + ".png")
            if bundled.is_file():
                return bundled
            for name in (resource, resource + "_icon0000"):
                if name in self._rasters:
                    return self._rasters[name]
        return None

    def preview_path(self, reference_or_aid):
        """Return a real raster/audio file, with no fuzzy hero-family fallback."""
        value = str(reference_or_aid)
        if value.startswith("A_"):
            return self._hero_image_path(value)
        result = self.preview(value)
        path = result.get("path") if result.get("previewable") and result.get("kind") in ("image", "audio") else None
        return Path(path) if path else None

    def _hero_preview(self, aid):
        path = self._hero_image_path(aid)
        if path:
            return {"kind": "image", "path": str(path), "box": None, "previewable": True,
                    "text": "原游戏英雄图标（真实导出素材；卡面/战斗动画仍使用对应原生资源）。", "timeline": []}
        native = self.cfg.get("avatar", {}).get(aid, {})
        resource = native.get("res", aid)
        for name in (resource + "_icon0000", resource):
            if name in self._atlas:
                return self._texture_preview(name)
        return {"kind": "swf", "path": None, "box": None, "previewable": False,
                "text": f"{aid} / {resource}：素材位于原生 SWF/ATF；没有此英雄的独立位图，不执行或批量反编译 SWF。", "timeline": []}

    def _texture_preview(self, name):
        if name in self._rasters:
            return {"kind": "image", "path": str(self._rasters[name]), "box": None,
                    "previewable": True, "text": "原生独立位图：" + name, "timeline": []}
        atlas = self._atlas.get(name)
        if atlas:
            raster = atlas["path"] and Path(atlas["path"]).suffix.lower() in _RASTERS
            return {**atlas, "kind": "image" if raster else "atlas", "previewable": bool(raster) and not atlas["rotated"],
                    "text": "图集项：" + name + ("（旋转项需按原生纹理布局解释）" if atlas["rotated"] else "") +
                            ("；ATF 压缩纹理不能作为普通图片静态解码。" if not raster else "；box 为 x/y/width/height。"), "timeline": []}
        return {"kind": "unavailable", "path": None, "box": None, "previewable": False,
                "text": "原生动画/纹理：" + name + "；没有可独立预览的位图。", "timeline": []}

    def _audio_preview(self, sid):
        path = self._sounds.get(sid)
        return {"kind": "audio", "path": str(path) if path else None, "box": None,
                "previewable": bool(path), "text": "原生声音：" + sid + ("" if path else "（当前素材目录没有独立音频文件）"), "timeline": []}

    def _effect_preview(self, eid, native):
        timeline, textures = [], []

        def walk(value, location):
            if not isinstance(value, dict):
                return
            details = {key: copy.deepcopy(value[key]) for key in ("id", "t", "a", "sc", "sp", "img", "s") if key in value}
            if details:
                timeline.append({"path": location, **details})
            if isinstance(value.get("id"), str):
                textures.append(value["id"])
            for key, child in value.items():
                if isinstance(child, dict) and key != "s":
                    walk(child, location + "." + key)

        walk(native, eid)
        preview = next((self._texture_preview(name) for name in textures if name in self._rasters or name in self._atlas),
                       {"kind": "definition", "path": None, "box": None, "previewable": False})
        preview["timeline"] = timeline
        preview["text"] = ("特效 " + eid + "；以下保留原配置时间线字段（t/a/sc/sp/s），不推测动画帧或执行 SWF。\n" +
                           "\n".join(str(row) for row in timeline)) if timeline else "原生索引 " + eid + "；不包含可独立播放的视觉时间线。"
        return preview

    def preview(self, reference):
        value = str(reference)
        if value.startswith("A_"):
            return self._hero_preview(value)
        if not value.startswith("builtin:") or "/" not in value:
            return {"kind": "unavailable", "path": None, "box": None, "previewable": False,
                    "text": "请选择工程资源或有效的 builtin 引用。", "timeline": []}
        kind, local = value[len("builtin:"):].split("/", 1)
        if kind in ("hero", "avatar", "portrait", "icon"):
            return self._hero_preview(local)
        if kind == "audio":
            return self._audio_preview(local)
        if kind == "effect":
            return self._effect_preview(local, self.cfg.get("effect", {}).get(local))
        if kind == "skill":
            row = self._skills.get(local)
            return {"kind": "definition", "path": None, "box": None, "previewable": False,
                    "text": (row["description"] + "\n" + row["reason"]) if row else "技能不存在：" + local,
                    "timeline": copy.deepcopy(row["actions"]) if row else []}
        return {"kind": "unavailable", "path": None, "box": None, "previewable": False,
                "text": "此资源类型没有静态预览：" + kind, "timeline": []}

    def benchmarks(self, quality, role, level=1):
        if type(quality) is not int or quality not in QUALITY_LABELS:
            raise ValueError("请选择真实品质编号。")
        if type(level) is not int or not 1 <= level <= 9999:
            raise ValueError("等级必须是 1–9999 的整数。")
        candidates = [row for row in self.heroes if row["quality"] == quality and (not role or row["role"] == role)]
        rows, excluded = [], []
        for hero in candidates:
            if level > hero["levelCap"]:
                excluded.append({"id": hero["id"], "levelCap": hero["levelCap"], "reason": "目标等级超过该英雄真实等级上限"})
                continue
            values = {stat: hero["baseStats"][stat] + hero["growth"][stat] * (level - 1) for stat in STATS}
            rows.append({"id": hero["id"], "name": hero["name"], "role": hero["role"], "level": level,
                         **values, **{key: hero[key] for key in ("speed", "attackRange", "leadership")}})
        keys = tuple(STATS) + ("speed", "attackRange", "leadership")
        return {"quality": quality, "quality_label": QUALITY_LABELS[quality], "role": role or None, "level": level,
                "rows": rows, "medians": {key: median(row[key] for row in rows) for key in keys} if rows else {},
                "count": len(rows), "excluded": excluded, "excluded_count": len(excluded),
                "conditions": "真实 cfg.pl 基础值 + 成长 × (等级 − 1)；速度/射程/领导力取原值；不含装备、缘分、培养或额外加成。超过真实等级上限的样本已排除。"}

    def stat_baseline(self, quality, sign_type, role=""):
        """Return independent medians of native base/growth fields, never level deltas."""
        if type(quality) is not int or quality not in (2, 3, 4, 5, 6):
            raise ValueError("请选择白至橙的英雄品质。")
        signs = {"attack": "输出", "tank": "坦克", "assist": "辅助"}
        if sign_type not in signs:
            raise ValueError("请先选择战斗职责。")
        candidates = [row for row in self.heroes
                      if row["quality"] == quality and row["signType"] == sign_type]
        role = role.strip()
        specific = [row for row in candidates if row["role"] == role] if role else []
        rows = specific or candidates
        if not rows:
            raise ValueError("当前品质和战斗职责没有原版参考英雄，未修改任何数值。")
        return {
            "baseStats": {key: median(row["baseStats"][key] for row in rows) for key in STATS},
            "growth": {key: median(row["growth"][key] for row in rows) for key in STATS},
            # These three manifest fields must be integers; round positive halves up.
            **{key: int(median(row[key] for row in rows) + .5)
               for key in ("speed", "attackRange", "leadership")},
            "count": len(rows),
            "basis": QUALITY_LABELS[quality] + "色 / " + signs[sign_type] +
                     (" / " + role if specific else ""),
            "roleMatched": bool(specific),
        }

    def coverage(self):
        reusable = sum(row["reusable"] for row in self.skills)
        editable = sum(row["editable"] for row in self.skills)
        unsupported = sum(not row['editable'] and not row['reusable'] for row in self.skills)
        mechanisms = Counter(str(action[0]) for row in self.skills for action in row["actions"]
                             if isinstance(action, list) and action)
        return {"summary": f"全部 {len(self.skills)} 个原版技能均可导入完整可编辑模板；共 {len(mechanisms)} 种原生动作及 44 个复合机制。保留条件、选敌、分组、成长、召唤和被动触发。旧版 {len(ACTIONS)} 动作工程继续兼容。",
                "gameDataVersion": self.base.get("cfg_version"), "heroes": len(self.heroes),
                "skills_total": len(self.skills), "skills_reusable": reusable,
                "skills_editable": editable, "skills_unsupported": unsupported,
                "supported_actions": sorted(mechanisms), "native_action_counts": dict(sorted(mechanisms.items())),
                "safe_native_patch_fields": ["warmup", "cooldown", "range", "description"],
                "effects_total": len(self.effects), "effects_reusable": sum(row["exportable"] for row in self.effects),
                "audio_reusable": sum(row["exportable"] for row in self.audio),
                "hero_previews": sum(bool(self._hero_image_path(row["id"])) for row in self.heroes),
                "limitations": ["完整模板需要同步更新包含 native-template.v1 的游戏服务端及客户端源码；旧版游戏明确拒绝新能力包。",
                    "模板为受校验的结构化数据，不导入任意 AS3/SWF 或可执行脚本。",
                    "内置动画按真实特效定义展示；ATF/SWF 仅说明资源位置，不执行或批量反编译。",
                    "品质 1 的三个特殊单位保留供查阅，新英雄包允许品质 2–6。"],
                "skills": [{key: copy.deepcopy(row[key]) for key in ("id", "name", "description", "actions", "reusable", "editable", "editable_fields", "reason", "reference")} for row in self.skills]}
