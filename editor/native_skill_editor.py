"""Editable native mechanism forms, including every nested battle parameter."""
from __future__ import annotations

import copy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,
    QTextEdit,QPushButton,QSplitter,QTreeWidget,QTreeWidgetItem,QCheckBox,QComboBox,
    QInputDialog,QTabWidget,QScrollArea,QGroupBox,QMessageBox)
from .widgets import number, integer, combo, RefCombo
from .skill_editor import ActionList
from mod_native import BOOK_PASSIVE_STATS, BOOK_BONUS_STATS, PARALLEL, OP_LABELS, NODE_SETTINGS, argument_label, reorder_actions, remove_action, ability_contract, ability_defaults
from mod_schema import digest

LABELS={
    'pl':'施放条件与时序','skillUp':'按字段成长','skillUpPaths':'嵌套参数成长',
    'actionTargetPolicies':'目标策略','actionTargetLocks':'锁定前序目标','actionTargetGroups':'共享目标组',
    'actionTargetMaxTargets':'目标数量（-1 全部）','actionTargetPolicyArgs':'选敌条件与范围',
    'damageShareGroups':'共享伤害结算组','rankInfoTemplate':'等级说明模板','manualSummonPolicy':'召唤策略',
    'manualClonePolicy':'分身策略','summonCombatPolicy':'召唤战斗策略','chainDot':'连锁持续状态',
    'captainSummonMultiplier':'队长召唤倍率','manualDamageMultiplier':'复合机制伤害倍率',
    'manualDefenseBuffMultiplier':'复合机制防御增益倍率','manualEffectMultiplier':'复合机制附加效果倍率',
    'recastNormalOnceOnKill':'击杀后追加普通技能','local_design':'机制设计说明','res':'原生表现索引',
    'centerActionIndex':'中心来源动作','primaryActionIndex':'主目标来源动作',
    'distinctFromActionIndices':'排除前序动作目标','requiresPrecastDotActionIndex':'要求施放前已有持续状态的动作',
    'laneFilter':'分路筛选','heroOnly':'仅英雄','excludeSelf':'排除施法者','forwardOnly':'仅前方',
    'maxRange':'最远距离','radius':'范围半径','maxForwardDistance':'最远向前距离','sortBy':'排序方式',
    'selfPriority':'优先自身','preferOtherAlly':'优先其他友军','useLastPosition':'保留目标最后位置',
    'familyKey':'共享召唤家族','unitId':'召唤单位','skillId':'技能绑定（编译时重绑）','maxAlive':'最多存活数量',
    'replaceOldest':'超出时替换最早单位','ttlOwnerTurns':'存续施法者回合','ttlOwnTurns':'存续自身回合',
    'clearSkills':'清除召唤物技能','actionType':'行动类型','attackRange':'攻击范围',
    'apRatio':'攻击比例','hpRatio':'生命比例','dePhRatio':'物防比例','deMaRatio':'魔防比例','panelStatRatio':'全属性比例',
    'arguments':'动作参数','passiveTrigger':'被动触发类型','abilityParameters':'复合机制内部参数',
}
TIMING=['首次等待','冷却回合','施放距离','生命触发条件','原生 AOE 规则','站桩许可（0 禁用／1 允许）']
TRIGGERS=['无额外被动触发','未命中时','暴击时','击杀时','邪恶状态时','沉默状态时','眩晕状态时','灼烧状态时','破甲状态时','中毒状态时',
          '虚弱状态时','护盾状态时','净化状态时','强化状态时','四属性状态时','祝福状态时','双抗提升时','嘲讽状态时','无上述状态时','控制／负面状态时']

class ValueTree(QWidget):
    """Tree + typed form. No raw JSON is required to edit nested parameters."""
    changed=Signal()
    def __init__(self,catalog,parent=None,kind=None):
        super().__init__(parent);self.catalog=catalog;self.data={};self.kind=kind;self.active=None;self.control=None;self.busy=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['字段 / 条件','当前值']);self.tree.setColumnWidth(0,300)
        layout.addWidget(self.tree)
        self.form=QFormLayout();layout.addLayout(self.form)
        buttons=QHBoxLayout()
        for text,fn in [('添加列表项 / 字段',self.add_value),('移除所选项',self.delete_value),('改变值类型',self.change_type)]:
            button=QPushButton(text);button.clicked.connect(fn);buttons.addWidget(button)
        layout.addLayout(buttons)
        self.tree.currentItemChanged.connect(self.selected)
    def bind(self,value,kind=None):
        self.data=copy.deepcopy(value);self.kind=kind;self.active=None;self.rebuild()
    def rebuild(self,selected=None):
        self.busy=True;self.tree.clear();target=None
        def add(parent,key,value,path):
            nonlocal target
            label=LABELS.get(str(key),str(key))
            if len(path)==1 and str(key) in ability_contract()['mechanisms']:
                label=next((r['name']+' · '+str(key) for r in self.catalog.skills
                            if any(a[0]=='manual_ability' and a[1]==key for a in r['actions'])),str(key))
            if len(path)==2 and path[0] in ability_contract()['mechanisms']:
                descriptor=ability_contract()['mechanisms'][path[0]].get(str(key),{})
                context=descriptor.get('context','')
                functions={'abilityEnemies':'敌方选取','abilityHit':'伤害结算','abilityHeal':'治疗结算','abilityShield':'护盾结算',
                           'abilityControl':'附加状态','abilitySummon':'召唤参数','abilityMark':'标记参数','abilityDash':'突进参数','addBuff':'增益参数'}
                label=descriptor.get('label') or next((name for namefn,name in functions.items() if namefn+'(' in context),'触发 / 条件 / 状态参数')+' · '+str(key)
            if path and path[0]=='arguments' and len(path)==2 and self.kind:
                label=argument_label(self.kind,int(key)+1,self.data['arguments'])
            elif path and path[0]=='pl' and len(path)==2 and int(key)<6:label=TIMING[int(key)]
            summary=('对象 · '+str(len(value))+' 个字段') if isinstance(value,dict) else ('列表 · '+str(len(value))+' 项') if isinstance(value,list) else '沿用原生默认' if value is None else '启用' if value is True else '关闭' if value is False else str(value)
            item=QTreeWidgetItem([label,summary]);item.setData(0,Qt.ItemDataRole.UserRole,path);item.setToolTip(0,'.'.join(map(str,path)))
            (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
            if path==selected:target=item
            if isinstance(value,(dict,list)):
                for k,v in value.items() if isinstance(value,dict) else enumerate(value):add(item,k,v,path+(k,))
        add(None,'参数与条件',self.data,())
        self.tree.expandToDepth(2);self.busy=False
        if target:self.tree.setCurrentItem(target)
        elif self.tree.topLevelItemCount():self.tree.setCurrentItem(self.tree.topLevelItem(0))
    def get(self,path):
        value=self.data
        for key in path:value=value[key]
        return value
    def put(self,path,value):
        parent=self.get(path[:-1]);parent[path[-1]]=value
    def selected(self,item,*_):
        if self.busy or item is None:return
        self.active=item.data(0,Qt.ItemDataRole.UserRole)
        while self.form.count():
            row=self.form.takeAt(0)
            if row.widget():
                row.widget().hide();row.widget().deleteLater()
        value=self.get(self.active);control=None
        if self.active and ('summonCombatPolicy' in self.active and self.active[-1]!='owner_ap_ratio') and not isinstance(value,(dict,list)):
            control=QLabel(str(value)+'（原版说明记录；召唤单位和回合在动作参数中调整）');signal=None
        elif self.active and self.active[-1]=='skillId':
            control=QLabel(str(value)+'（导出时自动绑定当前自制技能）');signal=None
        elif type(value) is bool:
            control=QCheckBox('启用');control.setChecked(value);signal=control.toggled
        elif type(value) in (int,float):
            descriptor=ability_contract()['mechanisms'].get(str(self.active[0]),{}).get(str(self.active[-1]),{}) if len(self.active)==2 else {}
            label=argument_label(self.kind,int(self.active[-1])+1,self.data['arguments']) if self.kind and len(self.active)==2 and self.active[0]=='arguments' else ''
            timing_index=self.active[1] if len(self.active)==2 and self.active[0]=='pl' else None
            if timing_index in (0,1,2,4,5):descriptor={'integer':True,'minimum':-100000 if timing_index==2 else -32 if timing_index==4 else 0,'maximum':100000 if timing_index in (2,4) else 100}
            if timing_index==5:descriptor.update(enum=[0,1],maximum=1)
            if descriptor.get('enum') or label=='伤害类型':
                values=descriptor.get('enum',[0,1,2,3]);names={0:'禁止站桩施放',1:'允许站桩施放'} if timing_index==5 else {0:'原生默认',1:'物理',2:'魔法',3:'真实伤害'}
                control=combo([(names.get(v,str(v)),v) for v in values],value)
                control.setProperty('numericEnum',True);signal=control.currentIndexChanged
            else:
                integer_field=descriptor.get('integer') or any(word in label for word in ('回合','次数','目标数','最大层数','段数'))
                if integer_field:
                    control=integer(value,int(descriptor.get('minimum',-1 if '目标数' in label else 0)),int(descriptor.get('maximum',100)))
                else:control=number(value,descriptor.get('minimum',-10_000_000),descriptor.get('maximum',10_000_000),8,.05)
                signal=control.valueChanged
        elif isinstance(value,str):
            options=self.options(self.active,value)
            if options:
                control=QComboBox();control.setEditable(True);control.addItems(options);control.setCurrentText(value);signal=control.currentTextChanged
            else:control=QLineEdit(value);signal=control.textChanged
        else:
            control=QLabel('在树中展开后选择具体字段；可添加／移除列表项和对象字段。空值表示沿用原生规则。');control.setWordWrap(True);signal=None
        self.control=control;self.form.addRow('编辑所选值',control)
        if signal:signal.connect(self.commit)
    def options(self,path,value):
        leaf=str(path[-1]);result=[]
        if leaf=='laneFilter':result=['all','same_as_caster','same_as_center']
        elif leaf=='sortBy':result=['nearest']
        elif self.kind and len(path)==2 and path[0]=='arguments' and argument_label(self.kind,int(path[-1])+1,self.data['arguments'])=='触发条件':
            result=sorted({a[int(path[-1])+1] for r in self.catalog.skills for a in r['actions']
                           if a[0]==self.kind and len(a)>int(path[-1])+1 and isinstance(a[int(path[-1])+1],str)})
        elif self.kind in ('book_passive','book_bonus') and path==('arguments',1):
            result=list(BOOK_PASSIVE_STATS if self.kind=='book_passive' else BOOK_BONUS_STATS)
        elif value.startswith(('FX','E_')) or ('arguments' in path and self.kind and path[-1]==len(self.data['arguments'])-1):
            result=list(self.catalog.cfg.get('effect',{}))
        elif value.startswith('A_'):result=list(self.catalog.cfg.get('avatar',{}))
        elif value.startswith('S_'):result=list(self.catalog.cfg.get('skill',{}))
        elif value.startswith(('enemy_','ally_')) or leaf=='actionTargetPolicies':
            result=sorted({p for r in self.catalog.skills for p in r['native'].get('actionTargetPolicies',[]) if isinstance(p,str)})
        elif self.kind=='manual_ability' and path==('arguments',0):
            result=sorted({a[1] for r in self.catalog.skills for a in r['actions'] if a[0]=='manual_ability'})
        return sorted(set([value]+result)) if result else []
    def commit(self,*_):
        if self.busy or self.active is None:return
        old=self.get(self.active);control=self.control
        if isinstance(control,QCheckBox):value=control.isChecked()
        elif hasattr(control,'value'):
            value=control.value()
            if type(old) is int and float(value).is_integer():value=int(value)
        elif isinstance(control,QComboBox):value=control.currentData() if control.property('numericEnum') else control.currentText()
        elif isinstance(control,QLineEdit):value=control.text()
        else:return
        self.put(self.active,value)
        item=self.tree.currentItem()
        if item:item.setText(1,str(value))
        self.changed.emit()
    def add_value(self):
        if self.active is None:return
        value=self.get(self.active)
        if isinstance(value,list):value.append(copy.deepcopy(value[-1]) if value else None)
        elif isinstance(value,dict):
            choices=list(PARALLEL)+['settings'] if self.kind and len(self.active)==0 else sorted(LABELS)
            key,ok=QInputDialog.getItem(self,'添加条件 / 字段','字段名',choices,editable=True)
            if not ok or not key or key in value:return
            # Supply a real native example, not an untyped invented object.
            samples=[]
            def walk(obj):
                if isinstance(obj,dict):
                    if key in obj:samples.append(obj[key])
                    for v in obj.values():walk(v)
                elif isinstance(obj,list):
                    for v in obj:walk(v)
            for row in self.catalog.skills:walk(row['native'])
            if self.kind and key in PARALLEL:samples=[v for sample in samples if isinstance(sample,list) for v in sample]
            value[key]=copy.deepcopy(next((s for s in samples if s is not None),None))
        else:
            parent=self.get(self.active[:-1])
            if not isinstance(parent,list):return
            parent.insert(self.active[-1]+1,copy.deepcopy(value))
        path=self.active;self.rebuild(path);self.changed.emit()
    def delete_value(self):
        if not self.active:return
        parent=self.get(self.active[:-1]);key=self.active[-1]
        if isinstance(parent,list):parent.pop(key)
        else:parent.pop(key,None)
        self.rebuild();self.changed.emit()
    def change_type(self):
        if not self.active:return
        choice,ok=QInputDialog.getItem(self,'设置参数类型','选择类型',['空值 / 原生默认','数值','文本','开关','列表','对象'],editable=False)
        if not ok:return
        value={'空值 / 原生默认':None,'数值':0,'文本':'','开关':False,'列表':[],'对象':{}}[choice]
        path=self.active;self.put(path,value);self.rebuild(path);self.changed.emit()
    def value(self):return copy.deepcopy(self.data)

class NativeSkillEditor(QWidget):
    changed=Signal();error=Signal(str)
    def __init__(self,catalog,project,parent=None):
        super().__init__(parent);self.catalog=catalog;self.project=project;self.skill=None;self.index=-1;self.busy=False
        layout=QVBoxLayout(self)
        title=QLabel('完整原生机制模板');title.setObjectName('pageTitle');layout.addWidget(title)
        self.source=QLabel();self.source.setWordWrap(True);layout.addWidget(self.source)
        library_row=QHBoxLayout();self.library=RefCombo(catalog.references('skillTemplate'),optional=False)
        library_row.addWidget(self.library);import_button=QPushButton('导入原版模板替换当前内容')
        import_button.clicked.connect(self.import_template);library_row.addWidget(import_button);layout.addLayout(library_row)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        basic=QWidget();form=QFormLayout(basic)
        self.id=QLineEdit();self.name=QLineEdit();self.description=QTextEdit();self.description.setMaximumHeight(110)
        self.trigger=combo([(name+' · '+str(i),i) for i,name in enumerate(TRIGGERS)])
        for label,widget in [('本地 ID',self.id),('名称',self.name),('说明',self.description),('被动触发方式',self.trigger)]:form.addRow(label,widget)
        self.timing=ValueTree(catalog);form.addRow(self.timing);self.tabs.addTab(basic,'基础与触发')
        actions=QWidget();actions_layout=QVBoxLayout(actions);buttons=QHBoxLayout()
        for text,fn in [('添加原生动作',self.add_action),('复制所选动作',self.duplicate_action),('删除动作',self.remove_action),
                        ('上移',lambda:self.move_action(self.index,self.index-1)),('下移',lambda:self.move_action(self.index,self.index+1))]:
            button=QPushButton(text);button.clicked.connect(fn);buttons.addWidget(button)
        actions_layout.addLayout(buttons);split=QSplitter();self.actions=ActionList();split.addWidget(self.actions)
        self.parameters=ValueTree(catalog);split.addWidget(self.parameters);split.setStretchFactor(1,3);actions_layout.addWidget(split)
        self.tabs.addTab(actions,'动作 / 选敌 / 条件 / 附加效果')
        self.settings=ValueTree(catalog);self.tabs.addTab(self.settings,'成长 / 分组 / 召唤 / 联动')
        self.abilities=ValueTree(catalog);self.tabs.addTab(self.abilities,'复合机制内部数值与条件')
        help_text=QLabel('所有参数以可编辑字段呈现。列表索引从 0 起；空值保留原生默认。拖动动作会同步目标锁、中心、伤害分组、成长及说明引用，非法前向依赖会拒绝。召唤／分身和被动使用独立机制身份，工程本地 ID 不会改变原生分派。')
        help_text.setWordWrap(True);help_text.setObjectName('muted');layout.addWidget(help_text)
        self.actions.currentRowChanged.connect(self.select_action);self.actions.moveRequested.connect(self.move_action)
        for field in (self.id,self.name,self.description):field.textChanged.connect(self.mark_changed)
        self.trigger.currentIndexChanged.connect(self.mark_changed)
        for field in (self.timing,self.settings,self.parameters,self.abilities):field.changed.connect(self.mark_changed)
    def mark_changed(self,*_):
        if not self.busy:self.changed.emit()
    def import_template(self):
        reference=self.library.value();row=self.catalog.skill(str(reference).split('/')[-1])
        if row is None:self.error.emit('请选择当前游戏目录中的技能模板');return
        if QMessageBox.question(self,'替换技能模板','导入所选原版的完整机制并替换当前技能内容？保留当前本地 ID。')!=QMessageBox.StandardButton.Yes:return
        self.flush();identity=self.skill['id'];replacement=copy.deepcopy(row['authored']);replacement['id']=identity
        self.skill.clear();self.skill.update(replacement);self.bind(self.skill);self.changed.emit()
    def bind(self,skill,index=0):
        self.busy=True;self.skill=skill;self.index=-1
        self.id.setText(skill['id']);self.name.setText(skill['name']);self.description.setPlainText(skill['description'])
        native=skill['nativeTemplate'];self.source.setText('来源：'+native['source']+' · 保留完整机制与原生默认；导出使用独立技能身份。')
        self.library.set_value(native['source'])
        self.trigger.setCurrentIndex(self.trigger.findData(native['passiveTrigger']))
        self.timing.bind({'pl':native['settings']['pl']})
        self.settings.bind({k:v for k,v in native['settings'].items() if k not in PARALLEL and k!='pl'})
        self.abilities.bind(native.get('abilityParameters',{}))
        self.actions.clear()
        for i,action in enumerate(skill['actions']):self.actions.addItem(f'{i+1}. {OP_LABELS.get(action["type"],action["type"])} · {action["type"]}')
        self.actions.setCurrentRow(min(index,len(skill['actions'])-1));self.busy=False
    def flush_action(self):
        if self.skill is None or not 0<=self.index<len(self.skill['actions']):return
        values=self.parameters.value();self.skill['actions'][self.index]['arguments']=values.get('arguments',[])
        if 'settings' in values:self.skill['actions'][self.index]['settings']=values['settings']
        else:self.skill['actions'][self.index].pop('settings',None)
        s=self.skill['nativeTemplate']['settings']
        for key in PARALLEL:
            if key in values:
                if key not in s:s[key]=[None]*len(self.skill['actions'])
                s[key][self.index]=values[key]
            elif key in s:s[key][self.index]=None
    def flush(self):
        if self.skill is None:return
        identity=self.id.text().strip()
        if identity!=self.skill['id']:
            index=next(i for i,r in enumerate(self.project.rows('skills')) if r is self.skill)
            self.project.rename('skills',index,identity)
        self.flush_action();s=self.skill['nativeTemplate']['settings']
        parallel={k:copy.deepcopy(s[k]) for k in PARALLEL if k in s}
        s.clear();s.update(self.settings.value());s.update(parallel);s['pl']=self.timing.value().get('pl')
        self.skill.update(name=self.name.text().strip(),description=self.description.toPlainText())
        self.skill['nativeTemplate']['passiveTrigger']=self.trigger.currentData()
        parameters=self.abilities.value()
        for action in self.skill['actions']:
            if action['type']=='manual_ability' and action['arguments']:
                parameters.setdefault(action['arguments'][0],ability_defaults(action['arguments'][0]))
        if parameters:
            self.skill['nativeTemplate']['abilityParameters']=parameters
            self.skill['nativeTemplate']['abilityContract']=digest(ability_contract())
    def select_action(self,index):
        if not self.busy:self.flush_action()
        self.index=index
        if self.skill is None or not 0<=index<len(self.skill['actions']):return
        action=self.skill['actions'][index];s=self.skill['nativeTemplate']['settings']
        values={'arguments':action['arguments']}
        if 'settings' in action:values['settings']=action['settings']
        values.update({k:s[k][index] for k in PARALLEL if k in s and index<len(s[k])})
        self.parameters.bind(values,action['type'])
    def move_action(self,old,new):
        if self.skill is None or not 0<=old<len(self.skill['actions']) or not 0<=new<len(self.skill['actions']):return False
        try:
            self.flush();order=list(range(len(self.skill['actions'])));order.insert(new,order.pop(old));reorder_actions(self.skill,order)
            self.bind(self.skill,new);self.changed.emit();return True
        except Exception as e:self.error.emit('顺序未改变：'+str(e));return False
    def add_action(self):
        if self.skill is None:return
        kinds=sorted({a[0] for row in self.catalog.skills for a in row['actions']})
        labels=[OP_LABELS.get(k,k)+' · '+k for k in kinds]
        choice,ok=QInputDialog.getItem(self,'添加动作','选择原生动作类型',labels,editable=False)
        if not ok:return
        kind=kinds[labels.index(choice)]
        examples=[];donors=[]
        for row in self.catalog.skills:
            for a in row['actions']:
                if a[0]==kind and a not in examples:examples.append(a);donors.append(row)
        names=[f'{i+1}. '+str(a[1:])[:150] for i,a in enumerate(examples)]
        choice,ok=QInputDialog.getItem(self,'选择参数预设','参数可在添加后继续修改',names,editable=False)
        if not ok:return
        self.flush();raw=copy.deepcopy(examples[names.index(choice)])
        donor=donors[names.index(choice)]
        donor_index=donor['actions'].index(raw)
        metadata={k:copy.deepcopy(donor['native'][k][donor_index]) for k in PARALLEL if k in donor['native']}
        metadata['actionTargetLocks']=None;metadata['actionTargetGroups']=None
        if isinstance(metadata.get('actionTargetPolicyArgs'),dict):
            for key in ('centerActionIndex','primaryActionIndex','requiresPrecastDotActionIndex','distinctFromActionIndices'):
                metadata['actionTargetPolicyArgs'].pop(key,None)
        self.append_action({'type':raw[0],'arguments':raw[1:],'origin':donor['reference'],
            'settings':copy.deepcopy({k:v for k,v in donor['native'].items() if k in NODE_SETTINGS})},metadata)
    def append_action(self,action,metadata=None):
        if len(self.skill['actions'])>=32:self.error.emit('最多 32 个动作');return
        self.skill['actions'].append(copy.deepcopy(action))
        if action['type']=='manual_ability':
            self.skill['nativeTemplate'].setdefault('abilityParameters',{}).setdefault(action['arguments'][0],ability_defaults(action['arguments'][0]))
            self.skill['nativeTemplate']['abilityContract']=digest(ability_contract())
        for key in PARALLEL:
            s=self.skill['nativeTemplate']['settings']
            if key not in s and (metadata or {}).get(key) is not None:s[key]=[None]*(len(self.skill['actions'])-1)
            if key in s:s[key].append(copy.deepcopy((metadata or {}).get(key)))
        self.bind(self.skill,len(self.skill['actions'])-1);self.changed.emit()
    def duplicate_action(self):
        if not 0<=self.index<len(self.skill['actions']):return
        self.flush();s=self.skill['nativeTemplate']['settings']
        self.append_action(self.skill['actions'][self.index],{k:s[k][self.index] for k in PARALLEL if k in s})
    def remove_action(self):
        if self.skill is None:return
        try:self.flush();remove_action(self.skill,self.index);self.bind(self.skill,max(0,self.index-1));self.changed.emit()
        except Exception as e:self.error.emit(str(e))
