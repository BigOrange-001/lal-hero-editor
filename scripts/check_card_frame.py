"""Focused anchor, transparency, selection, export/import and merge check."""
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'server')]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PIL import Image
from editor.media import _png,make_card,frame_layers
from editor.core import Project
from editor.catalog import Catalog
from editor.merge import merge_packages
from mod_packages import validate_media,inspect_package
from mod_schema import ModError
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QFontDatabase
from PySide6.QtCore import QRectF
from editor.source_selection import SourceShieldView
from editor.widgets import ImageEditorDialog


def main():
    app=QApplication.instance() or QApplication([])
    if not QFontDatabase.families():QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    source=Image.new('RGBA',(160,160),(60,100,180,255));raw=_png(source)
    view=SourceShieldView(QImage.fromData(raw),6);view.set_rect(QRectF(0,0,103,118))
    mask=view.default_selection()
    with Image.open(BytesIO(view.native['frame'])) as frame:
        alpha=frame.getchannel('A')
        for y in range(118):
            for x in range(103):
                if alpha.getpixel((x,y)):assert mask.pixelColor(x,y).red()==0,(x,y)
    for size,inset in [((160,160),.12),((320,480),.2),((412,472),0)]:
        result=make_card(raw,quality=6,size=size,frame_inset=inset,layer_order='front')
        info=validate_media(result,'card.png')
        assert info['cardFrame']==list(frame_layers(6,size,inset=inset)['bounds'])
        assert info['width']==size[0] and info['height']==size[1]
    image=Image.new('RGBA',(160,160),(0,0,0,0))
    for invalid in [(-1,0,103,118),(0,0,500,118),(0,0,0,0),(0,0,80,80)]:
        try:_png(image,invalid)
        except ModError:pass
        else:raise AssertionError(invalid)
    dialog=ImageEditorDialog(raw)
    assert dialog.layer_order.count()==1 and dialog.recipe()['layerOrder']=='front'
    legacy=ImageEditorDialog(raw,recipe={'box':[0,0,160,160],'size':[160,160],'quality':6,'framed':True,'layerOrder':'behind'})
    assert legacy.recipe()['layerOrder']=='behind'
    catalog=Catalog()
    with tempfile.TemporaryDirectory() as folder:
        paths=[]
        for i in range(2):
            project=Project.new(catalog=catalog);project.manifest['author']='Frame acceptance'
            project.assets['assets/card.png']=make_card(raw,quality=6,size=(160,160),frame_inset=.12)
            project.rows('heroes')[0]['presentation'].update(icon='self:asset/card.png',portrait='self:asset/card.png')
            path=Path(folder)/('card-%d.heropack'%i);project.export(path,catalog=catalog);paths.append(path)
            imported=Project.import_package(path,catalog=catalog)
            assert imported.assets==project.assets
            package=inspect_package(path,catalog.base)
            assert 'asset.image.card-frame' in package.manifest['requiredCapabilities']
            assert package.media['assets/card.png']['cardFrame']==[27,19,106,122]
        merged,_=merge_packages(paths,catalog=catalog,name='Frames',author='Acceptance')
        merged.export(Path(folder)/'merged.heropack',catalog=catalog)
    print('PASS: native frame anchor, transparent margins, border selection holes, fixed stack UI, old recipe, package round-trip and merge')


if __name__=='__main__':main()
