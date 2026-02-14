/**
 * Data Management Module
 *
 * Handles document and session management UI
 */

class DataManager {
    constructor() {
        this.documents = [];
        this.sessions = [];
        this.overview = null;
        this.sessionStats = null;
        this.currentTab = 'documents';

        // 后台任务管理
        this.activeTasks = new Map(); // 活跃任务 Map<taskId, taskInfo>
        this.taskCheckInterval = null; // 轮询定时器
        this.completedTasks = new Set(); // 已通知完成的任务ID

        // Markdown/LaTeX 库延迟加载
        this.markdownLibsLoaded = false;
        this.markdownLibsLoading = false;
        this.markdownLoadPromise = null;

        // 分页状态
        this.itemsPerPage = 6;
        this.currentDocPage = 1;
        this.currentSessionPage = 1;
        this.filteredDocuments = null; // 用于存储过滤后的文档列表
        this.filteredSessions = null; // 用于存储过滤后的会话列表

        this.init();
    }

    // ==================== Lazy Load Libraries ====================

    async loadMarkdownLibraries() {
        /**
         * 延迟加载 Markdown 和 LaTeX 渲染库
         * 只在需要时加载（查看文档详情或会话详情时）
         */
        if (this.markdownLibsLoaded) {
            return Promise.resolve();
        }

        if (this.markdownLibsLoading) {
            return this.markdownLoadPromise;
        }

        this.markdownLibsLoading = true;

        this.markdownLoadPromise = new Promise((resolve, reject) => {
            let loadedCount = 0;
            const totalLibs = 4; // marked, katex css, katex js, katex auto-render

            const checkAllLoaded = () => {
                loadedCount++;
                if (loadedCount === totalLibs) {
                    this.markdownLibsLoaded = true;
                    this.markdownLibsLoading = false;
                    console.log('✅ Markdown/LaTeX libraries loaded');
                    resolve();
                }
            };

            // Load Marked.js
            const markedScript = document.createElement('script');
            markedScript.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
            markedScript.onload = checkAllLoaded;
            markedScript.onerror = () => reject(new Error('Failed to load marked.js'));
            document.head.appendChild(markedScript);

            // Load KaTeX CSS
            const katexCss = document.createElement('link');
            katexCss.rel = 'stylesheet';
            katexCss.href = 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css';
            katexCss.onload = checkAllLoaded;
            katexCss.onerror = () => reject(new Error('Failed to load katex.css'));
            document.head.appendChild(katexCss);

            // Load KaTeX JS
            const katexScript = document.createElement('script');
            katexScript.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js';
            katexScript.onload = checkAllLoaded;
            katexScript.onerror = () => reject(new Error('Failed to load katex.js'));
            document.head.appendChild(katexScript);

            // Load KaTeX Auto-render
            const autoRenderScript = document.createElement('script');
            autoRenderScript.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js';
            autoRenderScript.onload = checkAllLoaded;
            autoRenderScript.onerror = () => reject(new Error('Failed to load auto-render.js'));
            document.head.appendChild(autoRenderScript);
        });

        return this.markdownLoadPromise;
    }

    // ==================== Initialization ====================

    async init() {
        // Tab switching
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });

        // Search functionality
        document.getElementById('doc-search')?.addEventListener('input', (e) => {
            this.filterDocuments(e.target.value);
        });

        document.getElementById('session-search')?.addEventListener('input', (e) => {
            this.filterSessions(e.target.value);
        });

        // Load initial data
        await this.loadAllData();
    }

    switchTab(tabName) {
        // Update tab buttons
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `${tabName}-tab`);
        });

        this.currentTab = tabName;

        // Load data if not loaded
        if (tabName === 'documents' && !this.documents.length) {
            this.loadDocuments();
        } else if (tabName === 'sessions' && !this.sessions.length) {
            this.loadSessions();
        }
    }

    async loadAllData() {
        await Promise.all([
            this.loadOverview(),
            this.loadDocuments(),
            this.loadSessionStats(),
            this.loadPendingPdfs()
        ]);
    }

    async loadOverview() {
        try {
            const response = await fetch('/api/v1/data/overview');
            if (!response.ok) throw new Error('Failed to fetch overview');

            this.overview = await response.json();
            this.renderOverview();
        } catch (error) {
            console.error('Error loading overview:', error);
            this.showError('加载概览失败: ' + error.message);
        }
    }

    renderOverview() {
        if (!this.overview) return;

        const totalDocs = this.overview.total_documents || 0;
        const pendingCount = this.pendingPdfs ? this.pendingPdfs.length : 0;
        const indexedCount = totalDocs;

        document.getElementById('total-docs').textContent = totalDocs + pendingCount;
        document.getElementById('pending-docs').textContent = pendingCount;
        document.getElementById('indexed-docs').textContent = indexedCount;
        document.getElementById('total-storage').innerHTML =
            `${this.overview.total_storage_mb?.toFixed(2) || 0}<span class="unit">MB</span>`;

        // 显示详细的存储分类
        const breakdown = this.overview.breakdown || {};
        document.getElementById('json-storage').innerHTML =
            `${breakdown.json_data?.size_mb?.toFixed(2) || 0}<span class="unit">MB</span>`;
        document.getElementById('vector-storage').innerHTML =
            `${breakdown.vector_db?.size_mb?.toFixed(2) || 0}<span class="unit">MB</span>`;
        document.getElementById('images-storage').innerHTML =
            `${breakdown.images?.size_mb?.toFixed(2) || 0}<span class="unit">MB</span>`;
        document.getElementById('summaries-storage').innerHTML =
            `${breakdown.summaries?.size_mb?.toFixed(2) || 0}<span class="unit">MB</span>`;
    }

    async loadDocuments() {
        const loadingEl = document.getElementById('documents-loading');
        const gridEl = document.getElementById('documents-grid');
        const emptyEl = document.getElementById('documents-empty');

        loadingEl.style.display = 'block';
        gridEl.style.display = 'none';
        emptyEl.style.display = 'none';

        try {
            const response = await fetch('/api/v1/data/documents');
            if (!response.ok) throw new Error('Failed to fetch documents');

            this.documents = await response.json();

            loadingEl.style.display = 'none';

            if (this.documents.length === 0) {
                emptyEl.style.display = 'block';
            } else {
                gridEl.style.display = 'grid';
                this.renderDocuments();
            }
        } catch (error) {
            console.error('Error loading documents:', error);
            loadingEl.style.display = 'none';
            this.showError('加载文档失败: ' + error.message);
        }
    }

    renderDocuments(filteredDocs = null) {
        const gridEl = document.getElementById('documents-grid');
        const docs = filteredDocs !== null ? filteredDocs : this.documents;

        // 保存过滤后的文档列表（用于分页）
        this.filteredDocuments = docs;

        // 计算分页
        const totalPages = Math.ceil(docs.length / this.itemsPerPage);
        const startIndex = (this.currentDocPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const paginatedDocs = docs.slice(startIndex, endIndex);

        // 渲染当前页的文档
        gridEl.innerHTML = paginatedDocs.map(doc => this.createDocumentCard(doc)).join('');

        // 渲染分页控件
        this.renderDocPagination(totalPages);

        // Add event listeners for checkboxes
        document.querySelectorAll('.document-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', () => this.updateDocSelectionUI());
        });

        // Add event listeners for expand/collapse
        document.querySelectorAll('.expand-toggle').forEach(toggle => {
            toggle.addEventListener('click', (e) => {
                const dataType = e.target.dataset.type;

                if (dataType === 'keywords') {
                    // 展开关键词
                    const keywordsDiv = e.target.previousElementSibling;
                    const allKeywords = JSON.parse(keywordsDiv.dataset.keywords);

                    if (!keywordsDiv.classList.contains('expanded')) {
                        // 展开 - 显示所有关键词
                        keywordsDiv.innerHTML = allKeywords.map(kw => `<span class="keyword-tag">${kw}</span>`).join('');
                        keywordsDiv.classList.add('expanded');
                        e.target.textContent = '收起';
                    } else {
                        // 收起 - 只显示前5个
                        keywordsDiv.innerHTML = allKeywords.slice(0, 5).map(kw => `<span class="keyword-tag">${kw}</span>`).join('');
                        keywordsDiv.classList.remove('expanded');
                        e.target.textContent = `展开更多关键词 (+${allKeywords.length - 5})`;
                    }
                } else {
                    // 展开摘要
                    const abstract = e.target.previousElementSibling;
                    abstract.classList.toggle('expanded');
                    e.target.textContent = abstract.classList.contains('expanded') ? '收起' : '展开更多';
                }
            });
        });
    }

    createDocumentCard(doc) {
        const title = doc.title || doc.doc_name;
        const abstract = doc.abstract || '暂无摘要';
        const keywords = doc.keywords || [];
        const hasAbstract = abstract && abstract.length > 100;
        const hasMoreKeywords = keywords.length > 5;

        return `
            <div class="document-card" data-doc-name="${doc.doc_name}" style="position: relative; cursor: pointer;" onclick="event.target.tagName !== 'INPUT' && event.target.tagName !== 'BUTTON' && !event.target.classList.contains('expand-toggle') && dataManager.showDocumentDetail('${doc.doc_name}')">
                <input type="checkbox" class="document-checkbox" data-doc-name="${doc.doc_name}" onclick="event.stopPropagation()">
                <div class="document-header">
                    <h3 class="document-title" title="${title}">${title}</h3>
                    <div class="document-meta">
                        📄 ${doc.doc_name} | 🕒 ${new Date(doc.created_at).toLocaleDateString('zh-CN')}
                    </div>
                    ${keywords.length > 0 ? `
                        <div class="document-keywords ${hasMoreKeywords ? '' : 'expanded'}" data-keywords='${JSON.stringify(keywords)}'>
                            ${keywords.slice(0, 5).map(kw => `<span class="keyword-tag">${kw}</span>`).join('')}
                        </div>
                        ${hasMoreKeywords ? '<div class="expand-toggle" data-type="keywords">展开更多关键词 (+' + (keywords.length - 5) + ')</div>' : ''}
                    ` : ''}
                </div>
                <div class="document-body">
                    <div class="document-abstract ${hasAbstract ? '' : 'expanded'}">${abstract}</div>
                    ${hasAbstract ? '<div class="expand-toggle">展开更多</div>' : ''}

                    <div class="data-stats">
                        <div class="data-stat">
                            <span class="stat-label">📋 JSON</span>
                            <span class="stat-value ${doc.has_json ? 'has-data' : 'no-data'}">
                                ${doc.has_json ? doc.json_size_mb.toFixed(2) + ' MB' : '-'}
                            </span>
                        </div>
                        <div class="data-stat">
                            <span class="stat-label">🗄️ Vector DB</span>
                            <span class="stat-value ${doc.has_vector_db ? 'has-data' : 'no-data'}">
                                ${doc.has_vector_db ? doc.vector_db_size_mb.toFixed(2) + ' MB' : '-'}
                            </span>
                        </div>
                        <div class="data-stat">
                            <span class="stat-label">🖼️ Images</span>
                            <span class="stat-value ${doc.has_images ? 'has-data' : 'no-data'}">
                                ${doc.has_images ? doc.images_size_mb.toFixed(2) + ' MB' : '-'}
                            </span>
                        </div>
                        <div class="data-stat">
                            <span class="stat-label">📝 Summary</span>
                            <span class="stat-value ${doc.has_summary ? 'has-data' : 'no-data'}">
                                ${doc.has_summary ? doc.summary_size_mb.toFixed(2) + ' MB' : '-'}
                            </span>
                        </div>
                    </div>
                </div>
                <div class="document-actions">
                    <button class="action-btn" style="background: var(--success-color); color: white;" onclick="event.stopPropagation(); dataManager.startSingleDocChat('${doc.doc_name}')">
                        💬 开始对话
                    </button>
                    <button class="action-btn" style="background: var(--primary-color); color: white;" onclick="event.stopPropagation(); dataManager.showChapterManager('${doc.doc_name}')">
                        📑 章节管理
                    </button>
                    <button class="action-btn action-btn-partial" onclick="event.stopPropagation(); dataManager.showPartialDelete('${doc.doc_name}')">
                        🗑️ 部分删除
                    </button>
                    <button class="action-btn action-btn-delete" onclick="event.stopPropagation(); dataManager.confirmDeleteDocument('${doc.doc_name}')">
                        ❌ 完全删除
                    </button>
                </div>
            </div>
        `;
    }

    filterDocuments(searchTerm) {
        if (!searchTerm.trim()) {
            this.currentDocPage = 1; // 重置分页
            this.renderDocuments();
            return;
        }

        const term = searchTerm.toLowerCase();
        const filtered = this.documents.filter(doc => {
            const title = (doc.title || '').toLowerCase();
            const docName = doc.doc_name.toLowerCase();
            const abstract = (doc.abstract || '').toLowerCase();
            const keywords = (doc.keywords || []).join(' ').toLowerCase();

            return title.includes(term) ||
                   docName.includes(term) ||
                   abstract.includes(term) ||
                   keywords.includes(term);
        });

        this.currentDocPage = 1; // 重置分页
        this.renderDocuments(filtered);
    }

    async loadSessions() {
        const loadingEl = document.getElementById('sessions-loading');
        const gridEl = document.getElementById('sessions-grid');
        const emptyEl = document.getElementById('sessions-empty');

        loadingEl.style.display = 'block';
        gridEl.style.display = 'none';
        emptyEl.style.display = 'none';

        try {
            // Load all sessions from unified API
            const resp = await fetch('/api/v1/sessions/list');
            if (!resp.ok) {
                throw new Error('Failed to fetch sessions');
            }
            const result = await resp.json();
            this.sessions = result.sessions || [];

            loadingEl.style.display = 'none';

            if (this.sessions.length === 0) {
                emptyEl.style.display = 'block';
            } else {
                gridEl.style.display = 'grid';
                this.renderSessions();
            }
        } catch (error) {
            console.error('Error loading sessions:', error);
            loadingEl.style.display = 'none';
            this.showError('加载会话失败: ' + error.message);
        }
    }

    async loadSessionStats() {
        try {
            const response = await fetch('/api/v1/data/sessions/stats');
            if (!response.ok) throw new Error('Failed to fetch session stats');

            this.sessionStats = await response.json();
            this.renderSessionStats();
        } catch (error) {
            console.error('Error loading session stats:', error);
        }
    }

    renderSessionStats() {
        if (!this.sessionStats) return;

        document.getElementById('session-total').textContent = this.sessionStats.total_sessions || 0;
        document.getElementById('session-single').textContent = this.sessionStats.by_mode?.single || 0;
        document.getElementById('session-cross').textContent = this.sessionStats.by_mode?.cross || 0;
        document.getElementById('session-manual').textContent = this.sessionStats.by_mode?.manual || 0;
    }

    renderSessions(filteredSessions = null) {
        const gridEl = document.getElementById('sessions-grid');
        const sessions = filteredSessions !== null ? filteredSessions : this.sessions;

        // 保存过滤后的会话列表（用于分页）
        this.filteredSessions = sessions;

        // 计算分页
        const totalPages = Math.ceil(sessions.length / this.itemsPerPage);
        const startIndex = (this.currentSessionPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const paginatedSessions = sessions.slice(startIndex, endIndex);

        // 渲染当前页的会话
        gridEl.innerHTML = paginatedSessions.map(session => this.createSessionCard(session)).join('');

        // 渲染分页控件
        this.renderSessionPagination(totalPages);

        // Add event listeners for checkboxes
        document.querySelectorAll('.session-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', () => this.updateSelectionUI());
        });

        // Add event listeners for session docs expand/collapse
        document.querySelectorAll('.session-docs-toggle').forEach(toggle => {
            toggle.addEventListener('click', (e) => {
                const sessionId = e.target.dataset.sessionId;
                const allDocs = JSON.parse(e.target.dataset.allDocs);
                const docsDiv = document.getElementById(`docs-${sessionId}`);

                if (!docsDiv.classList.contains('expanded')) {
                    // 展开 - 显示所有文档
                    docsDiv.innerHTML = `📄 ${allDocs.join(', ')}`;
                    docsDiv.classList.add('expanded');
                    e.target.textContent = '收起';
                } else {
                    // 收起 - 只显示前3个
                    docsDiv.innerHTML = `📄 ${allDocs.slice(0, 3).join(', ')}`;
                    docsDiv.classList.remove('expanded');
                    e.target.textContent = `展开更多文档 (+${allDocs.length - 3})`;
                }
            });
        });
    }

    renderSessionDocInfo(session) {
        if (session.mode === 'single') {
            // 单文档模式
            return `<div class="session-info">📄 ${session.doc_name || '未知文档'}</div>`;
        } else if (session.mode === 'cross') {
            // 跨文档模式（智能选择）
            return `<div class="session-info">📄 跨文档智能对话</div>`;
        } else if (session.mode === 'manual' && session.selected_docs) {
            // 手动选择模式 - 显示文档列表
            const docs = session.selected_docs;
            const maxDisplay = 3;

            if (docs.length <= maxDisplay) {
                // 少于等于3个，直接显示
                return `
                    <div class="session-info">
                        📄 ${docs.join(', ')}
                    </div>
                `;
            } else {
                // 多于3个，显示前3个+展开按钮
                const sessionId = session.session_id.replace(/[^a-zA-Z0-9]/g, '_');
                return `
                    <div class="session-info">
                        <div class="session-docs" id="docs-${sessionId}">
                            📄 ${docs.slice(0, maxDisplay).join(', ')}
                        </div>
                        <div class="expand-toggle session-docs-toggle" data-session-id="${sessionId}" data-all-docs='${JSON.stringify(docs)}' style="margin-top: 0.5rem;">
                            展开更多文档 (+${docs.length - maxDisplay})
                        </div>
                    </div>
                `;
            }
        } else {
            return `<div class="session-info">📄 通用对话</div>`;
        }
    }

    createSessionCard(session) {
        const modeLabels = {
            'single': '单文档',
            'cross': '跨文档',
            'manual': '手动选择'
        };

        const createdAt = new Date(session.created_at);
        const updatedAt = new Date(session.updated_at);

        return `
            <div class="session-card" data-session-id="${session.session_id}" data-mode="${session.mode}" style="position: relative; cursor: pointer;" onclick="event.target.tagName !== 'INPUT' && event.target.tagName !== 'BUTTON' && !event.target.classList.contains('session-title') && !event.target.classList.contains('expand-toggle') && dataManager.showSessionDetail('${session.session_id}')">
                <input type="checkbox" class="session-checkbox" data-session-id="${session.session_id}" onclick="event.stopPropagation()">
                <div class="session-header">
                    <div class="session-title-wrapper">
                        <div class="session-title"
                             data-original-title="${session.title}"
                             onclick="event.stopPropagation(); dataManager.startRenameSession('${session.session_id}')">
                            ${session.title}
                        </div>
                    </div>
                    <span class="session-mode">${modeLabels[session.mode] || '对话'}</span>
                </div>
                ${this.renderSessionDocInfo(session)}
                <div class="session-info">
                    🕒 创建: ${createdAt.toLocaleDateString('zh-CN')} ${createdAt.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}
                </div>
                <div class="session-info">
                    🔄 更新: ${updatedAt.toLocaleDateString('zh-CN')} ${updatedAt.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})}
                </div>
                <div class="session-stats">
                    <div class="session-stat">
                        <div class="session-stat-value">${session.message_count || 0}</div>
                        <div class="session-stat-label">消息数</div>
                    </div>
                    <div class="session-stat">
                        <div class="session-stat-value">${session.selected_docs ? session.selected_docs.length : '-'}</div>
                        <div class="session-stat-label">文档数</div>
                    </div>
                </div>
                <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-light);">
                    <button class="btn btn-primary" onclick="event.stopPropagation(); dataManager.continueChat('${session.session_id}')" style="width: 100%; padding: 0.75rem; font-weight: 600;">
                        💬 继续对话
                    </button>
                </div>
            </div>
        `;
    }

    filterSessions(searchTerm) {
        if (!searchTerm.trim()) {
            this.currentSessionPage = 1; // 重置分页
            this.renderSessions();
            return;
        }

        const term = searchTerm.toLowerCase();
        const filtered = this.sessions.filter(session => {
            const title = (session.title || '').toLowerCase();
            const docName = (session.doc_name || '').toLowerCase();

            return title.includes(term) || docName.includes(term);
        });

        this.currentSessionPage = 1; // 重置分页
        this.renderSessions(filtered);
    }

    // ==================== Pagination ====================

    renderDocPagination(totalPages) {
        const paginationEl = document.getElementById('doc-pagination');
        if (!paginationEl) return;

        if (totalPages <= 1) {
            paginationEl.style.display = 'none';
            return;
        }

        paginationEl.style.display = 'flex';

        const currentPage = this.currentDocPage;
        let html = '';

        // 上一页按钮
        html += `
            <button class="pagination-btn" ${currentPage === 1 ? 'disabled' : ''}
                    onclick="dataManager.goToDocPage(${currentPage - 1})">
                ‹ 上一页
            </button>
        `;

        // 页码按钮
        const maxVisible = 5;
        let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
        let endPage = Math.min(totalPages, startPage + maxVisible - 1);

        if (endPage - startPage < maxVisible - 1) {
            startPage = Math.max(1, endPage - maxVisible + 1);
        }

        if (startPage > 1) {
            html += `<button class="pagination-btn" onclick="dataManager.goToDocPage(1)">1</button>`;
            if (startPage > 2) {
                html += `<span class="pagination-ellipsis">...</span>`;
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            html += `
                <button class="pagination-btn ${i === currentPage ? 'active' : ''}"
                        onclick="dataManager.goToDocPage(${i})">
                    ${i}
                </button>
            `;
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                html += `<span class="pagination-ellipsis">...</span>`;
            }
            html += `<button class="pagination-btn" onclick="dataManager.goToDocPage(${totalPages})">${totalPages}</button>`;
        }

        // 下一页按钮
        html += `
            <button class="pagination-btn" ${currentPage === totalPages ? 'disabled' : ''}
                    onclick="dataManager.goToDocPage(${currentPage + 1})">
                下一页 ›
            </button>
        `;

        paginationEl.innerHTML = html;
    }

    renderSessionPagination(totalPages) {
        const paginationEl = document.getElementById('session-pagination');
        if (!paginationEl) return;

        if (totalPages <= 1) {
            paginationEl.style.display = 'none';
            return;
        }

        paginationEl.style.display = 'flex';

        const currentPage = this.currentSessionPage;
        let html = '';

        // 上一页按钮
        html += `
            <button class="pagination-btn" ${currentPage === 1 ? 'disabled' : ''}
                    onclick="dataManager.goToSessionPage(${currentPage - 1})">
                ‹ 上一页
            </button>
        `;

        // 页码按钮
        const maxVisible = 5;
        let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
        let endPage = Math.min(totalPages, startPage + maxVisible - 1);

        if (endPage - startPage < maxVisible - 1) {
            startPage = Math.max(1, endPage - maxVisible + 1);
        }

        if (startPage > 1) {
            html += `<button class="pagination-btn" onclick="dataManager.goToSessionPage(1)">1</button>`;
            if (startPage > 2) {
                html += `<span class="pagination-ellipsis">...</span>`;
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            html += `
                <button class="pagination-btn ${i === currentPage ? 'active' : ''}"
                        onclick="dataManager.goToSessionPage(${i})">
                    ${i}
                </button>
            `;
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                html += `<span class="pagination-ellipsis">...</span>`;
            }
            html += `<button class="pagination-btn" onclick="dataManager.goToSessionPage(${totalPages})">${totalPages}</button>`;
        }

        // 下一页按钮
        html += `
            <button class="pagination-btn" ${currentPage === totalPages ? 'disabled' : ''}
                    onclick="dataManager.goToSessionPage(${currentPage + 1})">
                下一页 ›
            </button>
        `;

        paginationEl.innerHTML = html;
    }

    goToDocPage(page) {
        const totalPages = Math.ceil((this.filteredDocuments || this.documents).length / this.itemsPerPage);
        if (page < 1 || page > totalPages) return;

        this.currentDocPage = page;
        this.renderDocuments(this.filteredDocuments);

        // 滚动到顶部
        document.getElementById('documents-grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    goToSessionPage(page) {
        const totalPages = Math.ceil((this.filteredSessions || this.sessions).length / this.itemsPerPage);
        if (page < 1 || page > totalPages) return;

        this.currentSessionPage = page;
        this.renderSessions(this.filteredSessions);

        // 滚动到顶部
        document.getElementById('sessions-grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    continueChat(sessionId) {
        window.location.href = `/chat?session_id=${encodeURIComponent(sessionId)}`;
    }

    startRenameSession(sessionId) {
        const card = document.querySelector(`[data-session-id="${sessionId}"]`);
        const titleEl = card.querySelector('.session-title');
        const originalTitle = titleEl.dataset.originalTitle;

        // Replace with input
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'session-title-input';
        input.value = originalTitle;

        titleEl.replaceWith(input);
        input.focus();
        input.select();

        // Handle save on blur or Enter
        const saveRename = async () => {
            const newTitle = input.value.trim();

            if (newTitle && newTitle !== originalTitle) {
                try {
                    const response = await fetch(`/api/v1/sessions/${sessionId}/rename`, {
                        method: 'PATCH',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({new_title: newTitle})
                    });

                    if (!response.ok) throw new Error('Failed to rename session');

                    const result = await response.json();

                    // Update in local data
                    const session = this.sessions.find(s => s.session_id === sessionId);
                    if (session) {
                        session.title = newTitle;
                    }

                    // Restore title element with new title
                    const newTitleEl = document.createElement('div');
                    newTitleEl.className = 'session-title';
                    newTitleEl.dataset.originalTitle = newTitle;
                    newTitleEl.textContent = newTitle;
                    newTitleEl.onclick = () => this.startRenameSession(sessionId);
                    input.replaceWith(newTitleEl);

                    this.showSuccess('会话已重命名');
                } catch (error) {
                    console.error('Error renaming session:', error);
                    this.showError('重命名失败: ' + error.message);

                    // Restore original
                    const titleEl = document.createElement('div');
                    titleEl.className = 'session-title';
                    titleEl.dataset.originalTitle = originalTitle;
                    titleEl.textContent = originalTitle;
                    titleEl.onclick = () => this.startRenameSession(sessionId);
                    input.replaceWith(titleEl);
                }
            } else {
                // Restore original
                const titleEl = document.createElement('div');
                titleEl.className = 'session-title';
                titleEl.dataset.originalTitle = originalTitle;
                titleEl.textContent = originalTitle;
                titleEl.onclick = () => this.startRenameSession(sessionId);
                input.replaceWith(titleEl);
            }
        };

        input.addEventListener('blur', saveRename);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();
            } else if (e.key === 'Escape') {
                // Cancel - restore original
                const titleEl = document.createElement('div');
                titleEl.className = 'session-title';
                titleEl.dataset.originalTitle = originalTitle;
                titleEl.textContent = originalTitle;
                titleEl.onclick = () => this.startRenameSession(sessionId, mode);
                input.replaceWith(titleEl);
            }
        });
    }

    confirmDeleteDocument(docName) {
        const doc = this.documents.find(d => d.doc_name === docName);
        const modal = document.getElementById('delete-modal');
        const title = doc?.title || docName;

        document.getElementById('modal-title').textContent = '确认删除文档';
        document.getElementById('modal-message').innerHTML = `
            <p>您确定要完全删除文档 <strong>${title}</strong> 吗？</p>
            <p style="color: var(--text-muted); font-size: 0.875rem;">
                这将删除：JSON 数据、向量数据库、图片、摘要文件和注册表记录
            </p>
            <p style="color: #dc3545; font-weight: 600;">此操作不可恢复！</p>
        `;

        const confirmBtn = document.getElementById('confirm-delete-btn');
        confirmBtn.onclick = () => this.deleteDocument(docName, ['all']);

        modal.style.display = 'flex';
    }

    showPartialDelete(docName) {
        const doc = this.documents.find(d => d.doc_name === docName);
        const title = doc?.title || docName;

        const modal = document.getElementById('delete-modal');
        document.getElementById('modal-title').textContent = '选择要删除的数据';

        // 构建所有数据部分选项（包括不存在的也显示，但禁用）
        const allParts = [
            {value: 'json', label: 'JSON 数据', has: doc.has_json, size: doc.json_size_mb},
            {value: 'vector_db', label: '向量数据库', has: doc.has_vector_db, size: doc.vector_db_size_mb},
            {value: 'images', label: '图片', has: doc.has_images, size: doc.images_size_mb},
            {value: 'summary', label: '摘要文件', has: doc.has_summary, size: doc.summary_size_mb}
        ];

        document.getElementById('modal-message').innerHTML = `
            <p>选择要删除的 <strong>${title}</strong> 数据部分：</p>
            <div style="margin: 1rem 0;">
                ${allParts.map(part => `
                    <label style="display: block; margin: 0.5rem 0; ${!part.has ? 'opacity: 0.5;' : ''}">
                        <input type="checkbox" class="delete-part" value="${part.value}" ${!part.has ? 'disabled' : ''}>
                        ${part.label} ${part.has ? `(${part.size.toFixed(2)} MB)` : '(不存在)'}
                    </label>
                `).join('')}
            </div>
            <p style="color: var(--text-muted); font-size: 0.875rem; margin-top: 1rem;">
                💡 提示：删除后可以重新生成相应的数据
            </p>
        `;

        const confirmBtn = document.getElementById('confirm-delete-btn');
        confirmBtn.onclick = () => {
            const selected = Array.from(document.querySelectorAll('.delete-part:checked'))
                .map(cb => cb.value);

            if (selected.length === 0) {
                this.showError('请至少选择一项要删除的数据');
                return;
            }

            this.deleteDocument(docName, selected);
        };

        modal.style.display = 'flex';
    }

    async deleteDocument(docName, parts) {
        // Close modal immediately for better UX
        this.closeModal();

        // Show processing notification
        const partsText = parts.includes('all') ? '所有数据' : parts.join(', ');
        this.showSuccess(`正在删除 ${docName} (${partsText})...`, 2000);

        // Perform deletion in background
        try {
            const response = await fetch(`/api/v1/data/documents/${docName}/parts`, {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({parts})
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to delete document');
            }

            const result = await response.json();

            // Show success notification
            this.showSuccess(`删除成功，释放空间 ${result.freed_space_mb.toFixed(2)} MB`);

            // Reload data
            await this.loadAllData();
        } catch (error) {
            console.error('Error deleting document:', error);
            this.showError('删除失败: ' + error.message);
        }
    }

    async showSmartCleanup() {
        const days = prompt('清理多少天前的数据？（默认 30 天）', '30');
        if (!days) return;

        const daysNum = parseInt(days);
        if (isNaN(daysNum) || daysNum < 1) {
            this.showError('请输入有效的天数');
            return;
        }

        if (!confirm(`确定要清理 ${daysNum} 天前的所有文档数据吗？此操作不可恢复！`)) {
            return;
        }

        try {
            const response = await fetch(`/api/v1/data/cleanup/smart?days=${daysNum}`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error('Failed to cleanup');

            const result = await response.json();

            this.showSuccess(`清理完成：删除 ${result.count} 个文档，释放 ${result.freed_mb.toFixed(2)} MB 空间`);

            // Reload data
            await this.loadAllData();
        } catch (error) {
            console.error('Error during cleanup:', error);
            this.showError('清理失败: ' + error.message);
        }
    }

    closeModal() {
        document.getElementById('delete-modal').style.display = 'none';
    }

    closeDetailModal() {
        document.getElementById('detail-modal').style.display = 'none';
        // 移除ESC键监听
        document.removeEventListener('keydown', this.handleDetailModalEsc);
    }

    handleDetailModalEsc(e) {
        if (e.key === 'Escape') {
            dataManager.closeDetailModal();
        }
    }

    async showDocumentDetail(docName) {
        try {
            // 从DocumentRegistry获取brief_summary
            const response = await fetch(`/api/v1/data/documents/${encodeURIComponent(docName)}/summary`);

            if (!response.ok) {
                throw new Error('Failed to fetch document summary');
            }

            const data = await response.json();
            const summary = data.brief_summary || '暂无摘要信息';

            // 显示modal
            document.getElementById('detail-modal-title').textContent = `📄 ${docName} - 文档摘要`;

            // 延迟加载 Markdown/LaTeX 库
            try {
                await this.loadMarkdownLibraries();
            } catch (error) {
                console.warn('Failed to load markdown libraries:', error);
                // 即使加载失败，也显示纯文本
                document.getElementById('detail-modal-content').innerHTML = `<pre>${summary}</pre>`;
                document.getElementById('detail-modal').style.display = 'flex';
                document.addEventListener('keydown', this.handleDetailModalEsc);
                return;
            }

            // Markdown渲染
            const htmlContent = marked.parse(summary);

            const contentDiv = document.createElement('div');
            contentDiv.innerHTML = htmlContent;

            // LaTeX/数学公式渲染
            if (typeof renderMathInElement !== 'undefined') {
                renderMathInElement(contentDiv, {
                    delimiters: [
                        {left: '$$', right: '$$', display: true},
                        {left: '$', right: '$', display: false},
                        {left: '\\[', right: '\\]', display: true},
                        {left: '\\(', right: '\\)', display: false}
                    ],
                    throwOnError: false
                });
            }

            document.getElementById('detail-modal-content').innerHTML = '';
            document.getElementById('detail-modal-content').appendChild(contentDiv);
            document.getElementById('detail-modal').style.display = 'flex';

            // 添加ESC键监听
            document.addEventListener('keydown', this.handleDetailModalEsc);
        } catch (error) {
            console.error('Error loading document detail:', error);
            this.showError('加载文档详情失败: ' + error.message);
        }
    }

    async showSessionDetail(sessionId) {
        try {
            // 从session API获取会话历史
            const response = await fetch(`/api/v1/sessions/${sessionId}`);

            if (!response.ok) {
                throw new Error('Failed to fetch session detail');
            }

            const session = await response.json();
            const messages = session.messages || [];

            // 显示modal
            document.getElementById('detail-modal-title').textContent = `💬 ${session.title} - 会话历史`;

            const contentDiv = document.getElementById('detail-modal-content');

            if (messages.length === 0) {
                contentDiv.innerHTML = `
                    <div style="text-align: center; padding: 2rem; color: var(--text-muted);">
                        暂无消息记录
                    </div>
                `;
            } else {
                // 延迟加载 Markdown/LaTeX 库
                try {
                    await this.loadMarkdownLibraries();
                } catch (error) {
                    console.warn('Failed to load markdown libraries:', error);
                    // 即使加载失败，也显示纯文本
                    contentDiv.innerHTML = '';
                    messages.forEach(msg => {
                        const div = document.createElement('div');
                        div.style.marginBottom = '1rem';
                        div.style.padding = '1rem';
                        div.style.background = 'var(--bg-secondary)';
                        div.style.borderRadius = '0.5rem';
                        div.innerHTML = `<strong>${msg.role}:</strong><br><pre style="white-space: pre-wrap;">${msg.content}</pre>`;
                        contentDiv.appendChild(div);
                    });
                    document.getElementById('detail-modal').style.display = 'flex';
                    document.addEventListener('keydown', this.handleDetailModalEsc);
                    return;
                }

                // 清空内容
                contentDiv.innerHTML = '';

                // 为每条消息创建DOM元素
                messages.forEach(msg => {
                    const isUser = msg.role === 'user';
                    const timestamp = msg.timestamp ? new Date(msg.timestamp).toLocaleString('zh-CN') : '';

                    // 创建消息容器
                    const messageWrapper = document.createElement('div');
                    messageWrapper.style.marginBottom = '1.5rem';

                    // 创建消息内容容器
                    const messageContainer = document.createElement('div');
                    messageContainer.style.display = 'flex';
                    messageContainer.style.justifyContent = isUser ? 'flex-end' : 'flex-start';

                    // 创建消息气泡
                    const messageBubble = document.createElement('div');
                    messageBubble.style.cssText = `
                        background: ${isUser ? 'var(--primary-color)' : 'var(--bg-secondary)'};
                        color: ${isUser ? 'white' : 'var(--text-primary)'};
                        padding: 1rem;
                        border-radius: 0.5rem;
                        max-width: 80%;
                        word-break: break-word;
                    `;

                    // 渲染消息内容
                    if (isUser) {
                        // User消息：保持原样，使用pre-wrap
                        messageBubble.style.whiteSpace = 'pre-wrap';
                        messageBubble.textContent = msg.content;
                    } else {
                        // Assistant消息：渲染Markdown和LaTeX
                        const htmlContent = marked.parse(msg.content);
                        messageBubble.innerHTML = htmlContent;

                        // LaTeX/数学公式渲染
                        if (typeof renderMathInElement !== 'undefined') {
                            renderMathInElement(messageBubble, {
                                delimiters: [
                                    {left: '$$', right: '$$', display: true},
                                    {left: '$', right: '$', display: false},
                                    {left: '\\[', right: '\\]', display: true},
                                    {left: '\\(', right: '\\)', display: false}
                                ],
                                throwOnError: false
                            });
                        }
                    }

                    messageContainer.appendChild(messageBubble);
                    messageWrapper.appendChild(messageContainer);

                    // 添加时间戳
                    if (timestamp) {
                        const timestampDiv = document.createElement('div');
                        timestampDiv.style.cssText = `
                            font-size: 0.75rem;
                            color: var(--text-muted);
                            margin-top: 0.25rem;
                            text-align: ${isUser ? 'right' : 'left'};
                        `;
                        timestampDiv.textContent = timestamp;
                        messageWrapper.appendChild(timestampDiv);
                    }

                    contentDiv.appendChild(messageWrapper);
                });
            }

            document.getElementById('detail-modal').style.display = 'flex';

            // 添加ESC键监听
            document.addEventListener('keydown', this.handleDetailModalEsc);
        } catch (error) {
            console.error('Error loading session detail:', error);
            this.showError('加载会话详情失败: ' + error.message);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async refreshDocuments() {
        await this.loadDocuments();
        await this.loadOverview();
        this.showSuccess('文档数据已刷新');
    }

    async refreshSessions() {
        await this.loadSessions();
        await this.loadSessionStats();
        this.renderOverview();  // Update last activity
        this.showSuccess('会话数据已刷新');
    }

    showSuccess(message, duration = 3000) {
        // Simple notification (you can enhance this)
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 2rem;
            right: 2rem;
            background: #28a745;
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 0.5rem;
            box-shadow: var(--shadow-lg);
            z-index: 2000;
            animation: slideInRight 0.3s ease-out;
        `;
        notification.textContent = message.startsWith('✅') ? message : '✅ ' + message;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'slideOutRight 0.3s ease-out';
            setTimeout(() => notification.remove(), 300);
        }, duration);
    }

    showError(message, duration = 5000) {
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 2rem;
            right: 2rem;
            background: #dc3545;
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 0.5rem;
            box-shadow: var(--shadow-lg);
            z-index: 2000;
            animation: slideInRight 0.3s ease-out;
        `;
        notification.textContent = message.startsWith('❌') ? message : '❌ ' + message;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'slideOutRight 0.3s ease-out';
            setTimeout(() => notification.remove(), 300);
        }, duration);
    }

    updateSelectionUI() {
        const checkboxes = document.querySelectorAll('.session-checkbox:checked');
        const count = checkboxes.length;

        // Update button visibility and count
        const deleteBtn = document.getElementById('batch-delete-btn');
        const countSpan = document.getElementById('selected-count');

        if (count > 0) {
            deleteBtn.style.display = 'inline-block';
            countSpan.textContent = count;
        } else {
            deleteBtn.style.display = 'none';
        }

        // Update card styling
        document.querySelectorAll('.session-card').forEach(card => {
            const checkbox = card.querySelector('.session-checkbox');
            if (checkbox && checkbox.checked) {
                card.classList.add('selected');
            } else {
                card.classList.remove('selected');
            }
        });
    }

    toggleSelectAll() {
        const checkboxes = document.querySelectorAll('.session-checkbox');
        const allChecked = Array.from(checkboxes).every(cb => cb.checked);

        checkboxes.forEach(cb => {
            cb.checked = !allChecked;
        });

        this.updateSelectionUI();

        // Update button text
        const selectAllText = document.getElementById('select-all-text');
        selectAllText.textContent = allChecked ? '☑️ 全选' : '⬜ 取消全选';
    }

    async batchDeleteSessions() {
        const checkboxes = document.querySelectorAll('.session-checkbox:checked');
        const sessionIds = Array.from(checkboxes).map(cb => cb.dataset.sessionId);

        if (sessionIds.length === 0) {
            this.showError('请先选择要删除的会话');
            return;
        }

        const confirm = window.confirm(`确定要删除 ${sessionIds.length} 个会话吗？此操作不可恢复！`);
        if (!confirm) return;

        let successCount = 0;
        let failCount = 0;

        for (const sessionId of sessionIds) {
            try {
                const response = await fetch(`/api/v1/sessions/${sessionId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    successCount++;
                } else {
                    failCount++;
                }
            } catch (error) {
                console.error('Error deleting session:', error);
                failCount++;
            }
        }

        if (successCount > 0) {
            this.showSuccess(`成功删除 ${successCount} 个会话`);
        }

        if (failCount > 0) {
            this.showError(`删除失败 ${failCount} 个会话`);
        }

        // Reload sessions
        await this.loadSessions();
        await this.loadSessionStats();

        // Reset selection UI
        document.getElementById('select-all-text').textContent = '☑️ 全选';
        this.updateSelectionUI();
    }

    updateDocSelectionUI() {
        const checkboxes = document.querySelectorAll('.document-checkbox:checked');
        const count = checkboxes.length;

        // Update button visibility and count
        const deleteBtn = document.getElementById('doc-batch-delete-btn');
        const chatBtn = document.getElementById('doc-batch-chat-btn');
        const countSpan = document.getElementById('doc-selected-count');
        const chatCountSpan = document.getElementById('doc-chat-count');

        if (count > 0) {
            deleteBtn.style.display = 'inline-block';
            countSpan.textContent = count;

            if (chatBtn && chatCountSpan) {
                chatBtn.style.display = 'inline-block';
                chatCountSpan.textContent = count;
            }
        } else {
            deleteBtn.style.display = 'none';
            if (chatBtn) {
                chatBtn.style.display = 'none';
            }
        }

        // Update card styling
        document.querySelectorAll('.document-card').forEach(card => {
            const checkbox = card.querySelector('.document-checkbox');
            if (checkbox && checkbox.checked) {
                card.classList.add('selected');
            } else {
                card.classList.remove('selected');
            }
        });
    }

    toggleDocSelectAll() {
        const checkboxes = document.querySelectorAll('.document-checkbox');
        const allChecked = Array.from(checkboxes).every(cb => cb.checked);

        checkboxes.forEach(cb => {
            cb.checked = !allChecked;
        });

        this.updateDocSelectionUI();

        // Update button text
        const selectAllText = document.getElementById('doc-select-all-text');
        selectAllText.textContent = allChecked ? '☑️ 全选' : '⬜ 取消全选';
    }

    async batchDeleteDocuments() {
        const checkboxes = document.querySelectorAll('.document-checkbox:checked');
        const docNames = Array.from(checkboxes).map(cb => cb.dataset.docName);

        if (docNames.length === 0) {
            this.showError('请先选择要删除的文档');
            return;
        }

        const confirm = window.confirm(
            `确定要完全删除 ${docNames.length} 个文档吗？\n\n这将删除：JSON 数据、向量数据库、图片、摘要文件和注册表记录\n\n此操作不可恢复！`
        );
        if (!confirm) return;

        try {
            const response = await fetch('/api/v1/data/documents', {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({doc_names: docNames})
            });

            if (!response.ok) throw new Error('Failed to batch delete documents');

            const result = await response.json();

            if (result.success > 0) {
                this.showSuccess(
                    `成功删除 ${result.success} 个文档，释放 ${result.total_freed_mb.toFixed(2)} MB 空间`
                );
            }

            if (result.failed > 0) {
                this.showError(`删除失败 ${result.failed} 个文档`);
            }

            // Reload data
            await this.loadAllData();

            // Reset selection UI
            document.getElementById('doc-select-all-text').textContent = '☑️ 全选';
            this.updateDocSelectionUI();
        } catch (error) {
            console.error('Error batch deleting documents:', error);
            this.showError('批量删除失败: ' + error.message);
        }
    }

    // ==================== Pending PDFs Management ====================

    async loadPendingPdfs() {
        try {
            const response = await fetch('/api/v1/data/documents/pending');
            if (!response.ok) throw new Error('Failed to fetch pending PDFs');

            this.pendingPdfs = await response.json();
            this.renderPendingPdfs();
            this.renderOverview(); // Update counts
        } catch (error) {
            console.error('Error loading pending PDFs:', error);
            this.pendingPdfs = [];
        }
    }

    renderPendingPdfs() {
        const section = document.getElementById('pending-section');
        const countText = document.getElementById('pending-count-text');
        const pendingList = document.getElementById('pending-list');
        const emptyState = document.getElementById('pending-empty');

        const count = this.pendingPdfs.length;
        countText.textContent = `${count} 个文件待索引`;

        if (count > 0) {
            section.style.display = 'block';
            emptyState.style.display = 'none';
            pendingList.style.display = 'grid';

            pendingList.innerHTML = this.pendingPdfs.map(pdf => `
                <div class="pending-pdf-item" style="background: var(--bg-secondary); padding: 1rem; border-radius: 0.5rem; display: flex; justify-content: space-between; align-items: center; position: relative;">
                    <input type="checkbox" class="pending-checkbox" data-filename="${pdf.filename}" style="position: absolute; top: 1rem; left: 1rem; width: 18px; height: 18px; cursor: pointer;">
                    <div style="flex: 1; margin-left: 2rem;">
                        <div style="font-weight: 600; margin-bottom: 0.25rem;">📄 ${pdf.filename}</div>
                        <div style="font-size: 0.875rem; color: var(--text-muted);">
                            ${pdf.size_mb.toFixed(2)} MB | ${new Date(pdf.created_at).toLocaleDateString('zh-CN')}
                        </div>
                    </div>
                    <button class="btn btn-primary" onclick="dataManager.indexPdf('${pdf.filename}')" style="margin-left: 1rem;">
                        🔄 索引
                    </button>
                </div>
            `).join('');

            // Add event listeners for checkboxes
            document.querySelectorAll('.pending-checkbox').forEach(checkbox => {
                checkbox.addEventListener('change', () => this.updatePendingSelectionUI());
            });
        } else if (this.overview && this.overview.total_documents > 0) {
            // 有已索引文档但没有待索引的
            section.style.display = 'none';
        } else {
            // 完全没有文档
            section.style.display = 'none';
        }
    }

    togglePendingSection() {
        const content = document.getElementById('pending-content');
        const icon = document.getElementById('pending-toggle-icon');

        if (content.style.display === 'none') {
            content.style.display = 'block';
            icon.style.transform = 'rotate(180deg)';
        } else {
            content.style.display = 'none';
            icon.style.transform = 'rotate(0deg)';
        }
    }

    async indexPdf(filename) {
        if (!confirm(`确定要索引 "${filename}" 吗？\n\n索引将在后台进行，完成后会通知您。`)) {
            return;
        }

        try {
            const response = await fetch(`/api/v1/data/documents/${encodeURIComponent(filename)}/index`, {
                method: 'POST'
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Index failed');
            }

            const result = await response.json();

            if (result.status === 'started') {
                // 添加到活跃任务
                this.activeTasks.set(result.task_id, {
                    filename: filename,
                    taskId: result.task_id,
                    startTime: Date.now()
                });

                // 开始轮询
                this.startTaskPolling();

                this.showSuccess(`✅ ${filename} 开始索引（后台运行）...`);
            }
        } catch (error) {
            console.error('Error indexing PDF:', error);
            this.showError(`索引失败: ${error.message}`);
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
                        this.showSuccess(`✅ ${taskInfo.filename} 索引完成！`, 5000);
                        this.completedTasks.add(taskId);

                        // 刷新数据（只刷新一次）
                        await this.loadAllData();

                        // 更新pending badge
                        if (typeof updatePendingBadge === 'function') {
                            updatePendingBadge();
                        }
                    }

                    this.activeTasks.delete(taskId);

                } else if (task.status === 'failed') {
                    // 任务失败
                    if (!this.completedTasks.has(taskId)) {
                        this.showError(`❌ ${taskInfo.filename} 索引失败: ${task.error || '未知错误'}`, 7000);
                        this.completedTasks.add(taskId);
                    }

                    this.activeTasks.delete(taskId);
                }
            } catch (error) {
                console.error('检查任务状态失败:', error);
            }
        }
    }

    updatePendingSelectionUI() {
        const checkboxes = document.querySelectorAll('.pending-checkbox:checked');
        const count = checkboxes.length;

        // Update button visibility and count
        const batchIndexBtn = document.getElementById('pending-batch-index-btn');
        const countSpan = document.getElementById('pending-selected-count');

        if (batchIndexBtn && countSpan) {
            if (count > 0) {
                batchIndexBtn.style.display = 'inline-block';
                countSpan.textContent = count;
            } else {
                batchIndexBtn.style.display = 'none';
            }
        }

        // Update item styling
        document.querySelectorAll('.pending-pdf-item').forEach(item => {
            const checkbox = item.querySelector('.pending-checkbox');
            if (checkbox && checkbox.checked) {
                item.style.background = 'rgba(0, 123, 255, 0.1)';
                item.style.border = '2px solid var(--primary-color)';
            } else {
                item.style.background = 'var(--bg-secondary)';
                item.style.border = 'none';
            }
        });
    }

    togglePendingSelectAll() {
        const checkboxes = document.querySelectorAll('.pending-checkbox');
        const allChecked = Array.from(checkboxes).every(cb => cb.checked);

        checkboxes.forEach(cb => {
            cb.checked = !allChecked;
        });

        this.updatePendingSelectionUI();

        // Update button text
        const selectAllText = document.getElementById('pending-select-all-text');
        if (selectAllText) {
            selectAllText.textContent = allChecked ? '☑️ 全选' : '⬜ 取消全选';
        }
    }

    async batchIndexPdfs() {
        const checkboxes = document.querySelectorAll('.pending-checkbox:checked');
        const filenames = Array.from(checkboxes).map(cb => cb.dataset.filename);

        if (filenames.length === 0) {
            this.showError('请先选择要索引的PDF文件');
            return;
        }

        if (!confirm(`确定要批量索引 ${filenames.length} 个PDF文件吗？\n\n所有文件将在后台索引，完成后会通知您。`)) {
            return;
        }

        this.showSuccess(`正在启动 ${filenames.length} 个索引任务...`);

        let startedCount = 0;
        let failedCount = 0;

        for (const filename of filenames) {
            try {
                const response = await fetch(`/api/v1/data/documents/${encodeURIComponent(filename)}/index`, {
                    method: 'POST'
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Start failed');
                }

                const result = await response.json();

                if (result.status === 'started') {
                    // 添加到活跃任务
                    this.activeTasks.set(result.task_id, {
                        filename: filename,
                        taskId: result.task_id,
                        startTime: Date.now()
                    });
                    startedCount++;
                } else {
                    failedCount++;
                }
            } catch (error) {
                console.error(`Error starting index for ${filename}:`, error);
                failedCount++;
            }
        }

        // 开始轮询
        if (startedCount > 0) {
            this.startTaskPolling();
            this.showSuccess(`✅ ${startedCount} 个索引任务已启动（后台运行）`);
        }

        if (failedCount > 0) {
            this.showError(`❌ ${failedCount} 个任务启动失败`);
        }

        // Reset selection UI
        const selectAllText = document.getElementById('pending-select-all-text');
        if (selectAllText) {
            selectAllText.textContent = '☑️ 全选';
        }
        this.updatePendingSelectionUI();

        // 刷新待索引列表
        await this.loadPendingPdfs();
    }

    // ==================== Chapter Management ====================

    showChapterManager(docName) {
        // 跳转到章节管理页面（structure editor）
        window.location.href = `/structure?doc=${encodeURIComponent(docName)}`;
    }

    // ==================== Chat Navigation ====================

    startSingleDocChat(docName) {
        window.location.href = `/chat?doc=${encodeURIComponent(docName)}`;
    }

    startMultiDocChat() {
        const checkboxes = document.querySelectorAll('.document-checkbox:checked');
        const selectedDocs = Array.from(checkboxes).map(cb => cb.dataset.docName);

        if (selectedDocs.length === 0) {
            this.showError('请先选择要对话的文档');
            return;
        }

        const docsParam = encodeURIComponent(JSON.stringify(selectedDocs));
        window.location.href = `/chat?docs=${docsParam}`;
    }
}

// Initialize on page load
const dataManager = new DataManager();
