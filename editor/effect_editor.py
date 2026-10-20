"""Visual editor for bounded effect sequences; all fields remain editable data."""
from __future__ import annotations

import copy
import re
import math
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QHBoxLayout,QLineEdit,
    QTextEdit,QLabel,QPushButton,QSplitter,QScrollArea,QCheckBox)
from .widgets import combo,integer,number,RefCombo
from .skill_editor import ActionList
from mod_effects import DEFAULTS, GROWTH_FIELDS, EVENTS
from mod_schema import ModError

OPERATIONS={'heal':'治疗（攻击＋自身生命）','damage':'伤害','buff':'施加状态／护盾',
            'push':'击退','move':'突进至目标前','summon':'召唤自定义单位'}
TARGETS={'self':'自身','all_allies':'全体友军','all_enemies':'全体敌人',
         'ally_radius':'自身本路半径内友军（含自己）','lane_lowest_hp':'本路最低生命百分比敌人',
         'lane_front':'本路最前方敌人','enemy_radius':'前序目标原位置附近敌人',
         'event_source':'事件来源单位（按动作阵营过滤）','event_target':'事件目标单位（按动作阵营过滤）','previous':'复用前序目标'}
BUFFS={'shield':'护盾','purify':'净化','strong':'攻击提升','weak':'虚弱',
       'sunder':'破甲','steel':'双防提升','bless':'永久神佑','timed_bless':'限时神佑','curse':'诅咒','critup':'暴击',
       'toughup':'韧性','fleeup':'闪避','hitup':'精准／命中','stun':'眩晕'}
FIELDS={'eventRatio':'事件实际数值倍率','overhealRatio':'事件过量治疗倍率','centerAction':'中心／锁定动作（从 0 起；-1 自身）','radius':'范围半径（本路）',
        'attackRatio':'攻击面板倍率','maxHpRatio':'自身最大生命倍率','amount':'增减益比例／固定属性',
        'buff':'状态','duration':'状态持续目标行动回合','distance':'击退距离／突进距离上限（0 不限）',
        'unit':'召唤单位','statRatio':'即时面板继承倍率','lifetime':'召唤物存续自身回合',
        'maxAlive':'同一施法者此步骤最多存活数量','excludeCenter':'范围结算排除中心目标',
        'damageType':'伤害类型','effect':'原版视觉特效'}


class EffectEditor(QWidget):
    changed=Signal()
    error=Signal(str)

    def __init__(self,catalog,project,parent=None):
        super().__init__(parent)
        self.catalog,self.project=catalog,project
        self.skill=None;self.loading=True;self.selected=-1
        layout=QVBoxLayout(self)
        heading=QLabel('效果序列 · 条件、召唤与面板联动');heading.setObjectName('pageTitle');layout.addWidget(heading)
        form=QFormLayout()
        self.id=QLineEdit();self.name=QLineEdit();self.description=QTextEdit();self.description.setMaximumHeight(80)
        self.rank=QTextEdit();self.rank.setMaximumHeight(110)
        self.rank.setToolTip('引用实际参数：{rank:动作索引:5} 攻击倍率，:6 自身生命倍率，:7 增减益比例；flat 显示固定值。升级和动作重排会同步。')
        self.warmup=integer(0,0,100);self.cooldown=integer(1,0,100);self.cooldown.setToolTip('事件被动允许 0；其他技能至少为 1。事件冷却按自身行动机会计数。');self.reach=integer(3000,0,10000)
        self.trigger=combo([('冷却就绪','ready'),('自身缺少指定状态时','absent_buff'),('事件发生时（被动槽）','event')])
        self.trigger_buff=combo([(v,k) for k,v in BUFFS.items()],'purify')
        event_labels={'turn_start':'自身回合开始','turn_end':'自身回合结束','basic_attack':'完成普攻（包括未命中）',
                      'skill_cast':'完成主动施法','hit':'攻击命中','crit':'攻击暴击','miss':'自身攻击未命中','dodge':'闪避对方攻击',
                      'damage_taken':'自身实际损失生命','damage_dealt':'造成实际生命伤害','healed':'自身受到治疗（含过量）',
                      'heal_done':'为单位施加治疗（含过量）','kill':'最终击杀敌人','death':'自身最终死亡','shield_break':'自身护盾被击破'}
        self.event_fields={'event':combo([(event_labels[k],k) for k in EVENTS]),
            'maxPerRound':integer(1,1,16),'allowChain':QCheckBox('允许响应其他被动引发的事件（仍有安全上限）'),
            'relation':combo([('不限','any'),('自身','self'),('其他友军','ally'),('敌军','enemy')]),
            'unitType':combo([('不限','any'),('普通英雄','hero'),('召唤物','summon')]),
            'minAmount':number(0,0,10000000,0,100),'hpBelow':number(1,0,1,4,.05),
            'requiredBuff':combo([('不要求',None)]+[(v,k) for k,v in BUFFS.items()]),
            'absentBuff':combo([('不要求',None)]+[(v,k) for k,v in BUFFS.items()])}
        self.maxlevel=integer(10,1,10)
        for label,field in [('本地 ID',self.id),('名称',self.name),('普通说明',self.description),('数值联动说明',self.rank),
                            ('准备',self.warmup),('冷却（沿用原版行动机会约定）',self.cooldown),
                            ('默认施放距离',self.reach),('触发条件',self.trigger),('检查状态',self.trigger_buff),('最高技能等级',self.maxlevel)]:form.addRow(label,field)
        self.header_form=form
        for key,label in [('event','触发事件'),('maxPerRound','每个全局回合最多触发'),('allowChain','被动连锁'),
                          ('relation','关联单位阵营'),('unitType','关联单位类型'),('minAmount','最低事件实际值'),
                          ('hpBelow','自身生命比例不高于'),('requiredBuff','自身必须持有'),('absentBuff','自身必须缺少')]:form.addRow(label,self.event_fields[key])
        layout.addLayout(form)
        buttons=QHBoxLayout()
        for text,callback in [('添加步骤',self.add),('删除步骤',self.remove),
                              ('上移',lambda:self.move_action(self.selected,self.selected-1)),
                              ('下移',lambda:self.move_action(self.selected,self.selected+1))]:
            b=QPushButton(text);b.clicked.connect(callback);buttons.addWidget(b)
        layout.addLayout(buttons)
        split=QSplitter();self.actions=ActionList();split.addWidget(self.actions)
        panel=QWidget();action_form=QFormLayout(panel);self.action_form=action_form
        self.kind=combo([(v,k) for k,v in OPERATIONS.items()])
        self.target=combo([(v,k) for k,v in TARGETS.items()])
        action_form.addRow('动作',self.kind);action_form.addRow('目标',self.target)
        self.fields={
            'centerAction':integer(-1,-1,31),'radius':number(0,0,10000,2,10),
            'eventRatio':number(0,0,1000,6,.1),'overhealRatio':number(0,0,1000,6,.1),'attackRatio':number(0,0,1000,6,.1),'maxHpRatio':number(0,0,1000,6,.01),
            'amount':number(0,0,100000,6,.1),'buff':combo([(v,k) for k,v in BUFFS.items()]),
            'duration':integer(1,1,100),'distance':number(0,0,10000,2,100),
            'unit':RefCombo(self.unit_refs()),'statRatio':number(1,.01,100,4,.1),
            'lifetime':integer(3,1,100),'maxAlive':integer(1,1,16),'excludeCenter':QCheckBox(),
            'damageType':combo([('物理','physical'),('魔法','magic'),('真实（标注比例为实际攻击倍率）','true')]),
            'effect':RefCombo(catalog.references('skillEffect'))}
        for key,widget in self.fields.items():action_form.addRow(FIELDS[key],widget)
        self.growth={key:number(0,0,100000,6,.01) for key in GROWTH_FIELDS}
        for key,widget in self.growth.items():action_form.addRow('每级增加 · '+FIELDS[key],widget)
        action_form.addRow(QLabel('成长＝初值＋每级增加×(等级−1)。状态回合、距离与目标数量不随伤害成长变化。'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(panel);split.addWidget(scroll);split.setStretchFactor(1,3)
        layout.addWidget(split)
        self.preview_level=integer(1,1,10);layout.addWidget(self.preview_level)
        self.preview=QLabel();self.preview.setWordWrap(True);layout.addWidget(self.preview)
        self.actions.currentRowChanged.connect(self.select)
        self.actions.moveRequested.connect(self.move_action)
        for widget in [self.name,self.description,self.rank,self.warmup,self.cooldown,self.reach,self.trigger,self.trigger_buff,self.maxlevel,*self.event_fields.values(),self.kind,self.target,*self.fields.values(),*self.growth.values()]:
            if isinstance(widget,RefCombo):widget.currentTextChanged.connect(self.edit)
            elif hasattr(widget,'currentIndexChanged'):widget.currentIndexChanged.connect(self.edit)
            elif isinstance(widget,QTextEdit):widget.textChanged.connect(self.edit)
            elif isinstance(widget,QLineEdit):widget.textChanged.connect(self.edit)
            elif isinstance(widget,QCheckBox):widget.toggled.connect(self.edit)
            else:widget.valueChanged.connect(self.edit)
        # Commit IDs through atomic rename on finish, allowing intermediate text.
        self.id.textChanged.connect(self.identity_changed)
        self.id.editingFinished.connect(self.edit)
        self.preview_level.valueChanged.connect(self.update_preview)
        self.loading=False
        self.update_fields()

    def unit_refs(self):
        return [('召唤物 · '+h.get('name',h['id']),f"self:hero/{h['id']}/{h['variant']}")
                for h in self.project.rows('heroes') if h.get('unitType')=='summon']

    @staticmethod
    def get(widget):
        if isinstance(widget,RefCombo):return widget.value()
        if isinstance(widget,QCheckBox):return widget.isChecked()
        if hasattr(widget,'currentData'):return widget.currentData()
        return widget.value()

    @staticmethod
    def put(widget,value):
        if isinstance(widget,QCheckBox):widget.setChecked(bool(value))
        elif isinstance(widget,RefCombo):widget.set_value(value)
        elif hasattr(widget,'findData'):widget.setCurrentIndex(widget.findData(value))
        else:widget.setValue(value)

    def bind(self,skill,action_index=0):
        self.loading=True;self.skill=skill;self.selected=-1
        self.id.setText(skill['id']);self.name.setText(skill['name']);self.description.setPlainText(skill['description']);self.rank.setPlainText(skill['rankInfoTemplate'])
        self.warmup.setValue(skill['warmup']);self.cooldown.setValue(skill['cooldown']);self.reach.setValue(skill['range']);self.maxlevel.setValue(skill['maxLevel'])
        self.trigger.setCurrentIndex(self.trigger.findData(skill['trigger']['kind']))
        for key,widget in self.event_fields.items():
            self.put(widget,skill['trigger'].get(key,{'event':EVENTS[0],'maxPerRound':1,'allowChain':False,'relation':'any','unitType':'any','minAmount':0,'hpBelow':1}.get(key)))
        self.trigger_buff.setCurrentIndex(self.trigger_buff.findData(skill['trigger'].get('buff','purify')))
        self.rebuild();self.loading=False;self.actions.setCurrentRow(min(action_index,len(skill['actions'])-1));self.update_fields();self.update_preview()

    def rebuild(self):
        self.actions.clear()
        for i,a in enumerate(self.skill['actions']):self.actions.addItem(f"{i} · {OPERATIONS[a['type']]} · {TARGETS[a.get('target','self')]}")

    def select(self,index):
        if self.loading:return
        self.flush();self.selected=index
        if not 0<=index<len(self.skill['actions']):return
        self.loading=True;a={**DEFAULTS,**self.skill['actions'][index]}
        self.kind.setCurrentIndex(self.kind.findData(a['type']));self.target.setCurrentIndex(self.target.findData(a['target']))
        for key,widget in self.fields.items():self.put(widget,a[key])
        for key,widget in self.growth.items():widget.setValue(a['growth'].get(key,0))
        self.loading=False
        self.update_fields()

    def update_fields(self):
        kind=self.kind.currentData();target=self.target.currentData();buff=self.fields['buff'].currentData()
        active={'effect'}
        if target in ('previous','enemy_radius'):active.add('centerAction')
        if target in ('ally_radius','enemy_radius'):active.add('radius')
        if target=='enemy_radius':active.add('excludeCenter')
        if kind in ('heal','damage') or (kind=='buff' and buff=='shield'):active.add('attackRatio')
        if kind=='heal' or (kind=='buff' and buff=='shield'):active.add('maxHpRatio')
        if kind=='buff':active.update(('buff','duration','amount'))
        if kind in ('push','move'):active.add('distance')
        if kind=='summon':active.update(('unit','statRatio','lifetime','maxAlive'))
        if kind=='damage':active.add('damageType')
        event_mode=self.trigger.currentData()=='event'
        if event_mode and (kind in ('heal','damage') or kind=='buff' and buff=='shield'):active.update(('eventRatio','overhealRatio'))
        for widget in self.event_fields.values():self.header_form.setRowVisible(widget,event_mode)
        for key,widget in self.fields.items():self.action_form.setRowVisible(widget,key in active)
        for key,widget in self.growth.items():self.action_form.setRowVisible(widget,key in active)
        self.trigger_buff.setEnabled(self.trigger.currentData()=='absent_buff')

    def flush(self):
        if self.loading or self.skill is None:return
        identity=self.id.text().strip()
        if identity != self.skill.get('id'):
            index=next(i for i,row in enumerate(self.project.rows('skills')) if row is self.skill)
            self.project.rename('skills',index,identity)
        self.skill.update(name=self.name.text().strip(),description=self.description.toPlainText(),rankInfoTemplate=self.rank.toPlainText(),
                          warmup=self.warmup.value(),cooldown=self.cooldown.value(),range=self.reach.value(),maxLevel=self.maxlevel.value(),
                          trigger={'kind':self.trigger.currentData()})
        if self.trigger.currentData()=='absent_buff':self.skill['trigger']['buff']=self.trigger_buff.currentData()
        elif self.trigger.currentData()=='event':
            self.skill['trigger'].update({k:self.get(w) for k,w in self.event_fields.items() if self.get(w) is not None})
        if 0<=self.selected<len(self.skill['actions']):
            a={key:self.get(widget) for key,widget in self.fields.items()}
            if a['unit']=='':a['unit']=None
            if a['effect']=='':a['effect']=None
            a.update(type=self.kind.currentData(),target=self.target.currentData(),
                     growth={key:w.value() for key,w in self.growth.items() if w.value()!=0})
            if a['type']!='summon':a['unit']=None
            self.skill['actions'][self.selected]=a

    def identity_changed(self,*_):
        if not self.loading:self.changed.emit()

    def edit(self,*_):
        if self.loading:return
        try:self.flush()
        except ModError as exc:
            self.error.emit(str(exc));return
        self.update_fields();self.update_preview();self.changed.emit()
        if 0<=self.selected<self.actions.count():
            a=self.skill['actions'][self.selected];self.actions.item(self.selected).setText(f"{self.selected} · {OPERATIONS[a['type']]} · {TARGETS[a['target']]}")

    def update_preview(self,*_):
        if self.skill is None:return
        level=min(self.preview_level.value(),self.skill['maxLevel'])
        inverse={4:'radius',5:'attackRatio',6:'maxHpRatio',7:'amount',9:'duration',10:'distance',12:'statRatio',13:'lifetime',14:'maxAlive',18:'eventRatio',19:'overhealRatio'}
        def token(m):
            try:
                a={**DEFAULTS,**self.skill['actions'][int(m[2])]};key=inverse[int(m[3])]
                v=a[key]+a['growth'].get(key,0)*(level-1)
                return (f'{math.floor(v*10000+.5)/100:g}%') if m[1]=='rank' else str(math.floor(v+.5))
            except (IndexError,KeyError,ValueError):return '【无效绑定】'
        self.preview.setText(f'等级 {level} 实际参数说明\n'+re.sub(r'\{(rank|flat):(\d+):(\d+)\}',token,self.skill['rankInfoTemplate']))

    def add(self):
        if self.skill is None:return
        if len(self.skill['actions']) >= 32:
            self.error.emit('效果序列最多包含 32 个步骤。');return
        self.flush();self.skill['actions'].append({'type':'heal',**copy.deepcopy(DEFAULTS)})
        self.loading=True;self.rebuild();self.loading=False;self.selected=-1;self.actions.setCurrentRow(len(self.skill['actions'])-1);self.changed.emit()

    def move_action(self,old,new):
        if not 0<=old<len(self.skill['actions']) or not 0<=new<len(self.skill['actions']):return
        self.flush();order=list(range(len(self.skill['actions'])));order.insert(new,order.pop(old));mapping={before:after for after,before in enumerate(order)}
        for i,a in enumerate(self.skill['actions']):
            center=a.get('centerAction',-1)
            if center>=0 and mapping[center]>=mapping[i]:self.error.emit('依赖中心的步骤必须位于中心动作之后。');return
        self.skill['actions']=[self.skill['actions'][i] for i in order]
        for a in self.skill['actions']:
            if a.get('centerAction',-1)>=0:a['centerAction']=mapping[a['centerAction']]
        self.skill['rankInfoTemplate']=re.sub(r'\{(rank|flat):(\d+):',lambda m:'{'+m[1]+':'+str(mapping.get(int(m[2]),int(m[2])))+':',self.skill['rankInfoTemplate'])
        self.bind(self.skill,new);self.changed.emit()

    def remove(self):
        self.flush();index=self.selected
        if len(self.skill['actions'])<=1 or index<0:return
        if any(a.get('centerAction')==index for a in self.skill['actions']) or re.search(r'\{(?:rank|flat):'+str(index)+':',self.skill['rankInfoTemplate']):
            self.error.emit('此步骤仍被目标或说明引用，请先解除引用。');return
        self.skill['actions'].pop(index)
        for a in self.skill['actions']:
            if a.get('centerAction',-1)>index:a['centerAction']-=1
        self.skill['rankInfoTemplate']=re.sub(r'\{(rank|flat):(\d+):',lambda m:'{'+m[1]+':'+str(int(m[2])-(int(m[2])>index))+':',self.skill['rankInfoTemplate'])
        self.bind(self.skill,max(0,index-1));self.changed.emit()
