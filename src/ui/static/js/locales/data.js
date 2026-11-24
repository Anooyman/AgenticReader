/**
 * /data (Data Center) page locale strings — English.
 *
 * Covers manage.html static DOM text and all user-visible strings produced by
 * manage.js (document/session/memory listings, deletion dialogs, pending-PDF
 * controls, smart cleanup, toasts). Note: native confirm()/prompt() dialogs
 * are not reachable by the DOM-level translator, but their strings are still
 * registered here for completeness (see notes in the handoff message).
 */
(function () {
    const PART_LABELS = {
        'JSON 数据': 'JSON data',
        '向量数据库': 'vector database',
        '图片': 'images',
        '摘要文件': 'summary files',
        '源 PDF 文件 (data/pdf)': 'source PDF file (data/pdf)',
        'JSON': 'JSON',
        '向量库': 'vector DB',
        '摘要': 'summaries',
        '源PDF': 'source PDF',
        '所有数据': 'all data',
    };

    // Map a "、"-joined list of Chinese part labels into English.
    function partsToEn(text) {
        return String(text)
            .split('、')
            .map((p) => PART_LABELS[p.trim()] || p.trim())
            .join(', ');
    }

    I18N.register({
        lang: 'en',
        exact: {
            // ==================== Page header / tabs ====================
            'AgenticReader - 数据管理': 'AgenticReader - Data Center',
            '🗂️ 数据管理': '🗂️ Data Management',
            '管理文档数据、会话历史和系统存储': 'Manage document data, session history and system storage',
            '📄 文档与存储': '📄 Documents & Storage',
            '💬 历史对话': '💬 History',
            '🧠 Memory': '🧠 Memory',

            // ==================== Overview cards ====================
            '总文档数': 'Total Documents',
            '待索引': 'Pending',
            '已索引': 'Indexed',
            '总存储空间': 'Total Storage',
            'JSON 数据': 'JSON Data',
            '向量数据库': 'Vector Database',
            '图片缓存': 'Image Cache',
            '摘要文件': 'Summary Files',

            // ==================== Pending PDFs section ====================
            '待索引PDF': 'Pending PDFs',
            '⏳ 加载待索引PDF...': '⏳ Loading pending PDFs...',
            '所有PDF都已索引完成': 'All PDFs are already indexed',
            '☑️ 全选': '☑️ Select All',
            '⬜ 取消全选': '⬜ Deselect All',
            '删除本地 PDF 源文件': 'Delete local PDF source file',

            // ==================== Controls / common buttons ====================
            '搜索文档标题、关键词...': 'Search document titles, keywords...',
            '🔄 刷新': '🔄 Refresh',
            '🧹 智能清理': '🧹 Smart Cleanup',
            '← 返回主页': '← Back to Home',
            '⏳ 加载文档数据中...': '⏳ Loading document data...',
            '暂无文档': 'No Documents',
            '开始上传并索引 PDF 文档': 'Upload and index PDF documents to get started',

            // ==================== Sessions tab ====================
            '总会话数': 'Total Sessions',
            '单文档会话': 'Single-Doc Sessions',
            '跨文档会话': 'Cross-Doc Sessions',
            '手动选择会话': 'Manual-Selection Sessions',
            '搜索会话标题...': 'Search session titles...',
            '⏳ 加载会话数据中...': '⏳ Loading session data...',
            '暂无会话': 'No Sessions',
            '开始对话以创建会话历史': 'Start chatting to create session history',
            '消息数': 'Messages',
            '文档数': 'Docs',
            '单文档': 'Single Doc',
            '跨文档': 'Cross-Doc',
            '手动选择': 'Manual Select',
            '📄 未知文档': '📄 Unknown document',
            '📄 跨文档智能对话': '📄 Cross-document chat',
            '📄 通用对话': '📄 General chat',
            '📚 文档检索': '📚 Document Retrieval',
            '🌐 网络搜索': '🌐 Web Search',
            '🔧 工具:': '🔧 Tools:',
            '🤖 调用:': '🤖 Called:',
            '🔍 检索代理': '🔍 Retrieval Agent',
            '🌐 搜索代理': '🌐 Search Agent',

            // ==================== Memory tab ====================
            '总记忆条数': 'Total Memories',
            'Namespace 数': 'Namespaces',
            '此 namespace 暂无记忆': 'This namespace has no memories yet',
            '[整篇摘要]': '[Full-text summary]',
            '删除这条': 'Delete This Item',
            '删除整组': 'Delete Entire Group',
            '全部 namespace': 'All namespaces',
            '检索测试...': 'Test retrieval...',
            '检索': 'Search',
            '清空当前 namespace': 'Clear current namespace',
            '检索中...': 'Searching...',
            '(无结果)': '(No results)',

            // ==================== Modals ====================
            '详细信息': 'Details',
            '确认删除': 'Confirm Delete',
            '确认删除文档': 'Confirm Delete Document',
            '选择要删除的数据': 'Select Data to Delete',
            '确认批量删除': 'Confirm Batch Delete',
            '删除 PDF 源文件': 'Delete PDF Source File',
            '批量删除 PDF 源文件': 'Batch Delete PDF Source Files',
            '同时删除本地 PDF 源文件': 'Also delete local PDF source file',
            '(不存在)': '(does not exist)',
            '该文件尚未索引，删除后无法再对此文件进行索引。': 'This file has not been indexed yet; once deleted it can no longer be indexed.',
            '这些文件尚未索引，删除后无法再对它们进行索引。': 'These files have not been indexed yet; once deleted they can no longer be indexed.',
            '此操作不可恢复！': 'This action cannot be undone!',
            '请至少选择一项要删除的数据': 'Please select at least one data part to delete',

            // Partial-delete part labels (standalone list items)
            '源 PDF 文件 (data/pdf)': 'Source PDF file (data/pdf)',
            '图片': 'Images',

            // ==================== Expand / collapse & summaries ====================
            '收起': 'Collapse',
            '展开更多': 'Show more',
            '暂无摘要': 'No summary',
            '暂无摘要信息': 'No summary information',
            '暂无消息记录': 'No message history',

            // ==================== Toast messages (clean, non-dynamic) ====================
            '会话已重命名': 'Session renamed',
            '文档数据已刷新': 'Document data refreshed',
            '会话数据已刷新': 'Session data refreshed',
            '请输入有效的天数': 'Please enter a valid number of days',
            '请先选择要删除的会话': 'Please select sessions to delete first',
            '请先选择要删除的文档': 'Please select documents to delete first',
            '请先选择要索引的PDF文件': 'Please select PDF files to index first',
            '请先选择要对话的文档': 'Please select documents to chat with first',

            // ==================== Native confirm()/prompt() strings ====================
            // Registered for completeness; native dialogs bypass the DOM translator.
            '删除这一条记忆？': 'Delete this memory item?',
            '清理多少天前的数据？（默认 30 天）': 'How many days back should data be cleaned? (default 30 days)',
        },
        patterns: [
            // ---------- Pending PDF count ----------
            { re: /^(\d+) 个文件待索引$/, repl: '$1 file(s) pending indexing' },

            // ---------- Error toasts: "<prefix> 中文标签: message" ----------
            { re: /^(?:[✅❌]\s*)?加载概览失败[:：]\s*(.*)$/, repl: 'Failed to load overview: $1' },
            { re: /^(?:[✅❌]\s*)?加载文档详情失败[:：]\s*(.*)$/, repl: 'Failed to load document details: $1' },
            { re: /^(?:[✅❌]\s*)?加载会话详情失败[:：]\s*(.*)$/, repl: 'Failed to load session details: $1' },
            { re: /^(?:[✅❌]\s*)?加载文档失败[:：]\s*(.*)$/, repl: 'Failed to load documents: $1' },
            { re: /^(?:[✅❌]\s*)?加载会话失败[:：]\s*(.*)$/, repl: 'Failed to load sessions: $1' },
            { re: /^(?:[✅❌]\s*)?重命名失败[:：]\s*(.*)$/, repl: 'Rename failed: $1' },
            { re: /^(?:[✅❌]\s*)?批量删除失败[:：]\s*(.*)$/, repl: 'Batch deletion failed: $1' },
            { re: /^(?:[✅❌]\s*)?清理失败[:：]\s*(.*)$/, repl: 'Cleanup failed: $1' },
            { re: /^(?:[✅❌]\s*)?删除失败[:：]\s*(.*)$/, repl: 'Deletion failed: $1' },
            { re: /^(?:[✅❌]\s*)?索引失败[:：]\s*(.*)$/, repl: 'Indexing failed: $1' },
            { re: /^未知错误$/, repl: 'Unknown error' },

            // ---------- Delete-progress toast: "正在删除 <doc> (<parts>)..." ----------
            {
                re: /^(?:[✅❌]\s*)?正在删除 (.+?) \((.+)\)\.\.\.$/,
                repl: function (_, doc, parts) { return 'Deleting ' + doc + ' (' + partsToEn(parts) + ')...'; },
            },
            { re: /^(?:[✅❌]\s*)?删除成功，释放空间 ([\d.]+) MB$/, repl: 'Deleted successfully, freed $1 MB' },

            // ---------- Smart cleanup toast ----------
            {
                re: /^(?:[✅❌]\s*)?清理完成：删除 (\d+) 个文档，释放 ([\d.]+) MB 空间$/,
                repl: 'Cleanup complete: deleted $1 document(s), freed $2 MB',
            },

            // ---------- Batch-delete result toasts ----------
            { re: /^(?:[✅❌]\s*)?成功删除 (\d+) 个会话$/, repl: 'Successfully deleted $1 session(s)' },
            {
                re: /^(?:[✅❌]\s*)?成功删除 (\d+) 个文档，释放 ([\d.]+) MB 空间$/,
                repl: 'Successfully deleted $1 document(s), freed $2 MB',
            },
            {
                re: /^(?:[✅❌]\s*)?已删除 (\d+) 个 PDF 文件，释放 ([\d.]+) MB 空间$/,
                repl: 'Deleted $1 PDF file(s), freed $2 MB',
            },
            {
                re: /^(?:[✅❌]\s*)?删除失败 (\d+) 个(会话|文档)$/,
                repl: function (_, n, kind) {
                    return 'Failed to delete ' + n + ' ' + (kind === '会话' ? 'session(s)' : 'document(s)');
                },
            },

            // ---------- Indexing toasts ----------
            { re: /^✅ (.+) 开始索引（后台运行）\.\.\.$/, repl: '✅ $1 indexing started (running in background)...' },
            { re: /^✅ (.+) 索引完成！$/, repl: '✅ $1 indexed successfully!' },
            {
                re: /^❌ (.+) 索引失败: (.*)$/,
                repl: function (_, f, err) {
                    return '❌ ' + f + ' index failed: ' + (err === '未知错误' ? 'Unknown error' : err);
                },
            },
            { re: /^(?:[✅❌]\s*)?正在启动 (\d+) 个索引任务\.\.\.$/, repl: 'Starting $1 indexing task(s)...' },
            {
                re: /^✅ (\d+) 个索引任务已启动（后台运行）$/,
                repl: '✅ $1 indexing task(s) started (running in background)',
            },
            { re: /^(?:[✅❌]\s*)?(\d+) 个任务启动失败$/, repl: '$1 task(s) failed to start' },

            // ---------- Whitespace-tolerant fallbacks for one-off exact keys ----------
            { re: /^\s*此操作不可恢复！\s*$/, repl: 'This action cannot be undone!' },

            // ---------- Detail modal titles (doc/session names preserved) ----------
            { re: /^📄 (.+) - 文档摘要$/, repl: '📄 $1 - Document Summary' },
            { re: /^💬 (.+) - 会话历史$/, repl: '💬 $1 - Chat History' },

            // ---------- Session card labels ----------
            { re: /^🕒 创建[:：] (.*)$/, repl: '🕒 Created: $1' },
            { re: /^🔄 更新[:：] (.*)$/, repl: '🔄 Updated: $1' },

            // ---------- Memory group header / expand ----------
            { re: /^\s*·\s*(\d+)\s*条\s*$/, repl: ' · $1 item(s)' },
            { re: /^\s*展开全部 (\d+) 条\s*$/, repl: 'Show all $1 item(s)' },

            // ---------- Expand toggles (whitespace-padded innerHTML text nodes) ----------
            { re: /^\s*展开更多关键词 \(\+(\d+)\)\s*$/, repl: 'Show more keywords (+$1)' },
            { re: /^\s*展开更多文档 \(\+(\d+)\)\s*$/, repl: 'Show more documents (+$1)' },

            // ---------- Pagination ----------
            { re: /^\s*‹ 上一页\s*$/, repl: '‹ Previous' },
            { re: /^\s*下一页 ›\s*$/, repl: 'Next ›' },

            // ---------- Document-card action buttons ----------
            { re: /^\s*💬 开始对话\s*$/, repl: '💬 Start Chat' },
            { re: /^\s*📑 章节管理\s*$/, repl: '📑 Chapter Manager' },
            { re: /^\s*🗑️ 部分删除\s*$/, repl: '🗑️ Partial Delete' },
            { re: /^\s*❌ 完全删除\s*$/, repl: '❌ Delete All' },
            { re: /^\s*💬 继续对话\s*$/, repl: '💬 Continue Chat' },
            { re: /^\s*🔄 索引\s*$/, repl: '🔄 Index' },

            // ---------- Toolbar buttons that end in a count span ----------
            { re: /^\s*🔄 批量索引 \($/, repl: '🔄 Batch Index (' },
            { re: /^\s*🗑️ 删除源文件 \($/, repl: '🗑️ Delete Source Files (' },
            { re: /^\s*💬 对话 \($/, repl: '💬 Chat (' },
            { re: /^\s*🗑️ 删除选中 \($/, repl: '🗑️ Delete Selected (' },

            // ---------- Delete confirmation modal fragments ----------
            { re: /^您确定要完全删除文档\s*$/, repl: 'Are you sure you want to completely delete document ' },
            {
                re: /^\s*这将删除：JSON 数据、向量数据库、图片、摘要文件和注册表记录\s*$/,
                repl: 'This will delete: JSON data, vector database, images, summary files and registry records',
            },
            {
                re: /^\s*⚠️ 不勾选时源 PDF 会保留，并重新出现在“待索引PDF”列表中。\s*$/,
                repl: '⚠️ If unchecked, source PDFs are kept and reappear in the "Pending PDFs" list.',
            },
            { re: /^\s*💡 提示：删除后可以重新生成相应的数据\s*$/, repl: '💡 Tip: deleted data parts can be regenerated afterwards' },
            {
                re: /^\s*⚠️ 勾选“源 PDF 文件”将删除唯一的原始文件，无法重新生成，请谨慎操作。\s*$/,
                repl: '⚠️ Checking "Source PDF file" deletes the only copy of the original file, which cannot be regenerated. Proceed with caution.',
            },

            // ---------- Partial-delete part list (label + "(size MB)" span) ----------
            {
                re: /^\s*(JSON 数据|向量数据库|图片|摘要文件|源 PDF 文件 \(data\/pdf\))\s*$/,
                repl: function (_, label) { return PART_LABELS[label] || label; },
            },
            { re: /^\(data\/pdf\/，未找到\)$/, repl: '(data/pdf/, not found)' },
            { re: /^\(data\/pdf\/，([\d.]+) MB\)$/, repl: '(data/pdf/, $1 MB)' },

            // ---------- Confirmation-dialog message fragments around interpolated names ----------
            { re: /^选择要删除的\s*$/, repl: 'Select data parts to delete of: ' },
            { re: /^\s*数据部分：\s*$/, repl: ' :' },
            { re: /^确定要完全删除选中的\s*$/, repl: 'Completely delete the selected ' },
            { re: /^\s*个文档吗？\s*$/, repl: ' document(s)?' },
            { re: /^确定要删除选中的\s*$/, repl: 'Delete the selected ' },
            { re: /^\s*个 PDF 源文件吗？\s*$/, repl: ' PDF source file(s)?' },
            { re: /^确定要删除\s*$/, repl: 'Are you sure you want to delete ' },
            { re: /^\uFF08([\d.]+) MB\uFF09\s*吗？\s*$/, repl: ' ($1 MB)?' },
            { re: /^\s*吗？\s*$/, repl: ' ?' },

            // ---------- Native confirm() strings (not DOM-translated; registered for completeness) ----------
            {
                re: /^确定要清理 (\d+) 天前的所有文档数据吗？此操作不可恢复！$/,
                repl: 'Delete all document data older than $1 day(s)? This action cannot be undone!',
            },
            {
                re: /^确定要删除 (\d+) 个会话吗？此操作不可恢复！$/,
                repl: 'Delete $1 session(s)? This action cannot be undone!',
            },
            {
                re: /^确定要索引 "(.+)" 吗？\n\n索引将在后台进行，完成后会通知您。$/,
                repl: '"$1" will be indexed in the background. You will be notified when it completes.',
            },
            {
                re: /^确定要批量索引 (\d+) 个PDF文件吗？\n\n所有文件将在后台索引，完成后会通知您。$/,
                repl: 'Index $1 PDF file(s) in the background? You will be notified when they complete.',
            },
            {
                re: /^删除来源 "(.+)" 的全部记忆？此操作不可撤销。$/,
                repl: 'Delete all memories for source "$1"? This action cannot be undone.',
            },
            {
                re: /^清空 namespace "(.+)" 下的全部记忆？此操作不可撤销。$/,
                repl: 'Clear all memories under namespace "$1"? This action cannot be undone.',
            },
        ],
    });
})();
