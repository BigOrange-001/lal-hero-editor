"""Movement protocol/compile/conversion acceptance; no game build or runtime."""
import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'server')]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('HERO_EDITOR_DATA_DIR', str(ROOT / 'build/mod-movement-check/data'))
from mod_schema import (CAPABILITIES, ModError, canonical, skill_extension_capabilities,
                        validate_skill, validate_manifest, validate_hero)
from mod_packages import _inspect_payload, inspect_package
from editor.catalog import Catalog
from editor.core import Project, compile_offline


def reject(fn):
    try:
        fn()
    except (ModError, ValueError):
        return
    raise AssertionError('Invalid contract accepted')


def main():
    catalog = Catalog()
    # This check covers the previous narrow action format. Complete native
    # templates have their own full-catalogue acceptance check.
    for row in catalog.skills:
        legacy=catalog._legacy_skill_row(row['id'],row['native'])
        row.update(authored=legacy['authored'],editable=legacy['editable'])
    out = ROOT / 'build/mod-movement-check'
    out.mkdir(parents=True, exist_ok=True)
    convertible = [r for r in catalog.skills if r['editable']]
    assert len(convertible) >= 8
    for row in convertible:
        authored, native = row['authored'], row['native']
        compiler = catalog._compiler
        package = SimpleNamespace(package_id='movement-check')
        compiler.skill_refs = {(package.package_id, authored['id']): row['id']}
        compiled = compiler.skill(package, authored)
        for key in ('skill', 'pl', 'actionTargetPolicies', 'actionTargetLocks', 'actionTargetMaxTargets', 'rankInfoTemplate'):
            assert compiled.get(key) == native.get(key), (row['id'], key)
        assert compiled['skillUp'] == native['skillUp']

    garen = copy.deepcopy(catalog.skill('S_201001_5')['authored'])
    assert garen['actions'][0]['type'] == 'move_to_target'
    assert garen['actions'][1]['lockOnly'] and garen['actions'][1]['lockToAction'] == 0
    for mutate in (
        lambda s: s['actions'][0].update(distance=-1),
        lambda s: s['actions'][0].update(distance=10001),
        lambda s: s['actions'][0].update(distance=True),
        lambda s: s['actions'][0].update(coefficient=1),
        lambda s: s['actions'][0].update(maxTargets=2),
        lambda s: s['actions'][0].update(targetPolicy='ally_self'),
        lambda s: s['actions'][0].update(lockOnly=True),
        lambda s: s['actions'][1].pop('lockToAction'),
        lambda s: s['actions'][1].update(lockToAction=1),
        lambda s: s['actions'][1].update(maxTargets=0),
        lambda s: s.update(rankInfoTemplate='{rank:999:1}'),
        lambda s: s.update(rankInfoTemplate='{rank:0:1}'),
    ):
        bad = copy.deepcopy(garen)
        mutate(bad)
        reject(lambda: validate_skill(bad, 'skill'))
    for distance in (0, 10000):
        valid = copy.deepcopy(garen)
        valid['actions'][0]['distance'] = distance
        validate_skill(valid, 'skill')

    for sid in ('S_201001_5', 'S_201007_5'):
        project = Project.new(catalog=catalog)
        project.manifest['author'] = 'Movement acceptance'
        skill = copy.deepcopy(catalog.skill(sid)['authored'])
        project.rows('skills').append(skill)
        project.rows('heroes')[0]['skills']['normal'] = 'self:skill/' + skill['id']
        manifest, _, payload = project._payload()
        assert skill_extension_capabilities(skill) <= set(manifest['requiredCapabilities'])
        missing = copy.deepcopy(payload)
        invalid = copy.deepcopy(manifest)
        invalid['requiredCapabilities'] = []
        missing['manifest.json'] = canonical(invalid)
        reject(lambda: _inspect_payload(missing))
        # A pre-extension server fails at capabilities before compiling arrays.
        with patch('mod_schema.CAPABILITIES', CAPABILITIES - skill_extension_capabilities(skill)):
            reject(lambda: validate_manifest(manifest))
        path = out / (sid + '.heropack')
        project.export(path, catalog=catalog)
        result = compile_offline([inspect_package(path)], catalog)
        compiled = next(v for k,v in result.document['cfg']['skill'].items()
                        if k.startswith('S_8') and v['name'] == skill['name'])
        assert compiled['skill'] == catalog.skill(sid)['native']['skill']
        if sid == 'S_201007_5':
            assert compiled['actionTargetMaxTargets'][-1] == -1

    moved = copy.deepcopy(garen)
    Project.reorder_actions(moved, 2, 3)
    assert '{rank:3:1}' in moved['rankInfoTemplate']
    assert moved['actions'][2]['lockToAction'] == 0
    before = copy.deepcopy(moved)
    reject(lambda: Project.reorder_actions(moved, 0, 3))
    assert moved == before
    reject(lambda: Project.remove_action(moved, 3))
    assert moved == before

    project = Project.new(catalog=catalog)
    project.manifest['author'] = 'True basic attack acceptance'
    hero = project.rows('heroes')[0]
    hero['damageType'] = 'true'
    validate_hero(hero, 'hero')
    bad = copy.deepcopy(hero)
    bad['damageType'] = 'unknown'
    reject(lambda: validate_hero(bad, 'hero'))
    manifest, _, _ = project._payload()
    assert 'hero.damage.true' in manifest['requiredCapabilities']
    true_path = out / 'true-basic.heropack'
    project.export(true_path, catalog=catalog)
    result = compile_offline([inspect_package(true_path)], catalog)
    assert all(result.document['cfg']['avatar'][aid]['tl'][2] == 3 for aid in result.runtime['heroes'])
    source = copy.deepcopy(catalog.base)
    source['cfg']['avatar']['A_1001_5']['tl'][2] = 3
    clone_project = Project.new(catalog=catalog)
    clone_project.add_hero(catalog=source, source_aid='A_1001_5')
    assert clone_project.rows('heroes')[-1]['damageType'] == 'true'
    patch_project = Project.new('replace', catalog=catalog)
    patch_project.manifest['author'] = 'True basic attack patch acceptance'
    change = patch_project.rows('patches')[0]
    patch_project.set_patch_field(change, 'damageType', 'true', catalog=catalog)
    patch_path = out / 'true-basic-patch.heropack'
    patch_project.export(patch_path, catalog=catalog)
    result = compile_offline([inspect_package(patch_path)], catalog)
    target = change['target'].split('/')[-1]
    assert result.document['cfg']['avatar'][target]['tl'][2] == 3
    assert compile_offline([], catalog).document['cfg']['avatar'][target]['tl'][2] == catalog.base['cfg']['avatar'][target]['tl'][2]

    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QMessageBox
    from editor.skill_editor import SkillEditor
    app = QApplication.instance() or QApplication(['mod-movement-check'])
    if not QFontDatabase.families():
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    from editor.ui import MainWindow, apply_theme
    apply_theme(app)
    window = MainWindow(catalog=catalog)
    window.set_project(project)
    window.select_entity('heroes', 0)
    assert window.field_widgets['damageType'].currentData() == 'true'
    window.flush()
    assert window.project.rows('heroes')[0]['damageType'] == 'true'
    window.set_project(patch_project)
    window.select_entity('patches', 0)
    patch_editor = window.current_editor
    index = next(i for i,op in enumerate(change['operations']) if op['path'] == 'damageType')
    patch_editor.select_field(index)
    assert patch_editor.value.currentData() == 'true'
    patch_editor.value.setCurrentIndex(patch_editor.value.findData('magic'))
    window.flush()
    assert change['operations'][index]['value'] == 'magic'
    window.dirty = False
    window.hide()
    project = Project.new(catalog=catalog)
    skill = project.add_skill()
    widget = SkillEditor(catalog, project)
    widget.bind(skill)
    widget.builtin.set_value('builtin:skill/S_201001_5')
    assert widget.template_button.isEnabled()
    with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
        assert widget.convert_template()
    widget.flush()
    identity = skill['id']
    assert {k:v for k,v in skill.items() if k != 'id'} == {k:v for k,v in garen.items() if k != 'id'}
    assert widget.distance.isEnabled() and widget.distance.value() == 0
    widget.select_action(1)
    assert widget.lock_only.isChecked()
    assert widget.move_action(2, 3)
    widget.flush()
    assert '{rank:3:1}' in skill['rankInfoTemplate']
    project.save(out / 'movement.lalhero')
    assert Project.load(out / 'movement.lalhero').rows('skills')[0] == skill
    widget.resize(1150, 900)
    widget.tabs.setCurrentIndex(1)
    widget.actions.setCurrentRow(0)
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / 'movement-ui.png'))
    widget.hide()
    print(f'PASS: {len(convertible)} exact native conversions, movement/lock boundaries, capability compatibility, real package install/compile, true basic attack new/patch/clone, GUI convert/reorder/save')


if __name__ == '__main__':
    main()
