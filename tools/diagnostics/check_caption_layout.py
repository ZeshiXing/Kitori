"""Real Qt WebEngine layout verification on synthetic text, no audio/network."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
from pathlib import Path
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

root = Path(__file__).resolve().parents[2]
web = root / 'jcaption/web'
app = QApplication([])
view = QWebEngineView()
view.resize(460, 300)
source = (web / 'layout.js').read_text(encoding='utf-8') + '\n' + (web / 'app.js').read_text(encoding='utf-8').split('const stream =')[0]
html = '''<html><meta charset="utf-8"><style>body{margin:0}#caption{font:32px sans-serif;line-height:1.8;width:430px;overflow-wrap:anywhere}rt{font-size:.45em}</style><div id="caption"></div><div id="phase"></div><div id="history"></div><div id="connection"></div><script>''' + source + '''
window.verifyLayout=()=>{
 const text='今日は日本語の字幕を見ながら長い台詞が二行に収まるか確認しています。'.repeat(6);
 const line={text,stable_text:text.slice(0,30),draft_text:text.slice(30),phase:'draft',ruby:[{start:0,end:2,surface:'今日',reading:'きょう',stable:true}]};
 const sizes=[430,260,700],results=[];
 for(const width of sizes){
  caption.style.width=width+'px';
  const result=fitCaptionRows(line,2,value=>{renderLine(caption,value);return caption;});
  results.push({width,rows:result.rows,trimmed:result.trimmed,nonempty:!!caption.textContent,suffix:caption.textContent.endsWith('確認しています。')});
 }
 const short={text:'今日',stable_text:'今日',phase:'final',ruby:[{start:0,end:2,surface:'今日',reading:'きょう',stable:true}]};
 renderLine(caption,short);results.push({ruby_rows:captionBodyRows(caption),ruby_count:caption.querySelectorAll('ruby').length});
 return results;
};</script></html>'''
def finished(ok):
    if not ok:
        raise RuntimeError('WebEngine document failed to load')
    def checked(result):
        result = json.loads(result) if result else None
        print(json.dumps(result), flush=True)
        valid = (result and all(r['rows'] <= 2 and r['nonempty'] and r['suffix'] and r['trimmed'] > 0 for r in result[:3])
                 and result[-1]['ruby_rows'] == 1 and result[-1]['ruby_count'] == 1)
        app.exit(0 if valid else 1)
    view.page().runJavaScript('JSON.stringify(window.verifyLayout())', checked)
view.loadFinished.connect(finished)
QTimer.singleShot(20000, lambda: app.exit(2))
view.setHtml(html)
view.show()
sys.exit(app.exec())
