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

        // ✅ 历史消息分页加载
        this.loadedMessageCount = 0;  // 已加载的消息数
        this.totalMessageCount = 0;   // 总消息数
        this.hasMoreMessages = false;  // 是否还有更多历史消息
        this.isLoadingMore = false;    // 是否正在加载更多
        
        // PDF懒加载相关
        this.renderedPages = new Set();  // 已渲染的页面
        this.renderQueue = [];  // 待渲染队列
        this.isRendering = false;  // 是否正在渲染
        this.initialRenderCount = 1;  // 初始渲染页数（仅1页加快加载）
        this.renderBuffer = 2;  // 可见区域前后缓冲页数

        // 新内容计数
        this.newContentCount = 0;  // 用户不在底部时的新内容数量

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

    /**
     * 检查消息容器是否在底部附近
     * @returns {boolean} 如果距离底部小于阈值，返回 true
     */
    isNearBottom() {
        const container = document.getElementById('messages');
        if (!container) return true;

        const threshold = 100; // 距离底部100px以内视为"在底部"
        const scrollBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
        return scrollBottom < threshold;
    }

    /**
     * 智能滚动到底部（仅在用户已经在底部时滚动）
     */
    smartScrollToBottom() {
        if (this.isNearBottom()) {
            const container = document.getElementById('messages');
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        }
        // 更新按钮状态
        this.updateScrollToBottomButton();
    }

    /**
     * 更新导航按钮的显示状态
     */
    updateScrollToBottomButton() {
        const container = document.getElementById('scroll-buttons-container');
        const btn = document.getElementById('scroll-to-bottom-btn');
        const badge = document.getElementById('new-message-badge');
        const btnText = btn ? btn.querySelector('.btn-text') : null;

        if (!container || !btn) return;

        // 如果用户不在底部，显示按钮；否则隐藏
        if (!this.isNearBottom()) {
            container.style.display = 'flex';

            // 根据是否有新内容更新显示
            if (this.newContentCount > 0) {
                // 有新内容：显示提醒文本和徽章
                if (btnText) btnText.textContent = '有新内容，点击查看';
                if (badge) {
                    badge.textContent = this.newContentCount;
                    badge.style.display = 'flex';
                }
            } else {
                // 无新内容：显示默认文本
                if (btnText) btnText.textContent = '查看最新内容';
                if (badge) badge.style.display = 'none';
            }
        } else {
            container.style.display = 'none';
            // 用户回到底部，重置计数和动画
            this.newContentCount = 0;
            btn.classList.remove('has-new-content');
            if (btnText) btnText.textContent = '查看最新内容';
            if (badge) badge.style.display = 'none';
        }
    }

    /**
     * 触发新内容提醒（当用户不在底部且有新内容时）
     */
    notifyNewContent() {
        if (!this.isNearBottom()) {
            this.newContentCount++;

            const btn = document.getElementById('scroll-to-bottom-btn');
            const badge = document.getElementById('new-message-badge');

            if (btn) {
                // 添加脉冲动画类
                btn.classList.add('has-new-content');

                // 更新徽章
                if (badge) {
                    badge.textContent = this.newContentCount;
                    badge.style.display = 'flex';
                }
            }

            // 确保按钮可见
            this.updateScrollToBottomButton();
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

        // 滚动到顶部按钮
        const scrollToTopBtn = document.getElementById('scroll-to-top-btn');
        if (scrollToTopBtn) {
            scrollToTopBtn.addEventListener('click', () => {
                const messagesDiv = document.getElementById('messages');
                if (messagesDiv) {
                    messagesDiv.scrollTo({
                        top: 0,
                        behavior: 'smooth'
                    });
                }
            });
        }

        // 回到底部按钮（跳转到最新助手回复）
        const scrollToBottomBtn = document.getElementById('scroll-to-bottom-btn');
        if (scrollToBottomBtn) {
            scrollToBottomBtn.addEventListener('click', () => {
                const messagesDiv = document.getElementById('messages');
                if (messagesDiv) {
                    // 重置新内容计数
                    this.newContentCount = 0;

                    // 找到最后一条助手消息
                    const assistantMessages = messagesDiv.querySelectorAll('.message-assistant');
                    const lastAssistantMessage = assistantMessages[assistantMessages.length - 1];

                    if (lastAssistantMessage) {
                        // 滚动到最后一条助手消息的顶部
                        lastAssistantMessage.scrollIntoView({
                            behavior: 'smooth',
                            block: 'start'  // 将消息顶部对齐到容器顶部
                        });
                    } else {
                        // 如果没有助手消息，滚动到底部
                        messagesDiv.scrollTo({
                            top: messagesDiv.scrollHeight,
                            behavior: 'smooth'
                        });
                    }

                    // 移除提醒动画
                    scrollToBottomBtn.classList.remove('has-new-content');

                    // 重置文本
                    const btnText = scrollToBottomBtn.querySelector('.btn-text');
                    if (btnText) btnText.textContent = '查看最新内容';

                    // 隐藏徽章
                    const badge = document.getElementById('new-message-badge');
                    if (badge) {
                        badge.style.display = 'none';
                    }
                }
            });
        }

        // 监听消息容器滚动，显示/隐藏导航按钮
        const messagesDiv = document.getElementById('messages');
        if (messagesDiv) {
            messagesDiv.addEventListener('scroll', () => {
                this.updateScrollToBottomButton();
            });
        }
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
                this.loadedMessageCount = result.messages.length;
            }

            // 设置分页信息
            this.totalMessageCount = result.message_count || 0;
            this.hasMoreMessages = result.has_more_messages || false;

            // 如果有更多历史消息，显示"加载更多"按钮
            if (this.hasMoreMessages) {
                this.showLoadMoreButton();
            }

            // ✅ 优化: 异步连接WebSocket，不阻塞初始化
            this.connectWebSocket().catch(err => {
                console.error('WebSocket连接失败:', err);
                Utils.notify('连接失败，请刷新页面重试', 'error');
            });

            // 处理PDF预览（异步加载，不阻塞聊天）
            if (this.mode === 'single' && this.docName) {
                // 单文档模式：异步加载PDF，不等待完成
                this.loadPdf(this.docName).catch(err => {
                    console.error('PDF加载失败:', err);
                });
            } else if (this.mode === 'manual' && this.selectedDocs && this.selectedDocs.length > 0) {
                // 手动选择模式：显示PDF选择器，填充已选择的文档
                this.setupPdfSelector(this.selectedDocs).catch(err => {
                    console.error('PDF选择器设置失败:', err);
                });
            } else if (this.mode === 'cross') {
                // 跨文档智能模式：延迟加载文档列表，减少初始化时间
                this.setupPdfSelectorForCross().catch(err => {
                    console.error('获取文档列表失败:', err);
                });
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

        // ✅ 优化: 使用 DocumentFragment 批量添加，减少DOM操作
        const fragment = document.createDocumentFragment();

        messages.forEach(msg => {
            const messageElement = this.createMessageElement(
                msg.role,
                msg.content,
                msg.references,
                msg.timestamp
            );
            fragment.appendChild(messageElement);
        });

        // 一次性添加所有消息
        messagesDiv.appendChild(fragment);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
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
        } else if (data.type === 'progress') {
            // Update progress indicator
            this.updateProgressIndicator(data);
        } else if (data.type === 'error') {
            // Remove loading indicator on error
            this.removeLoadingIndicator();
            this.isSending = false;
            document.getElementById('send-btn').disabled = false;
            Utils.notify('错误: ' + data.content, 'error');
        }
    }

    /**
     * 创建消息DOM元素（不添加到DOM）
     * @private
     */
    createMessageElement(role, content, references = null, messageTimestamp = null) {
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
        return messageDiv;
    }

    /**
     * 添加单条消息到聊天界面（用于实时消息）
     */
    addMessage(role, content, references = null, messageTimestamp = null) {
        const messagesDiv = document.getElementById('messages');

        // 移除欢迎消息
        const welcome = messagesDiv.querySelector('.welcome');
        if (welcome) welcome.remove();

        // 创建并添加消息元素
        const messageElement = this.createMessageElement(role, content, references, messageTimestamp);
        messagesDiv.appendChild(messageElement);

        // 如果是助手消息且用户不在底部，触发新内容提醒
        if (role === 'assistant') {
            this.notifyNewContent();
        }

        // 智能滚动到底部（仅在用户已经在底部时滚动）
        this.smartScrollToBottom();
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

        // 不自动显示PDF区域，等待用户选择文档后再加载
        // document.getElementById('pdf-section').classList.remove('hidden');

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

        // 使用DocumentFragment优化DOM操作
        const fragment = document.createDocumentFragment();

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
            fragment.appendChild(pageDiv);
        }

        // 一次性添加所有占位符
        container.appendChild(fragment);
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
        bubble.innerHTML = `
            <div class="progress-container">
                <div class="progress-header">
                    <div class="spinner"></div>
                    <div class="progress-text">
                        <div id="progress-main-text" style="font-size: 1rem; font-weight: 600;">🤔 正在思考...</div>
                    </div>
                </div>
                
                <!-- 单一进度条（用于单文档/非检索阶段） -->
                <div id="progress-bar-wrapper" style="display: none;">
                    <div class="progress-bar-container">
                        <div class="progress-bar" id="progress-bar" style="width: 0%"></div>
                    </div>
                    <div style="text-align: right; font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem;">
                        <span id="progress-percentage">0%</span>
                    </div>
                </div>

                <!-- 单一进度详情 -->
                <div id="progress-details" class="progress-details" style="display: none;">
                    <div id="progress-agent" class="progress-detail-item"></div>
                    <div id="progress-stage" class="progress-detail-item"></div>
                    <div id="progress-iteration" class="progress-detail-item"></div>
                    <div id="progress-tool" class="progress-detail-item"></div>
                    <div id="progress-message" class="progress-detail-item" style="font-style: italic;"></div>
                </div>

                <!-- 并行文档进度（用于跨文档检索） -->
                <div id="parallel-docs-progress" style="display: none;">
                    <div style="margin-top: 0.75rem; margin-bottom: 0.5rem; font-weight: 600; color: var(--text-primary);">
                        📚 并行检索进度
                    </div>
                    <div id="docs-progress-list" style="display: flex; flex-direction: column; gap: 0.5rem;"></div>
                </div>

                <div id="node-flow" class="node-flow" style="display: none;"></div>
            </div>
        `;

        messageDiv.appendChild(bubble);
        messagesDiv.appendChild(messageDiv);

        // 智能滚动到底部（仅在用户已经在底部时滚动）
        this.smartScrollToBottom();

        this.loadingMessageId = 'loading-indicator';
        this.parallelDocsState = {};  // 用于跟踪并行文档的状态
        this.collapsedDocs = {};  // 用于跟踪哪些文档是折叠的
    }

    updateProgressIndicator(progressData) {
        const mainText = document.getElementById('progress-main-text');
        const detailsDiv = document.getElementById('progress-details');
        const agentDiv = document.getElementById('progress-agent');
        const stageDiv = document.getElementById('progress-stage');
        const iterationDiv = document.getElementById('progress-iteration');
        const toolDiv = document.getElementById('progress-tool');
        const messageDiv = document.getElementById('progress-message');
        const progressBarWrapper = document.getElementById('progress-bar-wrapper');
        const progressBar = document.getElementById('progress-bar');
        const progressPercentage = document.getElementById('progress-percentage');
        const nodeFlow = document.getElementById('node-flow');
        const parallelDocsProgress = document.getElementById('parallel-docs-progress');

        if (!mainText || !detailsDiv) return;

        // 检测是否为并行检索场景
        // 关键判断：当 agent='retrieval' 且 doc_name 不是 'MultiDoc' 时，说明是具体文档的检索
        // 如果已经有其他文档在 parallelDocsState 中，或者 mode 是 cross/manual，就使用并行视图
        const isRetrievalAgent = progressData.agent === 'retrieval';
        const hasSpecificDoc = progressData.doc_name && progressData.doc_name !== 'MultiDoc';
        const isMultiDocMode = this.mode === 'cross' || this.mode === 'manual';
        const hasMultipleDocs = this.parallelDocsState && Object.keys(this.parallelDocsState).length > 0;
        
        // 情况1：回答代理进入 retrieve_multi 阶段（准备并行检索）
        const isParallelStageStart = progressData.stage === 'retrieve_multi' && progressData.doc_name === 'MultiDoc';
        
        // 情况2：检索代理的具体文档进度（在跨文档模式下）
        const isParallelRetrieval = isRetrievalAgent && hasSpecificDoc && (isMultiDocMode || hasMultipleDocs);
        
        if (isParallelStageStart) {
            // 准备并行视图（显示等待状态）
            this.prepareParallelView(progressData);
            return;
        }
        
        if (isParallelRetrieval) {
            // 使用并行文档进度视图（更新具体文档）
            this.updateParallelDocsProgress(progressData);
            return;
        }

        // Agent type mapping with icons
        const agentConfig = {
            'answer': { name: '💬 回答代理', icon: '💬', color: '#667eea' },
            'retrieval': { name: '🔍 检索代理', icon: '🔍', color: '#10b981' }
        };

        // Stage configuration with icons
        const stageConfig = {
            // Answer Agent stages
            'analyze_intent': { name: '意图分析', icon: '🎯' },
            'retrieve_single': { name: '单文档检索', icon: '📄' },
            'select_docs': { name: '文档选择', icon: '📚' },
            'rewrite_queries': { name: '查询改写', icon: '✏️' },
            'retrieve_multi': { name: '多文档检索', icon: '🔎' },
            'synthesize': { name: '综合答案', icon: '🧩' },
            'generate': { name: '生成答案', icon: '✨' },
            'generate_answer': { name: '生成答案', icon: '✨' },
            // Retrieval Agent stages
            'rewrite': { name: '查询重写', icon: '📝' },
            'think': { name: '思考选择', icon: '💭' },
            'act': { name: '执行检索', icon: '⚡' },
            'summary': { name: '累积总结', icon: '📊' },
            'evaluate': { name: '评估结果', icon: '✅' },
            'format': { name: '格式化输出', icon: '📋' }
        };

        // Tool configuration with icons
        const toolConfig = {
            'search_by_context': { name: '语义检索', icon: '🔍' },
            'extract_titles_from_structure': { name: '提取标题', icon: '📑' },
            'search_by_title': { name: '标题匹配', icon: '🎯' },
            'get_document_structure': { name: '获取结构', icon: '🏗️' },
            'search_by_page_range': { name: '页码检索', icon: '📖' },
            'get_pages': { name: '获取页面', icon: '📄' },
            'vector_search': { name: '向量检索', icon: '🔍' },
            'get_page_content': { name: '获取内容', icon: '📄' },
            'get_chapter_structure': { name: '获取章节', icon: '📚' },
            'get_images': { name: '获取图片', icon: '🖼️' }
        };

        const agent = agentConfig[progressData.agent] || { name: progressData.agent, icon: '🤖', color: '#667eea' };
        const stage = stageConfig[progressData.stage] || stageConfig[progressData.stage_name] || { name: progressData.stage || progressData.stage_name, icon: '⚙️' };

        // 隐藏并行进度视图（如果之前显示过）
        if (parallelDocsProgress) {
            parallelDocsProgress.style.display = 'none';
        }

        // Update main text with icon
        mainText.innerHTML = `${agent.icon} <strong>${agent.name}</strong> - ${stage.icon} ${stage.name}`;

        // Update progress bar if iteration info available
        if (progressData.iteration !== undefined && progressData.max_iterations !== undefined) {
            progressBarWrapper.style.display = 'block';
            const percentage = (progressData.iteration / progressData.max_iterations) * 100;
            progressBar.style.width = percentage + '%';
            progressPercentage.textContent = Math.round(percentage) + '%';
        } else {
            progressBarWrapper.style.display = 'none';
        }

        // Show details
        detailsDiv.style.display = 'block';

        // Update agent info
        agentDiv.innerHTML = `<strong>🤖 代理:</strong> ${agent.name} <span class="progress-badge">${progressData.doc_name || 'MultiDoc'}</span>`;
        agentDiv.style.display = 'flex';

        // Update stage info
        stageDiv.innerHTML = `<strong>⚙️ 阶段:</strong> ${stage.icon} ${stage.name}`;
        stageDiv.style.display = 'flex';

        // Update iteration info
        if (progressData.iteration !== undefined && progressData.max_iterations !== undefined) {
            iterationDiv.innerHTML = `<strong>🔄 迭代:</strong> 第 <span class="progress-badge">${progressData.iteration}/${progressData.max_iterations}</span> 轮`;
            iterationDiv.style.display = 'flex';
        } else {
            iterationDiv.style.display = 'none';
        }

        // Update tool info
        if (progressData.tool) {
            const tool = toolConfig[progressData.tool] || { name: progressData.tool, icon: '🔧' };
            toolDiv.innerHTML = `<strong>🛠️ 工具:</strong> ${tool.icon} ${tool.name}`;
            toolDiv.style.display = 'flex';
        } else {
            toolDiv.style.display = 'none';
        }

        // Update message
        if (progressData.message) {
            messageDiv.innerHTML = `<strong>💬 信息:</strong> ${progressData.message}`;
            messageDiv.style.display = 'flex';
        } else {
            messageDiv.style.display = 'none';
        }

        // Update node flow visualization
        // 对于单文档检索（agent=retrieval），也显示节点流程
        this.updateNodeFlow(progressData, agent, stageConfig);

        // 智能滚动到底部（仅在用户已经在底部时滚动）
        this.smartScrollToBottom();
    }

    updateNodeFlow(progressData, agent, stageConfig) {
        const nodeFlow = document.getElementById('node-flow');
        if (!nodeFlow) return;

        // Define workflow stages for each agent type
        const workflows = {
            'answer': [
                { key: 'analyze_intent', label: '意图分析' },
                { key: 'select_docs', label: '文档选择' },
                { key: 'retrieve_multi', label: '检索' },
                { key: 'synthesize', label: '综合' },
                { key: 'generate', label: '生成' }
            ],
            'retrieval': [
                { key: 'rewrite', label: '改写' },
                { key: 'think', label: '思考' },
                { key: 'act', label: '执行' },
                { key: 'evaluate', label: '评估' },
                { key: 'format', label: '输出' }
            ]
        };

        const workflow = workflows[progressData.agent] || [];
        if (workflow.length === 0) {
            nodeFlow.style.display = 'none';
            return;
        }

        // 总是显示节点流程（包括单文档检索）
        nodeFlow.style.display = 'flex';
        
        // Build node flow HTML
        let html = '';
        workflow.forEach((node, index) => {
            const stageInfo = stageConfig[node.key] || { icon: '⚙️' };
            const isActive = progressData.stage === node.key || progressData.stage_name === node.key;
            const isCompleted = index < workflow.findIndex(n => n.key === progressData.stage || n.key === progressData.stage_name);
            
            let nodeClass = 'node';
            if (isActive) nodeClass += ' active';
            else if (isCompleted) nodeClass += ' completed';

            html += `
                <div class="${nodeClass}">
                    <div class="node-icon">${stageInfo.icon || '⚙️'}</div>
                    <div class="node-label">${node.label}</div>
                </div>
            `;

            if (index < workflow.length - 1) {
                html += '<div class="node-arrow">→</div>';
            }
        });

        nodeFlow.innerHTML = html;
    }

    prepareParallelView(progressData) {
        /**
         * 准备并行文档视图（当收到 retrieve_multi 的总体进度时）
         * 显示等待状态，等待具体文档的进度更新
         */
        const parallelDocsProgress = document.getElementById('parallel-docs-progress');
        const docsProgressList = document.getElementById('docs-progress-list');
        const mainText = document.getElementById('progress-main-text');
        const nodeFlow = document.getElementById('node-flow');
        const progressBarWrapper = document.getElementById('progress-bar-wrapper');
        const progressDetails = document.getElementById('progress-details');

        if (!parallelDocsProgress || !docsProgressList) return;

        // 隐藏单一进度视图
        progressBarWrapper.style.display = 'none';
        progressDetails.style.display = 'none';
        nodeFlow.style.display = 'none';

        // 显示并行进度视图
        parallelDocsProgress.style.display = 'block';

        // 更新主文本
        mainText.innerHTML = `🔎 <strong>多文档并行检索</strong>`;

        // 显示等待状态
        docsProgressList.innerHTML = `
            <div style="text-align: center; padding: 2rem; color: var(--text-muted);">
                <div class="spinner" style="margin: 0 auto 1rem;"></div>
                <div>${progressData.message || '正在准备并行检索...'}</div>
            </div>
        `;

        // 重置状态
        this.parallelDocsState = {};

        // 智能滚动到底部（仅在用户已经在底部时滚动）
        this.smartScrollToBottom();
    }

    updateParallelDocsProgress(progressData) {
        /**
         * 更新并行文档检索进度
         * 为每个文档显示独立的进度条
         */
        const parallelDocsProgress = document.getElementById('parallel-docs-progress');
        const docsProgressList = document.getElementById('docs-progress-list');
        const mainText = document.getElementById('progress-main-text');
        const nodeFlow = document.getElementById('node-flow');
        const progressBarWrapper = document.getElementById('progress-bar-wrapper');
        const progressDetails = document.getElementById('progress-details');

        if (!parallelDocsProgress || !docsProgressList) return;

        // 隐藏单一进度视图
        progressBarWrapper.style.display = 'none';
        progressDetails.style.display = 'none';
        nodeFlow.style.display = 'none';

        // 显示并行进度视图
        parallelDocsProgress.style.display = 'block';

        // 更新主文本
        mainText.innerHTML = `🔎 <strong>多文档并行检索</strong>`;

        const docName = progressData.doc_name;
        
        // 初始化或更新文档状态
        if (!this.parallelDocsState) {
            this.parallelDocsState = {};
        }
        
        this.parallelDocsState[docName] = progressData;

        // 重新渲染所有文档的进度
        this.renderParallelDocsProgress();
    }

    renderParallelDocsProgress() {
        /**
         * 渲染所有并行文档的进度条（增量更新，避免刷新整个列表）
         */
        const docsProgressList = document.getElementById('docs-progress-list');
        if (!docsProgressList || !this.parallelDocsState) return;

        // 工具配置
        const toolConfig = {
            'search_by_context': { name: '语义检索', icon: '🔍' },
            'extract_titles_from_structure': { name: '提取标题', icon: '📑' },
            'search_by_title': { name: '标题匹配', icon: '🎯' },
            'get_document_structure': { name: '获取结构', icon: '🏗️' },
            'search_by_page_range': { name: '页码检索', icon: '📖' },
            'get_pages': { name: '获取页面', icon: '📄' },
            'vector_search': { name: '向量检索', icon: '🔍' },
            'get_page_content': { name: '获取内容', icon: '📄' },
            'get_chapter_structure': { name: '获取章节', icon: '📚' },
            'get_images': { name: '获取图片', icon: '🖼️' }
        };

        // 阶段配置
        const stageConfig = {
            'rewrite': { name: '查询重写', icon: '📝', color: '#3b82f6' },
            'think': { name: '思考选择', icon: '💭', color: '#8b5cf6' },
            'act': { name: '执行检索', icon: '⚡', color: '#f59e0b' },
            'summary': { name: '累积总结', icon: '📊', color: '#10b981' },
            'evaluate': { name: '评估结果', icon: '✅', color: '#06b6d4' },
            'format': { name: '格式化输出', icon: '📋', color: '#6366f1' }
        };

        // 检索代理工作流
        const retrievalWorkflow = [
            { key: 'rewrite', label: '改写' },
            { key: 'think', label: '思考' },
            { key: 'act', label: '执行' },
            { key: 'evaluate', label: '评估' },
            { key: 'format', label: '输出' }
        ];

        const docs = Object.entries(this.parallelDocsState);
        
        // 增量更新：只更新变化的文档，不重建整个列表
        docs.forEach(([docName, progressData]) => {
            const stage = stageConfig[progressData.stage] || { name: progressData.stage, icon: '⚙️', color: '#6b7280' };
            const tool = progressData.tool ? toolConfig[progressData.tool] || { name: progressData.tool, icon: '🔧' } : null;
            
            // 计算进度百分比
            let progressPercent = 0;
            if (progressData.iteration !== undefined && progressData.max_iterations !== undefined) {
                progressPercent = Math.round((progressData.iteration / progressData.max_iterations) * 100);
            }

            // 状态颜色
            const statusColor = stage.color || '#667eea';
            
            // 检查是否折叠（默认展开）
            const isCollapsed = this.collapsedDocs[docName] === true;
            const toggleIcon = isCollapsed ? '▶' : '▼';
            const docId = 'doc-progress-' + docName.replace(/[^a-zA-Z0-9]/g, '-');
            const cardId = 'doc-card-' + docName.replace(/[^a-zA-Z0-9]/g, '-');

            // 检查文档卡片是否已存在
            let docCard = document.getElementById(cardId);
            
            if (!docCard) {
                // 卡片不存在，创建新卡片
                docCard = document.createElement('div');
                docCard.id = cardId;
                docCard.className = 'doc-progress-item';
                docCard.style.cssText = `
                    background: var(--bg-tertiary);
                    border-radius: 0.5rem;
                    padding: 0.75rem;
                    border-left: 3px solid ${statusColor};
                    transition: all 0.3s ease;
                `;
                docsProgressList.appendChild(docCard);
            } else {
                // 卡片已存在，只更新边框颜色
                docCard.style.borderLeftColor = statusColor;
            }

            // 更新卡片内容（使用innerHTML，但只更新这一个卡片）
            docCard.innerHTML = `
                <!-- 可点击的标题栏 -->
                <div onclick="chatApp.toggleDocProgress('${docName}')" style="
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    cursor: pointer;
                    user-select: none;
                    margin-bottom: ${isCollapsed ? '0' : '0.5rem'};
                ">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-size: 0.9rem; color: var(--text-muted);">${toggleIcon}</span>
                        <div style="font-weight: 600; color: var(--text-primary); font-size: 0.9rem;">
                            📄 ${docName}
                        </div>
                    </div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">
                        ${stage.icon} ${stage.name} ${progressPercent > 0 ? `(${progressPercent}%)` : ''}
                    </div>
                </div>

                <!-- 折叠时的简化进度条 -->
                ${isCollapsed && progressData.iteration !== undefined && progressData.max_iterations !== undefined ? `
                    <div style="margin-top: 0.5rem;">
                        <div class="progress-bar-container" style="height: 4px;">
                            <div class="progress-bar" style="width: ${progressPercent}%; background: ${statusColor};"></div>
                        </div>
                    </div>
                ` : ''}

                <!-- 展开时的详细内容 -->
                <div id="${docId}" style="display: ${isCollapsed ? 'none' : 'block'};">
                    <!-- 节点流程图 -->
                    <div class="node-flow" style="
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 0.25rem;
                        padding: 0.75rem 0.5rem;
                        background: var(--bg-primary);
                        border-radius: 0.375rem;
                        margin-bottom: 0.75rem;
                        flex-wrap: wrap;
                    ">
                        ${this.renderRetrievalNodeFlow(progressData, retrievalWorkflow, stageConfig)}
                    </div>

                    <!-- 详细进度信息 -->
                    ${progressData.iteration !== undefined && progressData.max_iterations !== undefined ? `
                        <div style="margin-bottom: 0.5rem;">
                            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.25rem;">
                                <span>迭代进度</span>
                                <span>${progressData.iteration}/${progressData.max_iterations} (${progressPercent}%)</span>
                            </div>
                            <div class="progress-bar-container" style="height: 4px;">
                                <div class="progress-bar" style="width: ${progressPercent}%; background: ${statusColor};"></div>
                            </div>
                        </div>
                    ` : ''}

                    ${tool ? `
                        <div style="font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.25rem;">
                            🛠️ 当前工具: ${tool.icon} ${tool.name}
                        </div>
                    ` : ''}

                    ${progressData.message ? `
                        <div style="font-size: 0.75rem; color: var(--text-muted); font-style: italic; margin-top: 0.25rem;">
                            💬 ${progressData.message}
                        </div>
                    ` : ''}
                </div>
            `;
        });

        // 智能滚动到底部（仅在用户已经在底部时滚动）
        this.smartScrollToBottom();
    }

    renderRetrievalNodeFlow(progressData, workflow, stageConfig) {
        /**
         * 为单个检索代理渲染节点流程
         */
        let html = '';
        workflow.forEach((node, index) => {
            const stageInfo = stageConfig[node.key] || { icon: '⚙️' };
            const isActive = progressData.stage === node.key;
            const isCompleted = index < workflow.findIndex(n => n.key === progressData.stage);
            
            let nodeClass = 'node';
            if (isActive) nodeClass += ' active';
            else if (isCompleted) nodeClass += ' completed';

            html += `
                <div class="${nodeClass}" style="
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 0.25rem;
                    padding: 0.375rem 0.5rem;
                    border-radius: 0.375rem;
                    font-size: 0.75rem;
                    transition: all 0.3s ease;
                    ${isActive ? 'background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%); transform: scale(1.05);' : ''}
                    ${isCompleted ? 'opacity: 0.6;' : ''}
                ">
                    <div style="font-size: 1.2rem;">${stageInfo.icon || '⚙️'}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); white-space: nowrap;">${node.label}</div>
                </div>
            `;

            if (index < workflow.length - 1) {
                html += '<div style="color: var(--text-muted); font-size: 0.8rem;">→</div>';
            }
        });
        return html;
    }

    toggleDocProgress(docName) {
        /**
         * 切换文档进度的折叠/展开状态
         */
        // 切换状态
        this.collapsedDocs[docName] = !this.collapsedDocs[docName];
        
        // 重新渲染（现在是增量更新，不会闪烁）
        this.renderParallelDocsProgress();
    }

    prepareParallelView(progressData) {
        /**
         * 准备并行文档视图（当收到 retrieve_multi 的总体进度时）
         * 显示等待状态，等待具体文档的进度更新
         */
        const parallelDocsProgress = document.getElementById('parallel-docs-progress');
        const docsProgressList = document.getElementById('docs-progress-list');
        const mainText = document.getElementById('progress-main-text');
        const nodeFlow = document.getElementById('node-flow');
        const progressBarWrapper = document.getElementById('progress-bar-wrapper');
        const progressDetails = document.getElementById('progress-details');

        if (!parallelDocsProgress || !docsProgressList) return;

        // 隐藏单一进度视图
        progressBarWrapper.style.display = 'none';
        progressDetails.style.display = 'none';
        nodeFlow.style.display = 'none';

        // 显示并行进度视图
        parallelDocsProgress.style.display = 'block';

        // 更新主文本
        mainText.innerHTML = `🔎 <strong>多文档并行检索</strong>`;

        // 显示等待状态（只在列表为空时显示）
        if (docsProgressList.children.length === 0) {
            docsProgressList.innerHTML = `
                <div style="text-align: center; padding: 2rem; color: var(--text-muted);">
                    <div class="spinner" style="margin: 0 auto 1rem;"></div>
                    <div>${progressData.message || '正在准备并行检索...'}</div>
                </div>
            `;
        }

        // 智能滚动到底部（仅在用户已经在底部时滚动）
        this.smartScrollToBottom();
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
            // 重置分页状态
            this.loadedMessageCount = 0;
            this.totalMessageCount = 0;
            this.hasMoreMessages = false;
            Utils.notify('对话已清空', 'success');
        } catch (error) {
            Utils.notify('清空失败: ' + error.message, 'error');
        }
    }

    /**
     * 显示"加载更多历史消息"按钮
     */
    showLoadMoreButton() {
        const messagesDiv = document.getElementById('messages');

        // 检查是否已存在按钮
        let loadMoreBtn = document.getElementById('load-more-btn');
        if (loadMoreBtn) {
            loadMoreBtn.style.display = 'block';
            return;
        }

        // 创建按钮
        loadMoreBtn = document.createElement('div');
        loadMoreBtn.id = 'load-more-btn';
        loadMoreBtn.className = 'load-more-button';
        loadMoreBtn.innerHTML = `
            <button onclick="chatApp.loadMoreMessages()">
                📜 加载更早的消息 (还有 ${this.totalMessageCount - this.loadedMessageCount} 条)
            </button>
        `;

        // 插入到消息列表顶部
        messagesDiv.insertBefore(loadMoreBtn, messagesDiv.firstChild);
    }

    /**
     * 隐藏"加载更多"按钮
     */
    hideLoadMoreButton() {
        const loadMoreBtn = document.getElementById('load-more-btn');
        if (loadMoreBtn) {
            loadMoreBtn.style.display = 'none';
        }
    }

    /**
     * 加载更多历史消息
     */
    async loadMoreMessages() {
        if (this.isLoadingMore || !this.hasMoreMessages) return;

        this.isLoadingMore = true;
        const loadMoreBtn = document.getElementById('load-more-btn');
        const originalHTML = loadMoreBtn ? loadMoreBtn.innerHTML : '';

        try {
            // 更新按钮状态
            if (loadMoreBtn) {
                loadMoreBtn.innerHTML = '<button disabled>⏳ 加载中...</button>';
            }

            // 调用API加载更多消息
            const response = await fetch(
                `/api/v1/chat/load-more-messages?offset=${this.loadedMessageCount}&limit=20`
            );

            if (!response.ok) {
                throw new Error('加载失败');
            }

            const result = await response.json();

            if (result.status === 'success' && result.messages.length > 0) {
                // 保存当前滚动位置
                const messagesDiv = document.getElementById('messages');
                const oldScrollHeight = messagesDiv.scrollHeight;

                // 使用 DocumentFragment 批量添加消息
                const fragment = document.createDocumentFragment();

                // 倒序添加（因为是从旧到新）
                result.messages.forEach(msg => {
                    const messageElement = this.createMessageElement(
                        msg.role,
                        msg.content,
                        msg.references,
                        msg.timestamp
                    );
                    fragment.appendChild(messageElement);
                });

                // 找到第一条真实消息的位置（跳过load-more按钮）
                const firstMessage = messagesDiv.querySelector('.message');
                if (firstMessage) {
                    messagesDiv.insertBefore(fragment, firstMessage);
                } else {
                    messagesDiv.appendChild(fragment);
                }

                // 恢复滚动位置（保持在原来的消息位置）
                const newScrollHeight = messagesDiv.scrollHeight;
                messagesDiv.scrollTop = newScrollHeight - oldScrollHeight;

                // 更新计数
                this.loadedMessageCount += result.messages.length;
                this.hasMoreMessages = result.has_more;

                // 更新按钮文本
                if (this.hasMoreMessages) {
                    loadMoreBtn.innerHTML = `
                        <button onclick="chatApp.loadMoreMessages()">
                            📜 加载更早的消息 (还有 ${this.totalMessageCount - this.loadedMessageCount} 条)
                        </button>
                    `;
                } else {
                    this.hideLoadMoreButton();
                }

                console.log(`✅ 已加载 ${result.messages.length} 条历史消息，总共 ${this.loadedMessageCount}/${this.totalMessageCount}`);
            } else {
                Utils.notify('没有更多历史消息了', 'info');
                this.hideLoadMoreButton();
            }

        } catch (error) {
            console.error('加载更多消息失败:', error);
            Utils.notify('加载失败: ' + error.message, 'error');

            // 恢复按钮
            if (loadMoreBtn) {
                loadMoreBtn.innerHTML = originalHTML;
            }
        } finally {
            this.isLoadingMore = false;
        }
    }
}

// 初始化
const chatApp = new ChatApp();
