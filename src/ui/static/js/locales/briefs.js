/**
 * /briefs page locale strings (English).
 * Keys are the exact original Chinese strings produced by templates/briefs.html,
 * static/js/briefs.js and static/js/paper-ingest.js (text nodes plus
 * placeholder/title/aria-label attributes). Technical identifiers such as
 * AATF, ai-research, PDF and URLs are preserved as-is.
 *
 * Shared chrome strings (OK/Cancel/Close/job status labels, "已选 N 天",
 * "已将 x/y 篇加入深度精析队列", the empty-day tip sentences, page title)
 * are already registered by base.js and are not duplicated here.
 */
(function () {
    'use strict';

    // Composite strings like "状态：<label>" / "耗时 <duration>" need the inner
    // piece translated too; exact map lookup only sees the whole text node,
    // so function repls do the inner translation here.
    const JOB_STATUS_EN = {
        '排队中': 'Queued',
        '执行中': 'Running',
        '取消中': 'Cancelling',
        '已完成': 'Completed',
        '失败': 'Failed',
        '已中断': 'Interrupted',
        '已取消': 'Cancelled',
    };

    function statusLine(_match, inner) {
        return 'Status: ' + (JOB_STATUS_EN[inner] || inner);
    }

    function durationEn(text) {
        let m = /^(\d+) 秒$/.exec(text);
        if (m) return m[1] + 's';
        m = /^(\d+) 分 (\d+) 秒$/.exec(text);
        if (m) return m[1] + 'm ' + m[2] + 's';
        m = /^(\d+) 分$/.exec(text);
        if (m) return m[1] + 'm';
        m = /^(\d+) 小时 (\d+) 分$/.exec(text);
        if (m) return m[1] + 'h ' + m[2] + 'm';
        return text;
    }

    function elapsedLine(_match, inner) {
        return 'Elapsed: ' + durationEn(inner);
    }

    I18N.register({
        lang: 'en',
        exact: {
            // ---------------- Sidebar: calendar, list, legend, bulk box ----------------
            '简报日历': 'Briefing Calendar',
            '月历': 'Calendar',
            '列表': 'List',
            '日期视图切换': 'Date view toggle',
            '关闭日期栏': 'Close date sidebar',
            '上个月': 'Previous month',
            '下个月': 'Next month',
            '简报日期与入库状态': 'Briefing dates and import status',
            '日期状态图例': 'Date status legend',
            '状态图例': 'Status legend',
            '一': 'Mon',
            '二': 'Tue',
            '三': 'Wed',
            '四': 'Thu',
            '五': 'Fri',
            '六': 'Sat',
            '日': 'Sun',
            '无简报 HTML': 'No brief HTML',
            '有 HTML · 待入库': 'Has HTML · pending import',
            '已入简报库 (AATF)': 'In Brief Library (AATF)',
            '含深度精析': 'Includes deep analysis',
            '排队 / 入库中': 'Queued / importing',
            '异常 / 中断': 'Errors / interrupted',
            '显示无简报的断档日期': 'Show gap days with no brief',
            '点击日历用于多日批量勾选': 'Click calendar days for multi-day bulk selection',
            '开启后点击日历日期将加入/移出批量入库勾选，而非切换浏览日期':
                'When enabled, clicking a calendar date adds or removes it from the bulk import selection instead of switching the browsing date',
            '批量收入简报速览库': 'Bulk import into Brief Library',
            '勾选多日后一次排队入库（单次最多 40 天，已入库条目自动去重）。':
                'Select multiple days to queue them for import in one batch (max 40 days per run; already-imported items are deduplicated automatically).',
            '只选待入库': 'Select pending only',
            '只勾选有简报 HTML 且尚未进入简报速览库的日期':
                'Select only dates that have brief HTML and have not entered the Brief Library yet',
            '清空': 'Clear',
            '该日期未生成简报 HTML': 'No brief HTML generated for this date',
            '无 HTML': 'No HTML',

            // ---------------- Hero header, status pills, actions ----------------
            '当日简报内容': 'Daily brief content',
            '📅 选择日期': '📅 Choose date',
            '浏览每日筛选论文与文章：整日导读可收入':
                'Browse the daily curated papers and articles: import the whole-day digest into ',
            '，勾选重点做': ', check key items for ',
            '，或单篇收入 ': ', or import a single paper into the ',
            '精读。': 'for close reading.',
            '简报速览库': 'Brief Library',
            '深度精析': 'Deep Analyze',
            'PDF 文档库': 'PDF Library',
            '处理方式说明': 'How processing works',
            '收起说明': 'Collapse guide',
            '更多': 'More',
            '更多维护操作': 'More maintenance actions',
            '补写漏同步摘要': 'Backfill missed summaries',
            '仅用于运维兜底：把历史已完成但漏写进深度研报记忆 (ai-research) 的摘要补齐':
                'Ops fallback only: backfill summaries that finished in the past but were never written to Deep Research Memory (ai-research)',
            '前往数据中心管理记忆与文档 ↗': 'Manage memory & documents in Data Center ↗',
            '查看或清理简报速览库 (AATF)、深度研报记忆与本地 PDF 索引':
                'View or clean up the Brief Library (AATF), Deep Research Memory and local PDF index',
            '打开后台任务队列': 'Open background job queue',
            '查看排队、运行中、失败中断任务并支持取消或重试':
                'View queued, running and failed/interrupted jobs, with cancel or retry support',
            '后台任务队列': 'Background job queue',
            '加载状态中…': 'Loading status…',
            '将当前日期全部卡片导读写入简报速览库 (AATF)，不下载原文 PDF、不受卡片勾选影响':
                'Write the digests of all cards for the current date into the Brief Library (AATF); no PDF downloads, unaffected by card checkboxes',
            '整日入简报库': 'Import day to Brief Library',
            '新标签打开对话页，并预设记忆范围为简报速览库 (AATF)':
                'Open Chat in a new tab with the memory scope preset to the Brief Library (AATF)',
            '问简报库 ↗': 'Ask Brief Library ↗',

            // ---------------- Guide panel ----------------
            '按整天': 'Whole day',
            '1. 整日入简报库': '1. Import day to Brief Library',
            '将当天所有卡片的导读写入': 'Writes the digests of all cards of the day into ',
            '，不下载 PDF、不做多维问答。重复执行自动去重。':
                ', without downloading PDFs or running multi-dimensional Q&A. Re-running deduplicates automatically.',
            '耗时': 'Time',
            '：视存储模式而定（上游语义抽取约 1–数分钟/天；本地模式秒级）':
                ': depends on storage mode (upstream semantic extraction ~1 to several minutes/day; local mode is near-instant)',
            '对话怎么用': 'How Chat uses it',
            '：对话页默认不检索此库；点击「问简报库 ↗」或在对话页 🧠 记忆范围手动勾选。':
                ': Chat does not search this library by default; click "Ask Brief Library ↗" or tick it manually under 🧠 memory scope in Chat.',
            '按勾选条目': 'Selected items',
            '2. 深度精析选中': '2. Deep Analyze selected',
            '对左侧复选框勾选的条目下载 PDF 或抓取全文，经多维度问答提炼结构化研报摘要，写入':
                'Downloads PDFs or fetches full text for the items checked on the left, distills structured research summaries via multi-dimensional Q&A, and writes them into ',
            '：论文约 15–30 分钟/篇，文章约 3–5 分钟/篇（单队列串行排队）。':
                ': papers ~15–30 min each, articles ~3–5 min each (single serial queue).',
            '：完成后在对话页': ': after completion, the chat page ',
            '默认自动检索': 'searches it automatically by default',
            '，直接提问即可命中。': '; just ask directly to get hits.',
            '按单篇论文': 'Single paper',
            '3. 收入 PDF 文档库': '3. Import to PDF Library',
            '直接点击卡片操作行的「收入 PDF 文档库」，下载完整原 PDF 并建立独立本地全文向量索引（不写上述两个记忆库）。':
                'Click "Import to PDF Library" in the card action row to download the full original PDF and build a standalone local full-text vector index (neither memory library above is written).',
            '：约 2–10 分钟/篇（独立后台执行，不阻塞下方简报任务队列）。':
                ': ~2–10 min each (runs in a separate background lane, not blocking the brief job queue).',
            '：索引就绪后原地显示「📖 打开精读 ↗」，直达单篇全文深挖对话。':
                ': once indexed, "📖 Open deep read ↗" appears in place, opening a full-text deep-dive chat for this paper.',
            '关于状态徽标：': 'About the status badges: ',
            '每张卡片右上角的「未深度精析 / 精析排队中 / 已深度精析 / 精析失败」':
                'The "Not analyzed / Queued / Analyzed / Failed" badge at each card\'s top-right ',
            '仅代表第 2 项（深度精析）进度':
                'only reflects the progress of step 2 (Deep Analyze)',
            '，不受“整日入简报库”或“收入 PDF 文档库”影响。左侧日历完整显示每天状态——虚线灰格表示当天没有生成简报 HTML。':
                ', unaffected by "Import day to Brief Library" or "Import to PDF Library". The calendar on the left shows each day\'s full status — a dashed grey cell means no brief HTML was generated that day.',

            // ---------------- Filter bar ----------------
            '内容类型切换': 'Content type toggle',
            '搜索标题、导读、标签…': 'Search titles, digests, tags…',
            '按深度精析状态筛选': 'Filter by deep-analysis status',
            '全部精析状态': 'All analysis statuses',
            '未深度精析': 'Not analyzed',
            '精析排队中': 'Analysis queued',
            '已深度精析': 'Deep analyzed',
            '精析失败': 'Analysis failed',
            '隐藏没有中文导读的条目': 'Hide items without a Chinese digest',
            '仅有导读': 'With digest only',
            '全选或取消全选当前筛选下可参与深度精析的条目':
                'Select or deselect all items eligible for deep analysis under the current filter',
            '全选待精析': 'Select all to analyze',
            '重新全选': 'Re-select all',
            '取消全选': 'Deselect all',
            '全部展开': 'Expand all',
            '全部收起': 'Collapse all',
            '正在加载简报内容…': 'Loading brief content…',

            // ---------------- Selection dock / confirm modal ----------------
            '深度精析批量操作': 'Deep analyze bulk actions',
            '将加入后台串行队列，摘要自动写入深度研报记忆 (ai-research)':
                'Will join the background serial queue; summaries are written to Deep Research Memory (ai-research) automatically',
            '将加入后台队列，摘要自动写入深度研报记忆 (ai-research)':
                'Will join the background queue; summaries are written to Deep Research Memory (ai-research) automatically',
            '取消选择': 'Clear selection',
            '确认加入深度精析队列': 'Confirm adding to Deep Analyze queue',
            '确认加入队列': 'Confirm and enqueue',

            // ---------------- Jobs drawer ----------------
            '单队列串行执行：耗时较长的论文深度精析会阻塞后续排队任务':
                'The queue runs serially: long paper analyses block later queued tasks',
            '关闭任务抽屉': 'Close jobs drawer',
            '历史已完成深度精析但漏写记忆时使用：':
                'Use when past deep analyses were finished but missed writing to memory:',
            '补写漏同步摘要 (ai-research)': 'Backfill missed summaries (ai-research)',

            // ---------------- Date pills & calendar cell tooltips (briefs.js) ----------------
            '待入库': 'Pending import',
            '速览库入库中…': 'Importing into Brief Library…',
            '速览库排队': 'Brief Library queued',
            '速览库异常': 'Brief Library error',
            '取消中…': 'Cancelling…',
            '该日期没有发现简报 HTML 文件，不能入库或加载':
                'No brief HTML file found for this date; it cannot be imported or loaded',
            '该日卡片导读已进入简报速览库 (AATF)': 'The day\'s card digests are in the Brief Library (AATF)',
            '该日已有条目完成深度精析并写入深度研报记忆 (ai-research)':
                'Some items of this day finished deep analysis and were written to Deep Research Memory (ai-research)',
            '该日有深度精析条目排队或运行中': 'Some deep-analysis items of this day are queued or running',
            '该日有深度精析条目失败': 'Some deep-analysis items of this day failed',
            '该日有简报 HTML，但尚未进入记忆库；可整日入简报库或选择重点深度精析':
                'This day has brief HTML but nothing in any memory library yet; import the day to the Brief Library or deep-analyze key items',
            '后台任务：整日入简报库 (AATF)': 'Background job: Import day to Brief Library (AATF)',
            '整日入简报库任务失败或中断，可在任务抽屉重试':
                'The Import day to Brief Library job failed or was interrupted; retry in the jobs drawer',
            '暂无简报日期': 'No brief dates',
            '简报日期接口返回异常，请刷新页面或检查服务状态。':
                'The brief dates API returned an error. Refresh the page or check the service status.',
            '未找到简报日期。请确认简报目录已生成每日简报 HTML 后刷新页面。':
                'No brief dates found. Make sure the brief directory contains daily brief HTML, then refresh the page.',

            // ---------------- Card rendering (briefs.js) ----------------
            '该条目已完成深度精析，摘要已写入深度研报记忆 (ai-research)':
                'This item finished deep analysis; its summary is written to Deep Research Memory (ai-research)',
            '该条目已在深度精析队列中': 'This item is in the deep analysis queue',
            '深度精析失败，可重新勾选提交': 'Deep analysis failed; re-check and submit to retry',
            '尚未完成深度精析': 'Deep analysis not done yet',
            '无导读': 'No digest',
            '后续可追问：': 'Follow-up:',
            '为何值得看：': 'Why it matters:',
            'English brief：': 'English brief: ',
            '上次失败：': 'Last failure:',
            '原文 ↗': 'Source ↗',
            '✅ 已入文档库': '✅ In PDF Library',
            '✅ 已按其他版本入库': '✅ In PDF Library (other version)',
            '重新索引': 'Re-index',
            '⬇ 收入 PDF 文档库': '⬇ Import to PDF Library',
            '将本篇论文 PDF 收入本地 PDF 文档库并建立全文索引；不写入简报速览库或深度研报记忆':
                'Import this paper\'s PDF into the local PDF Library and build a full-text index; the Brief Library and Deep Research Memory are not written',
            '📖 打开精读 ↗': '📖 Open deep read ↗',
            '已在本地文档库': 'In local PDF library',
            '可原文深挖': 'Full-text digging available',
            '该论文已在本地文档库完成索引，可直接打开精读':
                'This paper is fully indexed in the local PDF library; open the deep read directly',
            '下载中…': 'Downloading…',
            '建立索引中…': 'Building index…',
            'PDF 入库组件加载失败，请刷新页面后重试':
                'PDF import component failed to load; refresh the page and retry',
            '重新检查 / 强制重下': 'Re-check / force redownload',
            '索引等待超时；如果文件已存在但未成功索引，再次点击会尝试强制重下并重建索引':
                'Index wait timed out; if the file exists but was not indexed, clicking again forces a redownload and reindex',
            'PDF 索引等待超时，可稍后重试': 'PDF index wait timed out, retry later',
            '收入 PDF 文档库失败，可重试': 'Import to PDF Library failed; you can retry',
            '当前条件无匹配条目': 'No items match the current filters',
            '论文当前筛选下无匹配条目，请尝试清除搜索或状态筛选。':
                'No papers match the current filters; try clearing the search or status filter.',
            '文章当前筛选下无匹配条目，请尝试清除搜索或状态筛选。':
                'No articles match the current filters; try clearing the search or status filter.',
            '当前日期没有匹配论文或文章，可能是简报文件为空、筛选条件过窄，或该日尚未生成内容。':
                'No matching papers or articles for this date — the brief file may be empty, the filters too narrow, or no content was generated that day.',

            // ---------------- Hero context tip & stats ----------------
            '请在左侧日历选择或加载简报日期。': 'Pick or load a brief date in the calendar on the left.',
            '今日尚未进入任何记忆库': 'This day has not entered any memory library yet',
            '：日常速览可点「整日入简报库」把全部卡片导入 ':
                ': for quick browsing, click "Import day to Brief Library" to import all cards into ',
            '简报速览库 (AATF)': 'Brief Library (AATF)',
            '；重点内容可勾选后「深度精析」写入 ':
                '; for key items, check them and run "Deep Analyze" to write them into ',
            '深度研报记忆 (ai-research)': 'Deep Research Memory (ai-research)',
            '状态待刷新': 'Status pending refresh',
            ' · 暂无卡片': ' · No cards',
            '上游 LLM-Memory 模式：卡片导读做 agentic 抽取，通常约 1–数分钟/天（卡片越多越久）':
                'Upstream LLM-Memory mode: card digests go through agentic extraction, typically ~1 to several minutes/day (more cards take longer)',
            '本地模式：本地直写通常几秒到几十秒完成；重复执行自动去重':
                'Local mode: direct local writes usually finish in seconds to tens of seconds; re-running deduplicates automatically',

            // ---------------- Jobs drawer & actions ----------------
            '重试': 'Retry',
            '重排队…': 'Re-queuing…',
            '任务取消请求已提交': 'Job cancel request submitted',
            '任务重试请求已提交': 'Job retry request submitted',
            '暂无后台任务。提交深度精析或整日入简报库后，任务会显示在这里。':
                'No background jobs yet. Submitting Deep Analyze or Import day to Brief Library will show tasks here.',
            '暂无该分类下的任务。': 'No tasks in this category.',
            '生成简报汇总页': 'Generate brief summary page',
            '未命名任务': 'Unnamed task',
            '：': ':',
        },
        patterns: [
            // Weekday/month calendar labels built from number + 年/月
            { re: /^(\d{4})年(\d{2})月$/, repl: '$1-$2' },

            // Date-prefixed tooltips and toasts (cell.title / warn messages in briefs.js)
            { re: /^(\d{4}-\d{2}-\d{2})：无简报 HTML$/, repl: '$1: No brief HTML' },
            { re: /^(\d{4}-\d{2}-\d{2})：入库任务失败\/中断$/, repl: '$1: Import job failed/interrupted' },
            { re: /^(\d{4}-\d{2}-\d{2})：入库任务进行中$/, repl: '$1: Import job running' },
            { re: /^(\d{4}-\d{2}-\d{2})：含深度精析，并已入简报速览库$/, repl: '$1: Includes deep analysis, imported into Brief Library' },
            { re: /^(\d{4}-\d{2}-\d{2})：含深度精析$/, repl: '$1: Includes deep analysis' },
            { re: /^(\d{4}-\d{2}-\d{2})：已入简报速览库 \(AATF\)$/, repl: '$1: Imported into Brief Library (AATF)' },
            { re: /^(\d{4}-\d{2}-\d{2})：有 HTML，待入库$/, repl: '$1: HTML present, pending import' },
            { re: /^(\d{4}-\d{2}-\d{2}) 没有简报 HTML，无法加入批量入库$/, repl: '$1 has no brief HTML and cannot be added to bulk import' },
            { re: /^(\d{4}-\d{2}-\d{2}) 没有简报 HTML，无法加载内容$/, repl: '$1 has no brief HTML and cannot be loaded' },
            { re: /^(\d{4}-\d{2}-\d{2}) 没有简报 HTML，无法进行入库或加载。$/, repl: '$1 has no brief HTML; importing or loading is unavailable.' },
            { re: /^(\d{4}-\d{2}-\d{2}) 已加入「简报速览库 \(AATF\)」入库队列$/, repl: '$1 added to the Brief Library (AATF) import queue' },
            { re: /^提示：(\d{4}-\d{2}-\d{2}) 尚未入简报速览库，打开对话后若检索为空可先点「整日入简报库」$/, repl: 'Note: $1 is not yet in the Brief Library. If retrieval is empty after opening Chat, click "Import day to Brief Library" first.' },

            // Date pills: "简报速览库 AATF · 12" / "深度研报 ai-research · 3" / "深度排队 2" / "深度失败 1"
            { re: /^简报速览库 AATF · (\d+)$/, repl: 'Brief Library AATF · $1' },
            { re: /^深度研报 ai-research · (\d+)$/, repl: 'Deep Research ai-research · $1' },
            { re: /^深度排队 (\d+)$/, repl: 'Deep queued $1' },
            { re: /^深度失败 (\d+)$/, repl: 'Deep failed $1' },

            // Bulk box: badge / hint
            { re: /^(\d+) 天尚未入库；(\d+) 天已有数据，重复条目由后端自动去重。单次最多排队 40 天。$/, repl: '$1 days not yet imported; $2 days already have data (duplicates are deduplicated by the backend). Max 40 days per run.' },
            { re: /^(\d+) 天尚未入库。单次最多排队 40 天。$/, repl: '$1 days not yet imported. Max 40 days per run.' },

            // Sidebar coverage meta: "有简报 30 天" / "有简报 30 天 · 断档 5 天"
            { re: /^有简报 (\d+) 天 · 断档 (\d+) 天$/, repl: '$1 days with briefs · $2 gap days' },
            { re: /^有简报 (\d+) 天$/, repl: '$1 days with briefs' },

            // Hero: day counts " · 3 篇论文 · 2 篇文章"
            { re: /^ · (\d+) 篇论文 · (\d+) 篇文章$/, repl: ' · $1 papers · $2 articles' },
            { re: /^(\d{4}-\d{2}-\d{2}) 尚未入简报速览库，打开对话后若检索为空可先点「整日入简报库」$/, repl: '$1 is not yet in the Brief Library. If retrieval is empty after opening Chat, click "Import day to Brief Library" first.' },

            // Hero context tip (non-empty-memory day): "简报速览库已有 12 条" etc.
            { re: /^简报速览库已有 (\d+) 条$/, repl: 'Brief Library has $1 entries' },
            { re: /^深度研报已完成 (\d+) 篇$/, repl: 'Deep research completed: $1' },
            { re: /^深度精析排队 (\d+) 篇$/, repl: 'Deep analysis queued: $1' },
            { re: /^深度精析失败 (\d+) 篇$/, repl: 'Deep analysis failed: $1' },

            // Section headings / feed empty states
            { re: /^已筛选 \/ 共 (\d+)$/, repl: 'Filtered / $1 total' },
            { re: /^已选 (\d+) 篇$/, repl: 'Selected $1 items' },

            // Tabs & drawer tabs whose text nodes carry trailing/leading whitespace around the count spans
            { re: /^(\s*)全部\s*$/, repl: '$1All' },
            { re: /^(\s*)论文\s*$/, repl: '$1Papers' },
            { re: /^(\s*)文章\s*$/, repl: '$1Articles' },
            { re: /^(\s*)批量入库 \($/, repl: '$1Bulk import (' },
            { re: /^(\s*)进行中\s*$/, repl: '$1In progress' },
            { re: /^(\s*)异常\/中断\s*$/, repl: '$1Errors/interrupted' },
            { re: /^(\s*)全部记录\s*$/, repl: '$1All records' },

            // Deep-Analyze confirm modal (dynamic numbers)
            { re: /^将把已选的 (\d+) 篇条目加入后台队列，经下载\/抓取、多维问答与摘要提取后写入「深度研报记忆 \(ai-research\)」。$/, repl: 'The $1 selected items will join the background queue: after downloading/scraping, multi-dimensional Q&A and summary extraction they are written to Deep Research Memory (ai-research).' },
            { re: /^论文 (\d+) 篇：通常 15–30 分钟\/篇$/, repl: 'Papers $1: usually 15–30 min each' },
            { re: /^文章 (\d+) 篇：通常 3–5 分钟\/篇$/, repl: 'Articles $1: usually 3–5 min each' },
            { re: /^预计总耗时：约 (\d+)–(\d+) 分钟（单队列串行执行，后续任务会排队）$/, repl: 'Estimated total: ~$1–$2 min (serial queue; later tasks wait their turn)' },

            // Job kinds (target is a date or item id)
            { re: /^整日入简报库 · (\d{4}-\d{2}-\d{2})$/, repl: 'Import day to Brief Library · $1' },
            { re: /^深度精析（论文） · (.+)$/, repl: 'Deep Analyze (paper) · $1' },
            { re: /^深度精析（条目） · (.+)$/, repl: 'Deep Analyze (item) · $1' },
            { re: /^补写漏同步摘要 · 全部待补灌摘要$/, repl: 'Backfill missed summaries · all pending summaries' },
            { re: /^补写漏同步摘要 · (.+)$/, repl: 'Backfill missed summaries · $1' },

            // Job card meta lines with inner translated pieces
            { re: /^状态：(.+)$/, repl: statusLine },
            { re: /^耗时 (.+)$/, repl: elapsedLine },
            { re: /^(\d+) 秒$/, repl: '$1s' },
            { re: /^(\d+) 分 (\d+) 秒$/, repl: '$1m $2s' },
            { re: /^(\d+) 小时 (\d+) 分$/, repl: '$1h $2m' },
            { re: /^(\d+) 分$/, repl: '$1m' },

            // Error-suffix toasts
            { re: /^加载简报日期失败：(.*)$/, repl: 'Failed to load brief dates: $1' },
            { re: /^加载 (\d{4}-\d{2}-\d{2}) 简报内容失败：(.*)$/, repl: 'Failed to load brief content for $1: $2' },
            { re: /^深度精析失败：(.*)$/, repl: 'Deep analysis failed: $1' },
            { re: /^整日入简报库请求失败：(.*)$/, repl: 'Import day to Brief Library request failed: $1' },
            { re: /^批量入库请求失败：(.*)$/, repl: 'Bulk import request failed: $1' },
            { re: /^补写漏同步摘要失败：(.*)$/, repl: 'Backfill missed summaries failed: $1' },
            { re: /^任务操作失败：(.*)$/, repl: 'Job action failed: $1' },
            { re: /^收入 PDF 文档库失败：(.*)$/, repl: 'Import to PDF Library failed: $1' },
        ],
    });
})();
