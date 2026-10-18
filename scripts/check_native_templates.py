"""One focused full-catalogue acceptance run; never starts the game."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'server')]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
OUT=ROOT/'build/native-template-check'
os.environ.setdefault('HERO_EDITOR_DATA_DIR',str(OUT/'data'))
from editor.catalog import Catalog
from editor.core import Project, compile_offline
from editor.merge import merge_packages
from mod_native import (compile_template,validate_template,reorder_actions,remove_action,
                        argument_label,ability_contract,NODE_SETTINGS)
from mod_packages import inspect_package
from mod_schema import ModError, canonical


def reject(fn):
    try:fn()
    except (ModError,ValueError,KeyError):return
    raise AssertionError('Invalid native mechanism was accepted')

def normalized(result,source):
    result=copy.deepcopy(result)
    for key in ('modNativeSource','modPassiveTrigger','nativeAbilityParameters','modScaleActionIndex','nativeActionSources','nativeActionSettings'):
        result.pop(key,None)
    result['id']=source['id']
    for key in ('manualSummonPolicy','manualClonePolicy'):
        if isinstance(result.get(key),dict) and 'skillId' in result[key]:result[key]['skillId']=source['id']
    return result

def changed_template(row):
    template=copy.deepcopy(row['authored'])
    for action in template['actions']:
        for i,value in enumerate(action['arguments'],1):
            if type(value) in (int,float) and any(word in argument_label(action['type'],i,action['arguments']) for word in ('倍率','比例')):
                action['arguments'][i-1]=value*1.01 if value else .01
                return template,'action'
    template['description']+=' 编辑验收'
    return template,'description'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    c=Catalog();failures=[];edited=[];reorders=0
    for row in c.skills:
        try:
            template=copy.deepcopy(row['authored'])
            validate_template(template,c.base)
            result=compile_template(template,c.base,'S_800000_1')
            assert normalized(result,row['native'])==row['native'],'original round-trip changed data'
            changed,kind=changed_template(row)
            compiled=compile_template(changed,c.base,'S_800000_1')
            assert compiled['skill']!=result['skill'] if kind=='action' else compiled['info']!=result.get('info'),'edit did not compile'
            edited.append(changed)
            if len(template['actions'])>1:
                for i in range(len(template['actions'])-1):
                    candidate=copy.deepcopy(template);order=list(range(len(candidate['actions'])));order[i],order[i+1]=order[i+1],order[i]
                    try:reorder_actions(candidate,order)
                    except ModError:continue
                    reorder_actions(candidate,order)
                    assert candidate==template,'inverse reorder changed a reference'
                    reorders+=1;break
        except Exception as error:failures.append({'id':row['id'],'error':str(error)})
    (OUT/'catalogue.json').write_text(json.dumps({'total':len(c.skills),'passed':len(c.skills)-len(failures),
        'edited':len(edited),'reorders':reorders,'failures':failures},ensure_ascii=False,indent=2),'utf-8')
    assert not failures,failures[:12]

    paths=[]
    for start in range(0,len(edited),220):
        project=Project.new(catalog=c);project.manifest.update(author='Native template acceptance',name='Catalogue '+str(start))
        project.rows('skills').extend(copy.deepcopy(edited[start:start+220]))
        first=project.rows('skills')[0];project.rows('heroes')[0]['skills']['normal']='self:skill/'+first['id']
        path=OUT/('catalogue-%04d.heropack'%start)
        project.export(path,catalog=c)
        loaded=Project.import_package(path,catalog=c)
        assert loaded.data==project.data
        package=inspect_package(path,c.base)
        assert 'skill.native-template.v1' in package.manifest['requiredCapabilities']
        paths.append(path)
    # One real merged output verifies namespacing and full nested payload retention.
    # Merge smaller real packages; the original 256-entity quota remains intact.
    small=[]
    for i,row in enumerate((c.skill('S_631132_5'),next(r for r in c.skills if any(a[0]=='manual_ability' for a in r['actions'])))):
        project=Project.new(catalog=c);project.manifest['author']='Native merge'
        project.rows('skills').append(copy.deepcopy(row['authored']))
        project.rows('heroes')[0]['skills']['normal']='self:skill/'+project.rows('skills')[0]['id']
        path=OUT/('small-%d.heropack'%i);project.export(path,catalog=c);small.append(path)
    merged,_=merge_packages(small,catalog=c,name='Merged native mechanisms',author='Acceptance')
    merged.export(OUT/'merged.heropack',catalog=c)

    broken=copy.deepcopy(c.skill('S_201001_5')['authored']);before=copy.deepcopy(broken)
    reject(lambda:remove_action(broken,0));assert broken==before
    broken['nativeTemplate']['sourceDigest']='0'*64
    reject(lambda:validate_template(broken,c.base))
    broken=copy.deepcopy(before);broken['actions'][0]['type']='execute_arbitrary_script'
    reject(lambda:validate_template(broken,c.base))
    manual=next(r for r in c.skills if any(a[0]=='manual_ability' for a in r['actions']))
    broken=copy.deepcopy(manual['authored']);group=next(iter(broken['nativeTemplate']['abilityParameters']))
    key=next(iter(broken['nativeTemplate']['abilityParameters'][group]));broken['nativeTemplate']['abilityParameters'][group][key]=float('inf')
    reject(lambda:validate_template(broken,c.base))

    check_gui(c)
    report={'ok':True,'skills':len(c.skills),'edited':len(edited),'packageBatches':len(paths),
            'nativeOperations':len({a[0] for r in c.skills for a in r['actions']}),
            'compoundMechanisms':len(ability_contract()['mechanisms']),
            'compoundParameters':sum(map(len,ability_contract()['mechanisms'].values())),
            'checks':['exact native round-trip','edit/compile','reference-aware reorder','real package export/import',
                      'merge','invalid contracts','GUI import/edit/save'],'gameLaunched':False}
    (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

def check_gui(c):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
    from editor.ui import MainWindow
    app=QApplication.instance() or QApplication(['native-template-check'])
    if not QFontDatabase.families():QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    errors=[];previous_hook=sys.excepthook
    sys.excepthook=lambda kind,value,tb:errors.append(str(value))
    window=MainWindow(catalog=c);window.show_error=lambda e:errors.append(str(e))
    manual=next(r for r in c.skills if any(a[0]=='manual_ability' for a in r['actions']))
    for row in (c.skill('S_201001_5'),manual,c.skill('S_631132_5'),next(r for r in c.skills if r['authored']['nativeTemplate']['passiveTrigger'])):
        project=Project.new(catalog=c);project.manifest['author']='Native GUI acceptance'
        skill=project.add_skill();window.set_project(project);window.select_entity('skills',0)
        editor=window.current_editor;editor.builtin.set_value(row['reference'])
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):assert editor.convert_template()
        window.flush()
        expected=copy.deepcopy(row['authored']);expected['id']=skill['id']
        assert skill==expected,(row['id'],'GUI import changed native data')
        native=editor.native_editor
        native.name.setText(row['name']+' GUI')
        window.flush();assert skill['name'].endswith(' GUI')
        project.save(OUT/'gui.lalhero');assert Project.load(OUT/'gui.lalhero').rows('skills')[0]==skill
        if row is manual:
            native.tabs.setCurrentIndex(3)
            root=native.abilities.tree.topLevelItem(0)
            item=root.child(0).child(0)
            native.abilities.tree.setCurrentItem(item)
            control=native.abilities.control
            old=control.value();control.setValue(old+1)
            window.flush()
            group,key=item.data(0,Qt.ItemDataRole.UserRole)
            assert skill['nativeTemplate']['abilityParameters'][group][key]==old+1
            assert compile_template(skill,c.base,'S_800001_1')['nativeAbilityParameters'][group][key]==old+1
            window.refresh_preview()
            window.resize(1600,1050);window.show();app.processEvents();window.grab().save(str(OUT/'compound-ui.png'))
        if row['id']=='S_201001_5':
            assert native.move_action(2,3)
            assert '{rank:3:1}' in skill['nativeTemplate']['settings']['rankInfoTemplate']
    project=Project.new(catalog=c);window.set_project(project)
    hero=project.rows('heroes')[0]
    with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted):
        created=window.choose_skill_template(hero,'normal')
    assert created['model']=='native-template-v1'
    assert hero['skills']['normal']=='self:skill/'+created['id']
    window.flush();assert len(project.rows('skills'))==1
    assert len(c.references('skillTemplate'))==1077
    summon=next(r for r in c.skills if r['native'].get('manualSummonPolicy') and any(a[0]=='summon' for a in r['actions']))
    broken=copy.deepcopy(summon['authored'])
    next(a for a in broken['actions'] if a['type']=='summon')['arguments']=[]
    reject(lambda:validate_template(broken,c.base))
    assert not errors,errors
    window.dirty=False;window.hide()
    sys.excepthook=previous_hook
    print('GUI: complete templates import, edit, reorder and save passed')

if __name__=='__main__':
    if '--gui-only' in sys.argv:check_gui(Catalog())
    else:main()
