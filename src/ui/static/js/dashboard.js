(async function loadSessionCount() {
    try {
        const data = await API.sessions.list({ errorText: '加载会话失败' });
        const count = (data.sessions || []).length;
        const countElement = document.getElementById('session-count');
        if (countElement) {
            countElement.textContent = count > 0 ? `📊 ${count} 个历史会话` : '🆕 暂无历史会话';
        }
    } catch (error) {
        console.error('加载会话统计失败:', error);
        const countElement = document.getElementById('session-count');
        if (countElement) countElement.textContent = '⚠️ 加载失败';
    }
})();

(function setupSessionsModal() {
    const overlay = document.getElementById('sessions-modal-overlay');
    const openBtn = document.getElementById('history-sessions-card');
    const closeBtn = document.getElementById('sessions-modal-close');

    function openModal() {
        overlay.classList.add('open');
        // 弹窗打开时才真正拉取会话列表/统计（sessionsOnly 模式下
        // DataManager 不会在页面加载时自动请求）。loadSessionStats()
        // 内部已经会调用 renderSessionStats()，不需要再手动调一次。
        dataManager.loadSessionStats();
        dataManager.loadSessions();
    }

    function closeModal() {
        overlay.classList.remove('open');
    }

    openBtn.addEventListener('click', openModal);
    closeBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay.classList.contains('open')) closeModal();
    });
})();

function escapeHtmlDashboard(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

// 今日简报预览——首页的视觉主体：显示最新一天的简报里有多少条、还有
// 多少没处理、以及几条标题预览，点了直接跳 /briefs 处理，不需要先猜
// "今天有没有新东西"。
(async function loadBriefsPreview() {
    const headingEl = document.getElementById('briefs-preview-heading');
    const summaryEl = document.getElementById('briefs-preview-summary');
    const listEl = document.getElementById('briefs-preview-list');
    const cardEl = document.getElementById('briefs-preview-card');

    cardEl.addEventListener('click', () => { window.location.href = '/briefs'; });

    try {
        const { dates } = await API.briefs.dates({ errorText: '加载简报日期失败' });

        if (!dates || !dates.length) {
            summaryEl.textContent = '暂无简报数据';
            listEl.innerHTML = '';
            return;
        }

        const latestDate = dates[0];
        headingEl.textContent = `📰 今日简报（${latestDate}）`;

        const data = await API.briefs.cards(latestDate, { errorText: '加载简报内容失败' });

        const notLoaded = (data.counts && data.counts.not_loaded) || 0;
        summaryEl.textContent = `${data.pdf.length} 篇论文 · ${data.web.length} 篇文章` +
            (notLoaded ? ` · ${notLoaded} 条未处理` : ' · 全部已处理');

        const preview = [...data.pdf, ...data.web].slice(0, 4);
        listEl.innerHTML = preview.length
            ? preview.map((c) => `<li>${escapeHtmlDashboard(c.title || c.url || c.item_id)}</li>`).join('')
            : '<li class="briefs-preview-empty" style="border-top:none;">暂无条目</li>';
    } catch (error) {
        console.error('加载简报预览失败:', error);
        summaryEl.textContent = '加载失败';
    }
})();

// 后台任务小面板——首页只做"看一眼有没有在跑"，点开展开一个轻量列表；
// 真正的管理（重试等）留在 /briefs 页面自己的任务表格里，不重复造轮子。
(function setupJobsSummary() {
    const card = document.getElementById('jobs-summary-card');
    const countEl = document.getElementById('jobs-summary-count');
    const listEl = document.getElementById('jobs-panel-list');
    let jobs = [];
    let expanded = false;

    function renderList() {
        if (!jobs.length) {
            listEl.innerHTML = '<div class="job-row"><span class="job-name">暂无进行中的任务</span></div>';
            return;
        }
        listEl.innerHTML = jobs.slice(0, 8).map((j) => `
            <div class="job-row">
                <span class="job-name">${escapeHtmlDashboard(j.title || j.target)}</span>
                <span>${escapeHtmlDashboard(j.status)}</span>
            </div>`).join('');
    }

    async function loadJobsSummary() {
        try {
            const data = await API.jobs.list({ errorText: '加载任务失败' });
            jobs = (data.jobs || []).filter((j) => j.status === 'queued' || j.status === 'running');
            countEl.textContent = jobs.length ? `⏳ ${jobs.length} 个进行中` : '✅ 空闲';
            if (expanded) renderList();
        } catch (error) {
            console.error('加载后台任务失败:', error);
            countEl.textContent = '⚠️ 加载失败';
        }
    }

    card.addEventListener('click', () => {
        expanded = !expanded;
        listEl.style.display = expanded ? 'block' : 'none';
        if (expanded) renderList();
    });

    loadJobsSummary();
    setInterval(loadJobsSummary, 15000);
})();
