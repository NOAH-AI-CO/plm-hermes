'use strict';

// Actual report extension + actual WebUI Markdown parser. The host drawing
// service is stubbed so these tests isolate when/how the extension requests it.
// Verify real Mermaid SVG rendering separately in the deployed browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { JSDOM } = require('jsdom');

const repo = path.resolve(__dirname, '../..');
const ui = fs.readFileSync(path.join(repo, 'webui/static/ui.js'), 'utf8');
const extension = fs.readFileSync(process.env.PLM_REPORT_TEST_SOURCE || path.join(repo, 'hermes-config/webui-extensions/noah/noah-plm-panels.js'), 'utf8');
function between(source, start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, 'Markdown parser source boundaries changed');
  return source.slice(a, b);
}
const markdown = between(ui, 'const esc=', '/**\n * Render fenced code blocks') + '\n' +
  between(ui, 'const _IMAGE_EXTS=', '// ── Media playback speed controls') + '\n' +
  between(ui, 'function renderMd(raw){', 'function _stripAttachedFilesMarkerForDisplay');
const diagram = '```mermaid\nflowchart TD\nA["开始"] -->|"条件成立"| B["处理"]\n```';
const report = {
  __plm_report__: true, status: 'ready', primary_organization: 'NCCN',
  diagnosis: '## 诊断\n' + diagram,
  examination: '## 检查\n' + diagram,
  treatment: '## 治疗\n' + diagram,
  comprehensive: '## 综合报告\n' + diagram,
};

async function harness(t, initial, options = {}) {
  const dom = new JSDOM('<!doctype html><body><div class="msg-body"></div></body>', {
    url: 'https://example.test/plm-hermes/', runScripts: 'outside-only', pretendToBeVisual: true,
  });
  t.after(() => dom.window.close());
  const w = dom.window;
  await new Promise(resolve => w.addEventListener('load', resolve, { once: true }));
  const frames = [], streams = [], draws = [], fetches = [];
  w.requestAnimationFrame = fn => { frames.push(fn); return frames.length; };
  w.setInterval = () => 1;
  w.console.log = () => {};
  w.fetch = async url => {
    fetches.push(url);
    return { json: async () => report };
  };
  w.EventSource = class {
    constructor(url) { this.url = url; this.closed = false; streams.push(this); }
    close() { this.closed = true; }
    emit(event, payload = {}) {
      if (!this.closed) this.onmessage({ data: JSON.stringify({ event, payload }) });
    }
  };
  w.eval(markdown);
  if (options.renderer !== false) {
    w.renderMermaidBlocks = panel => {
      assert(panel.isConnected, 'drawing must happen after DOM attachment');
      assert(panel.classList.contains('active'), 'draw request must target the active panel');
      for (const block of panel.querySelectorAll('.mermaid-block:not([data-rendered])')) {
        draws.push(block.textContent);
        block.dataset.rendered = 'true';
        block.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60"><text>test drawing</text></svg>';
      }
    };
  }
  const message = w.document.querySelector('.msg-body');
  const marker = () => {
    const pre = w.document.createElement('pre');
    pre.textContent = JSON.stringify(initial);
    return pre;
  };
  message.appendChild(marker());
  w.eval(extension);
  const flush = async () => {
    for (let i = 0; i < 5; i++) {
      await new Promise(resolve => setImmediate(resolve));
      for (const fn of frames.splice(0)) fn();
    }
  };
  const panel = name => message.querySelector(`.noah-plm-panel[data-label="${name}"]`);
  const click = name => [...message.querySelectorAll('.noah-plm-tab')].find(b => b.textContent === name).click();
  return { w, message, marker, flush, panel, click, streams, draws, fetches };
}

test('inline report draws after mount, and a hidden section draws when selected', async t => {
  const h = await harness(t, report);
  assert.equal(h.draws.length, 0);
  await h.flush();
  assert.equal(h.panel('诊断').querySelectorAll('svg').length, 1);
  h.click('治疗'); await h.flush();
  assert.equal(h.panel('治疗').querySelectorAll('svg').length, 1);
  h.click('诊断'); await h.flush();
  assert.equal(h.draws.length, 2, 'revisiting a rendered panel must not duplicate its SVG');
});

test('stream chunks do not repeatedly draw; completed result renders all visited sections', async t => {
  const h = await harness(t, { __plm_report__: true, report_id: 'test-report' });
  const stream = h.streams[0];
  for (const chunk of [diagram.slice(0, -3), diagram.slice(-3), '\n补充说明']) {
    stream.emit('section_chunk', { section: 'diagnosis', text: chunk });
    await h.flush();
  }
  h.click('诊断'); await h.flush();
  assert.equal(h.draws.length, 0);
  stream.emit('result'); await h.flush();
  assert(stream.closed);
  assert.equal(h.fetches.length, 1);
  for (const section of ['诊断', '检查', '治疗', '综合报告']) {
    h.click(section); await h.flush();
    assert.equal(h.panel(section).querySelectorAll('svg').length, 1, section);
  }
  assert.equal(h.panel('综合报告').querySelectorAll('.noah-plm-dlbtn').length, 2);
});

test('section_done draws a stable section without waiting for the whole report', async t => {
  const h = await harness(t, { __plm_report__: true, report_id: 'section-done' });
  h.streams[0].emit('section_chunk', { section: 'diagnosis', text: diagram });
  await h.flush(); assert.equal(h.draws.length, 0);
  h.streams[0].emit('section_done', { section: 'diagnosis' });
  await h.flush(); assert.equal(h.panel('诊断').querySelectorAll('svg').length, 1);
});

test('history restoration remounts the same panel without reconnecting or duplicate drawings', async t => {
  const h = await harness(t, { __plm_report__: true, report_id: 'history-report' });
  const wrap = h.message.querySelector('.noah-plm-report');
  wrap.remove();
  h.streams[0].emit('_done'); await h.flush();
  assert.equal(h.draws.length, 0, 'detached response must not draw');
  h.message.appendChild(h.marker()); h.w.__noahScanPlmPanels(); await h.flush();
  assert.equal(h.message.querySelector('.noah-plm-report'), wrap);
  assert.equal(h.streams.length, 1);
  assert.equal(h.panel('诊断').querySelectorAll('svg').length, 1);
});

for (const complete of [true, false]) {
  test(`stopping a stream only draws a complete Mermaid fence (${complete})`, async t => {
    const h = await harness(t, { __plm_report__: true, report_id: 'stop-report' });
    h.streams[0].emit('section_chunk', { section: 'diagnosis', text: complete ? diagram : diagram.slice(0, -3) });
    await h.flush(); h.w.noahStopReport(); await h.flush();
    assert.equal(h.panel('诊断').querySelectorAll('svg').length, complete ? 1 : 0);
    assert(h.streams[0].closed);
  });
}

test('older host without a Mermaid renderer still displays report text', async t => {
  const h = await harness(t, report, { renderer: false });
  await h.flush();
  assert.match(h.panel('诊断').textContent, /flowchart TD/);
});
