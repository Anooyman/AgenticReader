/**
 * /chat page locale strings (en).
 * Covers: chat.html, chat.js, chat-enhancer.js and the chat-facing
 * error texts from api.js / ui-components.js.
 * LLM answers, user messages and document content are intentionally not translated.
 */
(function () {
    // Names rendered inside concatenated innerHTML templates: the visible text
    // node often contains icon + name (e.g. " - 🧠 工具规划"), so exact matching
    // misses them. One non-global substring pattern maps them by longest-first.
    const NAME_MAP = {
        // Agents
        '💬 回答代理': '💬 Answer agent',
        '🔍 检索代理': '🔍 Retrieval agent',
        // Stages (answer / retrieval pipeline)
        '工具规划': 'Tool planning',
        '执行工具': 'Executing tools',
        '生成答案': 'Generating answer',
        '文档选择': 'Document selection',
        '文档检索': 'Document retrieval',
        '查询改写': 'Query rewriting',
        '多文档检索': 'Multi-doc retrieval',
        '综合答案': 'Synthesizing answer',
        '查询重写': 'Query rewriting',
        '思考选择': 'Thinking & selecting',
        '执行检索': 'Executing retrieval',
        '累积总结': 'Accumulating summary',
        '评估结果': 'Evaluating results',
        '格式化输出': 'Formatting output',
        // Tools
        '语义检索': 'Semantic search',
        '提取标题': 'Extracting titles',
        '标题匹配': 'Title matching',
        '获取结构': 'Getting structure',
        '页码检索': 'Page-range search',
        '获取页面': 'Getting pages',
        '向量检索': 'Vector search',
        '获取内容': 'Getting content',
        '获取章节': 'Getting chapters',
        '获取图片': 'Getting images',
        // NOTE: short workflow labels (规划/执行/生成/改写/思考/评估/输出) are
        // intentionally left OUT of this substring map — they are rendered as
        // whole text nodes (covered by exact) and would otherwise corrupt
        // unrelated Chinese text on other pages that load this locale.
        // Parallel retrieval banner (strong tag)
        '多文档并行检索': 'Multi-document parallel retrieval',
    };

    function mapName(match) {
        return Object.prototype.hasOwnProperty.call(NAME_MAP, match) ? NAME_MAP[match] : match;
    }

    // Longest-first alternation so compound names win over their short parts.
    // Escape each key separately so the alternation pipes stay functional.
    const nameKeys = Object.keys(NAME_MAP).sort(function (a, b) { return b.length - a.length; });
    const namePatternRe = new RegExp('(' + nameKeys.map(function (k) { return k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')');

    I18N.register({
        lang: 'en',
        exact: {
            // ---- Header / toolbar (chat.html) ----
            '智能对话': 'Smart Chat',
            '智能文档对话助手': 'Intelligent document assistant',
            '点击 📎 选择文档，或直接开始对话': 'Click 📎 to pick documents, or just start chatting',
            '📜 会话': '📜 Sessions',
            '会话管理': 'Session management',
            '📄 PDF': '📄 PDF',
            '🗑️ 清空': '🗑️ Clear',
            '← 返回': '← Back',

            // ---- Welcome panels ----
            '开始你的深度对话': 'Start your in-depth conversation',
            '输入问题，获取智能答案': 'Ask a question to get smart answers',
            '对话已清空': 'Chat cleared',
            '可以开始新的对话了': 'You can start a new conversation',

            // ---- Tool buttons (titles / tooltips) ----
            '选择PDF文档': 'Select PDF documents',
            '启用网络搜索': 'Enable web search',
            '记忆检索范围': 'Memory retrieval scope',
            '语音输入': 'Voice input',
            '点击停止录音': 'Click to stop recording',
            '朗读此回复': 'Read this reply aloud',

            // ---- Input placeholder ----
            '直接输入问题开始对话，或点击 📎 选择文档...': 'Type a question to start chatting, or click 📎 to choose documents...',

            // ---- Document picker modal ----
            '📚 选择文档': '📚 Select documents',
            '确认': 'Confirm',
            '暂无已索引文档': 'No indexed documents yet',
            '加载失败': 'Failed to load',

            // ---- Memory scope popover ----
            '🧠 记忆检索范围': '🧠 Memory Retrieval Scope',
            '深度研报记忆': 'Deep Research Memory',
            '历史对话': 'Chat History',
            '简报速览库': 'Brief Library',
            '(AATF · 简报页整日导入)': '(AATF · Briefs daily import)',
            '由简报页「深度精析」生成的高密度多维研报摘要，默认自动检索':
                'High-density multi-angle research summaries produced by "Deep Analyze" on the Briefs page; searched automatically by default',
            '过往会话中自动沉淀的历史问答记忆，默认自动检索':
                'Q&A history automatically distilled from past sessions; searched automatically by default',
            '由简报页「整日入简报库」写入的每日简报卡片导读；未导入过时检索为空':
                'Daily brief card digests written by "Import day to Brief Library" on the Briefs page; returns empty if that day was never imported',
            '恢复缺省': 'Restore defaults',
            '清除自定义勾选，恢复缺省白名单': 'Clear custom selections and restore the default allowlist',
            '完成': 'Done',

            // ---- Scroll navigation ----
            '回到最早消息': 'Jump to earliest message',
            '回到最新内容': 'Jump to latest content',
            '最早消息': 'Earliest',
            '查看最新内容': 'View latest',
            '有新内容，点击查看': 'New content — click to view',

            // ---- Connection status ----
            '已连接': 'Connected',
            '连接错误': 'Connection error',

            // ---- PDF panel ----
            '📄 PDF 预览': '📄 PDF Preview',
            '选择要预览的文档：': 'Select a document to preview:',
            '-- 请选择文档 --': '-- Select a document --',
            '点击页码引用查看PDF': 'Click a page reference to view the PDF',

            // ---- Loading / progress messages ----
            '初始化中...': 'Initializing...',
            '加载PDF...': 'Loading PDF...',
            '识别语音中...': 'Transcribing speech...',
            '⏳ 加载中...': '⏳ Loading...',
            '🤔 正在思考...': '🤔 Thinking...',
            '正在准备并行检索...': 'Preparing parallel retrieval...',
            '迭代进度': 'Iteration progress',
            '🤖 代理:': '🤖 Agent:',
            '⚙️ 阶段:': '⚙️ Stage:',
            '🔄 迭代:': '🔄 Iteration:',
            '🛠️ 工具:': '🛠️ Tool:',
            '💬 信息:': '💬 Message:',
            '多文档并行检索': 'Multi-document parallel retrieval',

            // ---- Agent / stage / tool names (also standalone nodes) ----
            '💬 回答代理': '💬 Answer agent',
            '🔍 检索代理': '🔍 Retrieval agent',
            '工具规划': 'Tool planning',
            '执行工具': 'Executing tools',
            '生成答案': 'Generating answer',
            '文档选择': 'Document selection',
            '文档检索': 'Document retrieval',
            '查询改写': 'Query rewriting',
            '多文档检索': 'Multi-doc retrieval',
            '综合答案': 'Synthesizing answer',
            '查询重写': 'Query rewriting',
            '思考选择': 'Thinking & selecting',
            '执行检索': 'Executing retrieval',
            '累积总结': 'Accumulating summary',
            '评估结果': 'Evaluating results',
            '格式化输出': 'Formatting output',
            '语义检索': 'Semantic search',
            '提取标题': 'Extracting titles',
            '标题匹配': 'Title matching',
            '获取结构': 'Getting structure',
            '页码检索': 'Page-range search',
            '获取页面': 'Getting pages',
            '向量检索': 'Vector search',
            '获取内容': 'Getting content',
            '获取章节': 'Getting chapters',
            '获取图片': 'Getting images',
            '规划': 'Plan',
            '执行': 'Execute',
            '生成': 'Generate',
            '改写': 'Rewrite',
            '思考': 'Think',
            '评估': 'Evaluate',
            '输出': 'Output',

            // ---- Voice feedback ----
            '当前浏览器不支持语音录制': 'This browser does not support voice recording',
            '开始录音...': 'Recording started...',
            '未识别到语音内容': 'No speech detected',

            // ---- Toasts (Utils.notify) ----
            '初始化完成': 'Initialization complete',
            '连接失败，请刷新页面重试': 'Connection failed. Please refresh and try again',
            '确定要清空对话吗？': 'Clear this conversation?',
            '没有更多历史消息了': 'No more history messages',
            '记忆范围保存失败': 'Failed to save memory scope',

            // ---- Paper ingest buttons (chat.js / briefs share) ----
            '⬇ 下载入库': '⬇ Download & index',
            '下载到 data/pdf 并索引，完成后可直接深读（只下这一篇）':
                'Download to data/pdf and index it, then deep-read directly (this paper only)',
            '只下载并索引这篇论文的 PDF': 'Download and index only this paper\'s PDF',
            '下载中…': 'Downloading…',
            '已在 PDF 库，检查索引…': 'Already in the PDF library, checking index…',
            '已下载，索引中…': 'Downloaded, indexing…',
            '✅ 已入库': '✅ Indexed',
            '继续检查索引': 'Keep checking index',
            '⬇ 下载失败，重试': '⬇ Download failed, retry',
            '📖 深读 ↗': '📖 Deep read ↗',

            // ---- Code-copy buttons (chat-enhancer.js) ----
            '📋 复制': '📋 Copy',
            '✓ 已复制': '✓ Copied',
            '✗ 失败': '✗ Failed',

            // ---- api.js error texts surfaced on /chat ----
            '获取文档列表失败': 'Failed to fetch the document list',
            '初始化失败': 'Initialization failed',
            '清空失败': 'Failed to clear',
            '语音转文字失败': 'Speech-to-text failed',
            '语音合成失败': 'Speech synthesis failed',
            '收入 PDF 文档库失败': 'Failed to add to the PDF library',
        },
        patterns: [
            // Error toasts prefixed with a fixed label + dynamic detail
            { re: /^错误: (.*)$/, repl: 'Error: $1' },
            { re: /^初始化失败: (.*)$/, repl: 'Initialization failed: $1' },
            { re: /^清空失败: (.*)$/, repl: 'Failed to clear: $1' },
            { re: /^加载失败: (.*)$/, repl: 'Load failed: $1' },
            { re: /^PDF加载成功: (.+)$/, repl: 'PDF loaded: $1' },
            { re: /^加载PDF失败: (.*)$/, repl: 'Failed to load PDF: $1' },
            { re: /^无法访问麦克风: (.*)$/, repl: 'Cannot access the microphone: $1' },
            { re: /^语音识别失败: (.*)$/, repl: 'Speech recognition failed: $1' },
            { re: /^语音播放失败: (.*)$/, repl: 'Speech playback failed: $1' },
            { re: /下载入库失败：(.+)/, repl: 'Download & index failed: $1' },

            // Page jump / lazy page placeholders with page numbers
            { re: /^已跳转到第 (\d+) 页$/, repl: 'Jumped to page $1' },
            { re: /^第 (\d+) 页（滚动时加载）$/, repl: 'Page $1 (loads on scroll)' },

            // Load-more history button ("还有 N 条")
            { re: /^(\s*)📜 加载更早的消息 \(还有 (\d+) 条\)(\s*)$/, repl: '$1📜 Load earlier messages ($2 more)$3' },

            // Chips / scope popover labels living in padded text nodes
            { re: /^(\s*)全部文档（自动匹配）(\s*)$/, repl: '$1All documents (auto-select)$2' },
            { re: /^📚 全部文档(\s*)$/, repl: '📚 All documents$1' },
            { re: /^🌐 网络搜索(\s*)$/, repl: '🌐 Web search$1' },
            { re: /^🧠 记忆: (.+)$/, repl: '🧠 Memory: $1' },
            { re: /^🛠️ 当前工具: /, repl: '🛠️ Current tool: ' },
            { re: /^(\s*)深度研报记忆(\s*)$/, repl: '$1Deep Research Memory$2' },
            { re: /^(\s*)历史对话(\s*)$/, repl: '$1Chat History$2' },
            { re: /^(\s*)简报速览库(\s*)$/, repl: '$1Brief Library$2' },

            // Memory scope popover description (padded text node, '+' escaped)
            { re: /^(\s*)默认开启「深度研报记忆 \+ 历史对话」。勾选修改会立即保存到当前会话。(\s*)$/,
              repl: '$1Deep Research Memory + Chat History are on by default. Checkbox changes are saved to the current session immediately.$2' },

            // Parallel-retrieval banner + "提及论文" header (dynamic count)
            { re: /^(\s*)📚 并行检索进度(\s*)$/, repl: '$1📚 Parallel retrieval progress$2' },
            { re: /^📄 提及论文 (\d+) 篇（点谁下谁，不点不下载）$/, repl: '📄 $1 paper(s) mentioned — click one to download it' },

            // Iteration line "第 <span>i/n</span> 轮": drop the standalone 第 / 轮 parts
            { re: /^(\s*)第\s*$/, repl: ' $1' },
            { re: /^(\s*)轮$/, repl: '' },

            // Agent / stage / tool / workflow names inside concatenated nodes
            { re: namePatternRe, repl: mapName },
        ],
    });
})();
