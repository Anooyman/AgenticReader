/**
 * LLMReader 章节管理页面 JavaScript
 * 管理文档章节结构，PDF预览，重建向量数据库
 */

class ChaptersManager {
    constructor() {
        // API基础URL
        this.apiBase = `${window.location.protocol}//${window.location.host}`;

        // 状态
        this.currentDoc = null;
        this.chapters = [];
        this.editingChapterIndex = null;

        // PDF相关
        this.pdfUrl = null;
        this.totalPages = 0;

        // 初始化
        this.init();
    }

    getApiUrl(endpoint) {
        return `${this.apiBase}${endpoint}`;
    }

    async init() {
        console.log('🚀 章节管理页面初始化...');

        this.bindEvents();
        await this.loadDocumentList();

        console.log('✅ 章节管理页面初始化完成');
    }

    bindEvents() {
        // 文档选择
        document.getElementById('doc-select')?.addEventListener('change', (e) => {
            this.selectDocument(e.target.value);
        });

        // 操作按钮
        document.getElementById('add-chapter-btn')?.addEventListener('click', () => {
            this.showAddChapterDialog();
        });

        document.getElementById('rebuild-btn')?.addEventListener('click', () => {
            this.rebuildDocumentData();
        });

        document.getElementById('refresh-btn')?.addEventListener('click', () => {
            if (this.currentDoc) {
                this.loadChapters(this.currentDoc);
            } else {
                this.loadDocumentList();
            }
        });

        // PDF 控制
        document.getElementById('go-to-page-btn')?.addEventListener('click', () => {
            const pageNum = parseInt(document.getElementById('current-page-input').value);
            this.goToPage(pageNum);
        });

        document.getElementById('current-page-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const pageNum = parseInt(e.target.value);
                this.goToPage(pageNum);
            }
        });

        document.getElementById('zoom-in-btn')?.addEventListener('click', () => {
            this.setZoom(this.scale + 0.25);
        });

        // 章节对话框
        document.getElementById('dialog-close')?.addEventListener('click', () => {
            this.hideChapterDialog();
        });

        document.getElementById('dialog-cancel')?.addEventListener('click', () => {
            this.hideChapterDialog();
        });

        document.getElementById('dialog-save')?.addEventListener('click', () => {
            this.saveChapter();
        });

        document.getElementById('preview-start-btn')?.addEventListener('click', () => {
            const startPage = parseInt(document.getElementById('chapter-start-input').value);
            if (startPage) this.goToPage(startPage);
        });

        document.getElementById('preview-end-btn')?.addEventListener('click', () => {
            const endPage = parseInt(document.getElementById('chapter-end-input').value);
            if (endPage) this.goToPage(endPage);
        });

        // 确认对话框
        document.getElementById('confirm-cancel')?.addEventListener('click', () => {
            this.hideConfirmDialog();
        });
    }

    // ==================== 文档管理 ====================

    async loadDocumentList() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/data/documents'));
            const result = await response.json();

            const select = document.getElementById('doc-select');
            if (!select) return;

            select.innerHTML = '<option value="">-- 请选择文档 --</option>';

            if (result.success && result.data && result.data.length > 0) {
                result.data.forEach(doc => {
                    const option = document.createElement('option');
                    option.value = doc.name;
                    option.textContent = doc.name;
                    select.appendChild(option);
                });
            }
        } catch (error) {
            console.error('加载文档列表失败:', error);
            this.showStatus('error', '加载文档列表失败');
        }
    }

    async selectDocument(docName) {
        if (!docName) {
            this.clearState();
            return;
        }

        this.currentDoc = docName;
        
        // 启用按钮
        document.getElementById('add-chapter-btn').disabled = false;
        document.getElementById('rebuild-btn').disabled = false;

        // 加载章节
        await this.loadChapters(docName);

        // 加载PDF预览
        await this.loadPdf(docName);
    }

    clearState() {
        this.currentDoc = null;
        this.chapters = [];
        this.pdfUrl = null;

        // 禁用按钮
        document.getElementById('add-chapter-btn').disabled = true;
        document.getElementById('rebuild-btn').disabled = true;

        // 清空章节列表
        document.getElementById('chapters-list-container').innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📚</div>
                <p>请选择一个文档查看章节</p>
            </div>
        `;

        // 隐藏统计
        document.getElementById('chapters-stats').style.display = 'none';

        // 清空PDF预览
        this.clearPdfPreview();
    }

    // ==================== 章节管理 ====================

    async loadChapters(docName) {
        try {
            const container = document.getElementById('chapters-list-container');
            container.innerHTML = '<div class="loading" style="text-align: center; padding: 40px; color: #6c757d;">加载中...</div>';

            const response = await fetch(this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(docName)}/chapters`));
            const result = await response.json();

            if (result.success && result.chapters) {
                this.chapters = result.chapters;
                this.renderChapters();
                this.updateStats();
            } else {
                container.innerHTML = '<div class="empty-state"><div class="empty-icon">❌</div><p>加载章节失败</p></div>';
            }
        } catch (error) {
            console.error('加载章节失败:', error);
            this.showStatus('error', '加载章节失败');
        }
    }

    renderChapters() {
        const container = document.getElementById('chapters-list-container');

        if (!this.chapters || this.chapters.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📭</div>
                    <p>暂无章节信息</p>
                    <p style="font-size: 13px; margin-top: 10px;">点击"添加章节"创建第一个章节</p>
                </div>
            `;
            return;
        }

        const html = this.chapters.map((chapter, index) => `
            <div class="chapter-item" data-index="${index}">
                <div class="chapter-header" onclick="chaptersManager.toggleChapterPages(${index})">
                    <div class="chapter-index">${index + 1}</div>
                    <div class="chapter-info">
                        <div class="chapter-title" title="${this.escapeHtml(chapter.title)}">${this.escapeHtml(chapter.title)}</div>
                        <div class="chapter-meta">
                            <span>📄 ${chapter.start_page} - ${chapter.end_page}</span>
                            <span>📊 ${chapter.page_count} 页</span>
                        </div>
                    </div>
                    <div class="chapter-actions" onclick="event.stopPropagation()">
                        <button class="btn btn-sm btn-info" onclick="chaptersManager.goToPage(${chapter.start_page})" title="跳转到此章节">
                            👁️
                        </button>
                        <button class="btn btn-sm btn-primary" onclick="chaptersManager.showEditChapterDialog(${index})" title="编辑章节">
                            ✏️
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="chaptersManager.confirmDeleteChapter(${index})" title="删除章节">
                            🗑️
                        </button>
                    </div>
                </div>
                <div class="chapter-pages" id="chapter-pages-${index}">
                    <div class="pages-label">包含页码:</div>
                    <div class="pages-list">
                        ${chapter.pages.map(p => `<span class="page-tag" onclick="chaptersManager.goToPage(${p})">${p}</span>`).join('')}
                    </div>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;
    }

    updateStats() {
        const statsEl = document.getElementById('chapters-stats');
        if (this.chapters && this.chapters.length > 0) {
            document.getElementById('chapter-count').textContent = this.chapters.length;
            const totalPages = this.chapters.reduce((sum, ch) => sum + ch.page_count, 0);
            document.getElementById('page-count').textContent = totalPages;
            statsEl.style.display = 'flex';
        } else {
            statsEl.style.display = 'none';
        }
    }

    toggleChapterPages(index) {
        const pagesEl = document.getElementById(`chapter-pages-${index}`);
        if (pagesEl) {
            pagesEl.classList.toggle('expanded');
        }
    }

    // ==================== 章节编辑对话框 ====================

    showAddChapterDialog() {
        this.editingChapterIndex = null;
        document.getElementById('dialog-title').textContent = '➕ 添加新章节';
        document.getElementById('chapter-title-input').value = '';
        document.getElementById('chapter-start-input').value = '1';
        document.getElementById('chapter-end-input').value = '1';
        document.getElementById('chapter-dialog').style.display = 'flex';
    }

    showEditChapterDialog(index) {
        if (index < 0 || index >= this.chapters.length) return;

        const chapter = this.chapters[index];
        this.editingChapterIndex = index;

        document.getElementById('dialog-title').textContent = '✏️ 编辑章节';
        document.getElementById('chapter-title-input').value = chapter.title;
        document.getElementById('chapter-start-input').value = chapter.start_page;
        document.getElementById('chapter-end-input').value = chapter.end_page;
        document.getElementById('chapter-dialog').style.display = 'flex';
    }

    hideChapterDialog() {
        document.getElementById('chapter-dialog').style.display = 'none';
        this.editingChapterIndex = null;
    }

    async saveChapter() {
        const title = document.getElementById('chapter-title-input').value.trim();
        const startPage = parseInt(document.getElementById('chapter-start-input').value);
        const endPage = parseInt(document.getElementById('chapter-end-input').value);

        // 验证
        if (!title) {
            this.showStatus('error', '请输入章节标题');
            return;
        }

        if (!startPage || !endPage || startPage > endPage) {
            this.showStatus('error', '页码范围无效');
            return;
        }

        // 生成页码数组
        const pages = [];
        for (let i = startPage; i <= endPage; i++) {
            pages.push(i);
        }

        const chapterData = { title, pages };

        try {
            this.showStatus('info', '保存中...');

            let response;
            if (this.editingChapterIndex !== null) {
                // 更新
                response = await fetch(
                    this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(this.currentDoc)}/chapters/${this.editingChapterIndex}`),
                    {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(chapterData)
                    }
                );
            } else {
                // 新增
                response = await fetch(
                    this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(this.currentDoc)}/chapters`),
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(chapterData)
                    }
                );
            }

            const result = await response.json();

            if (result.success) {
                const wasEditing = this.editingChapterIndex;
                const editedIndex = this.editingChapterIndex;
                this.showStatus('success', wasEditing !== null ? '章节已更新' : '章节已添加');
                this.hideChapterDialog();
                await this.loadChapters(this.currentDoc);

                // 高亮显示修改或新增的章节
                if (wasEditing !== null) {
                    // 编辑：高亮被编辑的章节
                    this.highlightChapter(editedIndex);
                } else {
                    // 新增：滚动到底部并高亮新章节
                    this.scrollToBottom();
                    this.highlightLastChapter();
                }
            } else {
                this.showStatus('error', result.detail || '保存失败');
            }
        } catch (error) {
            console.error('保存章节失败:', error);
            this.showStatus('error', '保存章节失败');
        }
    }

    scrollToBottom() {
        const container = document.getElementById('chapters-list-container');
        setTimeout(() => {
            container.scrollTop = container.scrollHeight;
        }, 100);
    }

    highlightLastChapter() {
        setTimeout(() => {
            const items = document.querySelectorAll('.chapter-item');
            if (items.length > 0) {
                const lastItem = items[items.length - 1];
                lastItem.classList.add('highlight');
                // 3秒后移除高亮
                setTimeout(() => lastItem.classList.remove('highlight'), 3000);
            }
        }, 150);
    }

    highlightChapter(index) {
        setTimeout(() => {
            const item = document.querySelector(`.chapter-item[data-index="${index}"]`);
            if (item) {
                item.classList.add('highlight');
                item.scrollIntoView({ behavior: 'smooth', block: 'center' });
                // 3秒后移除高亮
                setTimeout(() => item.classList.remove('highlight'), 3000);
            }
        }, 150);
    }

    // ==================== 删除章节 ====================

    confirmDeleteChapter(index) {
        if (index < 0 || index >= this.chapters.length) return;

        const chapter = this.chapters[index];
        this.pendingDeleteIndex = index;

        document.getElementById('confirm-title').textContent = '🗑️ 删除章节';
        document.getElementById('confirm-message').textContent = 
            `确定要删除章节 "${chapter.title}" 吗？\n\n删除后需要点击"重建数据"按钮更新向量数据库。`;
        document.getElementById('confirm-ok').className = 'btn btn-danger';  // 删除操作用红色按钮
        document.getElementById('confirm-ok').onclick = () => this.deleteChapter();
        document.getElementById('confirm-dialog').style.display = 'flex';
    }

    hideConfirmDialog() {
        document.getElementById('confirm-dialog').style.display = 'none';
    }

    async deleteChapter() {
        this.hideConfirmDialog();
        
        const index = this.pendingDeleteIndex;
        if (index === undefined || index < 0 || index >= this.chapters.length) return;

        try {
            this.showStatus('info', '删除中...');

            const response = await fetch(
                this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(this.currentDoc)}/chapters/${index}`),
                { method: 'DELETE' }
            );

            const result = await response.json();

            if (result.success) {
                this.showStatus('success', '章节已删除，请点击"重建数据"更新向量数据库');
                await this.loadChapters(this.currentDoc);
            } else {
                this.showStatus('error', result.detail || '删除失败');
            }
        } catch (error) {
            console.error('删除章节失败:', error);
            this.showStatus('error', '删除章节失败');
        }
    }

    // ==================== 重建数据 ====================

    async rebuildDocumentData() {
        if (!this.currentDoc) return;

        document.getElementById('confirm-title').textContent = '🔨 重建数据';
        document.getElementById('confirm-message').textContent = 
            `确定要重建文档 "${this.currentDoc}" 的向量数据库和摘要吗？\n\n这将根据当前章节信息重新生成所有数据，可能需要几分钟时间。`;
        document.getElementById('confirm-ok').onclick = () => this.doRebuild();
        document.getElementById('confirm-ok').className = 'btn btn-primary';
        document.getElementById('confirm-dialog').style.display = 'flex';
    }

    async doRebuild() {
        this.hideConfirmDialog();
        this.showProgress('🔨 正在重建数据...', '初始化中，请稍候...');

        try {
            // 更新进度提示
            setTimeout(() => this.updateProgress('正在处理章节内容...'), 1000);
            setTimeout(() => this.updateProgress('正在生成向量数据库...'), 3000);
            setTimeout(() => this.updateProgress('正在生成摘要文件...'), 6000);

            const response = await fetch(
                this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(this.currentDoc)}/rebuild`),
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rebuild_vectordb: true, rebuild_summary: true })
                }
            );

            const result = await response.json();
            this.hideProgress();

            if (result.success) {
                let message = '✅ 重建完成！';
                const results = result.results || {};

                if (results.vectordb?.success) {
                    message += `\n📊 向量数据库: 处理了 ${results.vectordb.chapters_processed} 个章节`;
                    if (results.vectordb.documents_created) {
                        message += `，创建了 ${results.vectordb.documents_created} 个文档`;
                    }
                } else if (results.vectordb?.error) {
                    message += `\n❌ 向量数据库重建失败: ${results.vectordb.error}`;
                }

                if (results.summary?.success) {
                    message += `\n📝 摘要文件已生成`;
                } else if (results.summary?.error) {
                    message += `\n❌ 摘要重建失败: ${results.summary.error}`;
                }

                this.showStatus('success', message);
                await this.loadChapters(this.currentDoc);
            } else {
                this.showStatus('error', result.detail || '重建失败');
            }
        } catch (error) {
            console.error('重建失败:', error);
            this.hideProgress();
            this.showStatus('error', '重建失败: ' + error.message);
        }
    }

    updateProgress(message) {
        const msgEl = document.getElementById('progress-message');
        if (msgEl && document.getElementById('progress-overlay').style.display !== 'none') {
            msgEl.textContent = message;
        }
    }

    // ==================== PDF 预览 ====================

    async loadPdf(docName) {
        try {
            // 隐藏空状态
            document.querySelector('.pdf-empty-state').style.display = 'none';

            // 通过 API 获取 PDF 文件（和聊天页面一样的方式）
            const response = await fetch(this.getApiUrl(`/api/v1/pdf/file/${encodeURIComponent(docName)}`));

            if (response.ok) {
                const blob = await response.blob();
                this.pdfUrl = URL.createObjectURL(blob);

                // 使用 PDF.js 获取页数
                const loadingTask = pdfjsLib.getDocument(this.pdfUrl);
                const pdfDoc = await loadingTask.promise;
                this.totalPages = pdfDoc.numPages;

                // 更新UI
                document.getElementById('total-pages').textContent = this.totalPages;

                // 使用 embed 显示 PDF（和聊天模式一样，清晰度更好）
                const embed = document.getElementById('pdf-embed');
                embed.src = this.pdfUrl;
                embed.type = 'application/pdf';
                embed.style.display = 'block';

                console.log(`✅ PDF加载成功: ${docName}, 共 ${this.totalPages} 页`);
            } else {
                throw new Error('PDF文件不可用');
            }
        } catch (error) {
            console.error('加载PDF失败:', error);
            this.clearPdfPreview();
            document.querySelector('.pdf-empty-state').innerHTML = `
                <div class="empty-icon">📄</div>
                <p>无法加载PDF预览</p>
                <p class="hint">PDF文件可能不存在或已被删除</p>
            `;
            document.querySelector('.pdf-empty-state').style.display = 'block';
        }
    }

    clearPdfPreview() {
        this.pdfUrl = null;
        this.totalPages = 0;

        document.getElementById('total-pages').textContent = '0';

        const embed = document.getElementById('pdf-embed');
        embed.src = '';
        embed.style.display = 'none';

        document.querySelector('.pdf-empty-state').style.display = 'block';
        document.querySelector('.pdf-empty-state').innerHTML = `
            <div class="empty-icon">📄</div>
            <p>选择文档后预览 PDF 内容</p>
            <p class="hint">点击章节眼睛图标可跳转到对应页面</p>
        `;
    }

    goToPage(pageNum) {
        if (!this.pdfUrl || pageNum < 1 || pageNum > this.totalPages) return;

        // 使用 embed 的 PDF 内置跳转功能
        const embed = document.getElementById('pdf-embed');
        embed.src = `${this.pdfUrl}#page=${pageNum}`;
    }

    // ==================== 工具方法 ====================

    showStatus(type, message) {
        const el = document.getElementById('status-message');
        el.className = `status-message ${type}`;
        el.textContent = message;
        el.style.display = 'block';

        if (type !== 'error') {
            setTimeout(() => {
                el.style.display = 'none';
            }, 5000);
        } else {
            setTimeout(() => {
                el.style.display = 'none';
            }, 8000);
        }
    }

    showProgress(title, message) {
        document.getElementById('progress-title').textContent = title;
        document.getElementById('progress-message').textContent = message;
        document.getElementById('progress-overlay').style.display = 'flex';
    }

    hideProgress() {
        document.getElementById('progress-overlay').style.display = 'none';
    }

    escapeHtml(text) {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return text.replace(/[&<>"']/g, m => map[m]);
    }
}

// 初始化
let chaptersManager;
document.addEventListener('DOMContentLoaded', () => {
    chaptersManager = new ChaptersManager();
});
