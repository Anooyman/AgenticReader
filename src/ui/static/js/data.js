/**
 * LLMReader 数据管理页面 JavaScript
 * 管理文档数据、清理缓存文件、监控存储使用情况
 */

class LLMReaderDataApp {
    constructor() {
        this.stats = {
            totalDocuments: 0,
            totalSize: '0 MB',
            chatSessions: 0,
            lastCleanup: '从未'
        };

        this.selectedDocuments = new Set();
        this.confirmationCallback = null;
        this.currentChapterDoc = null;
        this.currentChapters = [];

        // API基础URL配置
        this.apiBase = `${window.location.protocol}//${window.location.host}`;

        this.init();
    }

    getApiUrl(endpoint) {
        return `${this.apiBase}${endpoint}`;
    }

    async init() {
        console.log('🚀 数据管理页面初始化开始');

        this.initTabs();
        this.initEventListeners();
        this.initConfirmationDialog();

        // 加载初始数据
        await this.loadStorageOverview();
        await this.loadDocumentList();

        console.log('✅ 数据管理页面初始化完成');
    }

    /* === 初始化方法 === */

    initTabs() {
        const tabBtns = document.querySelectorAll('.management-tabs .tab-btn');
        const tabContents = document.querySelectorAll('.management-tab-content');

        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.getAttribute('data-tab');

                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                tabContents.forEach(content => {
                    content.classList.remove('active');
                    if (content.id === `${tabId}-tab`) {
                        content.classList.add('active');
                    }
                });

                // 根据标签页加载数据
                switch (tabId) {
                    case 'documents':
                        this.loadDocumentList();
                        break;
                    case 'chapters':
                        this.loadChapterDocumentList();
                        break;
                    case 'cache':
                        this.loadCacheStats();
                        break;
                    case 'chat':
                        this.loadChatStats();
                        break;
                }
            });
        });
    }

    initEventListeners() {
        // 刷新按钮
        document.getElementById('refresh-documents-btn')?.addEventListener('click', () => {
            this.loadDocumentList();
        });

        document.getElementById('refresh-cache-btn')?.addEventListener('click', () => {
            this.loadCacheStats();
        });

        document.getElementById('refresh-chat-btn')?.addEventListener('click', () => {
            this.loadChatStats();
        });

        // 清理按钮
        document.getElementById('cleanup-old-documents-btn')?.addEventListener('click', () => {
            this.confirmAction('清理旧文档', '确定要清理超过30天的旧文档数据吗？此操作不可撤销。', () => {
                this.smartCleanup(30);
            });
        });

        document.getElementById('clear-all-cache-btn')?.addEventListener('click', () => {
            this.confirmAction('清空所有缓存', '确定要清空所有缓存文件吗？这将删除PDF图片、向量数据库和JSON数据。', () => {
                this.clearAllCache();
            });
        });

        // 单独缓存清理
        document.getElementById('clear-pdf-cache-btn')?.addEventListener('click', () => {
            this.confirmAction('清理PDF缓存', '确定要清理PDF图片缓存吗？', () => {
                this.clearCache('pdf_image');
            });
        });

        document.getElementById('clear-vector-cache-btn')?.addEventListener('click', () => {
            this.confirmAction('清理向量数据库', '确定要清理向量数据库缓存吗？', () => {
                this.clearCache('vector_db');
            });
        });

        document.getElementById('clear-json-cache-btn')?.addEventListener('click', () => {
            this.confirmAction('清理JSON缓存', '确定要清理JSON数据缓存吗？', () => {
                this.clearCache('json_data');
            });
        });

        // 聊天数据清理
        document.getElementById('clear-local-sessions-btn')?.addEventListener('click', () => {
            this.confirmAction('清理本地会话', '确定要清理所有本地聊天会话吗？', () => {
                this.clearLocalSessions();
            });
        });

        document.getElementById('export-chat-history-btn')?.addEventListener('click', () => {
            this.exportChatHistory();
        });

        // 批量操作
        document.getElementById('smart-cleanup-btn')?.addEventListener('click', () => {
            this.confirmAction('智能清理', '确定要清理超过30天的数据吗？', () => {
                this.smartCleanup(30);
            });
        });

        document.getElementById('backup-data-btn')?.addEventListener('click', () => {
            this.createBackup();
        });

        document.getElementById('full-reset-btn')?.addEventListener('click', () => {
            this.confirmAction('完全重置', '⚠️ 警告：此操作将删除所有数据，包括文档、聊天历史、缓存等。确定要继续吗？', () => {
                this.fullReset();
            });
        });

        // 章节管理
        document.getElementById('chapter-document-select')?.addEventListener('change', (e) => {
            const docName = e.target.value;
            if (docName) {
                this.loadDocumentChapters(docName);
                // 显示重建按钮和添加章节按钮
                const rebuildBtn = document.getElementById('rebuild-vectordb-btn');
                if (rebuildBtn) rebuildBtn.style.display = 'inline-block';
                const addChapterBtn = document.getElementById('add-chapter-btn');
                if (addChapterBtn) addChapterBtn.style.display = 'inline-block';
            } else {
                this.clearChaptersList();
                // 隐藏重建按钮和添加章节按钮
                const rebuildBtn = document.getElementById('rebuild-vectordb-btn');
                if (rebuildBtn) rebuildBtn.style.display = 'none';
                const addChapterBtn = document.getElementById('add-chapter-btn');
                if (addChapterBtn) addChapterBtn.style.display = 'none';
            }
        });

        document.getElementById('refresh-chapters-btn')?.addEventListener('click', () => {
            const docSelect = document.getElementById('chapter-document-select');
            if (docSelect && docSelect.value) {
                this.loadDocumentChapters(docSelect.value);
            }
        });

        document.getElementById('rebuild-vectordb-btn')?.addEventListener('click', () => {
            const docSelect = document.getElementById('chapter-document-select');
            if (docSelect && docSelect.value) {
                this.confirmAction(
                    '重建向量数据库和摘要',
                    `确定要重建文档 "${docSelect.value}" 的向量数据库和摘要吗？这将根据修改后的章节信息重新生成所有数据。`,
                    () => {
                        this.rebuildDocumentData(docSelect.value);
                    }
                );
            }
        });

        document.getElementById('add-chapter-btn')?.addEventListener('click', () => {
            this.addNewChapter();
        });
    }

    initConfirmationDialog() {
        const dialog = document.getElementById('confirmation-dialog');
        const confirmBtn = document.getElementById('dialog-confirm');
        const cancelBtn = document.getElementById('dialog-cancel');
        const overlay = dialog?.querySelector('.dialog-overlay');

        const closeDialog = () => {
            if (dialog) dialog.style.display = 'none';
            this.confirmationCallback = null;
        };

        confirmBtn?.addEventListener('click', () => {
            if (this.confirmationCallback) {
                this.confirmationCallback();
            }
            closeDialog();
        });

        cancelBtn?.addEventListener('click', closeDialog);
        overlay?.addEventListener('click', closeDialog);
    }

    /* === API调用方法 === */

    async loadStorageOverview() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/data/overview'));
            const result = await response.json();

            if (result.success) {
                const data = result.data;
                document.getElementById('total-documents').textContent = data.total_documents;
                document.getElementById('total-size').textContent = data.total_size;
                document.getElementById('chat-sessions').textContent = data.chat_sessions;
                document.getElementById('last-cleanup').textContent = data.last_cleanup;
            }
        } catch (error) {
            console.error('加载存储概览失败:', error);
            this.showStatus('error', '加载存储概览失败');
        }
    }

    async loadDocumentList() {
        try {
            const listContainer = document.getElementById('document-list');
            if (!listContainer) return;

            listContainer.innerHTML = '<div class="loading-message">正在加载文档列表...</div>';

            const response = await fetch(this.getApiUrl('/api/v1/data/documents'));
            const result = await response.json();

            if (result.success && result.data) {
                this.displayDocumentList(result.data);
            } else {
                listContainer.innerHTML = '<div class="error-message">加载文档列表失败</div>';
            }
        } catch (error) {
            console.error('加载文档列表失败:', error);
            const listContainer = document.getElementById('document-list');
            if (listContainer) {
                listContainer.innerHTML = '<div class="error-message">加载文档列表失败</div>';
            }
        }
    }

    async loadCacheStats() {
        try {
            // 加载三种缓存类型的统计
            const types = ['pdf_image', 'vector_db', 'json_data'];

            for (const type of types) {
                const response = await fetch(this.getApiUrl(`/api/v1/data/cache/${type}`));
                const result = await response.json();

                if (result.success) {
                    const data = result.data;

                    if (type === 'pdf_image') {
                        document.getElementById('pdf-cache-count').textContent = `${data.total_count} 个文件`;
                        document.getElementById('pdf-cache-size').textContent = data.total_size;
                    } else if (type === 'vector_db') {
                        document.getElementById('vector-cache-count').textContent = `${data.total_count} 个文件`;
                        document.getElementById('vector-cache-size').textContent = data.total_size;
                    } else if (type === 'json_data') {
                        document.getElementById('json-cache-count').textContent = `${data.total_count} 个文件`;
                        document.getElementById('json-cache-size').textContent = data.total_size;
                    }
                }
            }
        } catch (error) {
            console.error('加载缓存统计失败:', error);
            this.showStatus('error', '加载缓存统计失败');
        }
    }

    async loadChatStats() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/data/sessions/stats'));
            const result = await response.json();

            if (result.success) {
                const stats = result.data;
                document.getElementById('local-sessions-count').textContent = stats.total_sessions || 0;
                document.getElementById('server-history-count').textContent = stats.total_messages || 0;
                document.getElementById('last-chat-activity').textContent = stats.last_activity || '无记录';
            }
        } catch (error) {
            console.error('加载聊天统计失败:', error);
            this.showStatus('error', '加载聊天统计失败');
        }
    }

    /* === 清理操作 === */

    async clearAllCache() {
        try {
            this.showStatus('info', '正在清空所有缓存...');

            const response = await fetch(this.getApiUrl('/api/v1/data/cache/all'), {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                this.showStatus('success', `所有缓存已清空，删除了 ${result.data.deleted_count} 个项目，释放了 ${result.data.deleted_size}`);
                this.loadStorageOverview();
                this.loadCacheStats();
            } else {
                this.showStatus('error', '清空缓存失败');
            }
        } catch (error) {
            console.error('清空缓存失败:', error);
            this.showStatus('error', '清空缓存失败');
        }
    }

    async clearCache(cacheType) {
        try {
            this.showStatus('info', `正在清理${cacheType}缓存...`);

            const response = await fetch(this.getApiUrl(`/api/v1/data/cache/${cacheType}`), {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                this.showStatus('success', `缓存已清理，删除了 ${result.data.deleted_count} 个项目，释放了 ${result.data.deleted_size}`);
                this.loadStorageOverview();
                this.loadCacheStats();
            } else {
                this.showStatus('error', '清理缓存失败');
            }
        } catch (error) {
            console.error('清理缓存失败:', error);
            this.showStatus('error', '清理缓存失败');
        }
    }

    clearLocalSessions() {
        try {
            // 清理localStorage中的会话数据
            const keys = Object.keys(localStorage);
            const sessionKeys = keys.filter(key =>
                key.startsWith('AgenticReader_') ||
                key.startsWith('llmreader_')
            );

            sessionKeys.forEach(key => localStorage.removeItem(key));

            this.showStatus('success', `本地会话已清理，删除了 ${sessionKeys.length} 个项目`);
            this.loadChatStats();
        } catch (error) {
            console.error('清理本地会话失败:', error);
            this.showStatus('error', '清理本地会话失败');
        }
    }

    /* === 批量操作 === */

    async smartCleanup(days = 30) {
        try {
            this.showStatus('info', '正在执行智能清理...');

            const response = await fetch(this.getApiUrl(`/api/v1/data/cleanup/smart?days=${days}`), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.success) {
                const data = result.data;
                this.showStatus('success', `智能清理完成：删除了 ${data.deleted_count} 个文件，释放了 ${data.total_freed}`);
                this.loadStorageOverview();
                this.loadDocumentList();
            } else {
                this.showStatus('error', '智能清理失败');
            }
        } catch (error) {
            console.error('智能清理失败:', error);
            this.showStatus('error', '智能清理失败');
        }
    }

    async createBackup() {
        try {
            this.showStatus('info', '正在创建数据备份...');

            const response = await fetch(this.getApiUrl('/api/v1/data/backup'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.success) {
                this.showStatus('success', `数据备份已创建: ${result.data.backup_file}`);
            } else {
                this.showStatus('error', '创建备份失败');
            }
        } catch (error) {
            console.error('创建备份失败:', error);
            this.showStatus('error', '创建备份失败');
        }
    }

    async fullReset() {
        try {
            this.showStatus('info', '正在执行完全重置...');

            const response = await fetch(this.getApiUrl('/api/v1/data/reset?confirm=CONFIRM_RESET'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.success) {
                // 同时清理本地存储
                localStorage.clear();

                this.showStatus('success', '完全重置完成，系统已恢复到初始状态');

                setTimeout(() => {
                    this.loadStorageOverview();
                    this.loadDocumentList();
                    this.loadCacheStats();
                    this.loadChatStats();
                }, 2000);
            } else {
                this.showStatus('error', '完全重置失败');
            }
        } catch (error) {
            console.error('完全重置失败:', error);
            this.showStatus('error', '完全重置失败');
        }
    }

    async exportChatHistory() {
        try {
            this.showStatus('info', '正在导出聊天历史...');

            const response = await fetch(this.getApiUrl('/api/v1/sessions/export'));

            if (response.ok) {
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);

                const a = document.createElement('a');
                a.href = url;
                a.download = `chat_history_${new Date().toISOString().split('T')[0]}.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                this.showStatus('success', '聊天历史已导出');
            } else {
                this.showStatus('error', '导出聊天历史失败');
            }
        } catch (error) {
            console.error('导出聊天历史失败:', error);
            this.showStatus('error', '导出聊天历史失败');
        }
    }

    /* === UI辅助方法 === */

    displayDocumentList(documents) {
        const listContainer = document.getElementById('document-list');
        if (!listContainer) return;

        if (!documents || documents.length === 0) {
            listContainer.innerHTML = '<div class="empty-message" style="text-align: center; padding: 40px; color: #999;">📭 暂无处理过的文档</div>';
            return;
        }

        const documentHTML = documents.map(doc => `
            <div class="document-item" style="border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                    <div class="doc-info" style="flex: 1;">
                        <div class="doc-name" style="font-weight: bold; margin-bottom: 8px; font-size: 1.1em;">
                            📄 ${this.escapeHtml(doc.name)}
                        </div>
                        <div class="doc-date" style="font-size: 0.85em; color: #999;">
                            ${doc.modified_time ? '最后修改: ' + new Date(doc.modified_time).toLocaleString('zh-CN') : ''}
                        </div>
                    </div>
                    <div class="doc-main-actions" style="display: flex; gap: 10px; align-items: center;">
                        <input type="checkbox" class="doc-checkbox" data-doc-name="${this.escapeHtml(doc.name)}"
                               style="width: 18px; height: 18px; cursor: pointer;">
                        <button class="btn btn-sm btn-danger" onclick="window.llmReaderDataApp.deleteDocument(['${this.escapeHtml(doc.name)}'])"
                                style="padding: 5px 15px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">
                            🗑️ 完全删除
                        </button>
                    </div>
                </div>

                <!-- 数据详情 -->
                <div class="data-details" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #f0f0f0;">
                    ${this.renderDataDetail(doc, 'JSON数据', 'json', doc.data_details?.json)}
                    ${this.renderDataDetail(doc, '向量数据库', 'vector_db', doc.data_details?.vector_db)}
                    ${this.renderDataDetail(doc, 'PDF图片', 'images', doc.data_details?.images)}
                    ${this.renderDataDetail(doc, '摘要文件', 'summary', doc.data_details?.summary)}
                </div>
            </div>
        `).join('');

        const header = `
            <div style="margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <label style="cursor: pointer;">
                        <input type="checkbox" id="select-all-docs" style="margin-right: 8px;">
                        全选
                    </label>
                </div>
                <button id="delete-selected-btn" class="btn btn-danger" style="padding: 5px 15px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">
                    🗑️ 删除选中项
                </button>
            </div>
        `;

        listContainer.innerHTML = header + documentHTML;

        // 添加全选功能
        document.getElementById('select-all-docs')?.addEventListener('change', (e) => {
            document.querySelectorAll('.doc-checkbox').forEach(cb => {
                cb.checked = e.target.checked;
            });
        });

        // 添加批量删除功能
        document.getElementById('delete-selected-btn')?.addEventListener('click', () => {
            const selected = Array.from(document.querySelectorAll('.doc-checkbox:checked'))
                .map(cb => cb.getAttribute('data-doc-name'));

            if (selected.length === 0) {
                this.showStatus('warning', '请先选择要删除的文档');
                return;
            }

            this.confirmAction('批量删除文档', `确定要删除选中的 ${selected.length} 个文档吗？`, () => {
                this.deleteDocument(selected);
            });
        });
    }

    async deleteDocument(documentNames) {
        try {
            this.showStatus('info', '正在删除文档...');

            const response = await fetch(this.getApiUrl('/api/v1/data/documents'), {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(documentNames)
            });

            const result = await response.json();

            if (result.success) {
                const data = result.data;
                this.showStatus('success', `成功删除 ${data.deleted_count} 个文档`);
                this.loadDocumentList();
                this.loadStorageOverview();
            } else {
                this.showStatus('error', '删除文档失败');
            }
        } catch (error) {
            console.error('删除文档失败:', error);
            this.showStatus('error', '删除文档失败');
        }
    }

    confirmAction(title, message, callback) {
        const dialog = document.getElementById('confirmation-dialog');
        const titleElement = document.getElementById('dialog-title');
        const messageElement = document.getElementById('dialog-message');

        if (titleElement) titleElement.textContent = title;
        if (messageElement) messageElement.textContent = message;
        this.confirmationCallback = callback;

        if (dialog) dialog.style.display = 'block';
    }

    showStatus(type, message) {
        const statusElement = document.getElementById('data-status');
        if (!statusElement) return;

        statusElement.className = `status-message ${type}`;
        statusElement.textContent = message;
        statusElement.style.display = 'block';

        // 自动隐藏消息
        if (type === 'success' || type === 'info') {
            setTimeout(() => {
                statusElement.style.display = 'none';
            }, 5000);
        }
    }

    renderDataDetail(doc, label, type, detail) {
        if (!detail || (detail.size === 0 && type !== 'images')) {
            return `
                <div class="data-detail-item" style="background: #f8f9fa; padding: 10px; border-radius: 4px; opacity: 0.6;">
                    <div style="font-size: 0.85em; color: #666; margin-bottom: 5px;">${label}</div>
                    <div style="font-size: 0.9em; color: #999;">暂无数据</div>
                </div>
            `;
        }

        const hasData = detail.size > 0 || (type === 'images' && detail.count > 0);
        const sizeInfo = type === 'images' && detail.count
            ? `${detail.count} 张图片 (${detail.size_formatted})`
            : detail.size_formatted;

        return `
            <div class="data-detail-item" style="background: #fff; padding: 10px; border: 1px solid #dee2e6; border-radius: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="font-size: 0.85em; color: #666;">${label}</div>
                    ${hasData ? `
                        <button class="btn-delete-part" onclick="window.llmReaderDataApp.deleteDocumentPart('${this.escapeHtml(doc.name)}', '${type}')"
                                style="padding: 2px 8px; font-size: 0.75em; background: #ffc107; color: #000; border: none; border-radius: 3px; cursor: pointer;">
                            🗑️ 删除
                        </button>
                    ` : ''}
                </div>
                <div style="font-weight: bold; color: #28a745;">${sizeInfo}</div>
            </div>
        `;
    }

    async deleteDocumentPart(documentName, dataType) {
        this.confirmAction(
            `删除${dataType}数据`,
            `确定要删除文档"${documentName}"的${dataType}数据吗？`,
            async () => {
                try {
                    this.showStatus('info', `正在删除${dataType}数据...`);

                    const response = await fetch(
                        this.getApiUrl(`/api/v1/data/documents/${encodeURIComponent(documentName)}/parts`),
                        {
                            method: 'DELETE',
                            headers: {
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify([dataType])
                        }
                    );

                    const result = await response.json();

                    if (result.success) {
                        const data = result.data;
                        this.showStatus('success', `成功删除${dataType}数据，释放了 ${data.total_freed}`);
                        this.loadDocumentList();
                        this.loadStorageOverview();
                    } else {
                        this.showStatus('error', '删除失败');
                    }
                } catch (error) {
                    console.error('删除数据失败:', error);
                    this.showStatus('error', '删除数据失败');
                }
            }
        );
    }

    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }

    /* === 章节管理方法 === */

    async loadChapterDocumentList() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/data/documents'));
            const result = await response.json();

            const select = document.getElementById('chapter-document-select');
            if (!select) return;

            if (result.success && result.data && result.data.length > 0) {
                select.innerHTML = '<option value="">选择文档...</option>';
                result.data.forEach(doc => {
                    const option = document.createElement('option');
                    option.value = doc.name;
                    option.textContent = doc.name;
                    select.appendChild(option);
                });
            } else {
                select.innerHTML = '<option value="">暂无文档</option>';
            }
        } catch (error) {
            console.error('加载文档列表失败:', error);
            this.showStatus('error', '加载文档列表失败');
        }
    }

    async loadDocumentChapters(docName) {
        try {
            const container = document.getElementById('chapters-container');
            if (!container) return;

            container.innerHTML = '<div class="loading-message">正在加载章节信息...</div>';

            const response = await fetch(this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(docName)}/chapters`));
            const result = await response.json();

            if (result.success && result.chapters) {
                this.currentChapterDoc = docName;
                this.currentChapters = result.chapters;
                this.displayChapters(result.chapters);
            } else {
                container.innerHTML = '<div class="error-message">加载章节信息失败</div>';
            }
        } catch (error) {
            console.error('加载章节信息失败:', error);
            const container = document.getElementById('chapters-container');
            if (container) {
                container.innerHTML = '<div class="error-message">加载章节信息失败</div>';
            }
        }
    }

    displayChapters(chapters) {
        const container = document.getElementById('chapters-container');
        if (!container) return;

        if (!chapters || chapters.length === 0) {
            container.innerHTML = '<div class="empty-message" style="text-align: center; padding: 40px; color: #999;">📭 该文档暂无章节信息</div>';
            return;
        }

        const chaptersHTML = chapters.map((chapter, index) => `
            <div class="chapter-item" style="border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin-bottom: 15px; background: #fff;">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 15px;">
                    <div class="chapter-info" style="flex: 1;">
                        <div class="chapter-title" style="font-weight: bold; margin-bottom: 8px; font-size: 1.2em; color: #2c3e50;">
                            📖 ${index + 1}. ${this.escapeHtml(chapter.title)}
                        </div>
                        <div class="chapter-meta" style="font-size: 0.9em; color: #7f8c8d;">
                            <span style="margin-right: 15px;">📄 页码范围: ${chapter.start_page} - ${chapter.end_page}</span>
                            <span>📊 共 ${chapter.page_count} 页</span>
                        </div>
                    </div>
                    <div class="chapter-actions" style="display: flex; gap: 10px;">
                        <button class="btn btn-sm btn-primary" onclick="window.llmReaderDataApp.editChapter(${index})"
                                style="padding: 5px 15px; background: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer;">
                            ✏️ 编辑
                        </button>
                        <button class="btn btn-sm btn-danger" onclick="window.llmReaderDataApp.deleteChapter(${index})"
                                style="padding: 5px 15px; background: #e74c3c; color: white; border: none; border-radius: 4px; cursor: pointer;">
                            🗑️ 删除
                        </button>
                        <button class="btn btn-sm btn-info" onclick="window.llmReaderDataApp.viewChapterPages(${index})"
                                style="padding: 5px 15px; background: #16a085; color: white; border: none; border-radius: 4px; cursor: pointer;">
                            👁️ 查看页码
                        </button>
                    </div>
                </div>

                <!-- 页码详情（默认折叠） -->
                <div id="chapter-pages-${index}" class="chapter-pages-detail" style="display: none; margin-top: 15px; padding-top: 15px; border-top: 1px solid #ecf0f1;">
                    <div style="font-size: 0.9em; color: #34495e;">
                        <strong>包含页码:</strong>
                        <div style="margin-top: 8px; padding: 10px; background: #f8f9fa; border-radius: 4px; max-height: 150px; overflow-y: auto;">
                            ${chapter.pages.map(p => `<span style="display: inline-block; margin: 2px 5px; padding: 3px 8px; background: #3498db; color: white; border-radius: 3px; font-size: 0.85em;">${p}</span>`).join('')}
                        </div>
                    </div>
                </div>
            </div>
        `).join('');

        const header = `
            <div style="margin-bottom: 20px; padding: 15px; background: #ecf0f1; border-radius: 8px;">
                <h5 style="margin: 0 0 10px 0; color: #2c3e50;">📚 文档章节概览</h5>
                <div style="display: flex; gap: 20px; font-size: 0.9em; color: #34495e;">
                    <span>📄 文档: <strong>${this.escapeHtml(this.currentChapterDoc)}</strong></span>
                    <span>📖 章节总数: <strong>${chapters.length}</strong></span>
                    <span>📊 总页数: <strong>${chapters.reduce((sum, ch) => sum + ch.page_count, 0)}</strong></span>
                </div>
            </div>
        `;

        container.innerHTML = header + chaptersHTML;
    }

    viewChapterPages(index) {
        const pagesDiv = document.getElementById(`chapter-pages-${index}`);
        if (pagesDiv) {
            const isVisible = pagesDiv.style.display !== 'none';
            pagesDiv.style.display = isVisible ? 'none' : 'block';
        }
    }

    editChapter(index) {
        if (!this.currentChapters || index >= this.currentChapters.length) {
            this.showStatus('error', '章节不存在');
            return;
        }

        const chapter = this.currentChapters[index];
        
        // 创建编辑对话框
        const dialogHTML = `
            <div id="chapter-edit-dialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000;">
                <div style="background: white; padding: 30px; border-radius: 12px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                    <h3 style="margin-top: 0; color: #2c3e50;">✏️ 编辑章节</h3>
                    
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #34495e;">章节标题:</label>
                        <input type="text" id="edit-chapter-title" value="${this.escapeHtml(chapter.title)}" 
                               style="width: 100%; padding: 10px; border: 1px solid #bdc3c7; border-radius: 4px; font-size: 1em;">
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #34495e;">起始页码:</label>
                        <input type="number" id="edit-chapter-start" value="${chapter.start_page}" min="1"
                               style="width: 100%; padding: 10px; border: 1px solid #bdc3c7; border-radius: 4px; font-size: 1em;">
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #34495e;">结束页码:</label>
                        <input type="number" id="edit-chapter-end" value="${chapter.end_page}" min="1"
                               style="width: 100%; padding: 10px; border: 1px solid #bdc3c7; border-radius: 4px; font-size: 1em;">
                    </div>

                    <div style="margin-top: 25px; display: flex; gap: 10px; justify-content: flex-end;">
                        <button onclick="window.llmReaderDataApp.saveChapterEdit(${index})" 
                                style="padding: 10px 25px; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em;">
                            💾 保存
                        </button>
                        <button onclick="window.llmReaderDataApp.cancelChapterEdit()" 
                                style="padding: 10px 25px; background: #95a5a6; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em;">
                            ❌ 取消
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', dialogHTML);
    }

    async saveChapterEdit(index) {
        try {
            const title = document.getElementById('edit-chapter-title')?.value;
            const startPage = parseInt(document.getElementById('edit-chapter-start')?.value);
            const endPage = parseInt(document.getElementById('edit-chapter-end')?.value);

            if (!title || !startPage || !endPage) {
                this.showStatus('error', '请填写所有字段');
                return;
            }

            if (startPage > endPage) {
                this.showStatus('error', '起始页码不能大于结束页码');
                return;
            }

            // 生成页码数组
            const pages = [];
            for (let i = startPage; i <= endPage; i++) {
                pages.push(i);
            }

            this.showStatus('info', '正在保存章节修改...');

            const response = await fetch(
                this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(this.currentChapterDoc)}/chapters/${index}`),
                {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        title: title,
                        pages: pages
                    })
                }
            );

            const result = await response.json();

            if (result.success) {
                this.showStatus('success', '章节修改已保存');
                this.cancelChapterEdit();
                // 重新加载章节列表
                await this.loadDocumentChapters(this.currentChapterDoc);
            } else {
                this.showStatus('error', '保存失败: ' + (result.message || '未知错误'));
            }
        } catch (error) {
            console.error('保存章节失败:', error);
            this.showStatus('error', '保存章节失败');
        }
    }

    cancelChapterEdit() {
        const dialog = document.getElementById('chapter-edit-dialog');
        if (dialog) {
            dialog.remove();
        }
    }

    async deleteChapter(index) {
        if (!this.currentChapters || index >= this.currentChapters.length) {
            this.showStatus('error', '章节不存在');
            return;
        }

        const chapter = this.currentChapters[index];
        
        this.confirmAction(
            '删除章节',
            `确定要删除章节 "${chapter.title}" 吗？\n\n注意：删除后需要重建数据才能生效。`,
            async () => {
                try {
                    this.showStatus('info', '正在删除章节...');

                    const response = await fetch(
                        this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(this.currentChapterDoc)}/chapters/${index}`),
                        {
                            method: 'DELETE'
                        }
                    );

                    const result = await response.json();

                    if (result.success) {
                        this.showStatus('success', '章节已删除，请点击"重建数据"按钮以更新向量数据库');
                        // 重新加载章节列表
                        await this.loadDocumentChapters(this.currentChapterDoc);
                    } else {
                        this.showStatus('error', '删除失败: ' + (result.message || '未知错误'));
                    }
                } catch (error) {
                    console.error('删除章节失败:', error);
                    this.showStatus('error', '删除章节失败');
                }
            }
        );
    }

    addNewChapter() {
        if (!this.currentChapterDoc) {
            this.showStatus('error', '请先选择一个文档');
            return;
        }

        // 创建添加对话框
        const dialogHTML = `
            <div id="chapter-add-dialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000;">
                <div style="background: white; padding: 30px; border-radius: 12px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                    <h3 style="margin-top: 0; color: #2c3e50;">➕ 添加新章节</h3>
                    
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #34495e;">章节标题:</label>
                        <input type="text" id="add-chapter-title" placeholder="请输入章节标题" 
                               style="width: 100%; padding: 10px; border: 1px solid #bdc3c7; border-radius: 4px; font-size: 1em;">
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #34495e;">起始页码:</label>
                        <input type="number" id="add-chapter-start" value="1" min="1"
                               style="width: 100%; padding: 10px; border: 1px solid #bdc3c7; border-radius: 4px; font-size: 1em;">
                    </div>

                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #34495e;">结束页码:</label>
                        <input type="number" id="add-chapter-end" value="1" min="1"
                               style="width: 100%; padding: 10px; border: 1px solid #bdc3c7; border-radius: 4px; font-size: 1em;">
                    </div>

                    <div style="margin-top: 25px; display: flex; gap: 10px; justify-content: flex-end;">
                        <button onclick="window.llmReaderDataApp.saveNewChapter()" 
                                style="padding: 10px 25px; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em;">
                            💾 添加
                        </button>
                        <button onclick="window.llmReaderDataApp.cancelAddChapter()" 
                                style="padding: 10px 25px; background: #95a5a6; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em;">
                            ❌ 取消
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', dialogHTML);
    }

    async saveNewChapter() {
        try {
            const title = document.getElementById('add-chapter-title')?.value;
            const startPage = parseInt(document.getElementById('add-chapter-start')?.value);
            const endPage = parseInt(document.getElementById('add-chapter-end')?.value);

            if (!title || !startPage || !endPage) {
                this.showStatus('error', '请填写所有字段');
                return;
            }

            if (startPage > endPage) {
                this.showStatus('error', '起始页码不能大于结束页码');
                return;
            }

            // 生成页码数组
            const pages = [];
            for (let i = startPage; i <= endPage; i++) {
                pages.push(i);
            }

            this.showStatus('info', '正在添加章节...');

            const response = await fetch(
                this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(this.currentChapterDoc)}/chapters`),
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        title: title,
                        pages: pages
                    })
                }
            );

            const result = await response.json();

            if (result.success) {
                this.showStatus('success', '章节已添加，请点击"重建数据"按钮以更新向量数据库');
                this.cancelAddChapter();
                // 重新加载章节列表
                await this.loadDocumentChapters(this.currentChapterDoc);
            } else {
                this.showStatus('error', '添加失败: ' + (result.message || '未知错误'));
            }
        } catch (error) {
            console.error('添加章节失败:', error);
            this.showStatus('error', '添加章节失败');
        }
    }

    cancelAddChapter() {
        const dialog = document.getElementById('chapter-add-dialog');
        if (dialog) {
            dialog.remove();
        }
    }

    clearChaptersList() {
        const container = document.getElementById('chapters-container');
        if (container) {
            container.innerHTML = '<div class="empty-message" style="text-align: center; padding: 40px; color: #999;">📚 请先选择一个文档查看章节信息</div>';
        }
        this.currentChapterDoc = null;
        this.currentChapters = [];
    }

    async rebuildDocumentData(docName) {
        try {
            // 显示进度覆盖层
            this.showProgressOverlay('🔨 正在重建数据...', '初始化中，请稍候...');
            
            this.showStatus('info', '🔨 正在重建向量数据库和摘要，这可能需要几分钟时间...');

            const response = await fetch(
                this.getApiUrl(`/api/v1/chapters/documents/${encodeURIComponent(docName)}/rebuild`),
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        rebuild_vectordb: true,
                        rebuild_summary: true
                    })
                }
            );

            const result = await response.json();
            
            // 隐藏进度覆盖层
            this.hideProgressOverlay();

            if (result.success) {
                const results = result.results || {};
                let message = '✅ 重建完成！\n';
                
                if (results.vectordb) {
                    if (results.vectordb.success) {
                        message += `\n📊 向量数据库: 处理了 ${results.vectordb.chapters_processed} 个章节，创建了 ${results.vectordb.documents_created} 个文档`;
                    } else {
                        message += `\n❌ 向量数据库重建失败: ${results.vectordb.error}`;
                    }
                }
                
                if (results.summary) {
                    if (results.summary.success) {
                        message += `\n📝 摘要: 已生成到 ${results.summary.output_path}`;
                    } else {
                        message += `\n❌ 摘要重建失败: ${results.summary.error}`;
                    }
                }
                
                this.showStatus('success', message);
                
                // 重新加载章节列表（从新的向量数据库）
                await this.loadDocumentChapters(docName);
            } else {
                this.showStatus('error', '重建失败: ' + (result.message || '未知错误'));
            }
        } catch (error) {
            console.error('重建文档数据失败:', error);
            this.hideProgressOverlay();
            this.showStatus('error', '重建文档数据失败: ' + error.message);
        }
    }

    showProgressOverlay(title, message) {
        // 移除已有的覆盖层
        this.hideProgressOverlay();
        
        const overlayHTML = `
            <div id="rebuild-progress-overlay" style="
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.7); display: flex; align-items: center;
                justify-content: center; z-index: 10001;">
                <div style="
                    background: white; padding: 40px; border-radius: 16px;
                    text-align: center; max-width: 500px; width: 90%;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.3);">
                    <div style="margin-bottom: 25px;">
                        <div class="spinner" style="
                            width: 60px; height: 60px; margin: 0 auto 20px;
                            border: 4px solid #f3f3f3; border-top: 4px solid #3498db;
                            border-radius: 50%; animation: spin 1s linear infinite;"></div>
                        <h3 style="margin: 0 0 15px 0; color: #2c3e50; font-size: 1.5em;">${title}</h3>
                        <p id="progress-message" style="color: #7f8c8d; margin: 0; font-size: 1.1em;">${message}</p>
                    </div>
                    <div style="
                        background: #ecf0f1; border-radius: 8px; padding: 15px;
                        font-size: 0.9em; color: #7f8c8d;">
                        <p style="margin: 0;">⏳ 处理过程可能需要 1-5 分钟</p>
                        <p style="margin: 5px 0 0 0;">📊 正在处理章节内容和生成摘要</p>
                    </div>
                </div>
            </div>
            <style>
                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        `;
        document.body.insertAdjacentHTML('beforeend', overlayHTML);
    }

    hideProgressOverlay() {
        const overlay = document.getElementById('rebuild-progress-overlay');
        if (overlay) {
            overlay.remove();
        }
    }

    updateProgressMessage(message) {
        const msgElement = document.getElementById('progress-message');
        if (msgElement) {
            msgElement.textContent = message;
        }
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 数据管理页面DOM内容已加载');
    setTimeout(() => {
        console.log('🚀 开始初始化数据管理页面应用');
        window.llmReaderDataApp = new LLMReaderDataApp();
    }, 200);
});
