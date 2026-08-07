/**
 * Report 页面——论文/文章摘要卡片浏览。
 * 改自 ai-research-pipeline 的 webapp/static/js/report.js 思路，去掉了
 * QA_LABELS 自带副本（现在由 pages.py 渲染时注入 window.QA_LABELS）。
 */
(function () {
  const dateSelect = document.getElementById('coverage-date-select');
  const pdfList = document.getElementById('pdf-list');
  const webList = document.getElementById('web-list');
  const pdfCount = document.getElementById('pdf-count');
  const webCount = document.getElementById('web-count');

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  function renderQaDetails(qa) {
    const rows = Object.entries(qa || {})
      .filter(([, answer]) => answer)
      .map(([key, answer]) => {
        const label = window.QA_LABELS[key] || key;
        const body = escapeHtml(answer).replace(/\n/g, '<br>');
        return `<dt>${escapeHtml(label)}</dt><dd>${body}</dd>`;
      });
    return `<dl>${rows.join('')}</dl>`;
  }

  function renderPdfCard(s) {
    const title = escapeHtml(s.title || s.doc_name || '');
    const links = [];
    if (s.url) links.push(`<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">arXiv abstract ↗</a>`);
    if (s.pdf_url) links.push(`<a href="${escapeHtml(s.pdf_url)}" target="_blank" rel="noopener">PDF ↗</a>`);

    let deepDiveHint = '';
    if (s.doc_name) {
      deepDiveHint = `<div class="card-actions">
        <button onclick="window.location.href='/chat?doc=${encodeURIComponent(s.doc_name)}'">针对这篇继续提问</button>
        <button class="danger" onclick="deleteItem('${escapeHtml(s.item_id)}')">删除</button>
      </div>`;
    } else {
      deepDiveHint = `<div class="card-actions"><button class="danger" onclick="deleteItem('${escapeHtml(s.item_id)}')">删除</button></div>`;
    }

    return `
    <div class="card">
      <span class="card-badge">已深度解析 · PDF</span>
      <h3>${title}</h3>
      <p class="meta">覆盖日期: ${escapeHtml(s.coverage_date || '')}</p>
      <div class="links">${links.join('')}</div>
      <ul class="qa-brief-list">${Object.entries(s.qa_brief || {}).map(([k, v]) =>
        `<li><b>${escapeHtml(window.QA_LABELS[k] || k)}：</b>${escapeHtml(v)}</li>`).join('')}</ul>
      <details class="deep-qa">
        <summary>展开详细问答</summary>
        ${renderQaDetails(s.qa)}
      </details>
      ${deepDiveHint}
    </div>`;
  }

  function renderWebCard(s) {
    const title = escapeHtml(s.title || s.url || '');
    let deepDiveHint = '';
    if (s.doc_name) {
      deepDiveHint = `<div class="card-actions">
        <button onclick="window.location.href='/chat?doc=${encodeURIComponent(s.doc_name)}'">针对这篇继续提问</button>
        <button class="danger" onclick="deleteItem('${escapeHtml(s.item_id)}')">删除</button>
      </div>`;
    } else {
      deepDiveHint = `<div class="card-actions"><button class="danger" onclick="deleteItem('${escapeHtml(s.item_id)}')">删除</button></div>`;
    }

    return `
    <div class="card">
      <span class="card-badge">已深度解析 · ${escapeHtml(s.processing_strategy || '')}</span>
      <h3>${title}</h3>
      <p class="meta">覆盖日期: ${escapeHtml(s.coverage_date || '')}</p>
      <div class="links"><a href="${escapeHtml(s.url || '')}" target="_blank" rel="noopener">原文链接 ↗</a></div>
      <ul class="qa-brief-list">${Object.entries(s.qa_brief || {}).map(([k, v]) =>
        `<li><b>${escapeHtml(window.QA_LABELS[k] || k)}：</b>${escapeHtml(v)}</li>`).join('')}</ul>
      <details class="deep-qa">
        <summary>展开详细问答</summary>
        ${renderQaDetails(s.qa)}
      </details>
      ${deepDiveHint}
    </div>`;
  }

  async function loadDates() {
    const res = await fetch('/api/v1/report/dates');
    const data = await res.json();
    dateSelect.innerHTML = '<option value="">全部</option>' +
      data.dates.map((d) => `<option value="${d}">${d}</option>`).join('');
  }

  async function loadSummaries() {
    const coverageDate = dateSelect.value;
    const url = coverageDate
      ? `/api/v1/report/summaries?coverage_date=${encodeURIComponent(coverageDate)}`
      : '/api/v1/report/summaries';
    const res = await fetch(url);
    const data = await res.json();

    pdfCount.textContent = data.pdf.length;
    webCount.textContent = data.web.length;
    pdfList.innerHTML = data.pdf.length
      ? data.pdf.map(renderPdfCard).join('')
      : '<p class="empty-hint">暂无</p>';
    webList.innerHTML = data.web.length
      ? data.web.map(renderWebCard).join('')
      : '<p class="empty-hint">暂无</p>';
  }

  window.deleteItem = async function (itemId) {
    const previewRes = await fetch(`/api/v1/report/item/${encodeURIComponent(itemId)}/delete-preview`);
    const preview = await previewRes.json();

    const targets = [];
    if (preview.has_summary && confirm(`删除摘要展示（${itemId}）？`)) targets.push('summary');
    if (preview.in_queue && confirm('同时从处理队列移除？')) targets.push('queue');
    if (confirm('同时删除记忆库中的相关记录？')) targets.push('memory');
    if (preview.has_index && confirm(`同时删除 AgenticReader 索引（doc_name: ${preview.doc_name}）？`)) targets.push('index');

    if (!targets.length) return;

    const res = await fetch(`/api/v1/report/item/${encodeURIComponent(itemId)}/delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ targets }),
    });
    const result = await res.json();
    alert(result.ok ? '删除完成' : '部分删除失败，请查看控制台');
    console.log('delete result', result);
    loadSummaries();
  };

  dateSelect.addEventListener('change', loadSummaries);

  (async function init() {
    await loadDates();
    await loadSummaries();
  })();
})();
