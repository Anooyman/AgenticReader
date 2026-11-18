/**
 * 每日简报浏览页——勾选加载、生成报告、补灌记忆、任务轮询，
 * 外加原 /memory 页并档过来的"轻量入库(全天)"（load_brief_date 任务，
 * 卡片导读直接入 A 自库 AATF）。
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

  // 卡片链接区"⬇ 下载入库"的适用判据：arXiv 直链或 .pdf 后缀
  const PDF_SOURCE_RE = /(arxiv\.org|\.pdf)/i;

  let currentDate = null;
  // 各日期的真实入库计数 {"2026-11-12": {aatf, heavy_done}}——来自 A 自库
  // 行 + queue 事实，不是任务账本（bridge 时代的 done 不算 A 自库数据）。
  let memoryCounts = {};

  // 「⬇ 下载入库」本地链路：下载与索引轮询都在共享原语 PaperIngest
  // （paper-ingest.js，/chat 回复按钮同用一份）——这里只把状态画到按钮上。
  async function fetchAndIndex(btn) {
    const url = btn.dataset.url;
    if (!window.PaperIngest) {
      alert('下载入库原语未加载（paper-ingest.js）');
      return;
    }
    btn.disabled = true;
    btn.textContent = '下载中…';
    await window.PaperIngest.start(url, (s) => {
      if (s.phase === 'indexing') {
        // exists 分支现在会如实带话：索引已在位、还是刚补排了一次——有 note
        // 就展示后端的说法，别统一刷成"检查索引…"让用户猜。
        btn.textContent = s.note || (s.status === 'exists' ? '已在 PDF 库，检查索引…' : '已下载，索引中…');
        if (s.note) btn.title = s.note;
      } else if (s.phase === 'indexed') {
        btn.textContent = '✅ 已入库';
        btn.classList.add('ok');
        if (!btn.dataset.deepLink) {
          btn.dataset.deepLink = '1';
          const link = document.createElement('a');
          link.href = '/chat?doc=' + encodeURIComponent(s.docName || '');
          link.target = '_blank'; link.rel = 'noopener';
          link.className = 'deep-read-link';
          link.textContent = '📖 深读 ↗';
          btn.after(link);
        }
      } else if (s.phase === 'timeout') {
        btn.disabled = false;
        btn.textContent = '继续检查索引';
      } else if (s.phase === 'failed') {
        btn.disabled = false;
        btn.textContent = '⬇ 下载入库';
        alert('下载入库失败：' + (s.error || ''));
      }
    });
  }

  async function loadMemoryStatus() {
    try {
      const data = await API.briefs.memoryStatus({ checkOk: false });
      memoryCounts = data.dates || {};
    } catch (err) {
      memoryCounts = {};
    }
    decorateDateOptions();
    renderStatusLine();
    renderIngestPanel();
  }

  // 日期下拉框每项带入库标记：一眼区分"有 HTML 未入库 / 有 HTML 已入库"
  //（无 HTML 的日期本来就不出现在列表里）。
  function decorateDateOptions() {
    for (const opt of dateSelect.options) {
      const c = memoryCounts[opt.value] || { aatf: 0, heavy_done: 0 };
      opt.textContent = (c.aatf || c.heavy_done)
        ? `${opt.value}（AATF ${c.aatf} · 重管线 ${c.heavy_done}）`
        : `${opt.value}（未入库）`;
    }
  }

  function renderStatusLine() {
    const line = document.getElementById('memory-status-line');
    if (!line) return;
    const c = memoryCounts[dateSelect.value] || { aatf: 0, heavy_done: 0 };
    line.textContent = `🧠 该日期入库状态：AATF 轻量档 ${c.aatf} 条 · 重管线 done ${c.heavy_done} 条` +
      (c.aatf === 0 && c.heavy_done === 0
        ? ' —— 还没进任何记忆库：「轻量入库(全天)」秒级写入，「加载选中」走重管线'
        : '');
  }

  // ===== 入库日期面板：跨日期多选批量轻量入库 + 队列可见性 ==================
  // 原 /memory 页 load 视图的归处：每行一天，徽章是 A 自库真实行 + queue
  // 事实（memoryCounts），行尾叠加该日 load job 的实时状态（lastJobs）。
  // 选择状态与上方下拉浏览完全解耦——批量入库不动当前浏览日期。
  let lastJobs = [];

  function ingestJobBadge(date) {
    const job = lastJobs.find(j => j.kind === 'load_brief_date' && j.target === date);
    if (!job) return '';
    const label = {
      queued: '排队中', running: '入库中…', cancelling: '取消中',
      failed: '失败 · 重勾再点可重排队', interrupted: '中断 · 重勾再点可重排队',
      cancelled: '已取消',
    }[job.status] ?? job.status;
    if (job.status === 'done') return '';
    return ` <span class="ingest-job-badge job-${job.status}">${escapeHtml(label)}</span>`;
  }

  function renderIngestPanel() {
    const list = document.getElementById('ingest-date-list');
    if (!list) return;
    // 每 5s 轮询都会重建列表——先记住已勾的，重建后原样恢复，
    // 否则用户刚勾完就被定时刷新清掉了。
    const prevChecked = new Set(checkedIngestDates());
    const opts = Array.from(dateSelect.options);
    list.innerHTML = opts.length
      ? opts.map(opt => {
          const c = memoryCounts[opt.value] || { aatf: 0, heavy_done: 0 };
          const ingested = c.aatf || c.heavy_done;
          const badge = ingested ? `AATF ${c.aatf} · 重管线 ${c.heavy_done}` : '未入库';
          return `<li class="ingest-date-item">` +
            `<label><input type="checkbox" class="ingest-date-cb" value="${escapeHtml(opt.value)}">` +
            `<span class="ingest-date-name">${escapeHtml(opt.value)}</span></label>` +
            `<span class="ingest-date-badge${ingested ? ' is-ok' : ''}">${badge}</span>` +
            `${ingestJobBadge(opt.value)}</li>`;
        }).join('')
      : '<li class="meta">没有可入库的日期（BRIEFS_DIR 为空？）</li>';
    list.querySelectorAll('.ingest-date-cb').forEach(cb => {
      cb.checked = prevChecked.has(cb.value);
      cb.addEventListener('change', updateIngestBulkCount);
    });
    updateIngestBulkCount();
  }

  function checkedIngestDates() {
    return Array.from(document.querySelectorAll('.ingest-date-cb:checked')).map(cb => cb.value);
  }

  function updateIngestBulkCount() {
    const el = document.getElementById('ingest-selected-count');
    if (el) el.textContent = checkedIngestDates().length;
  }

  function updateIngestQueueLine(jobs) {
    lastJobs = jobs || [];
    const line = document.getElementById('ingest-queue-line');
    if (!line) return;
    const active = lastJobs.filter(j => j.kind === 'load_brief_date'
      && ['queued', 'running', 'cancelling'].includes(j.status));
    if (!active.length) { line.textContent = ''; renderIngestPanel(); return; }
    const running = active.filter(j => j.status === 'running').map(j => j.target);
    const queued = active.filter(j => j.status !== 'running').length;
    line.textContent = `加载队列：running ${running.length} · queued ${queued}`
      + (running.length ? `｜正在入库 ${running.join('、')}` : '');
    renderIngestPanel();
  }

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
    // 「⬇下载入库」：只在能推断出 PDF 来源的卡片上出现（arXiv 直链/显式
    // PDF 链接），点了走本地 fetch-pdf + IndexingAgent，不再依赖外部服务。
    const pdfTarget = (card.pdf_url && PDF_SOURCE_RE.test(card.pdf_url)) ? card.pdf_url
                    : (PDF_SOURCE_RE.test(card.url || '') ? card.url : null);
    if (pdfTarget) {
      links.push(`<button type="button" class="fetch-pdf-btn" data-url="${escapeHtml(pdfTarget)}">⬇ 下载入库</button>`);
    }

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
        <input type="checkbox" class="brief-checkbox" value="${escapeHtml(card.item_id)}" ${selectable ? '' : 'disabled'}>
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
    article.querySelectorAll('.fetch-pdf-btn').forEach((btn) => {
      btn.addEventListener('click', () => fetchAndIndex(btn));
    });
    return article;
  }

  async function loadDates() {
    const data = await API.briefs.dates({ checkOk: false });
    dateSelect.innerHTML = data.dates.map((d) => `<option value="${d}">${d}</option>`).join('');
    if (data.dates.length) currentDate = data.dates[0];
    renderIngestPanel();
  }

  async function loadCards() {
    currentDate = dateSelect.value;
    if (!currentDate) return;
    const data = await API.briefs.cards(currentDate, { checkOk: false });

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
    const data = await API.jobs.list({ checkOk: false });
    updateIngestQueueLine(data.jobs);
    jobsTbody.innerHTML = data.jobs.slice(0, 20).map((j) => {
      // 排队中/运行中都能取消；"cancelling"是已发起取消、等待收尾的
      // 中间态，不能再点一次（避免重复调用 cancel）。failed/interrupted
      // 给重试入口——retry 端点一直活着，之前只是这张表没配按钮。
      const cancellable = j.status === 'queued' || j.status === 'running';
      const retryable = j.status === 'failed' || j.status === 'interrupted';
      const action = cancellable
        ? `<button class="job-cancel-btn" data-job-id="${escapeHtml(j.job_id)}">取消</button>`
        : (j.status === 'cancelling' ? '取消中…'
           : (retryable ? `<button class="job-retry-btn" data-job-id="${escapeHtml(j.job_id)}">重试</button>` : ''));
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
          await API.jobs.cancel(btn.dataset.jobId);
        } catch (err) {
          alert(`取消失败：${err.message}`);
        }
        loadJobs();
      });
    });
    jobsTbody.querySelectorAll('.job-retry-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = '重排队…';
        try {
          await API.jobs.action(btn.dataset.jobId, 'retry');
        } catch (err) {
          alert(`重试失败：${err.message}`);
          btn.disabled = false;
          btn.textContent = '重试';
          return;
        }
        loadJobs();
      });
    });
    // 任务账本每 5s 刷一次，顺带刷入库状态——load_brief_date 跑完后
    // 下拉框/状态行的 AATF 计数要跟上，不用手动刷新页面。
    loadMemoryStatus();
  }

  document.getElementById('select-all-btn').addEventListener('click', () => {
    // 每次点按当前状态取反：只要还有未勾选的可选项就全选，否则全部取消——
    // 跟"全部展开/收起"按钮同一套交互逻辑，避免误点全选之后想撤销还得
    // 一条条取消。disabled 的（已加载/排队中）checkbox 天然跳过。
    const boxes = [...document.querySelectorAll('.brief-checkbox:not(:disabled)')];
    const shouldCheck = boxes.some((el) => !el.checked);
    boxes.forEach((el) => { el.checked = shouldCheck; });
  });

  document.getElementById('load-selected-btn').addEventListener('click', async () => {
    const coverageDate = dateSelect.value;
    const itemIds = Array.from(document.querySelectorAll('.brief-checkbox:checked')).map((el) => el.value);
    if (!itemIds.length) {
      alert('请先勾选要加载的条目');
      return;
    }
    const data = await API.briefs.load(coverageDate, itemIds, { checkOk: false });
    alert(`已排队 ${data.queued}/${data.requested} 个任务`);
    await loadCards();
    loadJobs();
  });

  document.getElementById('sync-memory-btn').addEventListener('click', async () => {
    await API.briefs.syncMemory({ checkOk: false });
    alert('补灌任务已排队');
    loadJobs();
  });

  // 轻量入库：原 /memory 页的"日期加载"并入这里——一天一个
  // load_brief_date 任务，卡片导读直接写进 A 自库 AATF 命名空间。
  // 后台任务表里 kind=load_brief_date 的行就是它，取消/重试通用。
  document.getElementById('light-load-btn').addEventListener('click', async () => {
    const coverageDate = dateSelect.value;
    if (!coverageDate) return;
    try {
      await API.briefs.lightLoad(coverageDate, { checkOk: false });
      alert(`轻量入库已排队：${coverageDate}`);
    } catch (err) {
      alert(`轻量入库请求失败：${err.message}`);
    }
    loadJobs();
  });

  // ===== 入库日期面板交互（跨日期多选批量轻量入库）=====
  const ingestUncheckBtn = document.getElementById('ingest-select-unchecked-btn');
  if (ingestUncheckBtn) {
    ingestUncheckBtn.addEventListener('click', () => {
      // 与卡片"全选/清空"同一套 toggle 语义：还有没勾上的就全勾，否则全清。
      const boxes = [...document.querySelectorAll('.ingest-date-cb')];
      const shouldCheck = boxes.some((el) => !el.checked);
      boxes.forEach((el) => { el.checked = shouldCheck; });
      updateIngestBulkCount();
    });
  }
  const ingestClearBtn = document.getElementById('ingest-clear-btn');
  if (ingestClearBtn) {
    ingestClearBtn.addEventListener('click', () => {
      document.querySelectorAll('.ingest-date-cb').forEach((el) => { el.checked = false; });
      updateIngestBulkCount();
    });
  }
  const ingestBulkBtn = document.getElementById('ingest-bulk-btn');
  if (ingestBulkBtn) {
    ingestBulkBtn.addEventListener('click', async () => {
      const dates = checkedIngestDates();
      if (!dates.length) {
        alert('请先勾选要入库的日期');
        return;
      }
      ingestBulkBtn.disabled = true;
      try {
        const data = await API.briefs.lightLoad(dates, { checkOk: false });
        alert(`批量轻量入库已排队：${(data.dates || dates).join('、')}`
          + '（排队后徽章变"排队中/入库中…"，重复日期后端自动去重）');
      } catch (err) {
        alert(`批量轻量入库请求失败：${err.message}`);
      } finally {
        ingestBulkBtn.disabled = false;
      }
      loadJobs();
    });
  }

  // 「🧠 简报问答」：新标签打开 /chat 并把会话记忆范围预置为 AATF——
  // 旧 /memory 页对话面板的入口保留在这（检索走本地自库，不再碰外部）。
  const briefChatBtn = document.getElementById('brief-chat-btn');
  if (briefChatBtn) {
    briefChatBtn.addEventListener('click', () => {
      window.open('/chat?namespaces=AATF', '_blank', 'noopener');
    });
  }

  dateSelect.addEventListener('change', () => { loadCards(); renderStatusLine(); });

  (async function init() {
    await loadDates();
    await loadCards();
    await loadJobs();
    await loadMemoryStatus();
    setInterval(loadJobs, 5000);
  })();
})();
