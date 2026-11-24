/**
 * English locale strings for the /structure document structure editor.
 * Covers user-visible UI labels, dialogs, loading indicators, and notifications
 * in structure_editor.html, structure_editor.js, and shared PdfViewer placeholders.
 * Intentionally avoids translating document names, chapter titles, or console logs.
 */
(function () {
    if (typeof I18N === 'undefined') return;

    I18N.register({
        lang: 'en',
        exact: {
            // Page title & header
            '📝 LLMReader 文档结构编辑器': '📝 LLMReader Document Structure Editor',
            '章节管理': 'Chapter Management',
            '编辑文档章节结构，保存后可重建索引和摘要': 'Edit document chapter structure; rebuild index and summaries after saving',
            '返回数据管理': 'Back to Data Center',

            // Document selector & stats
            '选择文档：': 'Select Document:',
            '-- 请选择文档 --': '-- Select a document --',
            '总页数: -': 'Total Pages: -',
            '总章节: -': 'Total Chapters: -',

            // Chapter list panel
            '章节列表': 'Chapters',
            '➕ 添加章节': '➕ Add Chapter',
            '🗑️ 批量删除': '🗑️ Batch Delete',
            '✅ 确认删除': '✅ Confirm Delete',
            '❌ 取消': '❌ Cancel',
            '全选': 'Select All',
            '🔄 重建索引和摘要': '🔄 Rebuild Index & Summaries',
            '拖动调整宽度': 'Drag to resize panel',

            // Chapter item
            '未命名章节': 'Untitled Chapter',
            '✏️ 编辑': '✏️ Edit',
            '👁️ 查看': '👁️ View',
            '🗑️ 删除': '🗑️ Delete',
            '无': 'None',

            // PDF preview panel
            'PDF 预览': 'PDF Preview',
            '页码: - / -': 'Page: - / -',
            '跳页': 'Page',
            '跳转': 'Go',

            // Add / Edit chapter modal
            '添加章节': 'Add Chapter',
            '编辑章节': 'Edit Chapter',
            '章节标题：': 'Chapter Title:',
            '输入章节标题': 'Enter chapter title',
            '页码范围（用逗号分隔，支持范围如 1-5）：': 'Page Range (comma-separated, ranges like 1-5 supported):',
            '例如: 1-5, 7, 9-12': 'e.g., 1-5, 7, 9-12',
            '示例: "1-5" 表示第1到5页，"1-3, 5, 7-9" 表示多个不连续的页面': 'Example: "1-5" means pages 1 to 5; "1-3, 5, 7-9" selects multiple non-contiguous pages',
            '取消': 'Cancel',
            '确定': 'OK',

            // Loading messages
            '加载中...': 'Loading...',
            '加载文档列表...': 'Loading document list...',
            '加载文档结构...': 'Loading document structure...',
            '调整缩放...': 'Adjusting zoom...',
            '正在保存结构并启动重建...': 'Saving structure and starting rebuild...',

            // Validation, status & confirmations
            '请输入章节标题': 'Please enter a chapter title',
            '请输入页码范围': 'Please enter a page range',
            '页码格式无效': 'Invalid page number format',
            '请先选择要删除的章节': 'Please select chapters to delete first',
            '请先选择文档': 'Please select a document first',
            '加载文档结构失败': 'Failed to load document structure',
            '保存结构失败': 'Failed to save structure',
            '重建失败': 'Rebuild failed',
            '未知错误': 'Unknown error',
            '确定要删除这个章节吗？': 'Are you sure you want to delete this chapter?',
            '确定要根据当前结构重建索引和摘要吗？\n\n这将：\n• 重新生成章节chunks\n• 重新生成章节摘要\n• 重建向量数据库\n• 重新生成文档摘要\n\n重建将在后台进行，完成后会通知您。': 'Are you sure you want to rebuild the index and summaries with the current structure?\n\nThis will:\n• Regenerate chapter chunks\n• Regenerate chapter summaries\n• Rebuild the vector database\n• Regenerate the document summary\n\nThe rebuild will run in the background, and you will be notified when it completes.',
        },
        patterns: [
            // Multiline HTML text nodes with surrounding whitespace
            { re: /^(\s*)➕ 添加章节(\s*)$/, repl: '$1➕ Add Chapter$2' },
            { re: /^(\s*)🗑️ 批量删除(\s*)$/, repl: '$1🗑️ Batch Delete$2' },
            { re: /^(\s*)❌ 取消(\s*)$/, repl: '$1❌ Cancel$2' },
            { re: /^(\s*)全选(\s*)$/, repl: '$1Select All$2' },
            { re: /^(\s*)🔄 重建索引和摘要(\s*)$/, repl: '$1🔄 Rebuild Index & Summaries$2' },

            // Dynamic page / chapter counts and page ranges
            { re: /^(\s*)总页数:\s*(\d+|-)(\s*)$/, repl: '$1Total Pages: $2$3' },
            { re: /^(\s*)总章节:\s*(\d+|-)(\s*)$/, repl: '$1Total Chapters: $2$3' },
            {
                re: /^(\s*)已选择 (\d+) 个章节(\s*)$/,
                repl: (_, pre, n, post) => `${pre}${n} ${Number(n) === 1 ? 'chapter' : 'chapters'} selected${post}`,
            },
            { re: /^(\s*)页码:\s*(\d+|-)\s*\/\s*(\d+|-)(\s*)$/, repl: '$1Page: $2 / $3$4' },
            { re: /^(\s*)页码:\s*无(\s*)$/, repl: '$1Pages: None$2' },
            { re: /^(\s*)页码:\s*(\d[\d,\s-]*\d|\d)(\s*)$/, repl: '$1Pages: $2$3' },
            { re: /^(\s*)第\s*(\d+)\s*页(\s*)$/, repl: '$1Page $2$3' },
            { re: /^页码超出范围（1-(\d+)）$/, repl: 'Page number out of range (1-$1)' },

            // Dynamic confirmations
            {
                re: /^确定要删除选中的 (\d+) 个章节吗？$/,
                repl: (_, n) => `Are you sure you want to delete the selected ${n} ${Number(n) === 1 ? 'chapter' : 'chapters'}?`,
            },

            // Dynamic notifications (preserving document names and backend messages verbatim)
            { re: /^加载文档列表失败:\s*(.*)$/, repl: 'Failed to load document list: $1' },
            { re: /^加载文档失败:\s*加载文档结构失败$/, repl: 'Failed to load document: Failed to load document structure' },
            { re: /^加载文档失败:\s*(.*)$/, repl: 'Failed to load document: $1' },
            { re: /^重建失败:\s*保存结构失败:\s*未知错误$/, repl: 'Rebuild failed: Failed to save structure: Unknown error' },
            { re: /^重建失败:\s*保存结构失败:\s*(.+)$/, repl: 'Rebuild failed: Failed to save structure: $1' },
            { re: /^重建失败:\s*重建失败$/, repl: 'Rebuild failed' },
            { re: /^重建失败:\s*(.+)$/, repl: 'Rebuild failed: $1' },
            { re: /^保存结构失败:\s*未知错误$/, repl: 'Failed to save structure: Unknown error' },
            { re: /^保存结构失败:\s*(.+)$/, repl: 'Failed to save structure: $1' },
            { re: /^✅ 结构已保存，(.+) 开始重建（后台运行）\.\.\.$/, repl: '✅ Structure saved; rebuilding $1 in background...' },
            { re: /^✅ (.+) 重建完成！$/, repl: '✅ $1 rebuild completed!' },
            { re: /^❌ (.+) 重建失败:\s*未知错误$/, repl: '❌ $1 rebuild failed: Unknown error' },
            { re: /^❌ (.+) 重建失败:\s*(.+)$/, repl: '❌ $1 rebuild failed: $2' },
        ],
    });
})();
