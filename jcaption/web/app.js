const caption = document.getElementById('caption');
const phase = document.getElementById('phase');
const history = document.getElementById('history');
const connection = document.getElementById('connection');
let latestSequence = -1;
let latestSession = null;

function renderLine(target, line) {
  const characters = Array.from(line.text);
  const stableLength = Array.from(line.stable_text).length;
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  function plain(start, end) {
    if (end <= start) return;
    if (line.phase === 'draft' && start < stableLength && end > stableLength) {
      plain(start, stableLength);
      plain(stableLength, end);
      return;
    }
    const part = document.createElement('span');
    part.textContent = characters.slice(start, end).join('');
    if (end > stableLength && line.phase === 'draft') part.className = 'draft';
    fragment.appendChild(part);
  }
  for (const token of line.ruby || []) {
    if (token.start < cursor || characters.slice(token.start, token.end).join('') !== token.surface) continue;
    plain(cursor, token.start);
    if (token.reading) {
      const ruby = document.createElement('ruby');
      ruby.appendChild(document.createTextNode(token.surface));
      const reading = document.createElement('rt');
      reading.textContent = token.reading;
      ruby.appendChild(reading);
      if (!token.stable && line.phase === 'draft') ruby.className = 'draft';
      fragment.appendChild(ruby);
    } else plain(token.start, token.end);
    cursor = token.end;
  }
  plain(cursor, characters.length);
  target.replaceChildren(fragment);
}

const stream = new EventSource('/events');
stream.onopen = () => { connection.textContent = '已连接'; };
stream.onerror = () => { connection.textContent = '连接中断，正在重连'; };
stream.onmessage = message => {
  const state = JSON.parse(message.data);
  if (state.session_id !== latestSession) {
    latestSession = state.session_id;
    latestSequence = -1;
    caption.textContent = '播放视频后，字幕会在这里出现。';
    phase.textContent = '等待日语声音';
    history.replaceChildren();
    document.getElementById('backend').textContent = '';
  }
  if (state.sequence < latestSequence) return;
  latestSequence = state.sequence;
  if (!state.current) return;
  const current = state.current;
  phase.textContent = current.phase === 'final' ? '本句已完成' : current.phase === 'cancelled' ? '等待日语声音' : '正在听取 · 字幕持续更新';
  renderLine(caption, current);
  const lines = state.history.slice(-3).map(line => {
    const row = document.createElement('div'); row.className = 'history-line'; renderLine(row, line); return row;
  });
  history.replaceChildren(...lines);
  document.getElementById('backend').textContent = current.backend === 'windows_livecaptions' ? 'Windows Live Captions' : '本地识别';
};
