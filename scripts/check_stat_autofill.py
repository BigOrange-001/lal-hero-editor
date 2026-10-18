"""Focused stat autofill and AOE help checks; no game runtime."""
import copy
import os
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'server')]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('HERO_EDITOR_DATA_DIR', str(ROOT / 'build/stat-autofill-check/data'))

from editor.catalog import Catalog
from editor.core import Project
from editor.widgets import STATS
from editor.ui import MainWindow
from editor.skill_editor import SkillEditor
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QPushButton, QLabel


def main():
    catalog = Catalog()
    original = copy.deepcopy(catalog.heroes)
    for quality in range(2, 7):
        for sign in ('attack', 'tank', 'assist'):
            rows = [r for r in catalog.heroes if r['quality'] == quality and r['signType'] == sign]
            if not rows:
                continue
            baseline = catalog.stat_baseline(quality, sign)
            assert baseline['count'] == len(rows)
            for group in ('baseStats', 'growth'):
                for key in STATS:
                    assert baseline[group][key] == median(r[group][key] for r in rows)
            for key in ('speed', 'attackRange', 'leadership'):
                assert baseline[key] == int(median(r[key] for r in rows) + .5)
            role = next((r['role'] for r in rows if r['role']), '')
            if role:
                subset = [r for r in rows if r['role'] == role]
                exact = catalog.stat_baseline(quality, sign, role)
                assert exact['roleMatched'] and exact['count'] == len(subset)
            fallback = catalog.stat_baseline(quality, sign, '不存在的自定义说明')
            assert not fallback['roleMatched'] and fallback['baseStats'] == baseline['baseStats']
    assert catalog.heroes == original
    # No sample: explicit failure, rather than borrowing a different quality/role.
    catalog.heroes = []
    try:
        catalog.stat_baseline(6, 'tank')
    except ValueError:
        pass
    else:
        raise AssertionError('Empty reference set accepted')
    catalog.heroes = original

    app = QApplication.instance() or QApplication(['stat-autofill-check'])
    if not QFontDatabase.families():
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    window = MainWindow(catalog=catalog)
    errors = []
    window.show_error = lambda error: errors.append(str(error))
    window.set_project(Project.new(catalog=catalog))
    window.select_entity('heroes', 0)
    fields = window.field_widgets
    fields['quality'].setCurrentIndex(fields['quality'].findData(6))
    fields['signType'].setCurrentIndex(fields['signType'].findData('tank'))
    fields['role'].setText('自定义坦克')
    window.flush()
    before = copy.deepcopy(window.project.rows('heroes')[0])
    button = window.findChild(QPushButton, 'autofillStats')
    assert button
    button.click()
    assert not errors, errors
    expected = catalog.stat_baseline(6, 'tank', '自定义坦克')
    hero = window.project.rows('heroes')[0]
    for key in ('baseStats', 'growth', 'speed', 'attackRange', 'leadership'):
        assert hero[key] == expected[key], key
    assert {k:v for k,v in hero.items() if k not in expected} == {k:v for k,v in before.items() if k not in expected}
    assert window.dirty
    fields['baseStats.attack'].setValue(123.125)
    window.flush()
    assert hero['baseStats']['attack'] == 123.125
    output = ROOT / 'build/stat-autofill-check'
    output.mkdir(parents=True, exist_ok=True)
    window.project.save(output / 'autofill.lalhero')
    assert Project.load(output / 'autofill.lalhero').rows('heroes')[0] == hero
    window.resize(1450, 1000)
    window.show()
    app.processEvents()
    window.grab().save(str(output / 'autofill-ui.png'))
    skill = SkillEditor(catalog, window.project)
    assert '不是范围半径' in skill.aoe.toolTip()
    assert any('最大目标数仍为 1' in label.text() for label in skill.findChildren(QLabel))
    native = next(row for row in catalog.skills if row['reusable'] and row['editable']
                  and any(a[0] == 'move_to_target' for a in row['actions']))
    skill.builtin.set_value(native['reference'])
    skill.describe_builtin()
    assert skill.template_button.isEnabled()
    assert '可转换成 API 1 模板' in skill.builtin_info.text()
    window.dirty = False
    window.hide()
    print('PASS: quality/role medians, growth, fallback/no samples, GUI fill/manual override/save, AOE help')


if __name__ == '__main__':
    main()
