// Runs only in Luna's supported extra-HTML slot. Calls its existing renderer;
// no upstream code is copied. Its private renderer contract is version-sensitive.
const lineId = 'jcaption_stream';
const previousId = 'jcaption_previous';
let last = null, signature = null, style = boot.style, styleargs = boot.styleargs;
let stopped = false, failures = 0;
let preservedNativeClears = 0;
const css = document.createElement('style');
css.textContent = `
  .jcaption-active #luna_root_div_origin > :not(#div${lineId}):not(#div${previousId}) { display:none !important; }
  .jcaption-draft #luna_root_div_trans { display:none !important; }
  .jcaption-idle #luna_root_div_trans { display:none !important; }
  :is(#div${lineId},#div${previousId}) .lunatranslator_text_all { color:var(--jcaption-color) !important; }
  :is(#div${lineId},#div${previousId}) .span_ruby_flag { color:var(--jcaption-color) !important; }
  :is(#div${lineId},#div${previousId}) { --jcaption_shadow:var(--ColorControl_RAW_TEXT_COLOR,#000000); }
  #div${previousId} { opacity:.85; }
`;
document.head.appendChild(css);
// Follow Luna's font/shadow/outline changes without changing its configuration.
const setColors = window.setcolorstyle;
if (typeof setColors === 'function') window.setcolorstyle = function(encoded) {
  const info = JSON.parse(decodeURIComponent(encoded));
  style = info.style; styleargs = info.styleargs; signature = null;
  return setColors.apply(this, arguments);
};
const encode = value => encodeURIComponent(JSON.stringify(value));
function words(line) {
  const chars = Array.from(line.text), stable = Array.from(line.stable_text).length;
  const result = [];
  function plain(start, end) {
    if (start >= end) return;
    if (start < stable && end > stable) { plain(start, stable); plain(stable, end); return; }
    result.push({word:chars.slice(start,end).join(''), kana:'', isdeli:true, stable:end <= stable});
  }
  let cursor = 0;
  for (const token of line.ruby || []) {
    if (token.start < cursor || chars.slice(token.start,token.end).join('') !== token.surface) continue;
    plain(cursor,token.start);
    result.push({word:token.surface, kana:token.reading || '', prototype:token.surface,
                 color:'jcaption_empty', stable:token.end <= stable, orig:token.surface});
    cursor = token.end;
  }
  plain(cursor,chars.length);
  return result;
}
function release() {
  document.documentElement.classList.remove('jcaption-active','jcaption-draft','jcaption-idle');
  document.getElementById('div' + lineId)?.remove();
  document.getElementById('div' + previousId)?.remove();
  last = signature = null;
}
// Luna clears its normal original/translation rows when accepting a sentence.
// Keep only our two extension-owned nodes across that synchronous operation;
// restore them before reporting a new window height, without waiting for a poll.
for (const name of ['clear_all', 'clearparent']) {
  const original = window[name];
  if (typeof original !== 'function') continue;
  window[name] = function(...args) {
    const root = document.getElementById('luna_root_div_origin');
    const rows = [previousId,lineId].map(id=>document.getElementById('div'+id))
      .filter(row=>row?.parentNode === root);
    if (!last?.current?.text || !document.documentElement.classList.contains('jcaption-active') || !rows.length)
      return original.apply(this,args);
    const resize = window.safe_calllunaheightchange;
    rows.forEach(row=>row.remove());
    window.safe_calllunaheightchange = () => {};
    try { return original.apply(this,args); }
    finally {
      rows.forEach(row=>root.appendChild(row));
      preservedNativeClears++;
      window.safe_calllunaheightchange = resize;
      drawBackgrounds(); safe_calllunaheightchange();
    }
  };
}
function drawLine(id, line, state) {
  create_div_line_id(id, encode({texttype:0}));
  const tags = words(line);
  if (tags.length) {
    create_internal_rubytext(false, style, encode(styleargs), id, encode(tags),
                            encode({color:'jcaption_shadow',kanacolor:'jcaption_shadow'}));
  } else document.getElementById(id).replaceChildren();
  const target = document.getElementById(id);
  Array.from(target.children).forEach((element,index) => {
    const color = tags[index]?.stable ? state.colors.stable_color : state.colors.draft_color;
    element.style.setProperty('--jcaption-color',color);
    element.style.setProperty('--jcaption_stable',color);
    element.style.setProperty('--luna_mb_color',color);
  });
  return target;
}
function paint(state) {
  const line = state.current;
  if (!line) {
    document.getElementById('div' + lineId)?.remove();
    document.getElementById('div' + previousId)?.remove();
    document.documentElement.classList.add('jcaption-active','jcaption-idle');
    if (signature !== 'idle') { drawBackgrounds(); safe_calllunaheightchange(); }
    signature = 'idle'; return;
  }
  if (typeof create_internal_rubytext !== 'function' || typeof create_div_line_id !== 'function')
    throw new Error('Unsupported Luna renderer');
  const font = getComputedStyle(document.getElementById('div'+lineId)||document.getElementById('luna_root_div_origin'));
  const next = JSON.stringify([state.session_id, line, state.previous, state.colors, style, styleargs,
    state.max_caption_lines,innerWidth,font.fontSize,font.fontFamily,font.lineHeight]);
  const old = document.getElementById(lineId);
  if (signature === next && old?.dataset.jcaptionPaint === next && (old.childNodes.length || !line.text)) return;
  document.getElementById('div' + previousId)?.remove();
  const resize = window.safe_calllunaheightchange;
  let fitted, retained = {rows:0,visible:0};
  try {
    window.safe_calllunaheightchange = () => {};
    fitted = fitCaptionRows(line,state.max_caption_lines||2,value=>drawLine(lineId,value,state));
    if (state.previous && line.text && fitted.rows < (state.max_caption_lines||2))
      retained = fitCaptionRows(state.previous,(state.max_caption_lines||2)-fitted.rows,
        value=>drawLine(previousId,value,state));
  } finally { window.safe_calllunaheightchange = resize; }
  const target = fitted.target;
  const prior = document.getElementById('div' + previousId);
  const active = document.getElementById('div' + lineId);
  if (prior && prior.parentNode === active.parentNode) active.before(prior);
  target.dataset.jcaptionPaint = next;
  document.documentElement.classList.add('jcaption-active');
  document.documentElement.classList.toggle('jcaption-draft', line.phase === 'draft');
  document.documentElement.classList.toggle('jcaption-idle', !line.text);
  drawBackgrounds(); safe_calllunaheightchange();
  signature = next;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    // Metadata only. Neither the receipt nor routine logs contain caption text.
    const stable = Array.from(line.stable_text).length;
    fetch(boot.url + '/api/luna/paint', {
      method:'POST', headers:{'X-Caption-View':boot.token,'Content-Type':'application/json'},
      body:JSON.stringify({session_id:state.session_id,utterance_id:line.utterance_id,
        revision:line.revision,stable_characters:stable,
        draft_characters:Array.from(line.text).length-stable,
        previous_characters:retained.visible,
        visible_rows:fitted.rows+retained.rows,visible_characters:fitted.visible,
        trimmed_characters:fitted.trimmed,
        preserved_native_clears:preservedNativeClears,
        ruby_count:target.querySelectorAll('ruby').length})
    }).catch(() => {});
  }));
}
async function tick() {
  if (stopped) return;
  try {
    const response = await fetch(boot.url + '/api/luna/state', {
      headers:{'X-Caption-View':boot.token}, cache:'no-store', signal:AbortSignal.timeout(1200)
    });
    if (!response.ok) throw new Error('Caption service unavailable');
    const state = await response.json();
    // Polls are sequential: an earlier session/revision cannot arrive late.
    last = state; paint(state); failures = 0;
  } catch (_) {
    if (++failures >= 3) release(); // Restore Luna's normal display when disconnected.
  }
  if (!stopped) setTimeout(tick,120);
}
window.addEventListener('pagehide', () => { stopped = true; });
tick();
