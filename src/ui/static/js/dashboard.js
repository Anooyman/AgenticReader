/**
 * Dashboard 逻辑
 */

class Dashboard {
    constructor() {
        this.indexedDocs = [];
        this.pendingPdfs = [];
        this.init();
    }

    async init() {
        this.setupEventListeners();
        // 仅在有文档管理 UI 时才加载数据（简化后的主页不需要）
        const hasDocTable = document.getElementById('indexed-tbody');
        if (hasDocTable) {
            await this.loadData();
        }
    }

    setupEventListeners() {
        // Tab 切换 (only if tabs exist)
        const tabs = document.querySelectorAll('.tab');
        if (tabs.length > 0) {
            tabs.forEach(tab => {
                tab.addEventListener('click', (e) => {
                    const tabName = e.target.dataset.tab;
                    this.switchTab(tabName);
                });
            });
        }

        // 模式卡片点击
        const singleCard = document.getElementById('single-mode-card');
        const crossCard = document.getElementById('cross-mode-card');
        const manualCard = document.getElementById('manual-mode-card');

        if (singleCard) {
            singleCard.addEventListener('click', () => {
                if (!singleCard.classList.contains('disabled')) {
                    this.startSingleMode();
                }
            });
        }

        if (crossCard) {
            crossCard.addEventListener('click', () => {
                if (!crossCard.classList.contains('disabled')) {
                    this.startCrossMode();
                }
            });
        }

        if (manualCard) {
            manualCard.addEventListener('click', () => {
                if (!manualCard.classList.contains('disabled')) {
                    this.startManualMode();
                }
            });
        }

        // 刷新按钮 (only if exists)
        const refreshBtn = document.getElementById('refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.loadData();
            });
        }

        // 文件上传 (only if elements exist)
        const uploadZone = document.getElementById('upload-zone');
        const fileInput = document.getElementById('file-input');

        if (uploadZone && fileInput) {
            uploadZone.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', (e) => {
                if (e.target.files[0]) this.uploadFile(e.target.files[0]);
            });

            // 拖拽上传
            uploadZone.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadZone.classList.add('dragging');
            });

            uploadZone.addEventListener('dragleave', () => {
                uploadZone.classList.remove('dragging');
            });

            uploadZone.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadZone.classList.remove('dragging');
                const file = e.dataTransfer.files[0];
                if (file && file.type === 'application/pdf') {
                    this.uploadFile(file);
                }
            });
        }
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab').forEach(t => {
            t.classList.toggle('active', t.dataset.tab === tabName);
        });

        document.querySelectorAll('.tab-content').forEach(c => {
            c.classList.toggle('active', c.id === 'tab-' + tabName);
        });
    }

    async loadData() {
        UIComponents.showLoading('加载数据...');
        try {
            await Promise.all([
                this.loadIndexedDocs(),
                this.loadPendingPdfs()
            ]);
            this.updateStats();
            this.updateModeButtons();
        } catch (error) {
            console.error('加载数据失败:', error);
            Utils.notify('加载数据失败', 'error');
        } finally {
            UIComponents.hideLoading();
        }
    }

    async loadIndexedDocs() {
        this.indexedDocs = await API.documents.list();
        this.renderIndexedDocs();
    }

    async loadPendingPdfs() {
        this.pendingPdfs = await API.documents.getAvailablePdfs();
        this.renderPendingPdfs();
    }

    renderIndexedDocs() {
        const tbody = document.getElementById('indexed-tbody');
        if (!tbody) return; // Element doesn't exist in current page

        if (this.indexedDocs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3"><div class="empty-state"><div class="empty-icon">📭</div><p>暂无已索引文档</p></div></td></tr>';
            return;
        }

        tbody.innerHTML = this.indexedDocs.map(doc => {
            const docType = doc.doc_type ? doc.doc_type.toUpperCase() : 'PDF';
            return '<tr><td>' + doc.doc_name + '</td><td>' + docType + '</td><td><div class="doc-actions"><button class="btn btn-sm btn-primary" onclick="dashboard.startChat(\'' + doc.doc_name + '\')">💬 对话</button><button class="btn btn-sm btn-secondary" onclick="dashboard.manageChapters(\'' + doc.doc_name + '\')">📑 章节</button><button class="btn btn-sm btn-danger" onclick="dashboard.deleteDoc(\'' + doc.doc_name + '\')">🗑️ 删除</button></div></td></tr>';
        }).join('');
    }

    renderPendingPdfs() {
        const tbody = document.getElementById('pending-tbody');
        if (!tbody) return; // Element doesn't exist in current page

        if (this.pendingPdfs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="2"><div class="empty-state"><div class="empty-icon">✅</div><p>所有PDF已索引</p></div></td></tr>';
            return;
        }

        tbody.innerHTML = this.pendingPdfs.map(pdf => {
            return '<tr><td>' + pdf + '</td><td><button class="btn btn-sm btn-primary" onclick="dashboard.indexPdf(\'' + pdf + '\')">⚡ 索引</button></td></tr>';
        }).join('');
    }

    updateStats() {
        const total = this.indexedDocs.length + this.pendingPdfs.length;

        const statTotal = document.getElementById('stat-total');
        const statIndexed = document.getElementById('stat-indexed');
        const statPending = document.getElementById('stat-pending');

        if (statTotal) statTotal.textContent = total;
        if (statIndexed) statIndexed.textContent = this.indexedDocs.length;
        if (statPending) statPending.textContent = this.pendingPdfs.length;
    }

    updateModeButtons() {
        const singleCard = document.getElementById('single-mode-card');
        const crossCard = document.getElementById('cross-mode-card');
        const manualCard = document.getElementById('manual-mode-card');

        if (!singleCard || !crossCard || !manualCard) return; // Elements don't exist

        if (this.indexedDocs.length >= 1) {
            singleCard.classList.remove('disabled');
            crossCard.classList.remove('disabled');
            manualCard.classList.remove('disabled');
        } else {
            singleCard.classList.add('disabled');
            crossCard.classList.add('disabled');
            manualCard.classList.add('disabled');
        }
    }

    startSingleMode() {
        if (this.indexedDocs.length === 0) {
            Utils.notify('请先索引至少一个文档', 'warning');
            return;
        }

        if (this.indexedDocs.length === 1) {
            this.startChat(this.indexedDocs[0].doc_name);
        } else {
            this.showDocSelector();
        }
    }

    startCrossMode() {
        if (this.indexedDocs.length === 0) {
            Utils.notify('请先索引至少一个文档', 'warning');
            return;
        }

        this.showSessionChoice('cross');
    }

    startManualMode() {
        if (this.indexedDocs.length === 0) {
            Utils.notify('请先索引至少一个文档', 'warning');
            return;
        }

        this.showSessionChoice('manual');
    }

    async showSessionChoice(mode) {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';

        const modalContent = document.createElement('div');
        modalContent.className = 'modal-content';

        const header = document.createElement('div');
        header.className = 'modal-header';
        const title = document.createElement('h3');
        title.textContent = mode === 'cross' ? '跨文档智能对话' : '跨文档手动选择';
        header.appendChild(title);
        modalContent.appendChild(header);

        const body = document.createElement('div');
        body.className = 'modal-body';

        // 新会话按钮
        const newSessionBtn = document.createElement('button');
        newSessionBtn.className = 'btn btn-primary';
        newSessionBtn.textContent = '🆕 新会话';
        newSessionBtn.style.cssText = 'width: 100%; margin-bottom: 1rem; padding: 1.5rem; font-size: 1.1rem;';
        newSessionBtn.onclick = () => {
            modal.remove();
            if (mode === 'cross') {
                window.location.href = '/chat';
            } else {
                this.showMultiDocSelector();
            }
        };

        // 历史会话按钮
        const historyBtn = document.createElement('button');
        historyBtn.className = 'btn btn-secondary';
        historyBtn.textContent = '📜 历史会话';
        historyBtn.style.cssText = 'width: 100%; padding: 1.5rem; font-size: 1.1rem;';
        historyBtn.onclick = async () => {
            modal.remove();
            await this.showHistorySessions(mode);
        };

        body.appendChild(newSessionBtn);
        body.appendChild(historyBtn);
        modalContent.appendChild(body);

        const footer = document.createElement('div');
        footer.className = 'modal-footer';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.textContent = '取消';
        cancelBtn.onclick = () => modal.remove();
        footer.appendChild(cancelBtn);

        modalContent.appendChild(footer);

        modal.appendChild(modalContent);
        document.body.appendChild(modal);
    }

    async showHistorySessions(mode) {
        try {
            UIComponents.showLoading('加载历史会话...');

            // 获取所有历史会话
            const result = await API.sessions.list();
            // 按 mode 过滤（用于 dashboard 分类显示）
            const allSessions = result.sessions || [];
            const sessions = allSessions.filter(s => s.mode === mode);

            UIComponents.hideLoading();

            if (sessions.length === 0) {
                Utils.notify('暂无历史会话', 'info');
                return;
            }

            // 显示会话选择模态框
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.style.display = 'flex';

            const modalContent = document.createElement('div');
            modalContent.className = 'modal-content';
            modalContent.style.maxWidth = '600px';

            const header = document.createElement('div');
            header.className = 'modal-header';
            const title = document.createElement('h3');
            title.textContent = '选择历史会话';
            header.appendChild(title);
            modalContent.appendChild(header);

            const body = document.createElement('div');
            body.className = 'modal-body';
            body.style.maxHeight = '60vh';
            body.style.overflowY = 'auto';

            const sessionList = document.createElement('div');
            sessionList.style.margin = '1rem 0';

            sessions.forEach(session => {
                const sessionItem = document.createElement('div');
                sessionItem.style.cssText = 'padding: 1rem; border: 1px solid var(--border-light); border-radius: 0.375rem; margin-bottom: 0.75rem; cursor: pointer; transition: all 0.2s;';

                const titleDiv = document.createElement('div');
                titleDiv.style.cssText = 'font-weight: 600; margin-bottom: 0.5rem;';
                titleDiv.textContent = session.title;

                const infoDiv = document.createElement('div');
                infoDiv.style.cssText = 'font-size: 0.875rem; color: var(--text-muted); display: flex; gap: 1rem; flex-wrap: wrap;';

                const messageCount = document.createElement('span');
                messageCount.textContent = '💬 ' + session.message_count + ' 条消息';

                const updatedAt = document.createElement('span');
                const date = new Date(session.updated_at);
                updatedAt.textContent = '🕒 ' + date.toLocaleString('zh-CN');

                infoDiv.appendChild(messageCount);
                infoDiv.appendChild(updatedAt);

                // 显示文档信息
                if (mode === 'manual' && session.selected_docs) {
                    const docsInfo = document.createElement('span');
                    docsInfo.textContent = '📚 ' + session.selected_docs.length + ' 个文档';
                    infoDiv.appendChild(docsInfo);
                }

                sessionItem.appendChild(titleDiv);
                sessionItem.appendChild(infoDiv);

                sessionItem.onclick = () => {
                    modal.remove();
                    this.loadHistorySession(session.session_id);
                };

                sessionItem.onmouseover = () => {
                    sessionItem.style.background = 'var(--bg-secondary)';
                    sessionItem.style.borderColor = 'var(--primary-color)';
                };
                sessionItem.onmouseout = () => {
                    sessionItem.style.background = 'transparent';
                    sessionItem.style.borderColor = 'var(--border-light)';
                };

                sessionList.appendChild(sessionItem);
            });

            body.appendChild(sessionList);
            modalContent.appendChild(body);

            const footer = document.createElement('div');
            footer.className = 'modal-footer';

            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'btn btn-secondary';
            cancelBtn.textContent = '取消';
            cancelBtn.onclick = () => modal.remove();
            footer.appendChild(cancelBtn);

            modalContent.appendChild(footer);

            modal.appendChild(modalContent);
            document.body.appendChild(modal);

        } catch (error) {
            UIComponents.hideLoading();
            Utils.notify('加载历史会话失败: ' + error.message, 'error');
        }
    }

    loadHistorySession(sessionId) {
        window.location.href = '/chat?session_id=' + encodeURIComponent(sessionId);
    }

    showMultiDocSelector() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';

        const modalContent = document.createElement('div');
        modalContent.className = 'modal-content';

        const header = document.createElement('div');
        header.className = 'modal-header';
        const title = document.createElement('h3');
        title.textContent = '选择文档（可多选）';
        header.appendChild(title);
        modalContent.appendChild(header);

        const body = document.createElement('div');
        body.className = 'modal-body';

        const selectedDocs = new Set();

        // 添加全选按钮
        const selectAllDiv = document.createElement('div');
        selectAllDiv.style.cssText = 'margin-bottom: 1rem; padding: 0.75rem; background: var(--bg-secondary); border-radius: 0.375rem;';
        const selectAllCheckbox = document.createElement('input');
        selectAllCheckbox.type = 'checkbox';
        selectAllCheckbox.id = 'select-all';
        selectAllCheckbox.style.cssText = 'margin-right: 0.5rem; cursor: pointer;';
        const selectAllLabel = document.createElement('label');
        selectAllLabel.htmlFor = 'select-all';
        selectAllLabel.textContent = '全选';
        selectAllLabel.style.cssText = 'cursor: pointer; font-weight: 600;';
        selectAllDiv.appendChild(selectAllCheckbox);
        selectAllDiv.appendChild(selectAllLabel);
        body.appendChild(selectAllDiv);

        const docList = document.createElement('div');
        docList.style.margin = '1rem 0';

        this.indexedDocs.forEach(doc => {
            const docItem = document.createElement('div');
            docItem.style.cssText = 'padding: 0.75rem; border: 1px solid var(--border-light); border-radius: 0.375rem; margin-bottom: 0.5rem; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; gap: 0.5rem;';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = doc.doc_name;
            checkbox.className = 'doc-checkbox';
            checkbox.style.cursor = 'pointer';

            const label = document.createElement('label');
            label.style.cssText = 'cursor: pointer; flex: 1;';
            label.innerHTML = '<div style="font-weight: 600;">' + doc.doc_name + '</div>' +
                             '<div style="font-size: 0.875rem; color: var(--text-muted);">' +
                             (doc.brief_summary || '无摘要').substring(0, 60) + '...</div>';

            docItem.appendChild(checkbox);
            docItem.appendChild(label);

            docItem.onclick = (e) => {
                if (e.target !== checkbox) {
                    checkbox.checked = !checkbox.checked;
                }
                if (checkbox.checked) {
                    selectedDocs.add(doc.doc_name);
                    docItem.style.background = 'var(--bg-secondary)';
                    docItem.style.borderColor = 'var(--primary-color)';
                } else {
                    selectedDocs.delete(doc.doc_name);
                    docItem.style.background = 'transparent';
                    docItem.style.borderColor = 'var(--border-light)';
                }
                updateSelectAllCheckbox();
            };

            docList.appendChild(docItem);
        });

        body.appendChild(docList);
        modalContent.appendChild(body);

        // 全选功能
        const updateSelectAllCheckbox = () => {
            const allCheckboxes = docList.querySelectorAll('.doc-checkbox');
            const checkedCount = Array.from(allCheckboxes).filter(cb => cb.checked).length;
            selectAllCheckbox.checked = checkedCount === allCheckboxes.length && allCheckboxes.length > 0;
        };

        selectAllCheckbox.onclick = (e) => {
            const allCheckboxes = docList.querySelectorAll('.doc-checkbox');
            allCheckboxes.forEach(cb => {
                cb.checked = e.target.checked;
                const docItem = cb.parentElement;
                if (cb.checked) {
                    selectedDocs.add(cb.value);
                    docItem.style.background = 'var(--bg-secondary)';
                    docItem.style.borderColor = 'var(--primary-color)';
                } else {
                    selectedDocs.delete(cb.value);
                    docItem.style.background = 'transparent';
                    docItem.style.borderColor = 'var(--border-light)';
                }
            });
        };

        const footer = document.createElement('div');
        footer.className = 'modal-footer';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.textContent = '取消';
        cancelBtn.onclick = () => modal.remove();

        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'btn btn-primary';
        confirmBtn.textContent = '确定';
        confirmBtn.onclick = () => {
            if (selectedDocs.size === 0) {
                Utils.notify('请至少选择一个文档', 'warning');
                return;
            }
            const docsArray = Array.from(selectedDocs);
            modal.remove();
            this.startChatWithDocs(docsArray);
        };

        footer.appendChild(cancelBtn);
        footer.appendChild(confirmBtn);
        modalContent.appendChild(footer);

        modal.appendChild(modalContent);
        document.body.appendChild(modal);
    }

    startChatWithDocs(selectedDocs) {
        const docsParam = encodeURIComponent(JSON.stringify(selectedDocs));
        window.location.href = '/chat?docs=' + docsParam;
    }

    showDocSelector() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';

        const modalContent = document.createElement('div');
        modalContent.className = 'modal-content';

        const header = document.createElement('div');
        header.className = 'modal-header';
        const title = document.createElement('h3');
        title.textContent = '选择文档';
        header.appendChild(title);
        modalContent.appendChild(header);

        const body = document.createElement('div');
        body.className = 'modal-body';

        const docList = document.createElement('div');
        docList.style.margin = '1rem 0';

        this.indexedDocs.forEach(doc => {
            const docItem = document.createElement('div');
            docItem.style.cssText = 'padding: 0.75rem; border: 1px solid var(--border-light); border-radius: 0.375rem; margin-bottom: 0.5rem; cursor: pointer; transition: all 0.2s;';
            docItem.innerHTML = '<div style="font-weight: 600;">' + doc.doc_name + '</div>' +
                               '<div style="font-size: 0.875rem; color: var(--text-muted);">' +
                               (doc.brief_summary || '无摘要').substring(0, 60) + '...</div>';
            docItem.onclick = () => {
                this.selectDocument(doc.doc_name);
                modal.remove();
            };
            docItem.onmouseover = () => docItem.style.background = 'var(--bg-secondary)';
            docItem.onmouseout = () => docItem.style.background = 'transparent';
            docList.appendChild(docItem);
        });

        body.appendChild(docList);
        modalContent.appendChild(body);

        const footer = document.createElement('div');
        footer.className = 'modal-footer';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-secondary';
        cancelBtn.textContent = '取消';
        cancelBtn.onclick = () => modal.remove();
        footer.appendChild(cancelBtn);

        modalContent.appendChild(footer);

        modal.appendChild(modalContent);
        document.body.appendChild(modal);
    }

    selectDocument(docName) {
        this.startChat(docName);
    }

    startChat(docName) {
        window.location.href = '/chat?doc=' + encodeURIComponent(docName);
    }

    async uploadFile(file) {
        const statusDiv = document.getElementById('upload-status');
        statusDiv.innerHTML = '⏳ 正在上传...';

        try {
            await API.documents.upload(file);
            Utils.notify('上传成功', 'success');
            statusDiv.innerHTML = '✅ 上传成功';

            // 自动索引
            await this.indexPdf(file.name);
        } catch (error) {
            statusDiv.innerHTML = '❌ ' + error.message;
            Utils.notify('上传失败: ' + error.message, 'error');
        }
    }

    async indexPdf(pdfName) {
        UIComponents.showLoading('正在索引...');

        try {
            await API.documents.index(pdfName);
            Utils.notify('索引已启动，请稍候...', 'info');

            // 定时检查索引状态
            const checkInterval = setInterval(async () => {
                await this.loadIndexedDocs();
                await this.loadPendingPdfs();
                this.updateStats();
                this.updateModeButtons();

                const cleanName = pdfName.replace('.pdf', '');
                const doc = this.indexedDocs.find(d => d.doc_name === pdfName || d.doc_name === cleanName);
                if (doc) {
                    clearInterval(checkInterval);
                    UIComponents.hideLoading();
                    Utils.notify('索引完成！', 'success');
                }
            }, 5000);

            // 超时
            setTimeout(() => {
                clearInterval(checkInterval);
                UIComponents.hideLoading();
            }, 300000);

        } catch (error) {
            UIComponents.hideLoading();
            Utils.notify('索引失败: ' + error.message, 'error');
        }
    }

    async deleteDoc(docName) {
        const confirmed = await UIComponents.confirm('确定要删除文档 "' + docName + '" 吗？', '确认删除');
        if (!confirmed) return;

        UIComponents.showLoading('正在删除...');
        try {
            await API.documents.delete(docName);
            Utils.notify('删除成功', 'success');
            await this.loadData();
        } catch (error) {
            Utils.notify('删除失败: ' + error.message, 'error');
        } finally {
            UIComponents.hideLoading();
        }
    }

    // 章节管理相关方法
    async manageChapters(docName) {
        this.currentDoc = docName;
        this.structure = null;
        this.totalPages = 0;
        this.currentPage = 1;
        this.pdfDoc = null;
        this.pdfScale = 1.5;
        this.editingChapterIndex = null;
        this.selectedChapters = new Set();

        // 显示模态框
        document.getElementById('chapter-modal').style.display = 'flex';
        document.getElementById('chapter-doc-name').textContent = docName;

        // 加载章节数据
        await this.loadChapters(docName);

        // 加载PDF文件
        await this.loadPdfFile(docName);
    }

    async loadChapters(docName) {
        try {
            UIComponents.showLoading('加载章节数据...');

            const response = await fetch('/api/v1/structure/' + docName);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.detail || '加载章节失败');
            }

            this.structure = data.agenda_dict;
            this.totalPages = data.total_pages;

            // 显示文档信息
            document.getElementById('chapter-total-pages').textContent = this.totalPages;
            document.getElementById('chapter-total-chapters').textContent = data.total_chapters;

            // 渲染章节列表
            this.renderChapters();

            UIComponents.hideLoading();
        } catch (error) {
            UIComponents.hideLoading();
            Utils.notify('加载章节失败: ' + error.message, 'error');
        }
    }

    renderChapters() {
        const container = document.getElementById('chapters-list');
        container.innerHTML = '';

        const chapters = Object.entries(this.structure);

        if (chapters.length === 0) {
            container.innerHTML = '<p style="text-align: center; color: var(--text-muted);">暂无章节</p>';
            return;
        }

        chapters.forEach(([title, pages], index) => {
            const isSelected = this.selectedChapters.has(index);
            const chapterItem = document.createElement('div');
            chapterItem.className = 'chapter-item' + (isSelected ? ' selected' : '');
            chapterItem.innerHTML =
                '<div class="chapter-header">' +
                    '<div style="display: flex; align-items: center; gap: 0.5rem; flex: 1; cursor: pointer;" onclick="dashboard.showChapterPage(' + index + ')">' +
                        '<input type="checkbox" class="chapter-checkbox" data-index="' + index + '" ' +
                        (isSelected ? 'checked' : '') +
                        ' onclick="event.stopPropagation(); dashboard.toggleChapterSelection(' + index + ')" style="cursor: pointer;">' +
                        '<span class="chapter-title">' + title + '</span>' +
                    '</div>' +
                    '<div class="chapter-actions">' +
                        '<button class="btn btn-sm btn-secondary" onclick="dashboard.editChapter(' + index + ')">✏️</button>' +
                        '<button class="btn btn-sm btn-danger" onclick="dashboard.deleteChapter(' + index + ')">🗑️</button>' +
                    '</div>' +
                '</div>' +
                '<div class="chapter-pages">页码: ' + this.formatPages(pages) + '</div>';

            container.appendChild(chapterItem);
        });

        // 更新全选状态
        document.getElementById('select-all-chapters').checked =
            this.selectedChapters.size > 0 && this.selectedChapters.size === chapters.length;

        // 显示/隐藏批量删除按钮
        document.getElementById('delete-selected-btn').style.display =
            this.selectedChapters.size > 0 ? 'inline-block' : 'none';
    }

    formatPages(pages) {
        if (!Array.isArray(pages) || pages.length === 0) {
            return '-';
        }

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
                ranges.push(start === end ? start.toString() : start + '-' + end);
                start = sortedPages[i];
                end = sortedPages[i];
            }
        }
        ranges.push(start === end ? start.toString() : start + '-' + end);

        return ranges.join(', ');
    }

    parsePages(pagesStr) {
        const pages = [];
        const parts = pagesStr.split(',').map(p => p.trim());

        for (const part of parts) {
            if (part.includes('-')) {
                const [start, end] = part.split('-').map(p => parseInt(p.trim()));
                if (!isNaN(start) && !isNaN(end) && start <= end) {
                    for (let i = start; i <= end; i++) {
                        if (i >= 1 && i <= this.totalPages && !pages.includes(i)) {
                            pages.push(i);
                        }
                    }
                }
            } else {
                const page = parseInt(part);
                if (!isNaN(page) && page >= 1 && page <= this.totalPages && !pages.includes(page)) {
                    pages.push(page);
                }
            }
        }

        return pages.sort((a, b) => a - b);
    }

    showChapterDialog() {
        this.editingChapterIndex = null;
        document.getElementById('chapter-dialog-title').textContent = '添加章节';
        document.getElementById('chapter-title-input').value = '';
        document.getElementById('chapter-pages-input').value = '';
        document.getElementById('chapter-dialog').style.display = 'flex';
    }

    editChapter(index) {
        const chapters = Object.entries(this.structure);
        const [title, pages] = chapters[index];

        this.editingChapterIndex = index;
        document.getElementById('chapter-dialog-title').textContent = '编辑章节';
        document.getElementById('chapter-title-input').value = title;
        document.getElementById('chapter-pages-input').value = this.formatPages(pages);
        document.getElementById('chapter-dialog').style.display = 'flex';
    }

    saveChapter() {
        const title = document.getElementById('chapter-title-input').value.trim();
        const pagesStr = document.getElementById('chapter-pages-input').value.trim();

        if (!title) {
            Utils.notify('请输入章节标题', 'warning');
            return;
        }

        if (!pagesStr) {
            Utils.notify('请输入页码范围', 'warning');
            return;
        }

        const pages = this.parsePages(pagesStr);

        if (pages.length === 0) {
            Utils.notify('页码范围无效', 'warning');
            return;
        }

        // 检查标题重复
        const chapters = Object.entries(this.structure);
        if (this.editingChapterIndex === null) {
            if (this.structure[title]) {
                Utils.notify('章节标题已存在', 'warning');
                return;
            }
        } else {
            const [oldTitle] = chapters[this.editingChapterIndex];
            if (title !== oldTitle && this.structure[title]) {
                Utils.notify('章节标题已存在', 'warning');
                return;
            }
        }

        // 更新结构
        if (this.editingChapterIndex !== null) {
            const [oldTitle] = chapters[this.editingChapterIndex];
            delete this.structure[oldTitle];
        }

        this.structure[title] = pages;

        // 重新渲染
        this.renderChapters();
        document.getElementById('chapter-dialog').style.display = 'none';

        // 更新章节计数
        document.getElementById('chapter-total-chapters').textContent = Object.keys(this.structure).length;
    }

    async deleteChapter(index) {
        const chapters = Object.entries(this.structure);
        const [title] = chapters[index];

        const confirmed = await UIComponents.confirm('确定要删除章节 "' + title + '" 吗？', '确认删除');
        if (!confirmed) return;

        delete this.structure[title];
        this.renderChapters();

        // 更新章节计数
        document.getElementById('chapter-total-chapters').textContent = Object.keys(this.structure).length;
    }

    async saveStructure() {
        if (!this.currentDoc) return;

        try {
            UIComponents.showLoading('保存结构...');

            const response = await fetch('/api/v1/structure/' + this.currentDoc, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    agenda_dict: this.structure,
                    has_toc: false
                })
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.detail || '保存失败');
            }

            Utils.notify('结构保存成功！点击"重建数据"以应用更改', 'success');
            UIComponents.hideLoading();
        } catch (error) {
            UIComponents.hideLoading();
            Utils.notify('保存失败: ' + error.message, 'error');
        }
    }

    async rebuildData() {
        if (!this.currentDoc) return;

        const confirmed = await UIComponents.confirm(
            '确定要重建文档数据吗？\n\n这将重新生成：\n- 章节数据\n- 章节摘要\n- 向量数据库\n\n重建过程可能需要几分钟。',
            '确认重建'
        );
        if (!confirmed) return;

        try {
            UIComponents.showLoading('重建中，请稍候...');

            const response = await fetch('/api/v1/structure/' + this.currentDoc + '/rebuild', {
                method: 'POST'
            });

            const data = await response.json();

            if (!data.success) {
                throw new Error(data.detail || '重建失败');
            }

            Utils.notify('重建完成！', 'success');
            UIComponents.hideLoading();
        } catch (error) {
            UIComponents.hideLoading();
            Utils.notify('重建失败: ' + error.message, 'error');
        }
    }

    // PDF预览相关方法
    async loadPdfFile(docName) {
        try {
            UIComponents.showLoading('加载PDF...');
            const pdfUrl = '/api/v1/pdf/view/' + docName;
            const loadingTask = pdfjsLib.getDocument(pdfUrl);
            this.pdfDoc = await loadingTask.promise;
            this.totalPages = this.pdfDoc.numPages;

            // 更新页码信息
            document.getElementById('chapter-page-info').textContent = '- / ' + this.totalPages;
            document.getElementById('chapter-page-input').max = this.totalPages;

            // 渲染所有页面
            await this.renderAllPdfPages();

            // 设置滚动监听以更新当前页码
            this.setupPdfScrollListener();

            UIComponents.hideLoading();
        } catch (error) {
            console.error('加载PDF失败:', error);
            UIComponents.hideLoading();
            Utils.notify('加载PDF失败: ' + error.message, 'error');
        }
    }

    async renderAllPdfPages() {
        if (!this.pdfDoc) return;

        const viewer = document.getElementById('chapter-pdf-viewer');
        viewer.innerHTML = '<div id="pdf-pages-container"></div>';
        const container = document.getElementById('pdf-pages-container');

        // 渲染所有页面
        for (let pageNum = 1; pageNum <= this.totalPages; pageNum++) {
            try {
                const page = await this.pdfDoc.getPage(pageNum);
                const viewport = page.getViewport({ scale: this.pdfScale });

                // 创建页面容器
                const pageDiv = document.createElement('div');
                pageDiv.className = 'pdf-page';
                pageDiv.id = 'pdf-page-' + pageNum;
                pageDiv.style.marginBottom = '20px';
                pageDiv.setAttribute('data-page', pageNum);

                // 创建canvas
                const canvas = document.createElement('canvas');
                canvas.height = viewport.height;
                canvas.width = viewport.width;
                canvas.style.boxShadow = '0 0 10px rgba(0,0,0,0.5)';
                canvas.style.display = 'block';

                pageDiv.appendChild(canvas);
                container.appendChild(pageDiv);

                // 渲染页面
                const context = canvas.getContext('2d');
                await page.render({ canvasContext: context, viewport: viewport }).promise;

            } catch (error) {
                console.error('渲染第' + pageNum + '页失败:', error);
            }
        }
    }

    setupPdfScrollListener() {
        const viewer = document.getElementById('chapter-pdf-viewer');
        if (!viewer) return;

        viewer.addEventListener('scroll', () => {
            const pages = viewer.querySelectorAll('.pdf-page');
            let currentPage = 1;

            // 找到当前可见的页面
            for (let i = 0; i < pages.length; i++) {
                const page = pages[i];
                const rect = page.getBoundingClientRect();
                const viewerRect = viewer.getBoundingClientRect();

                // 如果页面顶部在视窗上半部分
                if (rect.top <= viewerRect.top + viewerRect.height / 2 && rect.bottom >= viewerRect.top) {
                    currentPage = i + 1;
                    break;
                }
            }

            this.currentPage = currentPage;
            document.getElementById('chapter-page-info').textContent = currentPage + ' / ' + this.totalPages;
            document.getElementById('chapter-page-input').value = currentPage;
        });
    }

    showChapterPage(index) {
        const chapters = Object.entries(this.structure);
        if (index < 0 || index >= chapters.length) return;

        const [title, pages] = chapters[index];
        if (pages && pages.length > 0) {
            this.scrollToPage(pages[0]);
        }
    }

    scrollToPage(pageNum) {
        const pageElement = document.getElementById('pdf-page-' + pageNum);
        if (pageElement) {
            pageElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    changePage(delta) {
        const newPage = this.currentPage + delta;
        if (newPage >= 1 && newPage <= this.totalPages) {
            this.scrollToPage(newPage);
        }
    }

    jumpToPage() {
        const pageNum = parseInt(document.getElementById('chapter-page-input').value);
        if (pageNum >= 1 && pageNum <= this.totalPages) {
            this.scrollToPage(pageNum);
        }
    }

    async zoomPdf(factor) {
        this.pdfScale *= factor;
        await this.renderAllPdfPages();
        this.setupPdfScrollListener();
    }

    // 多选相关方法
    toggleSelectAll(checked) {
        this.selectedChapters.clear();
        if (checked) {
            const chapters = Object.entries(this.structure);
            chapters.forEach((_, index) => {
                this.selectedChapters.add(index);
            });
        }
        this.renderChapters();
    }

    toggleChapterSelection(index) {
        if (this.selectedChapters.has(index)) {
            this.selectedChapters.delete(index);
        } else {
            this.selectedChapters.add(index);
        }
        this.renderChapters();
    }

    async deleteSelectedChapters() {
        if (this.selectedChapters.size === 0) return;

        const confirmed = await UIComponents.confirm(
            '确定要删除选中的 ' + this.selectedChapters.size + ' 个章节吗？',
            '确认删除'
        );
        if (!confirmed) return;

        // 获取要删除的章节标题
        const chapters = Object.entries(this.structure);
        const toDelete = Array.from(this.selectedChapters).sort((a, b) => b - a);

        toDelete.forEach(index => {
            const [title] = chapters[index];
            delete this.structure[title];
        });

        // 清空选择
        this.selectedChapters.clear();

        // 重新渲染
        this.renderChapters();

        // 更新章节计数
        document.getElementById('chapter-total-chapters').textContent = Object.keys(this.structure).length;

        Utils.notify('已删除 ' + toDelete.length + ' 个章节', 'success');
    }

    closeChapterModal() {
        document.getElementById('chapter-modal').style.display = 'none';
        this.currentDoc = null;
        this.structure = null;
        this.pdfDoc = null;
        this.selectedChapters = new Set();

        // 清空PDF预览区域
        const viewer = document.getElementById('chapter-pdf-viewer');
        if (viewer) {
            viewer.innerHTML = '<p style="color: #fff; text-align: center; padding: 3rem;">点击章节查看对应页面</p>';
        }
    }
}

// 初始化
const dashboard = new Dashboard();
