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
        this.pdfImages = [];
        this.editingChapterIndex = null;

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

        // 保存结构
        document.getElementById('save-structure-btn').addEventListener('click', () => {
            this.saveStructure();
        });

        // 重建按钮
        document.getElementById('rebuild-btn').addEventListener('click', () => {
            this.rebuild();
        });

        // PDF 导航
        document.getElementById('prev-page-btn').addEventListener('click', () => {
            this.goToPreviousPage();
        });

        document.getElementById('next-page-btn').addEventListener('click', () => {
            this.goToNextPage();
        });

        document.getElementById('page-jump-btn').addEventListener('click', () => {
            const pageNum = parseInt(document.getElementById('page-jump-input').value);
            if (pageNum >= 1 && pageNum <= this.totalPages) {
                this.showPage(pageNum);
            }
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
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.detail || '加载文档列表失败');
            }

            const select = document.getElementById('doc-select');
            select.innerHTML = '<option value="">-- 请选择文档 --</option>';

            data.documents.forEach(doc => {
                const option = document.createElement('option');
                option.value = doc.name;
                option.textContent = doc.name;
                select.appendChild(option);
            });

            this.hideLoading();
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
                throw new Error(data.detail || '加载文档结构失败');
            }

            this.structure = data.agenda_dict;
            this.totalPages = data.total_pages;

            // 显示文档信息
            document.getElementById('doc-info').style.display = 'block';
            document.getElementById('doc-total-pages').textContent = `总页数: ${this.totalPages}`;
            document.getElementById('doc-total-chapters').textContent = `总章节: ${data.total_chapters}`;

            // 显示编辑器
            document.getElementById('editor-container').style.display = 'flex';

            // 渲染章节列表
            this.renderChaptersList();

            // 加载 PDF 图片
            await this.loadPdfImages();

            // 显示第一页
            if (this.totalPages > 0) {
                this.showPage(1);
            }

            this.hideLoading();
        } catch (error) {
            console.error('加载文档失败:', error);
            alert('加载文档失败: ' + error.message);
            this.hideLoading();
        }
    }

    async loadPdfImages() {
        try {
            // 获取 PDF 图片列表
            const response = await fetch(`/api/v1/pdf/images/${this.currentDoc}`);
            const data = await response.json();

            if (data.success) {
                this.pdfImages = data.images || [];
            } else {
                console.warn('未找到 PDF 图片，将使用占位符');
                this.pdfImages = [];
            }
        } catch (error) {
            console.error('加载 PDF 图片失败:', error);
            this.pdfImages = [];
        }
    }

    renderChaptersList() {
        const container = document.getElementById('chapters-list');
        container.innerHTML = '';

        const chapters = Object.entries(this.structure);

        if (chapters.length === 0) {
            container.innerHTML = '<p class="placeholder-text">暂无章节，请添加</p>';
            return;
        }

        chapters.forEach(([title, pages], index) => {
            const chapterItem = document.createElement('div');
            chapterItem.className = 'chapter-item';
            chapterItem.innerHTML = `
                <div class="chapter-info" data-index="${index}">
                    <div class="chapter-header">
                        <span class="chapter-title">${title}</span>
                        <div class="chapter-actions">
                            <button class="btn-icon edit-chapter-btn" data-index="${index}" title="编辑">
                                ✏️
                            </button>
                            <button class="btn-icon delete-chapter-btn" data-index="${index}" title="删除">
                                🗑️
                            </button>
                        </div>
                    </div>
                    <div class="chapter-pages">
                        页码: ${this.formatPages(pages)}
                    </div>
                </div>
            `;

            // 点击章节标题跳转到对应页面
            const infoDiv = chapterItem.querySelector('.chapter-info');
            infoDiv.addEventListener('click', (e) => {
                if (!e.target.classList.contains('btn-icon') &&
                    !e.target.closest('.chapter-actions')) {
                    this.showPage(pages[0]);
                }
            });

            // 编辑按钮
            const editBtn = chapterItem.querySelector('.edit-chapter-btn');
            editBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.editChapter(index);
            });

            // 删除按钮
            const deleteBtn = chapterItem.querySelector('.delete-chapter-btn');
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteChapter(index);
            });

            container.appendChild(chapterItem);
        });
    }

    formatPages(pages) {
        if (!Array.isArray(pages) || pages.length === 0) {
            return '-';
        }

        // 简化显示，如果页码连续则显示范围
        const sortedPages = [...pages].sort((a, b) => a - b);

        if (sortedPages.length === 1) {
            return sortedPages[0].toString();
        }

        const ranges = [];
        let start = sortedPages[0];
        let end = sortedPages[0];

        for (let i = 1; i < sortedPages.length; i++) {
            if (sortedPages[i] === end + 1) {
                end = sortedPages[i];
            } else {
                ranges.push(start === end ? `${start}` : `${start}-${end}`);
                start = sortedPages[i];
                end = sortedPages[i];
            }
        }
        ranges.push(start === end ? `${start}` : `${start}-${end}`);

        return ranges.join(', ');
    }

    showPage(pageNum) {
        this.currentPage = pageNum;

        const previewDiv = document.getElementById('pdf-preview');

        if (this.pdfImages.length > 0 && this.pdfImages[pageNum - 1]) {
            const imgPath = this.pdfImages[pageNum - 1];
            previewDiv.innerHTML = `
                <img src="${imgPath}" alt="Page ${pageNum}" class="pdf-page-image">
            `;
        } else {
            previewDiv.innerHTML = `
                <div class="placeholder-box">
                    <p>第 ${pageNum} 页</p>
                    <p>（PDF 图片未找到）</p>
                </div>
            `;
        }

        // 更新页码信息
        document.getElementById('page-info').textContent = `页码: ${pageNum} / ${this.totalPages}`;

        // 更新按钮状态
        document.getElementById('prev-page-btn').disabled = (pageNum === 1);
        document.getElementById('next-page-btn').disabled = (pageNum === this.totalPages);
        document.getElementById('page-jump-input').max = this.totalPages;
    }

    goToPreviousPage() {
        if (this.currentPage > 1) {
            this.showPage(this.currentPage - 1);
        }
    }

    goToNextPage() {
        if (this.currentPage < this.totalPages) {
            this.showPage(this.currentPage + 1);
        }
    }

    showChapterDialog(chapterIndex = null) {
        this.editingChapterIndex = chapterIndex;

        const dialog = document.getElementById('chapter-dialog');
        const dialogTitle = document.getElementById('dialog-title');
        const titleInput = document.getElementById('chapter-title-input');
        const pagesInput = document.getElementById('chapter-pages-input');

        if (chapterIndex !== null) {
            // 编辑模式
            const chapters = Object.entries(this.structure);
            const [title, pages] = chapters[chapterIndex];

            dialogTitle.textContent = '编辑章节';
            titleInput.value = title;
            pagesInput.value = this.formatPages(pages);
        } else {
            // 添加模式
            dialogTitle.textContent = '添加章节';
            titleInput.value = '';
            pagesInput.value = '';
        }

        dialog.style.display = 'flex';
    }

    hideChapterDialog() {
        document.getElementById('chapter-dialog').style.display = 'none';
        this.editingChapterIndex = null;
    }

    parsePages(pagesStr) {
        // 解析页码字符串，支持 "1-5, 7, 9-12" 格式
        const pages = [];
        const parts = pagesStr.split(',').map(p => p.trim());

        for (const part of parts) {
            if (part.includes('-')) {
                // 范围
                const [start, end] = part.split('-').map(p => parseInt(p.trim()));
                if (!isNaN(start) && !isNaN(end) && start <= end) {
                    for (let i = start; i <= end; i++) {
                        if (i >= 1 && i <= this.totalPages && !pages.includes(i)) {
                            pages.push(i);
                        }
                    }
                }
            } else {
                // 单个页码
                const page = parseInt(part);
                if (!isNaN(page) && page >= 1 && page <= this.totalPages && !pages.includes(page)) {
                    pages.push(page);
                }
            }
        }

        return pages.sort((a, b) => a - b);
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

        const pages = this.parsePages(pagesStr);

        if (pages.length === 0) {
            alert('页码范围无效，请检查输入');
            return;
        }

        // 检查标题是否重复（编辑模式除外）
        const chapters = Object.entries(this.structure);
        if (this.editingChapterIndex === null) {
            if (this.structure[title]) {
                alert('章节标题已存在，请使用其他标题');
                return;
            }
        } else {
            const [oldTitle] = chapters[this.editingChapterIndex];
            if (title !== oldTitle && this.structure[title]) {
                alert('章节标题已存在，请使用其他标题');
                return;
            }
        }

        // 更新结构
        if (this.editingChapterIndex !== null) {
            // 编辑模式：删除旧章节，添加新章节
            const [oldTitle] = chapters[this.editingChapterIndex];
            delete this.structure[oldTitle];
        }

        this.structure[title] = pages;

        // 重新渲染
        this.renderChaptersList();
        this.hideChapterDialog();

        // 显示重建按钮
        document.getElementById('rebuild-btn').style.display = 'inline-block';
    }

    editChapter(index) {
        this.showChapterDialog(index);
    }

    deleteChapter(index) {
        const chapters = Object.entries(this.structure);
        const [title] = chapters[index];

        if (confirm(`确定要删除章节 "${title}" 吗？`)) {
            delete this.structure[title];
            this.renderChaptersList();

            // 显示重建按钮
            document.getElementById('rebuild-btn').style.display = 'inline-block';
        }
    }

    async saveStructure() {
        if (!this.currentDoc) {
            alert('请先选择文档');
            return;
        }

        try {
            this.showLoading('保存结构...');

            const response = await fetch(`/api/v1/structure/${this.currentDoc}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    agenda_dict: this.structure,
                    has_toc: false  // 手动编辑的都标记为 false
                })
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.detail || '保存失败');
            }

            alert('结构保存成功！\n\n点击"重建数据"按钮以应用更改。');

            // 显示重建按钮
            document.getElementById('rebuild-btn').style.display = 'inline-block';

            this.hideLoading();
        } catch (error) {
            console.error('保存结构失败:', error);
            alert('保存结构失败: ' + error.message);
            this.hideLoading();
        }
    }

    async rebuild() {
        if (!this.currentDoc) {
            alert('请先选择文档');
            return;
        }

        // 确认重建
        if (!confirm('确定要重建文档数据吗？\n\n这将重新生成：\n- 章节数据 (chunks.json)\n- 章节摘要\n- 向量数据库\n- 简要摘要\n\n重建过程可能需要几分钟，请耐心等待。')) {
            return;
        }

        try {
            this.showLoading('重建中，这可能需要几分钟...');

            const response = await fetch(`/api/v1/structure/${this.currentDoc}/rebuild`, {
                method: 'POST'
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.detail || '重建失败');
            }

            alert('重建完成！\n\n数据已更新，可以在聊天模式中使用新的章节结构。');

            // 隐藏重建按钮
            document.getElementById('rebuild-btn').style.display = 'none';

            this.hideLoading();
        } catch (error) {
            console.error('重建失败:', error);
            alert('重建失败: ' + error.message);
            this.hideLoading();
        }
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    new StructureEditor();
});
