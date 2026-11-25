/**
 * /briefs 双栏研究工作台
 *
 * 核心目标：
 * 1. 清晰区分 4 条操作路径：整日入简报库 / 深度精析 / PDF 文档库 / 补写漏同步摘要；
 * 2. 日期状态不再靠文字猜测：月历矩阵显示无 HTML / 待入库 / 速览库 / 深度精析 / 排队 / 异常；
 * 3. 卡片列表支持搜索、论文/文章 Tab、状态筛选和仅有导读；
 * 4. 后台任务抽屉化，任务枚举转成人话，避免页底原始日志污染阅读。
 */
(function () {
    'use strict';

    const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
    const PDF_SOURCE_RE = /(arxiv\.org|\.pdf)/i;
    const HEAVY_PDF_MIN_MIN = 15;
    const HEAVY_PDF_MAX_MIN = 30;
    const HEAVY_WEB_MIN_MIN = 3;
    const HEAVY_WEB_MAX_MIN = 5;

    const state = {
        allDates: [],
        dateUniverse: [],
        currentDate: null,
        cards: [],
        selectedIds: new Set(),
        expandedIds: new Set(),
        memoryDates: {},
        meta: null,
        storageMode: 'local',
        upstreamAvailable: false,
        monthOffset: 0,
        activeMonthAnchor: null,
        bulkMode: false,
        bulkSelectedDates: new Set(),
        showMissingDates: false,
        filters: {
            tab: 'all',
            search: '',
            status: 'all',
            onlyCn: false,
        },
        jobs: [],
        jobsTab: 'active',
        jobStatusSnapshot: {},
        ingestControllers: new Map(),
        docIndexSnapshot: new Map(),
        pollingTimer: null,
        guideVisible: false,
        loadError: null,
    };

    const STATUS_LABELS = {
        not_loaded: '未深度精析',
        queued: '精析排队中',
        done: '已深度精析',
        failed: '精析失败',
    };

    const STATUS_PILL_CLASS = {
        not_loaded: 'state-unloaded',
        queued: 'state-running',
        done: 'state-heavy',
        failed: 'state-error',
    };

    const JOB_STATUS_LABELS = {
        queued: '排队中',
        running: '执行中',
        cancelling: '取消中',
        done: '已完成',
        failed: '失败',
        interrupted: '已中断',
        cancelled: '已取消',
    };

    const JOB_STATUS_PILL_CLASS = {
        queued: 'state-running',
        running: 'state-running',
        cancelling: 'state-running',
        done: 'state-heavy',
        failed: 'state-error',
        interrupted: 'state-error',
        cancelled: 'state-unloaded',
    };

    const el = {
        $: (id) => document.getElementById(id),
        qs: (sel, root) => (root || document).querySelector(sel),
        qa: (sel, root) => Array.from((root || document).querySelectorAll(sel)),
    };

    function dom(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function svgIcon(paths, viewBox = '0 0 24 24', strokeWidth = '1.8') {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', viewBox);
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', strokeWidth);
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');
        svg.setAttribute('class', 'btn-svg');
        (Array.isArray(paths) ? paths : [paths]).forEach((d) => {
            const path = document.createElementNS(ns, 'path');
            path.setAttribute('d', d);
            svg.appendChild(path);
        });
        return svg;
    }

    function toggleSvg() {
        return svgIcon('M9 18l6-6-6-6', '0 0 24 24', '2');
    }

    function pill(text, stateClass) {
        const span = dom('span', `status-pill ${stateClass || 'state-unloaded'}`);
        const dot = dom('i', 'status-pill-dot');
        span.appendChild(dot);
        span.appendChild(document.createTextNode(text));
        return span;
    }

    function toast(msg, type = 'info') {
        if (window.UIFeedback && UIFeedback.toast) {
            UIFeedback.toast(msg, { type, duration: 4800 });
        } else {
            console.warn('[briefs]', msg);
        }
    }

    function safeDate(value) {
        return typeof value === 'string' && DATE_RE.test(value) ? value : null;
    }

    function toDateObj(date) {
        const [y, m, d] = date.split('-').map(Number);
        return new Date(Date.UTC(y, m - 1, d));
    }

    function toIsoDate(dt) {
        return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
    }

    function dateRange(start, end) {
        const out = [];
        let cur = toDateObj(start);
        const last = toDateObj(end);
        const maxDays = 2000; // 防御性上限，避免异常范围
        while (cur <= last && out.length < maxDays) {
            out.push(toIsoDate(cur));
            cur = new Date(cur.getTime() + 86400000);
        }
        return out;
    }

    function escapeHtml(str) {
        return String(str == null ? '' : str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatShortTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return String(iso);
        const now = new Date();
        const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
        const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
        if (sameDay) return time;
        return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${time}`;
    }

    function formatDuration(startIso, endIso) {
        if (!startIso) return '';
        const start = new Date(startIso);
        const end = endIso ? new Date(endIso) : new Date();
        if (Number.isNaN(start.getTime())) return '';
        const sec = Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000));
        if (sec < 60) return `${sec} 秒`;
        const min = Math.floor(sec / 60);
        const rem = sec % 60;
        if (min < 60) return `${min} 分${rem ? ` ${rem} 秒` : ''}`;
        const h = Math.floor(min / 60);
        const m = min % 60;
        return `${h} 小时${m ? ` ${m} 分` : ''}`;
    }

    function currentMemory(date) {
        const c = state.memoryDates[date] || { aatf: 0, heavy_done: 0 };
        const q = state.meta && state.meta.queue_by_date ? state.meta.queue_by_date[date] : null;
        return {
            aatf: Number(c.aatf || 0),
            heavy_done: Number(c.heavy_done || 0),
            heavy_queued: Number((q && q.heavy_queued) || 0),
            heavy_failed: Number((q && q.heavy_failed) || 0),
        };
    }

    function hasHtml(date) {
        if (!state.allDates.includes(date)) return false;
        const html = state.meta && state.meta.html_dates ? state.meta.html_dates[date] : null;
        if (!html) return true;
        return !!(html.has_pdf || html.has_web);
    }

    function isMissingDate(date) {
        return !hasHtml(date);
    }

    function datePills(date, opts = {}) {
        const out = [];
        const m = currentMemory(date);
        const html = hasHtml(date);

        if (!html) {
            if (opts.includeMissing !== false) {
                const p = pill('无简报 HTML', 'state-none');
                p.title = '该日期没有发现简报 HTML 文件，不能入库或加载';
                out.push(p);
            }
            return out;
        }

        if (m.aatf > 0) {
            const p = pill(`简报速览库 AATF · ${m.aatf}`, 'state-aatf');
            p.title = '该日卡片导读已进入简报速览库 (AATF)';
            out.push(p);
        }
        if (m.heavy_done > 0) {
            const p = pill(`深度研报 ai-research · ${m.heavy_done}`, 'state-heavy');
            p.title = '该日已有条目完成深度精析并写入深度研报记忆 (ai-research)';
            out.push(p);
        }
        if (m.heavy_queued > 0) {
            const p = pill(`深度排队 ${m.heavy_queued}`, 'state-running');
            p.title = '该日有深度精析条目排队或运行中';
            out.push(p);
        }
        if (m.heavy_failed > 0) {
            const p = pill(`深度失败 ${m.heavy_failed}`, 'state-error');
            p.title = '该日有深度精析条目失败';
            out.push(p);
        }

        if (!out.length) {
            const p = pill('待入库', 'state-unloaded');
            p.title = '该日有简报 HTML，但尚未进入记忆库；可整日入简报库或选择重点深度精析';
            out.push(p);
        }

        if (opts.showJobOverlay) {
            const job = state.jobs.find((j) => j.kind === 'load_brief_date' && j.target === date);
            if (job && ['queued', 'running', 'cancelling'].includes(job.status)) {
                const label = job.status === 'running' ? '速览库入库中…' : (job.status === 'cancelling' ? '取消中…' : '速览库排队');
                const p = pill(label, 'state-running');
                p.title = '后台任务：整日入简报库 (AATF)';
                out.push(p);
            } else if (job && ['failed', 'interrupted'].includes(job.status)) {
                const p = pill('速览库异常', 'state-error');
                p.title = '整日入简报库任务失败或中断，可在任务抽屉重试';
                out.push(p);
            }
        }
        return out;
    }

    function updateUniverse() {
        if (!state.allDates.length) {
            state.dateUniverse = [];
            return;
        }
        const sorted = [...state.allDates].sort();
        const range = dateRange(sorted[0], sorted[sorted.length - 1]);
        const set = new Set(state.allDates);
        state.dateUniverse = range.map((d) => ({ date: d, hasHtml: set.has(d) }));
    }

    function visibleDateRows() {
        const list = state.dateUniverse.filter((r) => (state.showMissingDates || r.hasHtml) && r.date <= (state.currentDate || '9999-12-31'));
        return list.sort((a, b) => (a.date < b.date ? 1 : -1));
    }

    function currentMonthRange() {
        const base = state.activeMonthAnchor || toDateObj(state.currentDate || state.allDates[0] || new Date().toISOString().slice(0, 10));
        const monthDate = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() + state.monthOffset, 1));
        return monthDate;
    }

    function monthCells() {
        const month = currentMonthRange();
        const y = month.getUTCFullYear();
        const m = month.getUTCMonth();
        el.$('cal-month-label').textContent = `${y}年${String(m + 1).padStart(2, '0')}月`;

        const first = new Date(Date.UTC(y, m, 1));
        const jsDay = (first.getUTCDay() + 6) % 7; // Monday first
        const start = new Date(first.getTime() - jsDay * 86400000);
        const cells = [];
        const dateSet = new Set(state.dateUniverse.map((r) => r.date));
        for (let i = 0; i < 42; i++) {
            const dt = new Date(start.getTime() + i * 86400000);
            const iso = toIsoDate(dt);
            const known = dateSet.has(iso);
            const isCurrentMonth = dt.getUTCMonth() === m;
            cells.push({ iso, known, isCurrentMonth, isMissing: known && !hasHtml(iso) });
        }
        return cells;
    }

    function dateJobStatus(date) {
        const jobs = state.jobs.filter((j) => (j.kind === 'load_brief_date' && j.target === date) || (j.kind === 'sync_memory' && j.target === date));
        if (jobs.some((j) => ['failed', 'interrupted'].includes(j.status))) return 'failed';
        if (jobs.some((j) => ['queued', 'running', 'cancelling'].includes(j.status))) return 'running';
        return '';
    }

    function cardJobStatus(card) {
        const job = state.jobs.find((j) => j.kind === 'process_item' && String(j.target) === String(card.item_id));
        if (!job) return '';
        if (['queued', 'running', 'cancelling'].includes(job.status)) return 'running';
        if (['failed', 'interrupted'].includes(job.status)) return 'failed';
        return '';
    }

    function renderCalendar() {
        const grid = el.$('calendar-grid');
        if (!grid) return;
        grid.innerHTML = '';
        const frag = document.createDocumentFragment();
        monthCells().forEach((cell) => {
            const btn = dom('button', 'cal-cell');
            btn.type = 'button';
            btn.dataset.date = cell.iso;

            if (!cell.isCurrentMonth) {
                btn.classList.add('is-empty');
                btn.tabIndex = -1;
            } else {
                const m = currentMemory(cell.iso);
                const jobStatus = dateJobStatus(cell.iso);
                if (!cell.known || cell.isMissing) {
                    btn.classList.add('state-none');
                    btn.title = `${cell.iso}：无简报 HTML`;
                } else if (jobStatus === 'failed') {
                    btn.classList.add('state-error');
                    btn.title = `${cell.iso}：入库任务失败/中断`;
                } else if (jobStatus === 'running') {
                    btn.classList.add('state-running');
                    btn.title = `${cell.iso}：入库任务进行中`;
                } else if (m.heavy_done > 0) {
                    btn.classList.add('state-heavy');
                    btn.title = `${cell.iso}：含深度精析${m.aatf ? '，并已入简报速览库' : ''}`;
                } else if (m.aatf > 0) {
                    btn.classList.add('state-aatf');
                    btn.title = `${cell.iso}：已入简报速览库 (AATF)`;
                } else {
                    btn.classList.add('state-unloaded', 'has-html');
                    btn.title = `${cell.iso}：有 HTML，待入库`;
                }

                if (cell.iso === state.currentDate) btn.classList.add('is-active');
                if (state.bulkMode && state.bulkSelectedDates.has(cell.iso)) btn.classList.add('is-bulk-checked');
                if (!cell.known) btn.classList.add('out-month');
            }

            const num = dom('span', 'cal-num', String(toDateObj(cell.iso).getUTCDate()));
            btn.appendChild(num);

            if (cell.known && hasHtml(cell.iso)) {
                const dots = dom('div', 'cal-dots');
                const m = currentMemory(cell.iso);
                if (m.aatf > 0) dots.appendChild(dom('i', 'cal-dot dot-aatf'));
                if (m.heavy_done > 0) dots.appendChild(dom('i', 'cal-dot dot-heavy'));
                const job = dateJobStatus(cell.iso);
                if (job === 'running') dots.appendChild(dom('i', 'cal-dot dot-running'));
                if (job === 'failed') dots.appendChild(dom('i', 'cal-dot dot-error'));
                if (dots.children.length) btn.appendChild(dots);
            }

            if (state.bulkMode && state.bulkSelectedDates.has(cell.iso)) {
                const mark = dom('span', 'cal-bulk-mark', '✓');
                btn.appendChild(mark);
            }

            btn.addEventListener('click', () => handleDateClick(cell.iso));
            frag.appendChild(btn);
        });
        grid.appendChild(frag);
    }

    function handleDateClick(date) {
        if (state.bulkMode) {
            if (isMissingDate(date)) {
                toast(`${date} 没有简报 HTML，无法加入批量入库`, 'warning');
                return;
            }
            if (state.bulkSelectedDates.has(date)) state.bulkSelectedDates.delete(date);
            else state.bulkSelectedDates.add(date);
            renderBulkBox();
            renderCalendar();
            return;
        }
        if (isMissingDate(date)) {
            toast(`${date} 没有简报 HTML，无法加载内容`, 'warning');
            return;
        }
        setDate(date);
    }

    function renderDateList() {
        const list = el.$('sidebar-date-list');
        if (!list) return;
        list.innerHTML = '';
        const frag = document.createDocumentFragment();
        visibleDateRows().forEach((row) => {
            const li = dom('li', 'date-list-row');
            if (!row.hasHtml) {
                li.classList.add('is-missing');
                li.title = '该日期未生成简报 HTML';
            }
            if (row.date === state.currentDate) li.classList.add('is-active');
            if (row.hasHtml) li.classList.add('has-html');

            const btn = dom('button', 'date-row-btn');
            btn.type = 'button';
            const label = dom('span', 'date-row-label', row.date);
            const tags = dom('span', 'date-row-tags');

            if (!row.hasHtml) {
                tags.appendChild(pill('无 HTML', 'state-none'));
            } else {
                const pills = datePills(row.date, { showJobOverlay: true });
                pills.forEach((p) => {
                    const mini = pillMiniFromPill(p);
                    tags.appendChild(mini);
                });
            }

            btn.appendChild(label);
            btn.appendChild(tags);
            btn.addEventListener('click', () => handleDateClick(row.date));
            li.appendChild(btn);
            frag.appendChild(li);
        });
        list.appendChild(frag);
    }

    function pillMiniFromPill(p) {
        const mini = document.createElement('span');
        mini.className = `mini-tag ${pillClassFromPill(p)}`;
        mini.textContent = p.textContent.trim();
        mini.title = p.title || '';
        return mini;
    }

    function pillClassFromPill(p) {
        const match = Array.from(p.classList).find((c) => c.startsWith('state-'));
        if (!match) return 't-unloaded';
        return {
            'state-none': 't-none',
            'state-unloaded': 't-unloaded',
            'state-aatf': 't-aatf',
            'state-heavy': 't-heavy',
            'state-running': 't-running',
            'state-error': 't-error',
        }[match] || 't-unloaded';
    }

    function renderSidebarCoverageMeta() {
        const meta = el.$('sidebar-coverage-meta');
        if (!meta) return;
        if (!state.dateUniverse.length) {
            meta.textContent = '暂无简报日期';
            return;
        }
        const htmlCount = state.allDates.length;
        const missingCount = state.dateUniverse.length - htmlCount;
        meta.textContent = `有简报 ${htmlCount} 天${missingCount > 0 ? ` · 断档 ${missingCount} 天` : ''}`;
    }

    function renderBulkBox() {
        const count = state.bulkSelectedDates.size;
        const badge = el.$('bulk-selected-badge');
        const input = el.$('ingest-selected-count');
        const btn = el.$('ingest-bulk-btn');
        if (badge) badge.textContent = `已选 ${count} 天`;
        if (input) input.textContent = String(count);
        if (btn) {
            btn.disabled = count === 0;
            const child = btn.querySelector('span');
            if (child) child.textContent = String(count);
        }
        const hint = el.$('bulk-box-hint');
        if (hint) {
            if (count > 0) {
                const pending = Array.from(state.bulkSelectedDates).filter((d) => currentMemory(d).aatf === 0).length;
                const already = count - pending;
                hint.textContent = `${pending} 天尚未入库${already ? `；${already} 天已有数据，重复条目由后端自动去重` : ''}。单次最多排队 40 天。`;
            } else {
                hint.textContent = '勾选多日后一次排队入库（单次最多 40 天，已入库条目自动去重）。';
            }
        }
    }

    function renderDateViews() {
        const activeMonth = currentMonthRange();
        el.$('cal-month-label') && (el.$('cal-month-label').textContent = `${activeMonth.getUTCFullYear()}年${String(activeMonth.getUTCMonth() + 1).padStart(2, '0')}月`);
        renderSidebarCoverageMeta();
        renderCalendar();
        renderDateList();
        renderBulkBox();
    }

    function normalizeDocState(item) {
        if (item.doc_state) return item.doc_state;
        const snapshot = state.docIndexSnapshot.get(String(item.item_id));
        if (snapshot) return snapshot;
        return null;
    }

    function cardHasCn(card) {
        const cn = card.cn || {};
        if (Object.keys(cn).length) return true;
        // web 卡片有时只有 excerpt/followup 等次要正文；作为“有导读”处理可避免被“仅有导读”过滤掉
        if ((card.excerpt || '').trim()) return true;
        return false;
    }

    function matchesFilters(card) {
        const f = state.filters;
        if (f.tab === 'pdf' && card.section !== 'pdf') return false;
        if (f.tab === 'web' && card.section !== 'web') return false;
        if (f.status !== 'all' && card.status !== f.status) return false;
        if (f.onlyCn && !cardHasCn(card)) return false;
        if (f.search) {
            const q = f.search.toLowerCase();
            const blob = [card.title, Object.values(card.cn || {}).join(' '), card.excerpt, card.topic_tag, (card.themes || []).join(' '), card.english_brief, card.why].filter(Boolean).join(' ').toLowerCase();
            if (!blob.includes(q)) return false;
        }
        return true;
    }

    function visibleCards() {
        return state.cards.filter(matchesFilters);
    }

    function isSelectable(card) {
        return card.status === 'not_loaded' || card.status === 'failed';
    }

    function getDocNameForCard(card) {
        const doc = normalizeDocState(card);
        if (doc && doc.doc_name) return doc.doc_name;
        return card.item_id;
    }

    function isPdfIndexReady(card) {
        const doc = normalizeDocState(card);
        return !!(doc && (doc.state === 'indexed' || doc.state === 'indexed_elsewhere'));
    }

    function ingestStateOf(card) {
        const doc = normalizeDocState(card);
        if (doc && doc.state === 'indexed') return { label: '✅ 已入文档库', cls: 'is-ok', disabled: true };
        if (doc && doc.state === 'indexed_elsewhere') return { label: '✅ 已按其他版本入库', cls: 'is-ok', disabled: true };
        if (doc && doc.state === 'not_indexed') return { label: '重新索引', cls: '', disabled: false };
        return { label: '⬇ 收入 PDF 文档库', cls: '', disabled: false };
    }

    function makeCard(card) {
        const article = dom('article', 'brief-card');
        article.dataset.itemId = card.item_id;
        article.dataset.section = card.section;
        article.classList.add(`status-border-${card.status}`);
        if (!cardHasCn(card) && (card.section === 'pdf' || card.status !== 'done')) article.classList.add('is-compact');
        if (state.selectedIds.has(card.item_id)) article.classList.add('is-selected');
        if (state.expandedIds.has(card.item_id)) article.classList.add('expanded');

        const check = dom('div', 'card-check');
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'brief-checkbox';
        cb.value = card.item_id;
        cb.checked = state.selectedIds.has(card.item_id);
        if (!isSelectable(card)) cb.disabled = true;
        cb.addEventListener('change', (e) => {
            if (e.target.checked) state.selectedIds.add(card.item_id);
            else state.selectedIds.delete(card.item_id);
            article.classList.toggle('is-selected', e.target.checked);
            updateSelectionUi();
        });
        check.appendChild(cb);

        const body = dom('div', 'card-body');

        const head = dom('div', 'card-head');
        const titleCol = dom('div', 'card-title-col');
        const title = dom('h3', 'card-title', card.title || card.url || card.item_id);
        titleCol.appendChild(title);

        const right = dom('div', 'card-meta-right');
        if (card.score) right.appendChild(dom('span', 'meta-text-chip tabular-nums', card.score));
        if (card.topic_tag) right.appendChild(dom('span', 'meta-text-chip', card.topic_tag));
        if (!cardHasCn(card)) right.appendChild(dom('span', 'meta-text-chip no-cn-tag', '无导读'));
        const statusLabel = STATUS_LABELS[card.status] || card.status;
        const p = pill(statusLabel, STATUS_PILL_CLASS[card.status] || 'state-unloaded');
        p.title = card.status === 'done'
            ? '该条目已完成深度精析，摘要已写入深度研报记忆 (ai-research)'
            : (card.status === 'queued' ? '该条目已在深度精析队列中' : (card.status === 'failed' ? '深度精析失败，可重新勾选提交' : '尚未完成深度精析'));
        right.appendChild(p);
        const toggle = dom('span', 'card-toggle');
        toggle.appendChild(toggleSvg());
        right.appendChild(toggle);

        head.appendChild(titleCol);
        head.appendChild(right);
        head.addEventListener('click', (e) => {
            if (e.target.closest('.card-check') || e.target.closest('button') || e.target.closest('a')) return;
            article.classList.toggle('expanded');
            if (article.classList.contains('expanded')) state.expandedIds.add(card.item_id);
            else state.expandedIds.delete(card.item_id);
            syncExpandAllLabel();
        });

        body.appendChild(head);

        if (card.themes && card.themes.length) {
            const themes = dom('div', 'themes');
            (card.themes || []).forEach((t) => themes.appendChild(dom('span', 'theme-chip', t)));
            body.appendChild(themes);
        }

        if (Object.keys(card.cn || {}).length || (card.excerpt || '').trim()) {
            const block = dom('div', 'cn-block');
            Object.entries(card.cn || {}).forEach(([label, text]) => {
                const item = dom('div', 'cn-item');
                const lead = dom('span', 'cn-label-lead', '');
                lead.appendChild(document.createTextNode(`${label}：`));
                item.appendChild(lead);
                item.appendChild(document.createTextNode(text));
                block.appendChild(item);
            });
            if (card.excerpt && !Object.keys(card.cn || {}).length) {
                const item = dom('div', 'cn-item');
                item.appendChild(document.createTextNode(card.excerpt));
                block.appendChild(item);
            }
            body.appendChild(block);
        }

        const extras = [];
        if (card.followup) extras.push([`后续可追问：`, card.followup]);
        if (card.authors) extras.push([null, card.authors]);
        if (card.english_brief) extras.push(['English brief：', card.english_brief]);
        if (card.why) extras.push(['为何值得看：', card.why]);
        if (card.status === 'failed' && card.last_error) extras.push(['上次失败：', card.last_error]);
        if (extras.length) {
            const extraBlock = dom('div', 'card-expanded-extra');
            extras.forEach(([label, text]) => {
                const para = dom('p');
                if (label) {
                    const strong = dom('strong', '', label);
                    para.appendChild(strong);
                }
                para.appendChild(document.createTextNode(text));
                extraBlock.appendChild(para);
            });
            body.appendChild(extraBlock);
        }

        const actionRow = dom('div', 'card-action-row');
        const links = dom('div', 'card-links-left');
        if (card.url) {
            const a = dom('a', 'card-ext-link', '原文 ↗');
            a.href = card.url;
            a.target = '_blank';
            a.rel = 'noopener';
            links.appendChild(a);
        }
        if (card.pdf_url) {
            const a = dom('a', 'card-ext-link', 'PDF ↗');
            a.href = card.pdf_url;
            a.target = '_blank';
            a.rel = 'noopener';
            links.appendChild(a);
        }
        actionRow.appendChild(links);

        const pdfTarget = (card.pdf_url && PDF_SOURCE_RE.test(card.pdf_url)) ? card.pdf_url
            : (PDF_SOURCE_RE.test(card.url || '') ? card.url : null);
        if (pdfTarget) {
            const group = dom('div', 'pdf-ingest-group');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'fetch-pdf-btn';
            btn.dataset.url = pdfTarget;
            const ing = ingestStateOf(card);
            btn.textContent = ing.label;
            if (ing.cls) btn.classList.add(ing.cls);
            if (ing.disabled) btn.disabled = true;
            btn.title = '将本篇论文 PDF 收入本地 PDF 文档库并建立全文索引；不写入简报速览库或深度研报记忆';
            btn.addEventListener('click', () => startPdfIngest(card, btn));
            group.appendChild(btn);

            if (isPdfIndexReady(card)) {
                const link = dom('a', 'deep-read-link', '📖 打开精读 ↗');
                link.href = `/chat?doc=${encodeURIComponent(getDocNameForCard(card))}`;
                link.target = '_blank';
                link.rel = 'noopener';
                group.appendChild(link);
                const note = dom('span', 'pdf-inline-note', '已在本地文档库');
                group.appendChild(note);
            }
            actionRow.appendChild(group);
        }
        body.appendChild(actionRow);

        article.appendChild(check);
        article.appendChild(body);
        return article;
    }

    function startPdfIngest(card, btn) {
        const url = btn.dataset.url;
        if (!window.PaperIngest) {
            toast('PDF 入库组件加载失败，请刷新页面后重试', 'error');
            return;
        }

        let controller = state.ingestControllers.get(card.item_id);
        if (controller) controller.abort();
        controller = new AbortController();
        state.ingestControllers.set(card.item_id, controller);
        btn.disabled = true;
        btn.textContent = '下载中…';
        btn.classList.add('is-busy');
        btn.classList.remove('is-ok');
        const existingLink = btn.parentElement && btn.parentElement.querySelector('.deep-read-link');
        if (existingLink) existingLink.remove();
        const existingNote = btn.parentElement && btn.parentElement.querySelector('.pdf-inline-note');
        if (existingNote) existingNote.remove();

        window.PaperIngest.start(url, (s) => {
            if (s.phase === 'indexing') {
                btn.textContent = s.note || '建立索引中…';
                btn.title = s.note || 'PDF 正在本地文档库建立全文索引';
            } else if (s.phase === 'indexed') {
                const doc = normalizeDocState(card) || { state: 'indexed', doc_name: s.docName };
                doc.state = 'indexed';
                doc.doc_name = s.docName || getDocNameForCard(card);
                card.doc_state = doc;
                state.docIndexSnapshot.set(String(card.item_id), doc);
                btn.textContent = '✅ 已入文档库';
                btn.disabled = true;
                btn.classList.remove('is-busy');
                btn.classList.add('is-ok');
                btn.title = '该论文已在本地文档库完成索引，可直接打开精读';
                const group = btn.parentElement;
                if (group) {
                    const link = dom('a', 'deep-read-link', '📖 打开精读 ↗');
                    link.href = `/chat?doc=${encodeURIComponent(s.docName || doc.doc_name)}`;
                    link.target = '_blank';
                    link.rel = 'noopener';
                    group.appendChild(link);
                    group.appendChild(dom('span', 'pdf-inline-note', '可原文深挖'));
                }
            } else if (s.phase === 'timeout') {
                btn.disabled = false;
                btn.classList.remove('is-busy');
                btn.textContent = '重新检查 / 强制重下';
                btn.title = '索引等待超时；如果文件已存在但未成功索引，再次点击会尝试强制重下并重建索引';
                toast('PDF 索引等待超时，可稍后重试', 'warning');
            } else if (s.phase === 'failed') {
                btn.disabled = false;
                btn.classList.remove('is-busy');
                btn.textContent = '⬇ 收入 PDF 文档库';
                btn.title = '收入 PDF 文档库失败，可重试';
                toast(`收入 PDF 文档库失败：${s.error || '未知错误'}`, 'error');
            }
        }, { signal: controller.signal });
    }

    function renderFeed() {
        const feed = el.$('briefs-feed');
        if (!feed) return;
        feed.innerHTML = '';
        if (state.loadError) {
            feed.appendChild(dom('div', 'feed-empty-state', state.loadError));
            return;
        }
        const groups = [
            { key: 'pdf', title: '论文', cards: state.cards.filter((c) => c.section === 'pdf') },
            { key: 'web', title: '文章', cards: state.cards.filter((c) => c.section === 'web') },
        ];
        if (state.filters.tab === 'pdf') groups.splice(1, 1);
        if (state.filters.tab === 'web') groups.splice(0, 1);

        let renderedAny = false;
        groups.forEach((group) => {
            const visible = group.cards.filter(matchesFilters);
            updateCount(group.key, group.cards.length);
            if (state.filters.tab !== 'all' && !visible.length) return;

            const section = dom('section', 'feed-section');
            section.dataset.section = group.key;
            const h = dom('div', 'section-heading');
            const left = dom('div', 'section-heading-left');
            left.appendChild(dom('h2', '', group.title));
            left.appendChild(dom('span', 'section-count-pill', String(visible.length)));
            h.appendChild(left);
            if (visible.length && visible.length !== group.cards.length) {
                h.appendChild(dom('span', 'section-hint', `已筛选 / 共 ${group.cards.length}`));
            } else if (!visible.length) {
                h.appendChild(dom('span', 'section-hint', '当前条件无匹配条目'));
            }
            section.appendChild(h);

            const list = dom('div', 'card-list');
            if (visible.length) {
                const frag = document.createDocumentFragment();
                visible.forEach((card) => frag.appendChild(makeCard(card)));
                list.appendChild(frag);
                renderedAny = true;
            } else if (group.cards.length) {
                list.appendChild(dom('div', 'feed-empty-state', `${group.title}当前筛选下无匹配条目，请尝试清除搜索或状态筛选。`));
                renderedAny = true;
            }
            section.appendChild(list);
            feed.appendChild(section);
        });

        if (!renderedAny) {
            feed.appendChild(dom('div', 'feed-empty-state', '当前日期没有匹配论文或文章，可能是简报文件为空、筛选条件过窄，或该日尚未生成内容。'));
        }
    }

    function updateCount(section, total) {
        if (section === 'pdf') {
            const x = el.$('tab-count-pdf');
            if (x) x.textContent = String(total);
        } else if (section === 'web') {
            const x = el.$('tab-count-web');
            if (x) x.textContent = String(total);
        }
        const all = el.$('tab-count-all');
        if (all) all.textContent = String(state.cards.length);
    }

    function selectedCards() {
        const byId = new Map(state.cards.map((c) => [String(c.item_id), c]));
        return Array.from(state.selectedIds).map((id) => byId.get(String(id))).filter(Boolean);
    }

    function updateSelectionUi() {
        const selected = selectedCards();
        const visibleSelectable = visibleCards().filter(isSelectable);
        const allVisibleSelected = visibleSelectable.length > 0 && visibleSelectable.every((c) => state.selectedIds.has(c.item_id));
        const someSelected = visibleSelectable.some((c) => state.selectedIds.has(c.item_id));
        const selectBtn = el.$('select-all-btn');
        if (selectBtn) selectBtn.textContent = allVisibleSelected ? '取消全选' : (someSelected ? '重新全选' : '全选待精析');

        const dock = el.$('selection-dock');
        const btn = el.$('load-selected-btn');
        if (!dock) return;
        const show = selected.length > 0;
        dock.hidden = !show;
        if (show) {
            const pdfN = selected.filter((c) => c.section === 'pdf').length;
            const webN = selected.filter((c) => c.section === 'web').length;
            el.$('selection-dock-summary').textContent = `已选 ${selected.length} 篇（论文 ${pdfN} · 文章 ${webN}）`;
            const hint = el.$('selection-dock-hint');
            if (hint) hint.textContent = pdfN ? '将加入后台串行队列，摘要自动写入深度研报记忆 (ai-research)' : '将加入后台队列，摘要自动写入深度研报记忆 (ai-research)';
            if (btn) btn.textContent = `深度精析选中 (${selected.length})`;
        }
    }

    function syncExpandAllLabel() {
        const btn = el.$('toggle-expand-all-btn');
        if (!btn) return;
        const cards = visibleCards();
        const expanded = cards.filter((c) => state.expandedIds.has(c.item_id)).length;
        btn.textContent = expanded >= cards.length && cards.length > 0 ? '全部收起' : '全部展开';
    }

    function renderHero() {
        const date = state.currentDate || '';
        const title = el.$('hero-date-title');
        if (title) title.textContent = date || '每日简报';
        const counts = el.$('hero-day-counts');
        const pdfN = state.cards.filter((c) => c.section === 'pdf').length;
        const webN = state.cards.filter((c) => c.section === 'web').length;
        if (counts) counts.textContent = state.cards.length ? ` · ${pdfN} 篇论文 · ${webN} 篇文章` : (date ? ' · 暂无卡片' : '');

        const pillHost = el.$('hero-status-pills');
        if (pillHost) {
            pillHost.innerHTML = '';
            if (date) {
                datePills(date, { showJobOverlay: true }).forEach((p) => {
                    const isAatf = p.className.includes('state-aatf');
                    const isHeavy = p.className.includes('state-heavy');
                    if ((isAatf || isHeavy) && !p.classList.contains('state-running')) {
                        const a = document.createElement('a');
                        a.href = isAatf ? '/data' : '/data';
                        a.className = p.className;
                        a.title = p.title;
                        a.appendChild(p.firstElementChild);
                        a.appendChild(document.createTextNode(p.textContent.trim()));
                        pillHost.appendChild(a);
                    } else {
                        pillHost.appendChild(p);
                    }
                });
            }
        }

        const tip = el.$('hero-context-tip');
        if (tip) {
            const m = currentMemory(date);
            const html = hasHtml(date);
            if (!date) tip.textContent = '请在左侧日历选择或加载简报日期。';
            else if (!html) tip.textContent = `${date} 没有简报 HTML，无法进行入库或加载。`;
            else if (m.aatf === 0 && m.heavy_done === 0 && m.heavy_queued === 0 && m.heavy_failed === 0) {
                tip.innerHTML = '<strong>今日尚未进入任何记忆库</strong>：日常速览可点「整日入简报库」把全部卡片导入 <strong>简报速览库 (AATF)</strong>；重点内容可勾选后「深度精析」写入 <strong>深度研报记忆 (ai-research)</strong>。';
            } else {
                const parts = [];
                if (m.aatf > 0) parts.push(`简报速览库已有 ${m.aatf} 条`);
                if (m.heavy_done > 0) parts.push(`深度研报已完成 ${m.heavy_done} 篇`);
                if (m.heavy_queued > 0) parts.push(`深度精析排队 ${m.heavy_queued} 篇`);
                if (m.heavy_failed > 0) parts.push(`深度精析失败 ${m.heavy_failed} 篇`);
                tip.innerHTML = `<strong>${escapeHtml(date)}</strong>：${escapeHtml(parts.join(' · ') || '状态待刷新')}。`;
            }
        }

        const latency = el.$('guide-aatf-latency');
        if (latency) {
            latency.textContent = state.storageMode === 'upstream'
                ? '上游 LLM-Memory 模式：卡片导读做 agentic 抽取，通常约 1–数分钟/天（卡片越多越久）'
                : '本地模式：本地直写通常几秒到几十秒完成；重复执行自动去重';
        }
    }

    function renderJobs() {
        const list = el.$('jobs-drawer-list');
        if (!list) return;
        const counts = {
            active: state.jobs.filter((j) => ['queued', 'running', 'cancelling'].includes(j.status)).length,
            failed: state.jobs.filter((j) => ['failed', 'interrupted'].includes(j.status)).length,
            all: state.jobs.length,
        };
        ['active', 'failed', 'all'].forEach((k) => {
            const x = el.$(`jobs-count-${k}`);
            if (x) x.textContent = String(counts[k]);
        });

        let jobs = state.jobs;
        if (state.jobsTab === 'active') jobs = jobs.filter((j) => ['queued', 'running', 'cancelling'].includes(j.status));
        else if (state.jobsTab === 'failed') jobs = jobs.filter((j) => ['failed', 'interrupted'].includes(j.status));

        list.innerHTML = '';
        if (!jobs.length) {
            list.appendChild(dom('div', 'feed-empty-state', state.jobsTab === 'all' ? '暂无后台任务。提交深度精析或整日入简报库后，任务会显示在这里。' : '暂无该分类下的任务。'));
            return;
        }
        const frag = document.createDocumentFragment();
        jobs.forEach((job) => frag.appendChild(makeJobCard(job)));
        list.appendChild(frag);
    }

    function jobKindLabel(job) {
        const kind = String(job.kind || '');
        const target = String(job.target || '');
        if (kind === 'load_brief_date') return `整日入简报库 · ${target}`;
        if (kind === 'process_item') {
            const type = String(job.item_type || '');
            if (type === 'pdf_arxiv' || target.match(/^\d{4}\.\d{4,5}$/)) return `深度精析（论文） · ${target}`;
            return `深度精析（条目） · ${target}`;
        }
        if (kind === 'sync_memory') return target === '__all_pending__' ? '补写漏同步摘要 · 全部待补灌摘要' : `补写漏同步摘要 · ${target}`;
        if (kind === 'render_report') return '生成简报汇总页';
        return job.title || kind || target || '未命名任务';
    }

    function makeJobCard(job) {
        const card = dom('div', 'job-card');
        const top = dom('div', 'job-card-top');
        const title = dom('div', 'job-card-title', job.title || job.target || job.job_id);
        const status = pill(JOB_STATUS_LABELS[job.status] || job.status, JOB_STATUS_PILL_CLASS[job.status] || 'state-unloaded');
        top.appendChild(title);
        top.appendChild(status);

        const meta = dom('div', 'job-card-meta');
        meta.appendChild(dom('span', '', jobKindLabel(job)));
        const time = dom('span', '', formatShortTime(job.created_at || job.started_at || job.finished_at));
        if (job.started_at && job.finished_at) {
            time.title = `耗时 ${formatDuration(job.started_at, job.finished_at)}`;
        }
        meta.appendChild(time);
        meta.appendChild(dom('span', '', `状态：${JOB_STATUS_LABELS[job.status] || job.status}`));

        const actions = dom('div', 'job-card-actions');
        if (job.status === 'queued' || job.status === 'running') {
            const btn = dom('button', 'btn btn-secondary btn-xs job-cancel-btn', '取消');
            btn.type = 'button';
            btn.addEventListener('click', () => jobAction(job.job_id, 'cancel', btn, '取消中…'));
            actions.appendChild(btn);
        } else if (job.status === 'cancelling') {
            actions.appendChild(dom('span', 'btn btn-ghost btn-xs', '取消中…'));
        } else if (job.status === 'failed' || job.status === 'interrupted') {
            const btn = dom('button', 'btn btn-secondary btn-xs job-retry-btn', '重试');
            btn.type = 'button';
            btn.addEventListener('click', () => jobAction(job.job_id, 'retry', btn, '重排队…'));
            actions.appendChild(btn);
        }

        card.appendChild(top);
        card.appendChild(meta);
        if (job.error) card.appendChild(dom('div', 'job-card-error', job.error));
        else if (job.detail) card.appendChild(dom('div', 'job-card-detail', job.detail));
        if (actions.children.length) card.appendChild(actions);
        return card;
    }

    async function jobAction(jobId, action, btn, busyText) {
        btn.disabled = true;
        btn.textContent = busyText;
        try {
            await API.jobs.action(jobId, action);
            toast(`任务${action === 'cancel' ? '取消请求已提交' : '重试请求已提交'}`, 'success');
        } catch (err) {
            btn.disabled = false;
            btn.textContent = action === 'cancel' ? '取消' : '重试';
            toast(`任务操作失败：${err.message}`, 'error');
        }
        await loadJobs(false);
    }

    function renderEverything() {
        renderDateViews();
        renderHero();
        renderFeed();
        renderJobs();
        updateSelectionUi();
        syncExpandAllLabel();
    }

    async function loadDates(preferDate) {
        state.loadError = null;
        try {
            const data = await API.briefs.dates({ checkOk: false });
            state.allDates = Array.isArray(data && data.dates) ? data.dates.filter(safeDate) : [];
            if (!state.allDates.length && data && !Array.isArray(data.dates)) {
                state.loadError = '简报日期接口返回异常，请刷新页面或检查服务状态。';
            }
        } catch (err) {
            state.allDates = [];
            state.loadError = `加载简报日期失败：${err.message || err}`;
            toast(state.loadError, 'error');
        }
        if (!state.allDates.length && !state.loadError) {
            state.loadError = '未找到简报日期。请确认简报目录已生成每日简报 HTML 后刷新页面。';
        }
        updateUniverse();
        const url = new URL(window.location.href);
        const candidate = preferDate || url.searchParams.get('date');
        const existing = candidate && safeDate(candidate) && hasHtml(candidate) ? candidate : null;
        if (!existing) {
            const latest = state.allDates[0];
            if (latest) state.currentDate = hasHtml(latest) ? latest : null;
        } else {
            state.currentDate = existing;
        }
        const anchorMonth = state.currentDate || state.allDates[0] || new Date().toISOString().slice(0, 10);
        const d = toDateObj(anchorMonth);
        state.monthOffset = 0;
        state.activeMonthAnchor = d;
    }

    async function loadMemoryStatus() {
        try {
            const data = await API.briefs.memoryStatus({ includeMeta: true, checkOk: false });
            state.memoryDates = data.dates || {};
            if (data.meta) {
                state.meta = data.meta;
                state.storageMode = data.meta.storage_mode || state.storageMode;
                state.upstreamAvailable = !!data.meta.upstream_available;
                if (Array.isArray(data.meta.html_dates)) {
                    // 容错：某些版本可能返回数组，统一转成 object
                    const obj = {};
                    data.meta.html_dates.forEach((r) => { if (r.date) obj[r.date] = r; });
                    state.meta.html_dates = obj;
                }
                if (data.meta.html_dates) {
                    Object.entries(data.meta.html_dates).forEach(([date, v]) => {
                        if (safeDate(date) && v && !v.has_pdf && !v.has_web) {
                            // 有目录但没有 HTML；若 /dates 列出了，应把它视作 missing
                            if (state.allDates.includes(date)) {
                                // 保留在 dateUniverse 中，hasHtml() 会返回 false
                            }
                        }
                    });
                }
            }
            if (!state.meta && state.allDates.length) {
                // 旧后端没有 meta 时，仍用 allDates 推断断档日
                state.meta = { html_dates: {}, queue_by_date: {} };
            }
            updateUniverse();
        } catch (err) {
            state.memoryDates = state.memoryDates || {};
            if (!state.meta) state.meta = { storage_mode: 'local', upstream_available: false, html_dates: {}, queue_by_date: {} };
        }
        renderDateViews();
        renderHero();
    }

    async function enrichPdfDocStates(cards) {
        const pdfs = cards.filter((c) => c.section === 'pdf' && !c.doc_state);
        if (!pdfs.length) return;

        if (state.docIndexSnapshot.size) {
            cards.forEach((card) => {
                if (card.section === 'pdf' && !card.doc_state) {
                    const doc = state.docIndexSnapshot.get(String(card.item_id));
                    if (doc) card.doc_state = doc;
                }
            });
            if (cards.every((c) => c.section !== 'pdf' || c.doc_state)) return;
        }

        try {
            const docs = await API.documents.list({ checkOk: false });
            const exact = new Map();
            const siblings = new Map();
            const verRe = /^(.+?)v\d+$/i;
            (docs || []).forEach((d) => {
                const name = String(d.doc_name || '').replace(/\.pdf$/i, '');
                if (!name) return;
                const indexed = !!(d.index_path && (d.status === 'completed' || d.index_ok));
                exact.set(name, indexed);
                const m = verRe.exec(name);
                if (m && indexed) {
                    const base = m[1];
                    if (!siblings.has(base)) siblings.set(base, name);
                }
            });
            cards.forEach((card) => {
                if (card.section !== 'pdf') return;
                const id = String(card.item_id);
                if (exact.has(id) && exact.get(id)) card.doc_state = { state: 'indexed', doc_name: id };
                else if (exact.has(id)) card.doc_state = { state: 'not_indexed', doc_name: id };
                else if (siblings.has(id)) card.doc_state = { state: 'indexed_elsewhere', doc_name: siblings.get(id) };
                else card.doc_state = { state: 'none', doc_name: '' };
                state.docIndexSnapshot.set(id, card.doc_state);
            });
        } catch (_) {
            // documents.list 失败时保持原有按钮状态，避免阻塞浏览
        }
    }

    async function loadCards(keepSelection = true) {
        if (!state.currentDate || !hasHtml(state.currentDate)) {
            state.cards = [];
            if (!keepSelection) state.selectedIds.clear();
            state.expandedIds.clear();
            renderEverything();
            return;
        }
        // 首屏只要卡片本身：它是本地文件，本来就该是毫秒级的东西。
        // `include_state` 会把"这条进没进简报库/文档库状态"一并算出来——那是
        // 一次要过记忆库的查询，放在这里就等于让整页等它。所以拆成两遍：
        // 先画出来，再补状态徽章。补不到也不算失败，屏幕上的东西不能倒回去。
        let data = null;
        try {
            data = await API.briefs.cards(state.currentDate, { compact: true, checkOk: false });
        } catch (err) {
            try {
                data = await API.briefs.cards(state.currentDate, { includeState: true, compact: true, checkOk: false });
            } catch (err2) {
                state.loadError = `加载 ${state.currentDate} 简报内容失败：${err2.message || err2}`;
                toast(state.loadError, 'error');
                state.cards = [];
                renderEverything();
                return;
            }
        }

        const cards = [];
        (data.pdf || []).forEach((c) => cards.push(Object.assign({}, c, { section: 'pdf' })));
        (data.web || []).forEach((c) => cards.push(Object.assign({}, c, { section: 'web' })));
        await enrichPdfDocStates(cards);
        state.cards = cards;
        if (!keepSelection) state.selectedIds.clear();
        state.expandedIds.clear();
        state.activeMonthAnchor = toDateObj(state.currentDate);
        state.monthOffset = 0;
        renderEverything();

        // 第二遍：状态。不 await——这一屏已经算出来了，剩下的活儿放后台补。
        const dateForState = state.currentDate;
        (async () => {
            let withState = null;
            try {
                withState = await API.briefs.cards(dateForState, { includeState: true, compact: true, checkOk: false });
            } catch (err) {
                return;   // 状态拿不到就维持现状：没有徽章也比把卡片弄没了强
            }
            if (state.currentDate !== dateForState) return;   // 用户已经翻页了，这趟就不必再改
            const byId = new Map();
            (withState.pdf || []).concat(withState.web || []).forEach((c) => byId.set(c.id || c.item_id, c));
            let touched = false;
            (state.cards || []).forEach((c) => {
                const hit = byId.get(c.id || c.item_id);
                if (hit && c.doc_state !== hit.doc_state) { c.doc_state = hit.doc_state; touched = true; }
            });
            if (touched) renderEverything();
        })();
    }

    async function loadJobs(updateCardsIfTransition = true) {
        try {
            const data = await API.jobs.list({ checkOk: false });
            state.jobs = Array.isArray(data.jobs) ? data.jobs : [];
        } catch (err) {
            state.jobs = state.jobs || [];
        }

        let shouldReloadCards = false;
        const next = {};
        state.jobs.forEach((j) => {
            const key = `${j.kind}:${j.target}`;
            next[key] = j.status;
            const prev = state.jobStatusSnapshot[key];
            if (prev && prev !== j.status && j.kind === 'process_item' && (j.status === 'done' || j.status === 'failed' || j.status === 'failed_permanent')) {
                if (!shouldReloadCards) shouldReloadCards = true;
            }
        });
        state.jobStatusSnapshot = next;

        if (state.jobs.some((j) => j.kind === 'load_brief_date' && j.target === state.currentDate)) {
            await loadMemoryStatus();
        }
        renderJobs();
        renderHero();
        renderDateViews();
        if (updateCardsIfTransition && shouldReloadCards) {
            await loadCards(true);
        }
    }

    async function pollTick() {
        if (document.hidden) return;
        await loadJobs();
    }

    function startPolling() {
        stopPolling();
        state.pollingTimer = window.setInterval(pollTick, 5000);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                window.clearTimeout(pollTick._resume);
                pollTick._resume = window.setTimeout(() => { pollTick(); }, 250);
            }
        });
    }

    function stopPolling() {
        if (state.pollingTimer) window.clearInterval(state.pollingTimer);
        state.pollingTimer = null;
    }

    async function setDate(date) {
        if (!safeDate(date)) return;
        if (state.currentDate === date) return;
        state.currentDate = date;
        state.selectedIds.clear();
        state.expandedIds.clear();
        state.docIndexSnapshot.clear();
        state.ingestControllers.forEach((c) => c.abort());
        state.ingestControllers.clear();
        state.activeMonthAnchor = toDateObj(date);
        state.monthOffset = 0;
        renderDateViews();
        renderHero();
        await loadCards(false);
    }

    function openJobsDrawer() {
        const drawer = el.$('jobs-drawer');
        const backdrop = el.$('jobs-drawer-backdrop');
        if (!drawer) return;
        drawer.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
        if (backdrop) {
            backdrop.hidden = false;
            backdrop.addEventListener('click', closeJobsDrawer, { once: true });
        }
        loadJobs(false);
    }

    function closeJobsDrawer() {
        const drawer = el.$('jobs-drawer');
        const backdrop = el.$('jobs-drawer-backdrop');
        if (drawer) drawer.classList.remove('open');
        drawer && drawer.setAttribute('aria-hidden', 'true');
        if (backdrop) backdrop.hidden = true;
    }

    function openMobileSidebar() {
        const side = el.$('briefs-sidebar');
        const backdrop = el.$('sidebar-backdrop');
        if (side) side.classList.add('mobile-open');
        if (backdrop) backdrop.classList.add('open');
    }

    function closeMobileSidebar() {
        const side = el.$('briefs-sidebar');
        const backdrop = el.$('sidebar-backdrop');
        if (side) side.classList.remove('mobile-open');
        if (backdrop) backdrop.classList.remove('open');
    }

    function showHeavyConfirm() {
        const selected = selectedCards();
        if (!selected.length) return;
        const pdfN = selected.filter((c) => c.section === 'pdf').length;
        const webN = selected.length - pdfN;
        const min = Math.ceil(pdfN * HEAVY_PDF_MIN_MIN + webN * HEAVY_WEB_MIN_MIN);
        const max = Math.ceil(pdfN * HEAVY_PDF_MAX_MIN + webN * HEAVY_WEB_MAX_MIN);
        const body = el.$('heavy-confirm-body');
        if (body) {
            body.innerHTML = '';
            const intro = dom('div', '', `将把已选的 ${selected.length} 篇条目加入后台队列，经下载/抓取、多维问答与摘要提取后写入「深度研报记忆 (ai-research)」。`);
            body.appendChild(intro);
            const ul = document.createElement('ul');
            ul.appendChild(dom('li', '', `论文 ${pdfN} 篇：通常 15–30 分钟/篇`));
            ul.appendChild(dom('li', '', `文章 ${webN} 篇：通常 3–5 分钟/篇`));
            ul.appendChild(dom('li', '', `预计总耗时：约 ${min}–${max} 分钟（单队列串行执行，后续任务会排队）`));
            ul.appendChild(dom('li', '', '已完成的条目会自动跳过；重复提交不会产生重复摘要，但仍会消耗上游调用预算'));
            body.appendChild(ul);
        }
        el.$('heavy-confirm-modal').hidden = false;
    }

    function closeHeavyConfirm() {
        el.$('heavy-confirm-modal').hidden = true;
    }

    async function submitHeavySelected() {
        const selected = selectedCards();
        if (!selected.length) return;
        const ids = selected.map((c) => c.item_id);
        const modal = el.$('heavy-confirm-modal');
        const submit = el.$('heavy-confirm-submit');
        if (modal) modal.hidden = true;
        if (submit) submit.disabled = true;
        try {
            const res = await API.briefs.load(state.currentDate, ids);
            if (res && typeof res.queued === 'number') {
                toast(`已将 ${res.queued}/${res.requested} 篇加入深度精析队列`, 'success');
            } else {
                toast('深度精析任务已提交', 'success');
            }
            state.selectedIds.clear();
            await loadCards(true);
            await loadJobs(false);
        } catch (err) {
            toast(`深度精析失败：${err.message}`, 'error');
        } finally {
            if (submit) submit.disabled = false;
        }
    }

    async function submitLightLoad(date) {
        if (!date) return;
        try {
            await API.briefs.lightLoad(date);
            toast(`${date} 已加入「简报速览库 (AATF)」入库队列`, 'success');
            await loadJobs(false);
        } catch (err) {
            toast(`整日入简报库请求失败：${err.message}`, 'error');
        }
    }

    async function submitBulkLightLoad() {
        const dates = Array.from(state.bulkSelectedDates).sort();
        if (!dates.length) {
            toast('请先在左侧日历或列表中选择需要批量入库的日期', 'warning');
            return;
        }
        if (dates.length > 40) {
            toast('单次最多排队 40 天，请分批选择', 'warning');
            return;
        }
        const btn = el.$('ingest-bulk-btn');
        if (btn) btn.disabled = true;
        try {
            const res = await API.briefs.lightLoad(dates);
            const list = (res && res.dates) || dates;
            toast(`已将 ${list.length} 个日期加入「简报速览库 (AATF)」入库队列`, 'success');
            state.bulkSelectedDates.clear();
            renderBulkBox();
            await loadJobs(false);
            await loadMemoryStatus();
        } catch (err) {
            toast(`批量入库请求失败：${err.message}`, 'error');
        } finally {
            if (btn) btn.disabled = state.bulkSelectedDates.size === 0;
        }
    }

    async function submitSyncMemory() {
        try {
            await API.briefs.syncMemory();
            toast('已加入「补写漏同步摘要 (ai-research)」后台任务', 'success');
            await loadJobs(false);
            closeMenu();
        } catch (err) {
            toast(`补写漏同步摘要失败：${err.message}`, 'error');
        }
    }

    function closeMenu() {
        const panel = el.$('more-menu-panel');
        const btn = el.$('more-menu-btn');
        if (panel) panel.hidden = true;
        if (btn) btn.setAttribute('aria-expanded', 'false');
    }

    function selectAllVisibleCards() {
        const selectable = visibleCards().filter(isSelectable);
        const allChecked = selectable.length > 0 && selectable.every((c) => state.selectedIds.has(c.item_id));
        selectable.forEach((c) => {
            if (allChecked) state.selectedIds.delete(c.item_id);
            else state.selectedIds.add(c.item_id);
        });
        renderFeed();
        updateSelectionUi();
    }

    function clearSelectedCards() {
        state.selectedIds.clear();
        renderFeed();
        updateSelectionUi();
    }

    function toggleAllVisibleExpanded() {
        const visible = visibleCards();
        const allExpanded = visible.length > 0 && visible.every((c) => state.expandedIds.has(c.item_id));
        visible.forEach((c) => {
            if (allExpanded) state.expandedIds.delete(c.item_id);
            else state.expandedIds.add(c.item_id);
        });
        renderFeed();
        syncExpandAllLabel();
    }

    function switchTab(tab) {
        state.filters.tab = tab;
        el.qa('.type-tab').forEach((btn) => {
            const active = btn.dataset.tab === tab;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', String(active));
        });
        renderFeed();
        syncExpandAllLabel();
    }

    function switchDrawerTab(tab) {
        state.jobsTab = tab;
        el.qa('.drawer-tab').forEach((btn) => {
            const active = btn.dataset.jobsTab === tab;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', String(active));
        });
        renderJobs();
    }

    function bindEvents() {
        el.qa('.type-tab').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
        el.qa('.drawer-tab').forEach((btn) => btn.addEventListener('click', () => switchDrawerTab(btn.dataset.jobsTab)));

        el.$('card-search-input').addEventListener('input', (e) => {
            state.filters.search = e.target.value.trim();
            renderFeed();
            syncExpandAllLabel();
        });
        el.$('status-filter-select').addEventListener('change', (e) => {
            state.filters.status = e.target.value;
            renderFeed();
            syncExpandAllLabel();
        });
        el.$('only-cn-toggle').addEventListener('change', (e) => {
            state.filters.onlyCn = e.target.checked;
            renderFeed();
            syncExpandAllLabel();
        });
        el.$('select-all-btn').addEventListener('click', selectAllVisibleCards);
        el.$('toggle-expand-all-btn').addEventListener('click', toggleAllVisibleExpanded);

        el.$('light-load-btn').addEventListener('click', () => submitLightLoad(state.currentDate));
        el.$('brief-chat-btn').addEventListener('click', () => {
            const m = currentMemory(state.currentDate);
            if (m.aatf === 0) {
                toast(`提示：${state.currentDate} 尚未入简报速览库，打开对话后若检索为空可先点「整日入简报库」`, 'warning');
            }
            window.open('/chat?namespaces=AATF', '_blank', 'noopener');
        });
        el.$('load-selected-btn').addEventListener('click', showHeavyConfirm);
        el.$('selection-clear-btn').addEventListener('click', clearSelectedCards);
        el.$('heavy-confirm-close').addEventListener('click', closeHeavyConfirm);
        el.$('heavy-confirm-cancel').addEventListener('click', closeHeavyConfirm);
        el.$('heavy-confirm-submit').addEventListener('click', submitHeavySelected);
        el.$('heavy-confirm-modal').addEventListener('click', (e) => {
            if (e.target === el.$('heavy-confirm-modal')) closeHeavyConfirm();
        });

        el.$('sync-memory-btn').addEventListener('click', submitSyncMemory);
        el.$('drawer-sync-memory-btn').addEventListener('click', submitSyncMemory);

        el.$('toggle-guide-btn').addEventListener('click', (e) => {
            const panel = el.$('briefs-guide-panel');
            const btn = e.currentTarget;
            state.guideVisible = !state.guideVisible;
            panel.hidden = !state.guideVisible;
            btn.setAttribute('aria-expanded', String(state.guideVisible));
            btn.lastChild && (btn.lastChild.textContent = state.guideVisible ? '收起说明' : '处理方式说明');
        });

        const menuBtn = el.$('more-menu-btn');
        const menuPanel = el.$('more-menu-panel');
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const open = menuPanel.hidden;
            menuPanel.hidden = !open;
            menuBtn.setAttribute('aria-expanded', String(open));
        });
        document.addEventListener('click', (e) => {
            if (!el.$('more-menu-wrap').contains(e.target)) closeMenu();
        });
        el.$('open-jobs-menu-btn').addEventListener('click', () => {
            closeMenu();
            openJobsDrawer();
        });

        const viewCalBtn = el.$('view-calendar-btn');
        const viewListBtn = el.$('view-list-btn');
        viewCalBtn.addEventListener('click', () => {
            el.$('calendar-view').hidden = false;
            el.$('date-list-view').hidden = true;
            viewCalBtn.classList.add('active');
            viewListBtn.classList.remove('active');
            viewCalBtn.setAttribute('aria-selected', 'true');
            viewListBtn.setAttribute('aria-selected', 'false');
        });
        viewListBtn.addEventListener('click', () => {
            el.$('date-list-view').hidden = false;
            el.$('calendar-view').hidden = true;
            viewListBtn.classList.add('active');
            viewCalBtn.classList.remove('active');
            viewListBtn.setAttribute('aria-selected', 'true');
            viewCalBtn.setAttribute('aria-selected', 'false');
            renderDateList();
        });

        el.$('cal-prev-month').addEventListener('click', () => {
            state.monthOffset -= 1;
            renderDateViews();
        });
        el.$('cal-next-month').addEventListener('click', () => {
            state.monthOffset += 1;
            renderDateViews();
        });
        el.$('cal-bulk-mode-toggle').addEventListener('change', (e) => {
            state.bulkMode = e.target.checked;
            document.body.classList.toggle('bulk-calendar-mode', state.bulkMode);
            renderDateViews();
        });
        el.$('list-show-missing-toggle').addEventListener('change', (e) => {
            state.showMissingDates = e.target.checked;
            renderDateList();
        });
        el.$('ingest-select-unchecked-btn').addEventListener('click', () => {
            const pending = state.dateUniverse.filter((r) => r.hasHtml && currentMemory(r.date).aatf === 0).map((r) => r.date);
            state.bulkSelectedDates = new Set(pending);
            renderDateViews();
        });
        el.$('ingest-clear-btn').addEventListener('click', () => {
            state.bulkSelectedDates.clear();
            renderDateViews();
        });
        el.$('ingest-bulk-btn').addEventListener('click', submitBulkLightLoad);

        el.$('mobile-sidebar-btn') && el.$('mobile-sidebar-btn').addEventListener('click', openMobileSidebar);
        el.$('sidebar-close-btn') && el.$('sidebar-close-btn').addEventListener('click', closeMobileSidebar);
        el.$('sidebar-backdrop') && el.$('sidebar-backdrop').addEventListener('click', closeMobileSidebar);
        el.$('jobs-drawer-close').addEventListener('click', closeJobsDrawer);
        el.$('jobs-drawer-backdrop').addEventListener('click', closeJobsDrawer);

        window.openJobsDrawer = openJobsDrawer;
        window.closeJobsDrawer = closeJobsDrawer;

        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            const heavy = el.$('heavy-confirm-modal');
            const drawer = el.$('jobs-drawer');
            if (heavy && !heavy.hidden) {
                closeHeavyConfirm();
            } else if (drawer && drawer.classList.contains('open')) {
                closeJobsDrawer();
            } else {
                closeMenu();
            }
        });
    }

    async function init() {
        bindEvents();
        await Promise.all([loadDates(), loadMemoryStatus()]);
        await loadCards(false);
        await loadJobs(false);
        startPolling();
    }

    document.addEventListener('DOMContentLoaded', init);
})();
