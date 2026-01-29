/**
 * Chat 页面逻辑（带PDF预览）
 */

class ChatApp {
    constructor() {
        this.mode = null;
        this.docName = null;
        this.selectedDocs = null;
        this.sessionId = null;
        this.ws = null;
        this.pdfDoc = null;
        this.currentDocName = null;  // 当前显示的PDF文档名
        this.currentPage = 1;
        this.totalPages = 0;
        // 提高默认缩放以获得更清晰的显示，并考虑设备像素比
        this.scale = 1.5;
        this.devicePixelRatio = window.devicePixelRatio || 2;
        this.isSending = false;  // Track if we're waiting for a response
        this.loadingMessageId = null;  // Track loading indicator
        
        // PDF懒加载相关
        this.renderedPages = new Set();  // 已渲染的页面
        this.renderQueue = [];  // 待渲染队列
        this.isRendering = false;  // 是否正在渲染
        this.initialRenderCount = 3;  // 初始渲染页数
        this.renderBuffer = 2;  // 可见区域前后缓冲页数
        
        this.init();
    }

    async init() {
        this.parseUrlParams();
        this.setupEventListeners();
        await this.initializeChat();
    }

    parseUrlParams() {
        const params = new URLSearchParams(window.location.search);
        this.mode = params.get('mode') || 'single';
        this.docName = params.get('doc') || null;
        this.sessionId = params.get('session_id') || null;

        // Parse selected docs for manual mode
        const docsParam = params.get('docs');
        if (docsParam) {
            try {
                this.selectedDocs = JSON.parse(decodeURIComponent(docsParam));
            } catch (e) {
                console.error('Failed to parse docs parameter:', e);
                this.selectedDocs = null;
            }
        }
    }

    setupEventListeners() {
        // 发送消息
        document.getElementById('send-btn').addEventListener('click', () => this.sendMessage());
        document.getElementById('message-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // 清空对话
        document.getElementById('clear-btn').addEventListener('click', async () => {
            if (await UIComponents.confirm('确定要清空对话吗？')) {
                await this.clearChat();
            }
        });

        // PDF控制
        document.getElementById('toggle-pdf').addEventListener('click', () => {
            document.getElementById('pdf-section').classList.toggle('hidden');
        });

        document.getElementById('close-pdf').addEventListener('click', () => {
            document.getElementById('pdf-section').classList.add('hidden');
        });

        document.getElementById('prev-page').addEventListener('click', () => this.changePage(-1));
        document.getElementById('next-page').addEventListener('click', () => this.changePage(1));
        document.getElementById('zoom-in').addEventListener('click', async () => {
            try {
                await this.zoom(1.2);
            } catch (error) {
                console.error('Zoom error:', error);
            }
        });
        document.getElementById('zoom-out').addEventListener('click', async () => {
            try {
                await this.zoom(0.8);
            } catch (error) {
                console.error('Zoom error:', error);
            }
        });

        document.getElementById('page-num').addEventListener('change', (e) => {
            const page = parseInt(e.target.value);
            if (page >= 1 && page <= this.totalPages) {
                this.scrollToPage(page);
            }
        });

        // PDF选择器
        document.getElementById('pdf-select').addEventListener('change', (e) => {
            const selectedDoc = e.target.value;
            if (selectedDoc) {
                this.loadPdf(selectedDoc);
            }
        });

        // Resizer拖动功能
        this.setupResizer();
    }

    setupResizer() {
        const resizer = document.getElementById('resizer');
        const chatSection = document.querySelector('.chat-section');
        const pdfSection = document.getElementById('pdf-section');

        if (!resizer || !chatSection || !pdfSection) return;

        let isResizing = false;

        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;

            const container = document.querySelector('.chat-container');
            const containerRect = container.getBoundingClientRect();
            const offsetX = e.clientX - containerRect.left;
            const totalWidth = containerRect.width;

            // 计算百分比
            const chatWidthPercent = (offsetX / totalWidth) * 100;

            // 限制最小和最大宽度（百分比）
            if (chatWidthPercent >= 30 && chatWidthPercent <= 70) {
                const pdfWidthPercent = 100 - chatWidthPercent;
                chatSection.style.flex = `0 0 ${chatWidthPercent}%`;
                pdfSection.style.flex = `0 0 ${pdfWidthPercent}%`;
            }
        });

        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            }
        });
    }

    async initializeChat() {
        UIComponents.showLoading('初始化中...');
        try {
            // 初始化聊天服务（传入 sessionId）
            const result = await API.chat.initialize(this.mode, this.docName, this.selectedDocs, this.sessionId);

            // 从返回的会话信息中恢复状态
            if (result.session_id) {
                this.sessionId = result.session_id;
                this.docName = result.doc_name || this.docName;
                this.selectedDocs = result.selected_docs || this.selectedDocs;

                console.log('会话已初始化:', {
                    session_id: this.sessionId,
                    doc_name: this.docName,
                    selected_docs: this.selectedDocs,
                    message_count: result.message_count
                });
            }

            // 更新UI标题
            if (this.mode === 'single') {
                document.getElementById('chat-title').textContent = '单文档对话: ' + this.docName;
                document.getElementById('chat-subtitle').textContent = '深度分析当前文档';
            } else if (this.mode === 'cross') {
                document.getElementById('chat-title').textContent = '跨文档智能对话';
                document.getElementById('chat-subtitle').textContent = '智能检索所有文档';
            } else if (this.mode === 'manual') {
                document.getElementById('chat-title').textContent = '跨文档手动选择模式';
                const docsCount = this.selectedDocs ? this.selectedDocs.length : 0;
                document.getElementById('chat-subtitle').textContent = '已选择 ' + docsCount + ' 个文档';
            }

            // 加载历史消息（如果有）
            if (result.messages && result.messages.length > 0) {
                console.log('加载历史消息:', result.messages.length, '条');
                this.loadHistoryMessages(result.messages);
            }

            // 连接WebSocket
            await this.connectWebSocket();

            // 处理PDF预览
            if (this.mode === 'single' && this.docName) {
                // 单文档模式：直接加载PDF
                await this.loadPdf(this.docName);
            } else if (this.mode === 'manual' && this.selectedDocs && this.selectedDocs.length > 0) {
                // 手动选择模式：显示PDF选择器，填充已选择的文档
                await this.setupPdfSelector(this.selectedDocs);
            } else if (this.mode === 'cross') {
                // 跨文档智能模式：显示PDF选择器，填充所有已索引文档
                await this.setupPdfSelectorForCross();
            }

            Utils.notify('初始化完成', 'success');
        } catch (error) {
            console.error('初始化失败:', error);
            Utils.notify('初始化失败: ' + error.message, 'error');
        } finally {
            UIComponents.hideLoading();
        }
    }

    loadHistoryMessages(messages) {
        const messagesDiv = document.getElementById('messages');

        // 清空欢迎消息
        messagesDiv.innerHTML = '';

        // 渲染历史消息
        messages.forEach(msg => {
            this.addMessage(msg.role, msg.content, msg.references, msg.timestamp);
        });
    }

    async connectWebSocket() {
        return new Promise((resolve, reject) => {
            const wsUrl = 'ws://' + window.location.host + '/ws/chat';
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                document.getElementById('status').textContent = '已连接';
                document.getElementById('message-input').disabled = false;
                document.getElementById('send-btn').disabled = false;
                resolve();
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                document.getElementById('status').textContent = '连接错误';
                reject(error);
            };

            this.ws.onclose = () => {
                console.log('WebSocket closed');
                document.getElementById('status').textContent = '未连接';
            };
        });
    }

    handleMessage(data) {
        if (data.type === 'user_message') {
            this.addMessage('user', data.content, null, data.timestamp);
        } else if (data.type === 'assistant_message') {
            // Remove loading indicator
            this.removeLoadingIndicator();
            // Add assistant response
            this.addMessage('assistant', data.content, data.references, data.timestamp);
            // Re-enable send button
            this.isSending = false;
            document.getElementById('send-btn').disabled = false;
        } else if (data.type === 'error') {
            // Remove loading indicator on error
            this.removeLoadingIndicator();
            this.isSending = false;
            document.getElementById('send-btn').disabled = false;
            Utils.notify('错误: ' + data.content, 'error');
        }
    }

    addMessage(role, content, references = null, messageTimestamp = null) {
        const messagesDiv = document.getElementById('messages');

        // 移除欢迎消息
        const welcome = messagesDiv.querySelector('.welcome');
        if (welcome) welcome.remove();

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-' + role;

        const bubble = document.createElement('div');
        bubble.className = 'bubble';

        if (role === 'assistant') {
            // Markdown渲染
            const htmlContent = marked.parse(content);
            // 处理页码引用
            const processedContent = this.processPageReferences(htmlContent);
            bubble.innerHTML = processedContent;

            // LaTeX/数学公式渲染
            if (typeof renderMathInElement !== 'undefined') {
                renderMathInElement(bubble, {
                    delimiters: [
                        {left: '$$', right: '$$', display: true},
                        {left: '$', right: '$', display: false},
                        {left: '\\[', right: '\\]', display: true},
                        {left: '\\(', right: '\\)', display: false}
                    ],
                    throwOnError: false
                });
            }
        } else {
            bubble.textContent = content;
        }

        // 添加时间戳
        const timestamp = document.createElement('div');
        timestamp.className = 'message-timestamp';

        // 使用传入的时间戳或当前时间（避免 Invalid Date）
        const timeToDisplay = messageTimestamp ? new Date(messageTimestamp) : new Date();
        const isValidTime = !Number.isNaN(timeToDisplay.getTime());
        timestamp.textContent = isValidTime
            ? timeToDisplay.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            })
            : '--';

        // 将时间戳放入气泡内，确保可见
        bubble.appendChild(timestamp);

        messageDiv.appendChild(bubble);
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    processPageReferences(html) {
        // 匹配 [📄 p.5] 或 [📄 文档名.pdf p.5]
        const pattern1 = /\[📄 p\.(\d+)\]/g;
        const pattern2 = /\[📄 (.+?) p\.(\d+)\]/g;

        let result = html.replace(pattern2, (match, docName, page) => {
            return '<a href="#" class="page-ref" onclick="chatApp.jumpToPage(\'' + docName + '\', ' + page + '); return false;">📄 ' + docName + ' p.' + page + '</a>';
        });

        result = result.replace(pattern1, (match, page) => {
            const doc = this.docName || '';
            return '<a href="#" class="page-ref" onclick="chatApp.jumpToPage(\'' + doc + '\', ' + page + '); return false;">📄 p.' + page + '</a>';
        });

        return result;
    }

    async jumpToPage(docName, page) {
        console.log('Jump to:', docName, 'page', page);

        // 如果不是当前文档，需要先加载
        if (!this.pdfDoc || this.currentDocName !== docName) {
            await this.loadPdf(docName);
        }

        if (page >= 1 && page <= this.totalPages) {
            this.scrollToPage(parseInt(page));
            document.getElementById('pdf-section').classList.remove('hidden');
            Utils.notify('已跳转到第 ' + page + ' 页', 'info');
        }
    }

    async setupPdfSelector(docList) {
        const selector = document.getElementById('pdf-selector');
        const select = document.getElementById('pdf-select');

        // 清空选项
        select.innerHTML = '<option value="">-- 请选择文档 --</option>';

        // 添加文档选项
        docList.forEach(doc => {
            const option = document.createElement('option');
            option.value = doc;
            option.textContent = doc;
            select.appendChild(option);
        });

        // 显示选择器
        selector.style.display = 'block';

        // 自动显示PDF区域
        document.getElementById('pdf-section').classList.remove('hidden');

        console.log('PDF选择器已设置，文档数:', docList.length);
    }

    async setupPdfSelectorForCross() {
        try {
            // 获取所有已索引的文档
            const result = await API.documents.list();
            const docNames = result.map(doc => doc.doc_name);

            if (docNames.length > 0) {
                await this.setupPdfSelector(docNames);
            } else {
                console.log('没有可用的文档');
            }
        } catch (error) {
            console.error('获取文档列表失败:', error);
        }
    }

    async loadPdf(docName) {
        UIComponents.showLoading('加载PDF...');
        try {
            const pdfUrl = '/api/v1/pdf/view/' + docName;
            const loadingTask = pdfjsLib.getDocument(pdfUrl);
            this.pdfDoc = await loadingTask.promise;
            this.totalPages = this.pdfDoc.numPages;
            this.currentDocName = docName;  // 保存当前显示的文档名

            document.getElementById('page-total').textContent = '/ ' + this.totalPages;
            document.getElementById('page-num').max = this.totalPages;
            document.getElementById('pdf-toolbar').style.display = 'flex';

            // 更新选择器的值
            const select = document.getElementById('pdf-select');
            if (select && select.style.display !== 'none') {
                select.value = docName;
            }

            // 渲染所有页面（支持滚动查看）
            await this.renderAllPdfPages();

            // 设置滚动监听以更新当前页码
            this.setupPdfScrollListener();

            Utils.notify('PDF加载成功: ' + docName, 'success');
        } catch (error) {
            console.error('加载PDF失败:', error);
            Utils.notify('加载PDF失败: ' + error.message, 'error');
        } finally {
            UIComponents.hideLoading();
        }
    }

    async renderAllPdfPages() {
        if (!this.pdfDoc) return;

        const viewer = document.getElementById('pdf-viewer');
        viewer.innerHTML = '<div id="pdf-pages-container"></div>';
        const container = document.getElementById('pdf-pages-container');

        // 重置渲染状态
        this.renderedPages.clear();
        this.renderQueue = [];

        // 创建所有页面的占位符（快速显示结构）
        await this.createPagePlaceholders(container);

        // 初始渲染前几页
        console.log(`初始渲染前 ${this.initialRenderCount} 页...`);
        for (let i = 1; i <= Math.min(this.initialRenderCount, this.totalPages); i++) {
            await this.renderPage(i);
        }

        // 更新缩放级别显示
        document.getElementById('zoom-level').textContent = Math.round(this.scale * 100) + '%';
        
        console.log('PDF加载完成，剩余页面将在滚动时加载');
    }

    async createPagePlaceholders(container) {
        // 获取第一页来计算尺寸
        const firstPage = await this.pdfDoc.getPage(1);
        const baseViewport = firstPage.getViewport({ scale: this.scale });
        const width = Math.floor(baseViewport.width);
        const height = Math.floor(baseViewport.height);

        // 为所有页面创建占位符
        for (let pageNum = 1; pageNum <= this.totalPages; pageNum++) {
            const pageDiv = document.createElement('div');
            pageDiv.className = 'pdf-page';
            pageDiv.id = 'pdf-page-' + pageNum;
            pageDiv.style.marginBottom = '20px';
            pageDiv.style.minHeight = height + 'px';
            pageDiv.setAttribute('data-page', pageNum);
            pageDiv.setAttribute('data-rendered', 'false');

            // 添加加载占位符
            const placeholder = document.createElement('div');
            placeholder.className = 'pdf-placeholder';
            placeholder.style.width = width + 'px';
            placeholder.style.height = height + 'px';
            placeholder.style.backgroundColor = '#f0f0f0';
            placeholder.style.display = 'flex';
            placeholder.style.alignItems = 'center';
            placeholder.style.justifyContent = 'center';
            placeholder.style.color = '#999';
            placeholder.style.fontSize = '14px';
            placeholder.style.boxShadow = '0 0 10px rgba(0,0,0,0.1)';
            placeholder.textContent = `第 ${pageNum} 页（滚动时加载）`;

            pageDiv.appendChild(placeholder);
            container.appendChild(pageDiv);
        }
    }

    async renderPage(pageNum) {
        // 检查是否已渲染
        if (this.renderedPages.has(pageNum)) return;
        if (!this.pdfDoc) return;

        try {
            const pageDiv = document.getElementById('pdf-page-' + pageNum);
            if (!pageDiv) return;

            // 标记为已渲染（防止重复渲染）
            this.renderedPages.add(pageNum);
            pageDiv.setAttribute('data-rendered', 'true');

            const page = await this.pdfDoc.getPage(pageNum);
            
            // 计算渲染质量因子
            const qualityScale = this.devicePixelRatio * 1.5;
            const baseViewport = page.getViewport({ scale: this.scale });
            const renderViewport = page.getViewport({ scale: this.scale * qualityScale });

            // 创建canvas
            const canvas = document.createElement('canvas');
            canvas.width = renderViewport.width;
            canvas.height = renderViewport.height;
            canvas.style.width = Math.floor(baseViewport.width) + 'px';
            canvas.style.height = Math.floor(baseViewport.height) + 'px';
            canvas.style.boxShadow = '0 0 10px rgba(0,0,0,0.5)';
            canvas.style.display = 'block';

            // 渲染到canvas
            const context = canvas.getContext('2d');
            context.imageSmoothingEnabled = true;
            context.imageSmoothingQuality = 'high';
            
            await page.render({ 
                canvasContext: context, 
                viewport: renderViewport,
                intent: 'display'
            }).promise;

            // 替换占位符
            pageDiv.innerHTML = '';
            pageDiv.appendChild(canvas);

        } catch (error) {
            console.error(`渲染第 ${pageNum} 页失败:`, error);
            this.renderedPages.delete(pageNum);  // 失败时移除标记，允许重试
        }
    }

    getVisiblePages() {
        const viewer = document.getElementById('pdf-viewer');
        if (!viewer) return [];

        const viewerRect = viewer.getBoundingClientRect();
        const pages = viewer.querySelectorAll('.pdf-page');
        const visiblePages = [];

        pages.forEach(page => {
            const rect = page.getBoundingClientRect();
            const pageNum = parseInt(page.getAttribute('data-page'));
            
            // 检查页面是否在可见区域内（包含缓冲区）
            const isVisible = rect.bottom >= viewerRect.top - 1000 && 
                            rect.top <= viewerRect.bottom + 1000;
            
            if (isVisible) {
                visiblePages.push(pageNum);
            }
        });

        return visiblePages;
    }

    async renderVisiblePages() {
        if (this.isRendering) return;
        this.isRendering = true;

        try {
            const visiblePages = this.getVisiblePages();
            
            // 渲染可见页面及其缓冲区
            for (const pageNum of visiblePages) {
                if (!this.renderedPages.has(pageNum)) {
                    await this.renderPage(pageNum);
                }
            }
        } finally {
            this.isRendering = false;
        }
    }

    setupPdfScrollListener() {
        const viewer = document.getElementById('pdf-viewer');
        if (!viewer) return;

        // 使用防抖优化滚动性能
        let scrollTimeout;
        viewer.addEventListener('scroll', () => {
            const pages = viewer.querySelectorAll('.pdf-page');
            let currentPage = 1;

            // 找到当前可见的页面
            for (let i = 0; i < pages.length; i++) {
                const page = pages[i];
                const rect = page.getBoundingClientRect();
                const viewerRect = viewer.getBoundingClientRect();

                if (rect.top <= viewerRect.top + viewerRect.height / 2 && rect.bottom >= viewerRect.top) {
                    currentPage = i + 1;
                    break;
                }
            }

            this.currentPage = currentPage;
            document.getElementById('page-num').value = currentPage;

            // 懒加载：滚动时渲染可见页面
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                this.renderVisiblePages();
            }, 100);  // 100ms防抖
        });

        // 初始触发一次，加载当前可见页面
        setTimeout(() => this.renderVisiblePages(), 200);
    }

    jumpToPage(pageNum) {
        // 滚动到指定页面
        this.scrollToPage(pageNum);
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

    async zoom(factor) {
        this.scale *= factor;
        // 重新渲染（懒加载模式）
        await this.renderAllPdfPages();
        // 重新设置滚动监听
        this.setupPdfScrollListener();
        // 滚动到当前页面
        this.scrollToPage(this.currentPage);
    }

    sendMessage() {
        const input = document.getElementById('message-input');
        const message = input.value.trim();

        // Prevent sending if already waiting for response
        if (this.isSending) return;

        if (!message || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        // Disable send button
        this.isSending = true;
        document.getElementById('send-btn').disabled = true;

        // Send message
        this.ws.send(JSON.stringify({
            type: 'user_message',
            message: message
        }));

        // Clear input
        input.value = '';

        // Show loading indicator
        this.showLoadingIndicator();
    }

    showLoadingIndicator() {
        const messagesDiv = document.getElementById('messages');

        // Remove welcome message if exists
        const welcome = messagesDiv.querySelector('.welcome');
        if (welcome) welcome.remove();

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-assistant';
        messageDiv.id = 'loading-indicator';

        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.innerHTML = '<div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-muted);"><div class="spinner"></div><span>正在思考...</span></div>';

        messageDiv.appendChild(bubble);
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;

        this.loadingMessageId = 'loading-indicator';
    }

    removeLoadingIndicator() {
        if (this.loadingMessageId) {
            const loadingElement = document.getElementById(this.loadingMessageId);
            if (loadingElement) {
                loadingElement.remove();
            }
            this.loadingMessageId = null;
        }
    }

    async clearChat() {
        try {
            await API.chat.clear();
            document.getElementById('messages').innerHTML = '<div class="welcome"><div style="font-size: 4rem; margin-bottom: 1rem;">✨</div><h3>对话已清空</h3><p>可以开始新的对话了</p></div>';
            Utils.notify('对话已清空', 'success');
        } catch (error) {
            Utils.notify('清空失败: ' + error.message, 'error');
        }
    }
}

// 初始化
const chatApp = new ChatApp();
