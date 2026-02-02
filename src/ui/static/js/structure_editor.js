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

            // Check if there's a doc parameter in the URL
            const urlParams = new URLSearchParams(window.location.search);
            const docParam = urlParams.get('doc');
            if (docParam) {
                // Set the select value and load the document
                select.value = docParam;
                await this.loadDocument(docParam);
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
                