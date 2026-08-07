/**
 * 每日简报浏览页——勾选加载、生成报告、补灌记忆、任务轮询。
 * 卡片交互改自 ai-research-pipeline 的 webapp/static/js/briefs.js：默认
 * 收起，只露标题+徽章+中文导读第一条（点击卡片头展开/收起）；English
 * brief/原文摘录/为何值得看等英文或次要内容折叠进"更多信息"，不与中文
 * 导读抢视觉焦点。
 */
(function () {
  const dateSelect = document.getElementById('brief-date-select');
  const pdfList = document.getElementById('brief-pdf-list');
  const webList = document.getElementById('brief-web-list');
  const pdfCount = document.getElementById('brief-pdf-count');
  const webCount = document.getElementById('brief-web-count');
  const jobsTbody = document.getElementById('jobs-tbody');
  const pdfToggleAllBtn = document.getElementById('pdf-toggle-all-btn');
  const webToggleAllBtn = document.getElementById('web-toggle-all-btn');

  const STATUS_LABELS = {
    not_loaded: '未加载', queued: '排队中', done: '已完成', failed: '失败',
  };

  let currentDate = null;

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function renderCnBlock(cn) {
    const entries = Object.entries(cn || {});
    if (!entries.length) {
      // 没有中文导读——通常是那一批简报生成时没开 --llm（parser 已经把
      // "本次未启用 LLM" 那句占位提示过滤掉了，不会当真导读显示）。收起
      // 态需要一行占位说明，否则这张卡看起来就是"标题一句话，别的卡都
      // 有摘要就它没有"，像是加载失败而不是数据本身就没有。
      return '<div class="cn-block"><div class="cn-item cn-empty">（本条暂无中文导读）</div></div>';
    }
    const rows = entries.map(([label, body]) =>
      `<div class="cn-item"><span class="cn-label">${escapeHtml(label)}：</span>${escapeHtml(body)}</div>`
    );
    return `<div class="cn-block">${rows.join('')}</div>`;
  }

  function renderCard(card) {
    const statusLabel = STATUS_LABELS[card.status] || card.status;
    const selectable = card.status === 'not_loaded' || card.status === 'failed';

    const chips = [];
    if (card.score) chips.push(`<span class="score-chip">${escapeHtml(card.score)}</span>`);
    if (card.topic_tag) chips.push(`<span class="score-chip">${escapeHtml(card.topic_tag)}</span>`);

    const themes = (card.themes || [])
      .map((t) => `<span class="theme-chip">${escapeHtml(t)}</span>`).join('');

    const links = [];
    if (card.url) links.push(`<a href="${escapeHtml(card.url)}" target="_blank" rel="noopener">原文 ↗</a>`);
    if (card.pdf_url) links.push(`<a href="${escapeHtml(card.pdf_url)}" target="_blank" rel="noopener">PDF ↗</a>`);

    // 只保留中文内容：不展示 english_brief/excerpt（原文英文摘要/原文
    // 摘录）；why 字段目前是固定的英文模板句（"Recent submission with
    // strong AI 与 Agents relevance..."），对所有卡片完全相同、没有信息量，
    // 同样不展示。作者/日期这类元信息折叠进"更多信息"。
    const extras = [];
    if (card.followup) extras.push(`<p><strong>后续可追问：</strong>${escapeHtml(card.followup)}</p>`);
    if (card.authors) extras.push(`<p>${escapeHtml(card.authors)}</p>`);

    let errNote = '';
    if (card.status === 'failed' && card.last_error) {
      errNote = `<p class="meta" style="color:var(--danger-color)">上次失败: ${escapeHtml(card.last_error)}</p>`;
    }

    const article = document.createElement('article');
    article.className = 'brief-card' + (card.status === 'done' ? ' is-done' : '');
    article.dataset.itemId = card.item_id;
    article.innerHTML = `
      <div class="card-check">
        <input type="checkbox" class="brief-checkbox" value="${escapeHtml(card.item_id)}" ${selectable ? '' : 'disabled'} ${selectable ? 'checked' : ''}>
      </div>
      <div class="card-body">
        <div class="card-head">
          <h3 class="card-title">${escapeHtml(card.title || card.url || card.item_id)}</h3>
          <span class="status-badge status-${card.status}">${statusLabel}</span>
          ${chips.join('')}
          <span class="card-toggle">▶</span>
        </div>
        ${themes ? `<div class="themes">${themes}</div>` : ''}
        ${renderCnBlock(card.cn)}
        ${errNote}
        <div class="card-links">${links.join('')}</div>
        ${extras.length ? `<details class="more"><summary>更多信息</summary><div class="more-body">${extras.join('')}</div></details>` : ''}
      </div>
    `;
    article.querySelector('.card-head').addEventListener('click', (e) => {
      if (e.target.closest('.card-check')) return;
      article.classList.toggle('expanded');
      // 单张卡片手动展开/收起后，同步一下所在分区"全部展开/收起"按钮的
      // 文案，否则手动点开几张后按钮还显示"全部展开"，点一下却把已经
      // 展开的也强制收起，行为和文案对不上。closest 在这里能拿到正确
      // 的列表容器，因为此时 article 已经挂在 DOM 里了（渲染阶段还没
      // append，这里是点击时才执行）。
      const listEl = article.closest('.card-list');
      const btn = listEl === pdfList ? pdfToggleAllBtn : listEl === webList ? webToggleAllBtn : null;
      syncToggleAllLabel(listEl, btn);
    });
    return article;
  }

  async function loadDates() {
    const res = await fetch('/api/v1/briefs/dates');
    const data = await res.json();
    dateSelect.innerHTML = data.dates.map((d) => `<option value="${d}">${d}</option>`).join('');
    if (data.dates.length) currentDate = data.dates[0];
  }

  async function loadCards() {
    currentDate = dateSelect.value;
    if (!currentDate) return;
    const res = await fetch(`/api/v1/briefs/cards?coverage_date=${encodeURIComponent(currentDate)}`);
    const data = await res.json();

    pdfCount.textContent = data.pdf.length;
    webCount.textContent = data.web.length;

    pdfList.innerHTML = '';
    if (data.pdf.length) {
      data.pdf.forEach((card) => pdfList.appendChild(renderCard(card)));
    } else {
      pdfList.innerHTML = '<p class="meta">暂无</p>';
    }

    webList.innerHTML = '';
    if (data.web.length) {
      data.web.forEach((card) => webList.appendChild(renderCard(card)));
    } else {
      webList.innerHTML = '<p class="meta">暂无</p>';
    }

    syncToggleAllLabel(pdfList, pdfToggleAllBtn);
    syncToggleAllLabel(webList, webToggleAllBtn);
  }

  // 一个分区（论文/文章）内"全部展开/收起"——每次点按当前状态取反：
  // 只要还有卡片是收起的就全部展开，否则全部收起。用户点了"折叠论文，
  // 直接看文章部分"这个诉求就是靠这个按钮，而不是一张张点。
  function syncToggleAllLabel(listEl, btn) {
    if (!btn) return;
    const cards = listEl.querySelectorAll('.brief-card');
    const expandedCount = listEl.querySelectorAll('.brief-card.expanded').length;
    btn.textContent = expandedCount === cards.length && cards.length > 0 ? '全部收起' : '全部展开';
  }

  function toggleAllInSection(listEl, btn) {
    const cards = [...listEl.querySelectorAll('.brief-card')];
    const shouldExpand = listEl.querySelectorAll('.brief-card.expanded').length < cards.length;
    cards.forEach((card) => card.classList.toggle('expanded', shouldExpand));
    syncToggleAllLabel(listEl, btn);
  }

  pdfToggleAllBtn.addEventListener('click', () => toggleAllInSection(pdfList, pdfToggleAllBtn));
  webToggleAllBtn.addEventListener('click', () => toggleAllInSection(webList, webToggleAllBtn));

  async function loadJobs() {
    const res = await fetch('/api/v1/jobs');
    const data = await res.json();
    jobsTbody.innerHTML = data.jobs.slice(0, 20).map((j) => {
      // 排队中/运行中都能取消；"cancelling"是已发起取消、等待收尾的
      // 中间态，不能再点一次（避免重复调用 cancel）。
      const cancellable = j.status === 'queued' || j.status === 'running';
      const action = cancellable
        ? `<button class="job-cancel-btn" data-job-id="${escapeHtml(j.job_id)}">取消</button>`
        : (j.status === 'cancelling' ? '取消中…' : '');
      return `
      <tr>
        <td>${escapeHtml(j.target)}</td>
        <td>${escapeHtml(j.kind)}</td>
        <td>${escapeHtml(j.status)}</td>
        <td>${escapeHtml(j.created_at || '')}</td>
        <td>${escapeHtml(j.error || '')}</td>
        <td>${action}</td>
      </tr>`;
    }).join('');

    jobsTbody.querySelectorAll('.job-cancel-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = '取消中…';
        try {
          const res = await fetch(`/api/v1/jobs/${encodeURIComponent(btn.dataset.jobId)}/cancel`, { method: 'POST' });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || `HTTP ${res.status}`);
          }
        } catch (err) {
          alert(`取消失败：${err.message}`);
        }
        loadJobs();
      });
    });
  }

  document.getElementById('load-selected-btn').addEventListener('click', async () => {
    const coverageDate = dateSelect.value;
    const itemIds = Array.from(document.querySelectorAll('.brief-checkbox:checked')).map((el) => el.value);
    if (!itemIds.length) {
      alert('请先勾选要加载的条目');
      return;
    }
    const res = await fetch('/api/v1/briefs/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coverage_date: coverageDate, item_ids: itemIds }),
    });
    const data = await res.json();
    alert(`已排队 ${data.queued}/${data.requested} 个任务`);
    await loadCards();
    loadJobs();
  });

  document.getElementById('render-report-btn').addEventListener('click', async () => {
    const coverageDate = dateSelect.value;
    if (!coverageDate) return;
    await fetch('/api/v1/briefs/render-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coverage_date: coverageDate }),
    });
    alert('报告生成任务已排队');
    loadJobs();
  });

  document.getElementById('sync-memory-btn').addEventListener('click', async () => {
    await fetch('/api/v1/briefs/sync-memory', { method: 'POST' });
    alert('补灌任务已排队');
    loadJobs();
  });

  dateSelect.addEventListener('change', loadCards);

  (async function init() {
    await loadDates();
    await loadCards();
    await loadJobs();
    setInterval(loadJobs, 5000);
  })();
})();
