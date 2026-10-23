/**
 * 文档结构编辑器
 *
 * 功能：
 * - 加载文档列表
 * - 编辑章节结构（添加、修改、删除）
 * - PDF 预览
 * - 保存结构并触发重建
 */

class StructureEditor {
    constructor() {
        this.currentDoc = null;
        this.structure = null;
        this.totalPages = 0;
        this.currentPage = 1;
        this.editingChapterIndex = null;

        // PDF.js 相关
        this.pdfDoc = null;
        this.scale = 1.5;
        this.devicePixelRatio = window.devicePixelRatio || 2;
        this.renderedPages = new Set();

        // 批量删除相关
        this.batchMode = false;
        this.selectedChapters = new Set();

        // 后台任务相关
        this.activeTasks = new Map(); // {taskId: {filename, taskId, startTime}}
        this.completedTasks = new Set(); // 已完成任务的ID集合
        this.taskCheckInterval = null; // 任务检查定时器

        this.init();
    }

    init() {
        this.bindEvents();
        this.loadDocumentList();
    }

    bindEvents() {
        // 文档选择
        document.getElementById('doc-select').addEventListener('change', (e) => {
            this.loadDocument(e.target.value);
        });

        // 添加章节
        document.getElementById('add-chapter-btn').addEventListener('click', () => {
            this.showChapterDialog();
        });

        // 批量删除
        document.getElementById('batch-delete-btn').addEventListener('click', () => {
            this.confirmBatchDelete();
        });

        // 取消批量删除
        document.getElementById('cancel-batch-btn').addEventListener('click', () => {
            this.cancelBatchMode();
        });

        // 全选
        document.getElementById('select-all-chapters').addEventListener('change', (e) => {
            this.selectAllChapters(e.target.checked);
        });

        // 重建按钮
        document.getElementById('rebuild-btn').addEventListener('click', () => {
            this.rebuild();
        });

        // 页码跳转
        document.getElementById('page-jump-btn').addEventListener('click', () => {
            this.handlePageJump();
        });

        document.getElementById('page-jump-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this.handlePageJump();
            }
        });

        // 缩放按钮
        document.getElementById('zoom-in-btn').addEventListener('click', () => {
            this.zoom(1.2);
        });

        document.getElementById('zoom-out-btn').addEventListener('click', () => {
            this.zoom(0.8);
        });

        // 章节对话框
        document.getElementById('close-dialog-btn').addEventListener('click', () => {
            this.hideChapterDialog();
        });

        document.getElementById('cancel-dialog-btn').addEventListener('click', () => {
            this.hideChapterDialog();
        });

        document.getElementById('confirm-dialog-btn').addEventListener('click', () => {
            this.saveChapter();
        });

        // 拖动分栏
        this.initPanelResizer();
    }

    showLoading(message = '加载中...') {
        document.getElementById('loading-message').textContent = message;
        document.getElementById('loading-overlay').style.display = 'flex';
    }

    hideLoading() {
        document.getElementById('loading-overlay').style.display = 'none';
    }

    async loadDocumentList() {
        try {
            this.showLoading('加载文档列表...');

            const response = await fetch('/api/v1/data/documents');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const documents = await response.json();

            // API 直接返回文档数组
            const select = document.getElementById('doc-select');
            select.innerHTML = '<option value="">-- 请选择文档 --</option>';

            documents.forEach(doc => {
                const option = document.createElement('option');
                option.value = doc.doc_name;
                option.textContent = doc.doc_name;
                select.appendChild(option);
            });

            this.hideLoading();

            // Check if there's a doc parameter in the URL
            const urlParams = new URLSearchParams(window.location.search);
            const docParam = urlParams.get('doc');
            if (docParam) {
                // Set the select value and load the document
                select.value = docParam;
                await this.loadDocument(docParam);

                // 隐藏文档选择器（从数据管理页面跳转过来的情况）
                const selectorElement = document.querySelector('.document-selector');
                if (selectorElement) {
                    selectorElement.style.display = 'none';
                }
            }
        } catch (error) {
            console.error('加载文档列表失败:', error);
            alert('加载文档列表失败: ' + error.message);
            this.hideLoading();
        }
    }

    async loadDocument(docName) {
        if (!docName) {
            document.getElementById('editor-container').style.display = 'none';
            return;
        }

        try {
            this.showLoading('加载文档结构...');
            this.currentDoc = docName;

            // 加载结构
            const response = await fetch(`/api/v1/structure/${docName}`);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || '加载文档结构失败');
            }

            // 将 agenda_dict 转换为数组格式
            // API 返回: {agenda_dict: {"章节1": [1,2,3], "章节2": [4,5,6]}}
            // 前端需要: [{chapter_title: "章节1", pages: [1,2,3]}, ...]
            const agendaDict = data.agenda_dict || {};
            this.structure = Object.entries(agendaDict).map(([title, pages]) => ({
                chapter_title: title,
                pages: pages
            }));

            this.totalPages = data.total_pages || 0;

            // 显示编辑器
            const editorContainer = document.getElementById('editor-container');
            editorContainer.style.display = 'flex';
            editorContainer.classList.remove('is-visible');
            void editorContainer.offsetWidth;
            editorContainer.classList.add('is-visible');
            document.getElementById('doc-info').style.display = 'flex';
            document.getElementById('doc-total-pages').textContent = `总页数: ${this.totalPages}`;
            document.getElementById('doc-total-chapters').textContent = `总章节: ${this.structure.length}`;

            // 渲染章节列表
            this.renderChapters();

            // 加载 PDF
            await this.loadPdf();

            this.hideLoading();
        } catch (error) {
            console.error('加载文档失败:', error);
            alert('加载文档失败: ' + error.message);
            this.hideLoading();
        }
    }

    async loadPdf() {
        try {
            const pdfUrl = `/api/v1/pdf/view/${this.currentDoc}`;
            const loadingTask = pdfjsLib.getDocument(pdfUrl);
            this.pdfDoc = await loadingTask.promise;
            this.totalPages = this.pdfDoc.numPages;

            // 更新页码显示
            document.getElementById('page-info').textContent = `页码: 1 / ${this.totalPages}`;
            const pageJumpInput = document.getElementById('page-jump-input');
            if (pageJumpInput) {
                pageJumpInput.max = this.totalPages;
                pageJumpInput.value = '';
            }

            // 渲染所有页面
            await this.renderAllPdfPages();

            console.log('PDF 加载成功:', this.currentDoc);
        } catch (error) {
            console.error('加载 PDF 失败:', error);
            // 不阻塞主流程，允许编辑器继续使用
        }
    }

    async renderAllPdfPages() {
        if (!this.pdfDoc) return;

        const container = document.getElementById('pdf-pages-container');
        container.innerHTML = '';

        this.renderedPages.clear();

        // 创建占位符
        await this.createPagePlaceholders(container);

        // 初始渲染前3页
        for (let i = 1; i <= Math.min(3, this.totalPages); i++) {
            await this.renderPage(i);
        }

        // 更新缩放显示
        document.getElementById('zoom-level').textContent = Math.round(this.scale * 100) + '%';

        // 设置滚动监听
        this.setupPdfScrollListener();

        // 立即触发一次可见页面渲染
        setTimeout(() => this.renderVisiblePages(), 200);
    }

    async createPagePlaceholders(container) {
        const firstPage = await this.pdfDoc.getPage(1);
        const baseViewport = firstPage.getViewport({ scale: this.scale });
        const width = Math.floor(baseViewport.width);
        const height = Math.floor(baseViewport.height);

        for (let pageNum = 1; pageNum <= this.totalPages; pageNum++) {
            const pageDiv = document.createElement('div');
            pageDiv.className = 'pdf-page';
            pageDiv.id = 'pdf-page-' + pageNum;
            pageDiv.setAttribute('data-page', pageNum);
            pageDiv.setAttribute('data-rendered', 'false');

            const placeholder = document.createElement('div');
            placeholder.className = 'pdf-placeholder';
            placeholder.style.width = width + 'px';
            placeholder.style.height = height + 'px';
            placeholder.textContent = `第 ${pageNum} 页`;

            pageDiv.appendChild(placeholder);
            container.appendChild(pageDiv);
        }
    }

    async renderPage(pageNum) {
        if (this.renderedPages.has(pageNum)) return;
        if (!this.pdfDoc) return;

        try {
            const pageDiv = document.getElementById('pdf-page-' + pageNum);
            if (!pageDiv) return;

            this.renderedPages.add(pageNum);
            pageDiv.setAttribute('data-rendered', 'true');

            const page = await this.pdfDoc.getPage(pageNum);

            const qualityScale = this.devicePixelRatio * 1.5;
            const baseViewport = page.getViewport({ scale: this.scale });
            const renderViewport = page.getViewport({ scale: this.scale * qualityScale });

            const canvas = document.createElement('canvas');
            canvas.width = renderViewport.width;
            canvas.height = renderViewport.height;
            canvas.style.width = Math.floor(baseViewport.width) + 'px';
            canvas.style.height = Math.floor(baseViewport.height) + 'px';

            const context = canvas.getContext('2d');
            context.imageSmoothingEnabled = true;
            context.imageSmoothingQuality = 'high';

            await page.render({
                canvasContext: context,
                viewport: renderViewport,
                intent: 'display'
            }).promise;

            pageDiv.innerHTML = '';
            pageDiv.appendChild(canvas);

        } catch (error) {
            console.error(`渲染第 ${pageNum} 页失败:`, error);
            this.renderedPages.delete(pageNum);
        }
    }

    setupPdfScrollListener() {
        const viewer = document.querySelector('.pdf-preview-container');
        if (!viewer) return;

        let scrollTimeout;
        viewer.addEventListener('scroll', () => {
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                this.renderVisiblePages();
                this.updateCurrentPageFromScroll();
            }, 100);
        });
    }

    updateCurrentPageFromScroll() {
        const viewer = document.querySelector('.pdf-preview-container');
        if (!viewer) return;

        const viewerRect = viewer.getBoundingClientRect();
        const viewerCenter = viewerRect.top + viewerRect.height / 2;

        // 找到最接近视口中心的页面
        for (let pageNum = 1; pageNum <= this.totalPages; pageNum++) {
            const pageDiv = document.getElementById('pdf-page-' + pageNum);
            if (!pageDiv) continue;

            const pageRect = pageDiv.getBoundingClientRect();
            if (pageRect.top <= viewerCenter && pageRect.bottom >= viewerCenter) {
                this.currentPage = pageNum;
                document.getElementById('page-info').textContent = `页码: ${pageNum} / ${this.totalPages}`;
                break;
            }
        }
    }

    handlePageJump() {
        const input = document.getElementById('page-jump-input');
        const value = parseInt(input.value, 10);

        if (isNaN(value)) {
            return;
        }

        if (value < 1 || value > this.totalPages) {
            alert(`页码超出范围（1-${this.totalPages}）`);
            return;
        }

        this.scrollToPage(value);
    }

    async renderVisiblePages() {
        const viewer = document.querySelector('.pdf-preview-container');
        if (!viewer) return;

        const viewerRect = viewer.getBoundingClientRect();
        const buffer = 500; // 缓冲距离（像素）

        for (let pageNum = 1; pageNum <= this.totalPages; pageNum++) {
            const pageDiv = document.getElementById('pdf-page-' + pageNum);
            if (!pageDiv) continue;

            const pageRect = pageDiv.getBoundingClientRect();

            // 检查页面是否在可视区域内或缓冲区内
            if (pageRect.bottom >= (viewerRect.top - buffer) &&
                pageRect.top <= (viewerRect.bottom + buffer)) {
                if (!this.renderedPages.has(pageNum)) {
                    await this.renderPage(pageNum);
                }
            }
        }
    }

    renderChapters() {
        const container = document.getElementById('chapters-list');
        container.innerHTML = '';

        // 显示批量删除按钮（如果有章节）
        const batchDeleteBtn = document.getElementById('batch-delete-btn');
        if (this.structure.length > 0) {
            batchDeleteBtn.style.display = 'inline-block';
        } else {
            batchDeleteBtn.style.display = 'none';
        }

        this.structure.forEach((chapter, index) => {
            const chapterDiv = document.createElement('div');
            chapterDiv.className = 'chapter-item';
            chapterDiv.setAttribute('data-index', index);

            let checkboxHtml = '';
            if (this.batchMode) {
                const isChecked = this.selectedChapters.has(index) ? 'checked' : '';
                checkboxHtml = `<input type="checkbox" class="chapter-checkbox" data-index="${index}" ${isChecked} style="margin-right: 10px;">`;
            }

            chapterDiv.innerHTML = `
                <div class="chapter-content">
                    <div class="chapter-title-row">
                        ${checkboxHtml}
                        <span class="chapter-number">${index + 1}</span>
                        <span class="chapter-title">${chapter.chapter_title || '未命名章节'}</span>
                    </div>
                    <div class="chapter-pages">
                        页码: ${this.formatPages(chapter.pages)}
                    </div>
                </div>
                <div class="chapter-actions" style="display: ${this.batchMode ? 'none' : 'flex'}">
                    <button class="btn btn-sm btn-primary" onclick="editor.editChapter(${index})">✏️ 编辑</button>
                    <button class="btn btn-sm btn-secondary" onclick="editor.viewChapter(${index})">👁️ 查看</button>
                    <button class="btn btn-sm btn-danger" onclick="editor.deleteChapter(${index})">🗑️ 删除</button>
                </div>
            `;
            container.appendChild(chapterDiv);

            // 批量模式下的事件监听
            if (this.batchMode) {
                const checkbox = chapterDiv.querySelector('.chapter-checkbox');

                // 复选框自身的change事件
                checkbox.addEventListener('change', (e) => {
                    e.stopPropagation(); // 防止触发卡片点击事件
                    this.toggleChapterSelection(index, e.target.checked);
                });

                // 整个卡片的点击事件
                chapterDiv.style.cursor = 'pointer';
                chapterDiv.addEventListener('click', (e) => {
                    // 如果点击的是复选框本身，不处理（复选框的change事件会处理）
                    if (e.target === checkbox || e.target.classList.contains('chapter-checkbox')) {
                        return;
                    }

                    // 切换复选框状态
                    checkbox.checked = !checkbox.checked;
                    this.toggleChapterSelection(index, checkbox.checked);
                });
            }
        });
    }

    formatPages(pages) {
        if (!pages || pages.length === 0) return '无';
        return pages.join(', ');
    }

    showChapterDialog(chapterIndex = null) {
        this.editingChapterIndex = chapterIndex;

        const dialog = document.getElementById('chapter-dialog');
        const title = document.getElementById('dialog-title');
        const titleInput = document.getElementById('chapter-title-input');
        const pagesInput = document.getElementById('chapter-pages-input');

        if (chapterIndex !== null) {
            // 编辑模式
            const chapter = this.structure[chapterIndex];
            title.textContent = '编辑章节';
            titleInput.value = chapter.chapter_title || '';
            pagesInput.value = this.formatPages(chapter.pages);
        } else {
            // 添加模式
            title.textContent = '添加章节';
            titleInput.value = '';
            pagesInput.value = '';
        }

        dialog.style.display = 'flex';
    }

    hideChapterDialog() {
        document.getElementById('chapter-dialog').style.display = 'none';
        this.editingChapterIndex = null;
    }

    saveChapter() {
        const titleInput = document.getElementById('chapter-title-input');
        const pagesInput = document.getElementById('chapter-pages-input');

        const title = titleInput.value.trim();
        const pagesStr = pagesInput.value.trim();

        if (!title) {
            alert('请输入章节标题');
            return;
        }

        if (!pagesStr) {
            alert('请输入页码范围');
            return;
        }

        // 解析页码
        const pages = this.parsePages(pagesStr);
        if (pages.length === 0) {
            alert('页码格式无效');
            return;
        }

        const chapter = {
            chapter_title: title,
            pages: pages
        };

        if (this.editingChapterIndex !== null) {
            // 更新现有章节
            this.structure[this.editingChapterIndex] = chapter;
        } else {
            // 添加新章节
            this.structure.push(chapter);
        }

        this.renderChapters();
        this.hideChapterDialog();

        // 更新章节数显示
        document.getElementById('doc-total-chapters').textContent = `总章节: ${this.structure.length}`;
    }

    parsePages(pagesStr) {
        const pages = [];
        const parts = pagesStr.split(',');

        for (let part of parts) {
            part = part.trim();

            if (part.includes('-')) {
                // 范围：1-5
                const [start, end] = part.split('-').map(p => parseInt(p.trim()));
                if (!isNaN(start) && !isNaN(end) && start <= end) {
                    for (let i = start; i <= end; i++) {
                        if (!pages.includes(i)) {
                            pages.push(i);
                        }
                    }
                }
            } else {
                // 单个页码
                const page = parseInt(part);
                if (!isNaN(page) && !pages.includes(page)) {
                    pages.push(page);
                }
            }
        }

        return pages.sort((a, b) => a - b);
    }

    editChapter(index) {
        this.showChapterDialog(index);
    }

    viewChapter(index) {
        const chapter = this.structure[index];
        if (chapter.pages && chapter.pages.length > 0) {
            this.scrollToPage(chapter.pages[0]);
        }
    }

    deleteChapter(index) {
        if (confirm('确定要删除这个章节吗？')) {
            this.structure.splice(index, 1);
            this.renderChapters();

            // 更新章节数显示
            document.getElementById('doc-total-chapters').textContent = `总章节: ${this.structure.length}`;
        }
    }

    scrollToPage(pageNum) {
        const pageDiv = document.getElementById('pdf-page-' + pageNum);
        if (pageDiv) {
            pageDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });
            this.currentPage = pageNum;
            document.getElementById('page-info').textContent = `页码: ${pageNum} / ${this.totalPages}`;
        }
    }

    initPanelResizer() {
        const resizer = document.getElementById('panel-resizer');
        const leftPanel = document.querySelector('.editor-panel');
        const rightPanel = document.querySelector('.preview-panel');
        const container = document.querySelector('.editor-container');

        if (!resizer || !leftPanel || !rightPanel || !container) return;

        let isDragging = false;

        const onMouseMove = (e) => {
            if (!isDragging) return;

            const containerRect = container.getBoundingClientRect();
            const minLeft = 320;
            const maxLeft = containerRect.width - 420;

            let newLeftWidth = e.clientX - containerRect.left;
            if (newLeftWidth < minLeft) newLeftWidth = minLeft;
            if (newLeftWidth > maxLeft) newLeftWidth = maxLeft;

            leftPanel.style.flex = `0 0 ${Math.round(newLeftWidth)}px`;
            leftPanel.style.width = `${Math.round(newLeftWidth)}px`;
            rightPanel.style.flex = '1 1 auto';
        };

        const stopDragging = () => {
            if (!isDragging) return;
            isDragging = false;
            resizer.classList.remove('is-dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', stopDragging);
        };

        resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            isDragging = true;
            resizer.classList.add('is-dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', stopDragging);
        });
    }

    async zoom(factor) {
        this.scale *= factor;
        if (this.scale < 0.5) this.scale = 0.5;
        if (this.scale > 3.0) this.scale = 3.0;

        this.showLoading('调整缩放...');

        // 保存当前页码
        const currentPageNum = this.currentPage;

        // 重新渲染
        await this.renderAllPdfPages();

        // 滚动回之前的页面
        setTimeout(() => {
            this.scrollToPage(currentPageNum);
            this.hideLoading();
        }, 100);
    }

    enterBatchMode() {
        this.batchMode = true;
        this.selectedChapters.clear();

        // 显示批量模式UI
        document.getElementById('batch-mode-hint').style.display = 'flex';
        document.getElementById('batch-delete-btn').textContent = '✅ 确认删除';
        document.getElementById('batch-delete-btn').classList.remove('btn-danger');
        document.getElementById('batch-delete-btn').classList.add('btn-warning');
        document.getElementById('cancel-batch-btn').style.display = 'inline-block';
        document.getElementById('add-chapter-btn').style.display = 'none';

        this.renderChapters();
        this.updateSelectedCount();
    }

    confirmBatchDelete() {
        if (!this.batchMode) {
            // 首次点击，进入批量模式
            this.enterBatchMode();
            return;
        }

        // 已在批量模式，执行删除
        if (this.selectedChapters.size === 0) {
            alert('请先选择要删除的章节');
            return;
        }

        if (confirm(`确定要删除选中的 ${this.selectedChapters.size} 个章节吗？`)) {
            // 按索引从大到小排序，避免删除时索引错位
            const toDelete = Array.from(this.selectedChapters).sort((a, b) => b - a);
            toDelete.forEach(index => {
                this.structure.splice(index, 1);
            });

            // 更新章节数显示
            document.getElementById('doc-total-chapters').textContent = `总章节: ${this.structure.length}`;

            // 退出批量模式
            this.exitBatchMode();
        }
    }

    cancelBatchMode() {
        this.exitBatchMode();
    }

    exitBatchMode() {
        this.batchMode = false;
        this.selectedChapters.clear();

        // 恢复正常UI
        document.getElementById('batch-mode-hint').style.display = 'none';
        document.getElementById('batch-delete-btn').textContent = '🗑️ 批量删除';
        document.getElementById('batch-delete-btn').classList.remove('btn-warning');
        document.getElementById('batch-delete-btn').classList.add('btn-danger');
        document.getElementById('cancel-batch-btn').style.display = 'none';
        document.getElementById('add-chapter-btn').style.display = 'inline-block';

        this.renderChapters();
    }

    toggleChapterSelection(index, checked) {
        if (checked) {
            this.selectedChapters.add(index);
        } else {
            this.selectedChapters.delete(index);
        }
        this.updateSelectedCount();
    }

    selectAllChapters(checked) {
        this.selectedChapters.clear();
        if (checked) {
            this.structure.forEach((_, index) => {
                this.selectedChapters.add(index);
            });
        }
        this.renderChapters();
        this.updateSelectedCount();
    }

    updateSelectedCount() {
        const countElem = document.getElementById('selected-count');
        if (countElem) {
            countElem.textContent = `已选择 ${this.selectedChapters.size} 个章节`;
        }
    }

    async rebuild() {
        if (!this.currentDoc) {
            alert('请先选择文档');
            return;
        }

        if (!confirm('确定要根据当前结构重建索引和摘要吗？\n\n这将：\n• 重新生成章节chunks\n• 重新生成章节摘要\n• 重建向量数据库\n• 重新生成文档摘要\n\n重建将在后台进行，完成后会通知您。')) {
            return;
        }

        try {
            // 🔥 重要：在重建前自动保存当前结构！
            this.showLoading('正在保存结构并启动重建...');

            // 1. 先保存当前结构
            const agendaDict = {};
            this.structure.forEach(chapter => {
                agendaDict[chapter.chapter_title] = chapter.pages;
            });

            const saveResponse = await fetch(`/api/v1/structure/${this.currentDoc}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    agenda_dict: agendaDict,
                    has_toc: false
                })
            });

            const saveData = await saveResponse.json();
            if (!saveData.success) {
                throw new Error('保存结构失败: ' + (saveData.message || '未知错误'));
            }

            console.log('✅ 结构已保存，开始重建...');

            // 2. 启动重建任务
            const response = await fetch(`/api/v1/structure/${this.currentDoc}/rebuild`, {
                method: 'POST'
            });

            const data = await response.json();
            this.hideLoading();

            if (!data.success) {
                throw new Error(data.message || '重建失败');
            }

            // API 返回: {success: true, status: "started", task_id: "...", message: "..."}
            if (data.status === 'started' && data.task_id) {
                // 添加到活跃任务
                this.activeTasks.set(data.task_id, {
                    filename: this.currentDoc,
                    taskId: data.task_id,
                    startTime: Date.now()
                });

                // 开始轮询
                this.startTaskPolling();

                this.showNotification(`✅ 结构已保存，${this.currentDoc} 开始重建（后台运行）...`, 'success', 4000);
            }
        } catch (error) {
            console.error('重建失败:', error);
            this.hideLoading();
            this.showNotification('重建失败: ' + error.message, 'error');
        }
    }

    startTaskPolling() {
        // 如果已经在轮询，不重复启动
        if (this.taskCheckInterval) return;

        console.log('📊 开始轮询后台任务状态...');

        this.taskCheckInterval = setInterval(() => {
            this.checkActiveTasks();
        }, 3000); // 每3秒检查一次
    }

    async checkActiveTasks() {
        if (this.activeTasks.size === 0) {
            // 没有活跃任务，停止轮询
            if (this.taskCheckInterval) {
                clearInterval(this.taskCheckInterval);
                this.taskCheckInterval = null;
                console.log('📊 所有任务完成，停止轮询');
            }
            return;
        }

        for (const [taskId, taskInfo] of this.activeTasks) {
            try {
                const response = await fetch(`/api/v1/data/tasks/${taskId}`);
                if (!response.ok) continue;

                const task = await response.json();

                if (task.status === 'completed') {
                    // 任务成功完成
                    if (!this.completedTasks.has(taskId)) {
                        this.showNotification(`✅ ${taskInfo.filename} 重建完成！`, 'success', 5000);
                        this.completedTasks.add(taskId);
                    }

                    this.activeTasks.delete(taskId);

                } else if (task.status === 'failed') {
                    // 任务失败
                    if (!this.completedTasks.has(taskId)) {
                        this.showNotification(`❌ ${taskInfo.filename} 重建失败: ${task.error || '未知错误'}`, 'error', 7000);
                        this.completedTasks.add(taskId);
                    }

                    this.activeTasks.delete(taskId);
                }
            } catch (error) {
                console.error('检查任务状态失败:', error);
            }
        }
    }

    showNotification(message, type = 'info', duration = 3000) {
        // 创建通知元素
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 8px;
            color: white;
            font-size: 14px;
            font-weight: 500;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 10001;
            max-width: 400px;
            animation: slideIn 0.3s ease-out;
        `;

        // 根据类型设置颜色
        const colors = {
            success: '#28a745',
            error: '#dc3545',
            info: '#2563eb',
            warning: '#ffc107'
        };
        notification.style.background = colors[type] || colors.info;

        notification.textContent = message;
        document.body.appendChild(notification);

        // 添加动画样式
        if (!document.getElementById('notification-styles')) {
            const style = document.createElement('style');
            style.id = 'notification-styles';
            style.textContent = `
                @keyframes slideIn {
                    from {
                        transform: translateX(400px);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
                @keyframes slideOut {
                    from {
                        transform: translateX(0);
                        opacity: 1;
                    }
                    to {
                        transform: translateX(400px);
                        opacity: 0;
                    }
                }
            `;
            document.head.appendChild(style);
        }

        // 自动移除
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, duration);
    }
}

// 初始化编辑器
let editor;
window.addEventListener('DOMContentLoaded', () => {
    editor = new StructureEditor();
});
