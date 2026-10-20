// Reuse the existing ruby renderer and browser layout. Count body-text rows;
// rt annotations do not count as another subtitle line. No ASR text is changed.
function captionBodyRows(target) {
  const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
  const bottoms = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent.trim() || node.parentElement.closest('rt')) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    for (const rect of range.getClientRects()) {
      if (rect.width < .1 || rect.height < .1) continue;
      if (!bottoms.some(y => Math.abs(y - rect.bottom) < Math.max(3, rect.height * .18))) bottoms.push(rect.bottom);
    }
  }
  return bottoms.length;
}
function captionSuffix(line, start) {
  const chars = Array.from(line.text), stable = Array.from(line.stable_text).length;
  return {...line, text:chars.slice(start).join(''),
    stable_text:chars.slice(start, Math.max(start,stable)).join(''),
    draft_text:chars.slice(Math.max(start,stable)).join(''),
    ruby:(line.ruby || []).filter(token => token.start >= start).map(token =>
      ({...token,start:token.start-start,end:token.end-start}))};
}
function fitCaptionRows(line, maxRows, draw) {
  const chars = Array.from(line.text);
  let target = draw(line), rows = captionBodyRows(target), start = 0;
  if (rows > maxRows) {
    let low = 0, high = chars.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      target = draw(captionSuffix(line,middle));
      if (captionBodyRows(target) > maxRows) low = middle + 1; else high = middle;
    }
    start = low;
    target = draw(captionSuffix(line,start)); rows = captionBodyRows(target);
    // Ruby words can change their break opportunities when a boundary moves.
    while (rows > maxRows && start < chars.length) {
      target = draw(captionSuffix(line,++start)); rows = captionBodyRows(target);
    }
  }
  return {target,rows,visible:chars.length-start,trimmed:start};
}
