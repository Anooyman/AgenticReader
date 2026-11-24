/**
 * English locale strings for the Dashboard (/) page, including
 * its inline briefs preview, background jobs summary, and session history modal.
 * User-generated content (session titles, brief titles, chat messages) is never translated.
 */
(function () {
    I18N.register({
        lang: 'en',
        exact: {
            // Page title & hero
            'AgenticReader - 主菜单': 'AgenticReader - Home',
            '智能文档对话助手 - 深入理解每一份文档': 'AI Document Chat Assistant — Understand Every Document Deeply',

            // Briefs preview section
            '📰 今日简报': "📰 Today's Briefs",
            '查看全部 →': 'View All →',
            '暂无简报数据': 'No briefs available',
            '暂无条目': 'No items',
            '加载简报日期失败': 'Failed to load brief dates',
            '加载简报内容失败': 'Failed to load brief items',
            '加载失败': 'Failed to load',
            '⚠️ 加载失败': '⚠️ Failed to Load',

            // Quick action cards
            '新对话': 'New Chat',
            '💡 多种模式': '💡 Multiple Modes',
            '历史对话': 'Chat History',
            '🆕 暂无历史会话': '🆕 No Chat History',
            '后台任务': 'Background Jobs',
            '✅ 空闲': '✅ Idle',
            '暂无进行中的任务': 'No active tasks',
            '加载会话失败': 'Failed to load sessions',
            '加载任务失败': 'Failed to load tasks',

            // Sessions modal header & stats
            '📜 历史对话': '📜 Chat History',
            '总会话数': 'Total Sessions',
            '单文档会话': 'Single-Doc Sessions',
            '跨文档会话': 'Cross-Doc Sessions',
            '手动选择会话': 'Manual-Select Sessions',

            // Sessions modal controls & empty/loading states
            '搜索会话标题...': 'Search session titles...',
            '☑️ 全选': '☑️ Select All',
            '⬜ 取消全选': '⬜ Deselect All',
            '🗑️ 删除选中': '🗑️ Delete Selected',
            '🔄 刷新': '🔄 Refresh',
            '⏳ 加载会话数据中...': '⏳ Loading sessions...',
            '暂无会话': 'No Sessions Yet',
            '开始对话以创建会话历史': 'Start a chat to create session history',

            // Session cards (rendered by manage.js in sessionsOnly mode)
            '单文档': 'Single Doc',
            '跨文档': 'Cross-Doc',
            '手动选择': 'Manual',
            '📄 未知文档': '📄 Unknown Document',
            '📄 跨文档智能对话': '📄 Smart Cross-Doc Chat',
            '📄 通用对话': '📄 General Chat',
            '收起': 'Collapse',
            '🔧 工具:': '🔧 Tools:',
            '🤖 调用:': '🤖 Agents:',
            '📚 文档检索': '📚 Doc Retrieval',
            '🌐 网络搜索': '🌐 Web Search',
            '🔍 检索代理': '🔍 Retrieval Agent',
            '🌐 搜索代理': '🌐 Search Agent',
            '消息数': 'Messages',
            '文档数': 'Documents',
            '💬 继续对话': '💬 Continue Chat',

            // Pagination & detail modal
            '‹ 上一页': '‹ Prev',
            '下一页 ›': 'Next ›',
            '详细信息': 'Details',
            '暂无消息记录': 'No messages yet',

            // Session modal toast messages
            '会话已重命名': 'Session renamed',
            '会话数据已刷新': 'Sessions refreshed',
            '请先选择要删除的会话': 'Please select sessions to delete first',
        },
        patterns: [
            // Briefs preview dynamic date & counts
            {
                re: /^📰 今日简报（([^）]+)）$/,
                repl: "📰 Today's Briefs ($1)",
            },
            {
                re: /^(\d+) 篇论文 · (\d+) 篇文章 · (\d+) 条未处理$/,
                repl: (_, papers, articles, pending) =>
                    `${papers} ${Number(papers) === 1 ? 'paper' : 'papers'} · ` +
                    `${articles} ${Number(articles) === 1 ? 'article' : 'articles'} · ` +
                    `${pending} pending`,
            },
            {
                re: /^(\d+) 篇论文 · (\d+) 篇文章 · 全部已处理$/,
                repl: (_, papers, articles) =>
                    `${papers} ${Number(papers) === 1 ? 'paper' : 'papers'} · ` +
                    `${articles} ${Number(articles) === 1 ? 'article' : 'articles'} · All processed`,
            },

            // Quick action dynamic counts
            {
                re: /^📊 (\d+) 个历史会话$/,
                repl: (_, count) =>
                    `📊 ${count} ${Number(count) === 1 ? 'Session' : 'Sessions'}`,
            },
            {
                re: /^⏳ (\d+) 个进行中$/,
                repl: '⏳ $1 running',
            },

            // Whitespace-padded template text nodes in dashboard.html & manage.js
            {
                re: /^\s*🗑️ 删除选中\s*\($/,
                repl: '🗑️ Delete Selected (',
            },
            {
                re: /^\s*💬 继续对话\s*$/,
                repl: '💬 Continue Chat',
            },
            {
                re: /^\s*‹ 上一页\s*$/,
                repl: '‹ Prev',
            },
            {
                re: /^\s*下一页 ›\s*$/,
                repl: 'Next ›',
            },
            {
                re: /^\s*暂无消息记录\s*$/,
                repl: 'No messages yet',
            },

            // Session card dynamic metadata (preserving session title & doc names)
            {
                re: /^\s*展开更多文档 \(\+(\d+)\)\s*$/,
                repl: 'Show more documents (+$1)',
            },
            {
                re: /^\s*🕒 创建:\s*(.+?)\s*$/,
                repl: '🕒 Created: $1',
            },
            {
                re: /^\s*🔄 更新:\s*(.+?)\s*$/,
                repl: '🔄 Updated: $1',
            },
            {
                re: /^(?:📚 文档检索|🌐 网络搜索)(?:,\s*(?:📚 文档检索|🌐 网络搜索|🔧 [^\n,]+))+$/,
                repl: (match) => match
                    .replace(/📚 文档检索/g, '📚 Doc Retrieval')
                    .replace(/🌐 网络搜索/g, '🌐 Web Search'),
            },
            {
                re: /^(?:🔍 检索代理|🌐 搜索代理|[^,\n]+)(?:,\s*(?:🔍 检索代理|🌐 搜索代理|[^,\n]+))*$/,
                repl: (match) => {
                    if (!match.includes('🔍 检索代理') && !match.includes('🌐 搜索代理')) return match;
                    return match
                        .replace(/🔍 检索代理/g, '🔍 Retrieval Agent')
                        .replace(/🌐 搜索代理/g, '🌐 Search Agent');
                },
            },
            {
                re: /^💬 (.+) - 会话历史$/,
                repl: '💬 $1 - Chat History',
            },

            // Pagination & count helpers
            {
                re: /^第 (\d+) \/ (\d+) 页$/,
                repl: 'Page $1 of $2',
            },
            {
                re: /^共 (\d+) 条$/,
                repl: (_, count) =>
                    `${count} ${Number(count) === 1 ? 'item' : 'items'} total`,
            },

            // Session operation feedback
            {
                re: /^加载会话失败:\s*(.+)$/,
                repl: 'Failed to load sessions: $1',
            },
            {
                re: /^加载会话详情失败:\s*(.+)$/,
                repl: 'Failed to load session details: $1',
            },
            {
                re: /^成功删除 (\d+) 个会话$/,
                repl: (_, count) =>
                    `Deleted ${count} ${Number(count) === 1 ? 'session' : 'sessions'}`,
            },
            {
                re: /^删除失败 (\d+) 个会话$/,
                repl: (_, count) =>
                    `Failed to delete ${count} ${Number(count) === 1 ? 'session' : 'sessions'}`,
            },
            {
                re: /^确定要删除 (\d+) 个会话吗？此操作不可恢复！$/,
                repl: (_, count) =>
                    `Delete ${count} ${Number(count) === 1 ? 'session' : 'sessions'}? This action cannot be undone.`,
            },
        ],
    });
})();
