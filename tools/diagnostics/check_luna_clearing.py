"""Synthetic clearing regression using the installed, unmodified Luna renderer."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS','--disable-gpu')
from pathlib import Path
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT=Path(__file__).resolve().parents[2]
upstream=ROOT/'apps/LunaTranslator/LunaTranslator_x64/LunaTranslator/htmlcode/uiwebview/mainui.html'
setup='''<meta charset="utf-8"><script>
window.heightReports=[];
window.LUNAJSObject={calllunaloadready(){},calllunaSizeChanged(h,w){heightReports.push(h);}};
window.fetch=async()=>({ok:true});
</script>'''
extension=(ROOT/'jcaption/web/layout.js').read_text('utf-8')+'\n'+(
    ROOT/'jcaption/web/luna.js').read_text('utf-8').split('async function tick()')[0]
checks='''
window.verifyClearing=()=>{
  const line={utterance_id:1,revision:1,text:'今日は字幕を見る',stable_text:'今日は',phase:'draft',
    ruby:[{start:0,end:2,surface:'今日',reading:'きょう',stable:true}]};
  const state={session_id:'synthetic-clear',current:line,previous:null,max_caption_lines:2,
    colors:{stable_color:'#ffffff',draft_color:'#aaaaaa'}};
  last=state;paint(state);
  const expected=document.getElementById(lineId).textContent;
  diagnosticOriginalClear();
  const original_erases_stream=!document.getElementById(lineId);
  signature=null;paint(state);
  const node=document.getElementById(lineId);
  heightReports=[];clear_all();
  const clear_all_retains_same_node=node===document.getElementById(lineId)&&node.textContent===expected;
  const no_zero_height=heightReports.length>0&&heightReports.every(h=>h>0);
  create_div_line_id('native_sentence',encode({texttype:0}));
  create_internal_text(true,'normal',encode({}),'native_sentence','',encodeURIComponent('通常の原文'),
    encode({color:'ColorControl_RAW_TEXT_COLOR'}));
  const native_text_retains_stream=node===document.getElementById(lineId)&&node.textContent===expected;
  const ruby_retained=node.querySelectorAll('ruby').length>0;
  last={...state,current:{...line,text:'',stable_text:'',ruby:[]}};
  paint(last);clear_all();
  const idle_can_clear=!document.getElementById(lineId);
  release();create_div_line_id('native_after_release',encode({texttype:0}));clear_all();
  const released_native_can_clear=!document.getElementById('native_after_release');
  return {original_erases_stream,clear_all_retains_same_node,no_zero_height,
    native_text_retains_stream,ruby_retained,idle_can_clear,released_native_can_clear};
};
'''
html=setup+upstream.read_text('utf-8')+'''<style>
body{font:28px sans-serif}rt{font-size:.45em}
</style><script>window.diagnosticOriginalClear=window.clear_all;
(()=>{const boot={url:'http://127.0.0.1:0',token:'synthetic',style:'normal',styleargs:{}};
'''+extension+checks+'})();</script>'
app=QApplication([]);view=QWebEngineView();view.resize(700,300)
def finished(ok):
    if not ok:
        app.exit(2);return
    def checked(value):
        result=json.loads(value) if value else {}
        (ROOT/'logs/luna-clearing-check.json').write_text(json.dumps(result,indent=2),'utf-8')
        print(json.dumps(result),flush=True)
        app.exit(0 if result and all(result.values()) else 1)
    view.page().runJavaScript('JSON.stringify(window.verifyClearing())',checked)
view.loadFinished.connect(finished)
QTimer.singleShot(20000,lambda:app.exit(2))
view.setHtml(html);view.show();sys.exit(app.exec())
