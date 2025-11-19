/**
 * LLMReader 聊天页面 JavaScript
 * 专用于全屏聊天体验
 */

class LLMReaderChatApp {
    constructor() {
        this.config = {
            provider: 'openai',
            currentDocName: null,
            hasPdfReader: false,
            hasWebReader: false
        };

        this.websocket = null;
        this.isConnected = false;
        this.chatHistory = [];
        this.pdfViewerVisible = true;
        this.isProcessing = false; // 添加处理状态标志
        
        // 🔥 新增：消息队列配置，限制最多保留 20 条消息
        this.maxHistorySize = 20;
        this.deletedMessageCount = 0; // 统计已删除的消息数量


        // API基础URL配置 - 自动检测当前协议和主机
        this.apiBase = `${window.location.protocol}//${window.location.host}`;

        this.init();
    }

    // 获取完整的API URL
    getApiUrl(endpoint) {
        return `${this.apiBase}${endpoint}`;
    }

    async init() {
        console.log('🚀 聊天页面初始化开始');

        // 初始化UI组件
        this.initChatInterface();
        this.initPdfViewer();
        this.initEventListeners();

        // 监听localStorage变化，以同步主页面的状态变化
        this.initStorageSync();

        // 加载配置和状态
        await this.loadConfig();

        // 加载聊天历史
        await this.loadChatHistory();

        // 连接WebSocket
        this.connectWebSocket();

        console.log('✅ 聊天页面初始化完成');
    }

    initChatInterface() {
        const chatInput = document.getElementById('chat-input-full');
        const sendBtn = document.getElementById('send-btn-full');

        // 发送按钮事件
        sendBtn.addEventListener('click', () => {
            this.sendMessage();
        });

        // 回车发送（Shift+Enter换行）
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // 输入框自动调整高度
        chatInput.addEventListener('input', (e) => {
            this.autoResizeTextarea(e.target);
        });

        // 建议问题按钮
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('suggestion-btn')) {
                const question = e.target.getAttribute('data-question');
                if (question) {
                    chatInput.value = question;
                    this.sendMessage();
                }
            }
        });
    }

    initPdfViewer() {
        // PDF查看器控制
        const toggleBtn = document.getElementById('toggle-pdf-viewer');
        const closeBtn = document.getElementById('close-pdf-viewer');
        const prevBtn = document.getElementById('pdf-prev-page-full');
        const nextBtn = document.getElementById('pdf-next-page-full');

        toggleBtn.addEventListener('click', () => {
            this.togglePdfViewer();
        });

        closeBtn.addEventListener('click', () => {
            this.hidePdfViewer();
        });

        prevBtn.addEventListener('click', () => {
            this.previousPdfPage();
        });

        nextBtn.addEventListener('click', () => {
            this.nextPdfPage();
        });

        // 初始化PDF查看器状态
        this.pdfViewerState = {
            currentPage: 1,
            totalPages: 0,
            pdfUrl: null,
            images: []
        };
    }

    initStorageSync() {
        // 监听localStorage变化事件，同步主页面的会话变化
        window.addEventListener('storage', (e) => {
            if (e.key === 'llmreader_document_state') {
                console.log('🔄 检测到文档状态变化，同步状态');
                this.syncDocumentStateFromStorage(e.newValue);
            }
        });

        // 定期检查状态变化（备用机制）
        setInterval(() => {
            this.checkStateSync();
        }, 2000); // 每2秒检查一次
    }

    syncDocumentStateFromStorage(newValue) {
        if (!newValue) return;

        try {
            const newState = JSON.parse(newValue);

            // 检查是否有状态变化
            if (newState.currentDocName !== this.config.currentDocName) {

                console.log('📄 同步文档状态变化:', newState);

                // 更新配置
                this.config.currentDocName = newState.currentDocName;
                this.config.hasPdfReader = newState.hasPdfReader;
                this.config.hasWebReader = newState.hasWebReader;
                this.chatHistory = []; // 清空当前聊天历史

                // 更新UI
                this.updateDocumentStatus();
                this.clearChatMessages();
                this.showWelcomeMessage();

                // 重新加载PDF查看器
                if (this.config.currentDocName) {
                    this.loadPdfViewer();
                    this.showQuickSuggestions();
                } else {
                    this.displayNoPdfContent();

                    // 隐藏快速建议
                    const suggestions = document.getElementById('quick-suggestions');
                    if (suggestions) {
                        suggestions.style.display = 'none';
                    }
                }

                console.log('✅ 文档状态同步完成');
            }
        } catch (error) {
            console.error('同步文档状态失败:', error);
        }
    }


    checkStateSync() {
        try {
            // 检查文档状态是否与本地存储一致
            const savedState = this.loadDocumentStateFromLocal();
            if (savedState) {
                // 检查文档状态变化
                if (savedState.currentDocName !== this.config.currentDocName) {
                    console.log('🔄 检测到文档状态变化，进行同步:', {
                        current: this.config.currentDocName,
                        saved: savedState.currentDocName
                    });
                    this.syncDocumentStateFromStorage(JSON.stringify(savedState));
                }
            }
        } catch (error) {
            console.warn('⚠️ 状态同步检查失败:', error);
        }
    }

    initEventListeners() {
        // 清空当前对话按钮
        document.getElementById('clear-chat-full').addEventListener('click', () => {
            this.clearCurrentChat();
        });

        // 导出对话按钮
        document.getElementById('export-chat').addEventListener('click', () => {
            this.exportChat();
        });

        // 键盘快捷键
        document.addEventListener('keydown', (e) => {
            // ESC键切换PDF查看器
            if (e.key === 'Escape') {
                this.togglePdfViewer();
            }
        });
    }

    /* === WebSocket连接 === */
    connectWebSocket() {
        // 自动检测WebSocket URL，使用当前页面的协议和主机
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

        console.log('🔌 WebSocket URL:', wsUrl);
        this.websocket = new WebSocket(wsUrl);

        this.websocket.onopen = () => {
            this.isConnected = true;
            this.updateConnectionStatus('connected', '已连接');
            this.enableChatInput();
        };

        this.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };

        this.websocket.onclose = () => {
            this.isConnected = false;
            this.updateConnectionStatus('disconnected', '连接已断开');

            // 如果正在处理中，恢复输入状态
            if (this.isProcessing) {
                this.restoreInputState();
            }

            this.disableChatInput();

            // 尝试重连
            setTimeout(() => {
                if (!this.isConnected) {
                    this.updateConnectionStatus('connecting', '重新连接中...');
                    this.connectWebSocket();
                }
            }, 3000);
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket错误:', error);
            this.updateConnectionStatus('disconnected', '连接错误');
        };
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'user_message':
                this.addChatMessage('user', data.content, data.timestamp);
                break;
            case 'assistant_message':
                // 恢复输入状态
                this.restoreInputState();
                this.addChatMessage('assistant', data.content, data.timestamp);
                break;
            case 'status':
                this.addStatusMessage(data.content);
                break;
            case 'error':
                // 恢复输入状态（错误时也要恢复）
                this.restoreInputState();
                this.addChatMessage('assistant', `❌ ${data.content}`, data.timestamp);
                break;
        }
    }

    /* === API调用方法 === */
    async loadConfig() {
        try {
            console.log('🔄 开始加载配置...');

            // 首先检查本地存储的文档状态
            const savedDocState = this.loadDocumentStateFromLocal();

            const response = await fetch(this.getApiUrl('/api/v1/config'));
            const config = await response.json();
            console.log('📊 获取到的配置:', config);

            // 映射后端的下划线命名到前端的驼峰命名
            const mappedConfig = {
                ...config,
                currentDocName: config.current_doc_name,
                hasPdfReader: config.has_pdf_reader,
                hasWebReader: config.has_web_reader
            };

            this.config = { ...this.config, ...mappedConfig };

            // 检查本地存储的状态是否与服务器状态一致
            if (savedDocState && savedDocState.currentDocName) {
                // 🔥 关键修复：优先使用本地存储状态，因为它代表用户的实际工作状态
                // 服务器重启后状态会被重置，但本地存储保留了用户的文档选择
                console.log('🔄 检测到本地存储的文档状态，优先使用本地状态:', savedDocState.currentDocName);
                this.config = { ...this.config, ...savedDocState };
            } else if (this.config.currentDocName) {
                // 如果本地存储没有状态，但服务器有状态（这种情况很少见）
                console.log('📊 使用服务器状态（本地存储为空）:', this.config.currentDocName);
            }

            this.updateDocumentStatus();

            // 🔥 新增：聊天页面采用延迟加载策略
            if (this.config.currentDocName) {
                console.log('📄 检测到文档，采用延迟加载策略:', this.config.currentDocName);
                console.log('💡 PDF查看器将在聊天历史加载后初始化');
                // 不再自动加载PDF查看器，等待聊天历史加载完成后再决定
            } else {
                console.log('❌ 没有检测到文档');
                this.displayNoPdfContent();
            }

        } catch (error) {
            console.error('加载配置失败:', error);
            this.displayNoPdfContent();
        }
    }

    async loadChatHistory() {
        try {
            // 🔥 核心修复：正确的session查找和恢复逻辑
            console.log('🔄 开始加载聊天历史...');

            // 步骤1：优先使用localStorage中已保存的session ID
            await this.loadSessionIdFromLocalStorage();

            // 步骤2：尝试从后端加载对应的会话数据
            await this.loadChatHistoryFromBackend();

            // 步骤3：如果没有从后端加载到历史记录，尝试从chat API加载
            if (this.chatHistory.length === 0) {
                console.log('📖 后端会话数据为空，尝试从chat API加载历史');
                await this.loadChatHistoryFromChatAPI();
            }

            console.log('✅ 聊天历史加载完成，消息数量:', this.chatHistory.length);

            // 🔥 关键修复：加载完聊天历史后，立即加载PDF查看器
            if (this.config.currentDocName) {
                console.log('📄 聊天历史加载完成，现在初始化PDF查看器...');
                await this.loadPdfViewer();
                this.showQuickSuggestions();
            }
        } catch (error) {
            console.error('加载聊天历史失败:', error);
        }
    }

    async loadSessionIdFromLocalStorage() {
        try {
            if (!this.config.currentDocName) {
                console.log('📄 没有当前文档，跳过localStorage会话ID恢复');
                return;
            }

            // 优先从localStorage恢复session ID
            const savedState = this.loadDocumentStateFromLocal();
            if (savedState && savedState.currentChatId && savedState.currentDocName === this.config.currentDocName) {
                this.currentChatId = savedState.currentChatId;
                console.log('🔄 从localStorage恢复现有会话ID:', this.currentChatId);
                return;
            }

            // 如果localStorage中没有，查找后端是否有该文档的现有session
            const response = await fetch(this.getApiUrl('/api/v1/sessions/list'));
            const result = await response.json();

            if (response.ok && result.sessions) {
                // 查找与当前文档相关的所有会话
                const docSessions = Object.entries(result.sessions).filter(([sessionId, sessionData]) => {
                    return sessionData.docName === this.config.currentDocName;
                });

                if (docSessions.length > 0) {
                    // 使用最新的会话（按时间戳排序）
                    docSessions.sort((a, b) => b[1].timestamp - a[1].timestamp);
                    const [latestSessionId] = docSessions[0];
                    this.currentChatId = latestSessionId;
                    console.log('🔍 从后端找到现有文档会话ID:', latestSessionId);

                    // 保存到localStorage以便下次使用
                    this.saveDocumentStateToLocal();
                    return;
                }
            }

            // 如果都没有找到，创建新的基于文档的session ID
            this.currentChatId = this.generateDocumentSessionId(this.config.currentDocName);
            console.log('🆕 为文档创建新会话ID:', this.currentChatId);

            // 保存到localStorage
            this.saveDocumentStateToLocal();

        } catch (error) {
            console.error('恢复会话ID失败:', error);
            // 失败时创建新的session ID
            if (this.config.currentDocName) {
                this.currentChatId = this.generateDocumentSessionId(this.config.currentDocName);
                console.log('🛟 创建备用会话ID:', this.currentChatId);
            }
        }
    }

    async loadChatHistoryFromBackend() {
        try {
            // 确保有当前文档和会话ID
            if (!this.config.currentDocName || !this.currentChatId) {
                console.log('📄 没有当前文档或会话ID，跳过后端会话加载');
                return;
            }

            console.log('🔑 使用会话ID查找历史:', this.currentChatId);

            // 从后端加载会话列表
            const response = await fetch(this.getApiUrl('/api/v1/sessions/list'));
            const result = await response.json();

            if (response.ok && result.sessions) {
                // 查找与当前会话ID对应的会话
                const sessionData = result.sessions[this.currentChatId];

                if (sessionData && sessionData.messages && sessionData.messages.length > 0) {
                    console.log('✅ 从后端找到对应的会话数据:', sessionData);

                    // 🔥 修复消息格式兼容性
                    const messages = sessionData.messages.map(msg => {
                        // 如果是后端格式的消息对象，转换为数组格式
                        if (msg.role && msg.content && msg.timestamp) {
                            return [msg.role, msg.content, msg.timestamp];
                        }
                        // 如果已经是数组格式，直接使用
                        return msg;
                    });

                    // 清除欢迎消息
                    this.hideWelcomeMessage();

                    // 将历史消息存储到数组中
                    // 🔥 新增：加载时也应用消息队列限制，只保留最新 20 条
                    if (messages.length > this.maxHistorySize) {
                        const deletedCount = messages.length - this.maxHistorySize;
                        this.deletedMessageCount = deletedCount; // 记录已删除的消息数
                        messages.splice(0, deletedCount); // 只保留最新的消息
                        console.log(`📦 加载历史时应用队列限制: 删除了 ${deletedCount} 条旧消息`);
                    }
                    
                    this.chatHistory = [...messages];

                    // 显示在UI中，不再添加到历史记录
                    messages.forEach(([role, content, timestamp]) => {
                        this.addChatMessage(role, content, timestamp, false, false);
                    });

                    // 滚动到底部
                    this.scrollToBottom();

                    console.log('✅ 从后端加载会话历史成功，消息数量:', messages.length, this.getHistoryStatusString());
                } else {
                    console.log('📝 后端没有对应会话ID的数据:', this.currentChatId);
                }
            }
        } catch (error) {
            console.error('从后端加载会话历史失败:', error);
        }
    }

    async loadChatHistoryFromChatAPI() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/chat/history'));
            const data = await response.json();

            if (data.history && data.history.length > 0) {
                // 清除欢迎消息
                this.hideWelcomeMessage();

                // 先将历史消息存储到 chatHistory 数组中
                // 🔥 新增：应用消息队列限制，只保留最新 20 条
                let messages = [...data.history];
                if (messages.length > this.maxHistorySize) {
                    const deletedCount = messages.length - this.maxHistorySize;
                    this.deletedMessageCount = deletedCount; // 记录已删除的消息数
                    messages.splice(0, deletedCount); // 只保留最新的消息
                    console.log(`📦 加载历史时应用队列限制: 删除了 ${deletedCount} 条旧消息`);
                }
                
                this.chatHistory = [...messages];

                // 然后只显示在UI中，不再添加到历史记录
                messages.forEach(([role, content, timestamp]) => {
                    this.addChatMessage(role, content, timestamp, false, false);
                });

                // 滚动到底部
                this.scrollToBottom();

                console.log('✅ 从chat API加载聊天历史，消息数量:', messages.length, this.getHistoryStatusString());
            } else {
                console.log('📝 chat API没有聊天历史，显示欢迎页面');
            }
        } catch (error) {
            console.error('从chat API加载聊天历史失败:', error);
        }
    }

    async clearAllDataAndSessions() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/chat/clear'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.status === 'success') {
                // 清除所有本地会话数据
                this.chatSessions.clear();
                this.currentChatId = null;
                this.chatHistory = [];
                
                // 🔥 新增：重置消息队列统计
                this.deletedMessageCount = 0;

                // 清除本地存储
                this.clearDocumentStateFromLocal();
                localStorage.removeItem('llmreader_chat_sessions');

                // 重置配置和UI状态
                this.config.currentDocName = null;
                this.config.hasPdfReader = false;
                this.config.hasWebReader = false;
                this.updateDocumentStatus();
                this.displayNoPdfContent();

                this.clearChatMessages();
                this.showWelcomeMessage();

                console.log('🗑️ 已清空所有聊天数据和会话，消息队列已重置');
            }
        } catch (error) {
            console.error('清空聊天失败:', error);
        }
    }

    /* === 聊天界面方法 === */
    sendMessage() {
        const chatInput = document.getElementById('chat-input-full');
        const sendBtn = document.getElementById('send-btn-full');
        const message = chatInput.value.trim();

        // 检查连接状态和处理状态
        if (!message || !this.isConnected || this.isProcessing) return;

        // 设置处理状态为true
        this.isProcessing = true;

        // 禁用输入框和发送按钮
        chatInput.disabled = true;
        sendBtn.disabled = true;
        chatInput.placeholder = '正在处理您的问题，请稍等...';

        // 更新发送按钮状态
        const sendIcon = sendBtn.querySelector('.send-icon');
        const sendText = sendBtn.querySelector('.send-text');
        if (sendIcon) sendIcon.textContent = '⏳';
        if (sendText) sendText.textContent = '处理中';

        // 清空输入框
        chatInput.value = '';
        this.autoResizeTextarea(chatInput);

        // 隐藏欢迎消息和建议
        this.hideWelcomeMessage();

        // 添加处理状态消息
        this.addProcessingMessage();

        // 通过WebSocket发送消息
        this.websocket.send(JSON.stringify({
            message: message
        }));
    }

    addProcessingMessage() {
        const chatMessages = document.getElementById('chat-messages-full');

        // 移除之前的处理消息（如果存在）
        const existingProcessingMsg = chatMessages.querySelector('.processing-message');
        if (existingProcessingMsg) {
            existingProcessingMsg.remove();
        }

        const processingDiv = document.createElement('div');
        processingDiv.className = 'processing-message';
        processingDiv.innerHTML = `
            <div class="processing-indicator">
                <div class="processing-spinner"></div>
                <span class="processing-text">🤖 正在思考中...</span>
            </div>
        `;

        chatMessages.appendChild(processingDiv);
        this.scrollToBottom();
    }

    removeProcessingMessage() {
        const chatMessages = document.getElementById('chat-messages-full');
        const processingMsg = chatMessages.querySelector('.processing-message');
        if (processingMsg) {
            processingMsg.remove();
        }
    }

    restoreInputState() {
        const chatInput = document.getElementById('chat-input-full');
        const sendBtn = document.getElementById('send-btn-full');

        // 恢复处理状态
        this.isProcessing = false;

        // 启用输入框和发送按钮
        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatInput.placeholder = '请输入您的问题…';

        // 恢复发送按钮状态
        const sendIcon = sendBtn.querySelector('.send-icon');
        const sendText = sendBtn.querySelector('.send-text');
        if (sendIcon) sendIcon.textContent = '📤';
        if (sendText) sendText.textContent = '发送';

        // 移除处理消息
        this.removeProcessingMessage();

        // 聚焦输入框
        chatInput.focus();
    }

    addChatMessage(role, content, timestamp, shouldScroll = true, addToHistory = true) {
        const chatMessages = document.getElementById('chat-messages-full');

        // 移除欢迎消息
        this.hideWelcomeMessage();

        console.log(`📨 添加消息: role=${role}, contentLength=${content.length}, addToHistory=${addToHistory}`);

        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${role}`;

        const avatar = document.createElement('div');
        avatar.className = `message-avatar ${role}`;
        avatar.textContent = role === 'user' ? '👤' : '🤖';

        const messageContent = document.createElement('div');
        messageContent.className = `message-content ${role}`;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'tex2jax_process';
        
        // 渲染Markdown内容
        console.log(`🔄 正在渲染Markdown...`);
        const renderedContent = this.renderMarkdown(content);
        console.log(`✓ Markdown渲染完成，输出长度: ${renderedContent.length}`);
        
        contentDiv.innerHTML = renderedContent;
        console.log(`✓ innerHTML已设置`);
        console.log(`📝 设置后的 innerHTML:`, contentDiv.innerHTML.substring(0, 150));
        console.log(`📝 设置后的 textContent:`, contentDiv.textContent.substring(0, 150));
        console.log(`📝 包含$符号: ${contentDiv.innerHTML.includes('$') || contentDiv.textContent.includes('$')}`);

        const timeDiv = document.createElement('div');
        timeDiv.className = 'message-time';
        timeDiv.textContent = new Date(timestamp).toLocaleTimeString();

        messageContent.appendChild(contentDiv);
        messageContent.appendChild(timeDiv);

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(messageContent);

        chatMessages.appendChild(messageDiv);
        console.log(`✓ DOM元素已添加到页面`);
        
        // 再次验证DOM中的内容
        console.log(`🔍 验证 DOM 中的实际内容:`, {
            innerHTML: contentDiv.innerHTML.substring(0, 150),
            textContent: contentDiv.textContent.substring(0, 150),
            has$: contentDiv.innerHTML.includes('$'),
            hasBackslash: contentDiv.innerHTML.includes('\\')
        });

        // 只有在需要时才添加到聊天历史（避免重复添加）
        if (addToHistory) {
            this.chatHistory.push([role, content, timestamp]);
            
            // 🔥 新增：维护消息队列大小，限制最多 20 条消息
            this.maintainHistorySize();

            // 确保有聊天ID
            this.getCurrentChatId();

            // 保存状态到本地存储
            this.saveDocumentStateToLocal();

            // 🔥 优化：延迟保存，使用防抖机制避免频繁保存
            if (this.saveTimeout) {
                clearTimeout(this.saveTimeout);
            }
            this.saveTimeout = setTimeout(() => {
                this.saveChatSessionToBackend();
            }, 3000); // 延迟3秒保存，并且只保存最后一次更新
        }

        if (shouldScroll) {
            this.scrollToBottom();
        }

        // 🔥 改进：使用 requestAnimationFrame 确保 DOM 已完全渲染
        // 然后再调用 MathJax，避免时序问题
        requestAnimationFrame(() => {
            console.log(`🎯 DOM已渲染，调用 renderMath()，role=${role}`);
            console.log(`📝 contentDiv内容: ${contentDiv.innerHTML.substring(0, 150)}`);
            console.log(`🔍 是否包含LaTeX: ${/\$|\\\(|\\\[/.test(contentDiv.innerHTML)}`);
            this.renderMath(contentDiv);
        });
    }

    /* === 消息队列管理 === */
    
    /**
     * 维护聊天历史大小，限制最多保留 maxHistorySize 条消息
     * 当超过限制时，删除最老的消息（FIFO 队列）
     */
    maintainHistorySize() {
        if (this.chatHistory.length > this.maxHistorySize) {
            // 计算需要删除的消息数量
            const messagesToDelete = this.chatHistory.length - this.maxHistorySize;
            
            // 删除最老的消息
            this.chatHistory.splice(0, messagesToDelete);
            this.deletedMessageCount += messagesToDelete;
            
            // 同步删除 UI 中的消息
            const chatMessages = document.getElementById('chat-messages-full');
            const messages = chatMessages.querySelectorAll('.chat-message');
            
            for (let i = 0; i < messagesToDelete && i < messages.length; i++) {
                messages[i].remove();
            }
            
            console.log(`📦 消息队列已维护: 删除了 ${messagesToDelete} 条旧消息，当前保留 ${this.chatHistory.length} 条，总删除数: ${this.deletedMessageCount}`);
        }
    }
    
    /**
     * 获取聊天历史统计信息
     */
    getHistoryStats() {
        return {
            currentSize: this.chatHistory.length,
            maxSize: this.maxHistorySize,
            deletedCount: this.deletedMessageCount,
            isFull: this.chatHistory.length >= this.maxHistorySize
        };
    }
    
    /**
     * 获取消息队列状态字符串（用于日志）
     */
    getHistoryStatusString() {
        const stats = this.getHistoryStats();
        return `[${stats.currentSize}/${stats.maxSize}] (已删${stats.deletedCount}条)`;
    }

    addStatusMessage(message) {
        const chatMessages = document.getElementById('chat-messages-full');

        const statusDiv = document.createElement('div');
        statusDiv.className = 'status-message-chat';
        statusDiv.textContent = message;

        chatMessages.appendChild(statusDiv);
        this.scrollToBottom();

        // 5秒后移除状态消息
        setTimeout(() => {
            if (statusDiv.parentNode) {
                statusDiv.remove();
            }
        }, 5000);
    }

    clearChatMessages() {
        const chatMessages = document.getElementById('chat-messages-full');
        // 清除所有聊天消息，但保留欢迎消息结构
        const messages = chatMessages.querySelectorAll('.chat-message, .status-message-chat');
        messages.forEach(msg => msg.remove());
    }

    hideWelcomeMessage() {
        const welcomeMessage = document.querySelector('.welcome-message-full');
        if (welcomeMessage) {
            welcomeMessage.style.display = 'none';
        }
    }

    showWelcomeMessage() {
        const welcomeMessage = document.querySelector('.welcome-message-full');
        if (welcomeMessage) {
            welcomeMessage.style.display = 'flex';
        }
    }

    showQuickSuggestions() {
        const suggestions = document.getElementById('quick-suggestions');
        const statusElement = document.getElementById('welcome-doc-status');

        if (suggestions && this.config.currentDocName) {
            suggestions.style.display = 'block';
            statusElement.innerHTML = `
                <span class="status-text" style="background: var(--success-color); color: white;">
                    ✅ 已加载文档: ${this.config.currentDocName}
                </span>
            `;
        }
    }

    scrollToBottom() {
        const chatMessages = document.getElementById('chat-messages-full');
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    autoResizeTextarea(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
    }

    /* === UI状态更新 === */
    updateConnectionStatus(status, message) {
        const indicator = document.getElementById('status-indicator-full');
        const text = document.getElementById('status-text-full');

        indicator.className = `status-indicator-full ${status}`;
        text.textContent = message;
    }

    updateDocumentStatus() {
        const docStatus = document.getElementById('chat-current-doc');

        if (this.config.currentDocName) {
            docStatus.textContent = this.config.currentDocName;
            docStatus.style.color = 'var(--success-color)';
        } else {
            docStatus.textContent = '未加载文档';
            docStatus.style.color = 'inherit';
        }
    }

    enableChatInput() {
        const chatInput = document.getElementById('chat-input-full');
        const sendBtn = document.getElementById('send-btn-full');

        // 只有在非处理状态下才启用输入
        if (!this.isProcessing) {
            chatInput.disabled = false;
            sendBtn.disabled = false;
            chatInput.placeholder = '请输入您的问题…';

            // 恢复发送按钮状态
            const sendIcon = sendBtn.querySelector('.send-icon');
            const sendText = sendBtn.querySelector('.send-text');
            if (sendIcon) sendIcon.textContent = '📤';
            if (sendText) sendText.textContent = '发送';
        }
    }

    disableChatInput() {
        const chatInput = document.getElementById('chat-input-full');
        const sendBtn = document.getElementById('send-btn-full');

        chatInput.disabled = true;
        sendBtn.disabled = true;

        if (this.isProcessing) {
            chatInput.placeholder = '正在处理您的问题，请稍等...';
        } else {
            chatInput.placeholder = '连接中断，请等待重连...';
        }
    }

    /* === PDF查看器方法 === */
    togglePdfViewer() {
        const pdfViewer = document.getElementById('chat-pdf-viewer');
        const conversation = document.getElementById('chat-conversation');

        this.pdfViewerVisible = !this.pdfViewerVisible;

        if (this.pdfViewerVisible) {
            pdfViewer.classList.remove('hidden');
            conversation.classList.remove('full-width');
        } else {
            pdfViewer.classList.add('hidden');
            conversation.classList.add('full-width');
        }
    }

    hidePdfViewer() {
        const pdfViewer = document.getElementById('chat-pdf-viewer');
        const conversation = document.getElementById('chat-conversation');

        this.pdfViewerVisible = false;
        pdfViewer.classList.add('hidden');
        conversation.classList.add('full-width');
    }


    async loadPdfViewer() {
        if (!this.config.currentDocName) {
            console.log('❌ loadPdfViewer: 没有文档名');
            return;
        }

        // 根据文档类型加载不同内容
        const documentType = this.config.documentType || (this.config.hasPdfReader ? 'pdf' : 'web');
        console.log(`🔍 开始加载${documentType}内容，文档名:`, this.config.currentDocName);

        if (documentType === 'web') {
            // Web 内容：显示摘要
            await this.loadWebContent();
        } else {
            // PDF 内容：显示 PDF 查看器
            try {
                console.log('📄 尝试加载PDF文件...');
                await this.tryLoadPdfFile();
            } catch (error) {
                console.log('📄 无法加载PDF文件，尝试加载图片:', error);
                await this.tryLoadPdfImages();
            }
        }
    }

    async loadWebContent() {
        console.log('🌐 开始加载Web内容摘要...');

        try {
            const response = await fetch(this.getApiUrl(`/api/v1/web/summary/${this.config.currentDocName}?summary_type=brief`));
            const result = await response.json();

            if (result.status === 'success' && result.content) {
                console.log('✅ 成功加载Web摘要');
                this.displayWebContent(result.content);
            } else if (result.is_large_file) {
                // 大文件模式，显示提示信息
                this.displayWebLargeFileNotice();
            } else {
                console.log('❌ Web摘要未生成');
                this.displayNoWebContent(result.message);
            }
        } catch (error) {
            console.error('❌ 加载Web内容失败:', error);
            this.displayNoWebContent('加载Web内容时发生错误');
        }
    }

    displayWebContent(markdownContent) {
        const content = document.getElementById('pdf-viewer-content-full');

        // 使用 marked 库渲染 Markdown（如果可用）
        let htmlContent;
        if (typeof marked !== 'undefined') {
            htmlContent = marked.parse(markdownContent);
        } else {
            // 简单的 Markdown 到 HTML 转换
            htmlContent = markdownContent.replace(/\n/g, '<br>');
        }

        content.innerHTML = `
            <div class="web-content-viewer" style="padding: 20px; height: 100%; overflow-y: auto; background: white;">
                <div class="web-content-header" style="margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid #e9ecef;">
                    <h3 style="margin: 0; color: #2c3e50;">📄 网页内容摘要</h3>
                    <p style="margin: 5px 0 0 0; color: #6c757d; font-size: 0.9em;">${this.config.currentDocName}</p>
                </div>
                <div class="web-content-body" style="line-height: 1.6; color: #333;">
                    ${htmlContent}
                </div>
            </div>
        `;

        // 隐藏PDF翻页按钮
        document.getElementById('pdf-page-info-full').textContent = 'Web内容';
        document.getElementById('pdf-prev-page-full').style.display = 'none';
        document.getElementById('pdf-next-page-full').style.display = 'none';
    }

    displayWebLargeFileNotice() {
        const content = document.getElementById('pdf-viewer-content-full');
        content.innerHTML = `
            <div class="no-document-message">
                <div class="no-doc-content">
                    <span class="no-doc-icon">🌐</span>
                    <h3>大文件模式</h3>
                    <p>该网页内容较大，已使用向量数据库存储。</p>
                    <p style="color: #6c757d;">请直接使用聊天功能进行问答。</p>
                </div>
            </div>
        `;

        document.getElementById('pdf-page-info-full').textContent = 'Web内容（大文件）';
        document.getElementById('pdf-prev-page-full').style.display = 'none';
        document.getElementById('pdf-next-page-full').style.display = 'none';
    }

    displayNoWebContent(message) {
        const content = document.getElementById('pdf-viewer-content-full');
        content.innerHTML = `
            <div class="no-document-message">
                <div class="no-doc-content">
                    <span class="no-doc-icon">🌐</span>
                    <h3>Web内容未就绪</h3>
                    <p>${message || 'Web内容摘要尚未生成'}</p>
                    <p style="color: #6c757d;">请返回主页面重新处理URL。</p>
                </div>
            </div>
        `;

        document.getElementById('pdf-page-info-full').textContent = 'Web内容';
        document.getElementById('pdf-prev-page-full').style.display = 'none';
        document.getElementById('pdf-next-page-full').style.display = 'none';
    }

    async tryLoadPdfFile() {
        const response = await fetch(this.getApiUrl(`/api/v1/pdf/file/${this.config.currentDocName}`));

        if (response.ok) {
            const blob = await response.blob();
            this.pdfViewerState.pdfUrl = URL.createObjectURL(blob);
            this.displayPdfFile();
        } else {
            throw new Error('PDF文件不可用');
        }
    }

    async tryLoadPdfImages() {
        console.log('🖼️ 尝试加载PDF图片...');
        const response = await fetch(this.getApiUrl(`/api/v1/pdf/images/${this.config.currentDocName}`));
        const result = await response.json();
        console.log('🖼️ 图片API响应:', result);

        if (result.status === 'success') {
            console.log('✅ 成功加载PDF图片，数量:', result.images.length);
            this.pdfViewerState.images = result.images;
            this.pdfViewerState.totalPages = result.images.length;
            this.displayPdfImages();
        } else {
            console.log('❌ 加载PDF图片失败');
            this.displayNoPdfContent();
        }
    }

    displayPdfFile() {
        const content = document.getElementById('pdf-viewer-content-full');
        content.innerHTML = `
            <embed src="${this.pdfViewerState.pdfUrl}"
                   type="application/pdf"
                   class="pdf-embedded-full">
        `;

        document.getElementById('pdf-page-info-full').textContent = 'PDF文件模式';
        document.getElementById('pdf-prev-page-full').style.display = 'none';
        document.getElementById('pdf-next-page-full').style.display = 'none';
    }

    displayPdfImages() {
        if (this.pdfViewerState.images.length === 0) {
            this.displayNoPdfContent();
            return;
        }

        this.pdfViewerState.totalPages = this.pdfViewerState.images.length;
        this.updatePdfPage();
    }

    updatePdfPage() {
        const content = document.getElementById('pdf-viewer-content-full');
        const currentImage = this.pdfViewerState.images[this.pdfViewerState.currentPage - 1];

        if (currentImage) {
            content.innerHTML = `
                <div class="pdf-page-display-full">
                    <img src="${this.getApiUrl(currentImage.url)}"
                         alt="PDF第${currentImage.page}页"
                         class="pdf-page-image-full">
                </div>
            `;
        }

        this.updatePdfControls();
    }

    updatePdfControls() {
        const pageInfo = document.getElementById('pdf-page-info-full');
        const prevBtn = document.getElementById('pdf-prev-page-full');
        const nextBtn = document.getElementById('pdf-next-page-full');

        pageInfo.textContent = `第 ${this.pdfViewerState.currentPage} 页 / 共 ${this.pdfViewerState.totalPages} 页`;

        prevBtn.disabled = this.pdfViewerState.currentPage <= 1;
        nextBtn.disabled = this.pdfViewerState.currentPage >= this.pdfViewerState.totalPages;

        prevBtn.style.display = 'inline-block';
        nextBtn.style.display = 'inline-block';
    }

    displayNoPdfContent() {
        const content = document.getElementById('pdf-viewer-content-full');
        content.innerHTML = `
            <div class="no-document-message">
                <div class="no-doc-content">
                    <span class="no-doc-icon">📄</span>
                    <h3>暂无文档</h3>
                    <p>请先在主页面上传并处理文档</p>
                    <a href="/" class="btn btn-primary">前往主页面</a>
                </div>
            </div>
        `;

        document.getElementById('pdf-page-info-full').textContent = '无内容';
        document.getElementById('pdf-prev-page-full').style.display = 'none';
        document.getElementById('pdf-next-page-full').style.display = 'none';
    }

    previousPdfPage() {
        if (this.pdfViewerState.currentPage > 1) {
            this.pdfViewerState.currentPage--;
            this.updatePdfPage();
        }
    }

    nextPdfPage() {
        if (this.pdfViewerState.currentPage < this.pdfViewerState.totalPages) {
            this.pdfViewerState.currentPage++;
            this.updatePdfPage();
        }
    }

    /* === UUID生成和会话管理方法 === */

    generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    // 🔥 新增：基于文档名生成固定的会话ID
    generateDocumentSessionId(docName) {
        if (!docName) return this.generateUUID();

        // 使用简单的哈希算法基于文档名生成固定的UUID
        let hash = 0;
        for (let i = 0; i < docName.length; i++) {
            const char = docName.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // 转换为32位整数
        }

        // 将哈希值转换为UUID格式
        const hashStr = Math.abs(hash).toString(16).padStart(8, '0');
        const sessionId = `doc-${hashStr}-xxxx-4xxx-yxxx-xxxxxxxxxxxx`.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });

        console.log('🔑 聊天页面为文档生成固定会话ID:', docName, '->', sessionId);
        return sessionId;
    }

    getCurrentChatId() {
        if (!this.currentChatId) {
            // 🔥 关键修复：如果有文档，基于文档名生成固定的会话ID
            if (this.config.currentDocName) {
                this.currentChatId = this.generateDocumentSessionId(this.config.currentDocName);
                console.log('🔑 聊天页面基于文档生成固定聊天会话ID:', this.currentChatId);
            } else {
                this.currentChatId = this.generateUUID();
                console.log('🆕 聊天页面生成随机聊天会话ID:', this.currentChatId);
            }
        }
        return this.currentChatId;
    }

    /* === 简化的聊天管理方法 === */

    clearCurrentChat() {
        // 清空当前聊天历史（但保持文档状态）
        this.chatHistory = [];
        
        // 🔥 新增：重置消息队列统计
        console.log(`🗑️ 清空当前对话历史 ${this.getHistoryStatusString()}`);
        this.deletedMessageCount = 0; // 重置已删除计数

        // 如果正在处理中，恢复输入状态
        if (this.isProcessing) {
            this.restoreInputState();
        }

        // 清空聊天UI并显示欢迎消息
        this.clearChatMessages();
        this.showWelcomeMessage();

        // 如果有文档，显示快速建议
        if (this.config.currentDocName) {
            this.showQuickSuggestions();
        }
    }

    reloadChatMessages() {
        this.clearChatMessages();

        if (this.chatHistory.length > 0) {
            // 隐藏欢迎消息
            this.hideWelcomeMessage();

            // 重新加载所有消息 - 注意: 传递 addToHistory = false 避免重复添加到历史记录
            this.chatHistory.forEach(([role, content, timestamp]) => {
                this.addChatMessage(role, content, timestamp, false, false);
            });

            // 滚动到底部
            this.scrollToBottom();
        } else {
            // 如果没有历史消息，显示欢迎消息
            this.showWelcomeMessage();
        }
    }

    forceRefreshChatInterface() {
        console.log('🔄 强制刷新聊天界面');

        // 清空聊天历史
        this.chatHistory = [];

        // 清空聊天消息
        this.clearChatMessages();

        // 显示欢迎消息
        this.showWelcomeMessage();

        // 更新文档状态显示
        this.updateDocumentStatus();

        console.log('✅ 聊天界面刷新完成');
    }

    async saveChatSessionToBackend() {
        // 🔥 优化：更严格的保存条件检查
        if (!this.currentChatId || !this.config.currentDocName || this.chatHistory.length === 0) {
            console.log('⏭️ 跳过保存会话到后端：缺少必要条件', {
                chatId: !!this.currentChatId,
                docName: !!this.config.currentDocName,
                historyLength: this.chatHistory.length
            });
            return;
        }

        // 🔥 优化：检查是否有实际的用户消息，避免保存空会话
        const userMessages = this.chatHistory.filter(([role]) => role === 'user');
        if (userMessages.length === 0) {
            console.log('⏭️ 跳过保存会话：没有用户消息');
            return;
        }

        try {
            const sessionData = {
                chatId: this.currentChatId,
                docName: this.config.currentDocName,
                messages: [...this.chatHistory],
                timestamp: Date.now(),
                hasPdfReader: this.config.hasPdfReader,
                hasWebReader: this.config.hasWebReader,
                provider: this.config.provider
            };

            const response = await fetch(this.getApiUrl('/api/v1/sessions/add'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(sessionData)
            });

            if (response.ok) {
                console.log('💾 会话已保存到后端文件系统:', this.currentChatId, '用户消息数:', userMessages.length);
            } else {
                console.error('❌ 保存会话到后端失败:', response.status);
            }
        } catch (error) {
            console.error('❌ 保存会话到后端时发生错误:', error);
        }
    }

    /* === 本地状态持久化方法 === */

    saveDocumentStateToLocal() {
        const documentState = {
            currentDocName: this.config.currentDocName,
            hasPdfReader: this.config.hasPdfReader,
            hasWebReader: this.config.hasWebReader,
            provider: this.config.provider,
            currentChatId: this.currentChatId, // 添加当前聊天会话ID
            timestamp: Date.now() // 添加时间戳以便验证状态的有效性
        };

        try {
            localStorage.setItem('llmreader_document_state', JSON.stringify(documentState));
            console.log('💾 文档状态已保存到本地存储:', documentState.currentDocName);
        } catch (error) {
            console.error('保存文档状态失败:', error);
        }
    }

    loadDocumentStateFromLocal() {
        try {
            const savedState = localStorage.getItem('llmreader_document_state');
            if (!savedState) return null;

            const documentState = JSON.parse(savedState);

            // 检查状态是否过期（24小时）
            const MAX_AGE = 24 * 60 * 60 * 1000; // 24小时
            if (Date.now() - documentState.timestamp > MAX_AGE) {
                console.log('📅 本地存储的文档状态已过期，清除');
                this.clearDocumentStateFromLocal();
                return null;
            }

            // 恢复聊天会话ID
            if (documentState.currentChatId) {
                this.currentChatId = documentState.currentChatId;
                console.log('🔄 聊天页面恢复聊天会话ID:', this.currentChatId);
            }

            console.log('📖 从本地存储加载文档状态:', documentState.currentDocName);
            return documentState;
        } catch (error) {
            console.error('加载文档状态失败:', error);
            return null;
        }
    }

    clearDocumentStateFromLocal() {
        try {
            localStorage.removeItem('llmreader_document_state');
            console.log('🗑️ 已清除本地存储的文档状态');
        } catch (error) {
            console.error('清除文档状态失败:', error);
        }
    }

    /* === 工具方法 === */
    exportChat() {
        const messages = [];
        document.querySelectorAll('.chat-message').forEach(msg => {
            const role = msg.classList.contains('user') ? 'User' : 'Assistant';
            const content = msg.querySelector('.message-content .tex2jax_process').textContent;
            const time = msg.querySelector('.message-time').textContent;
            messages.push(`[${time}] ${role}: ${content}`);
        });

        const chatContent = messages.join('\n\n');
        const blob = new Blob([chatContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `chat_history_${new Date().toISOString().split('T')[0]}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /* === Markdown和LaTeX渲染 === */
    renderMarkdown(content) {
        if (typeof content !== 'string') {
            console.warn('⚠️ 内容不是字符串:', typeof content);
            return content;
        }

        const hasLatex = /\$\$[\s\S]*?\$\$|\$[^\$\n]+?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/.test(content);
        const isMarkdownContent = this.isMarkdown(content);
        const isComplexMarkdownContent = this.isComplexMarkdown(content);

        console.log(`📝 renderMarkdown 输入分析:`, {
            contentLength: content.length,
            hasLatex: hasLatex,
            isMarkdownContent: isMarkdownContent,
            isComplexMarkdownContent: isComplexMarkdownContent,
            preview: content.substring(0, 100)
        });

        // 🔥 调整修复逻辑：只有在纯LaTeX内容时才跳过Markdown渲染
        // 对于包含LaTeX的Markdown，使用改进的保护机制
        if (hasLatex && !isComplexMarkdownContent && !isMarkdownContent) {
            // 只有当内容不是Markdown且不是复杂结构时，才使用简单处理
            console.log(`🔧 检测到纯LaTeX内容，使用简单换行处理避免公式被破坏`);
            return content.replace(/\n/g, '<br>');
        }

        // 🔥 对于极高密度LaTeX内容（80%以上都是公式），也直接使用简单处理
        if (hasLatex) {
            const latexMatches = content.match(/\$\$[\s\S]*?\$\$|\$[^\$\n]+?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/g) || [];
            const latexLength = latexMatches.reduce((sum, match) => sum + match.length, 0);
            const latexRatio = latexLength / content.length;

            if (latexRatio > 0.8) { // 提高阈值到80%
                console.log(`🔧 检测到极高密度LaTeX公式 (${(latexRatio * 100).toFixed(1)}%)，使用简单处理避免渲染冲突`);
                return content.replace(/\n/g, '<br>');
            }
        }

        if (isMarkdownContent) {
            if (typeof marked !== 'undefined') {
                try {
                    marked.setOptions({
                        breaks: true,
                        gfm: true,
                        sanitize: false,
                        smartLists: true,
                        smartypants: false,
                        headerIds: false,
                        mangle: false
                    });

                    // 🔧 改进：保护 LaTeX 公式不被 Markdown 渲染器破坏
                    let processedContent = content;
                    const latexBlocks = [];
                    const latexInline = [];
                    const latexMathEnvs = [];
                    
                    console.log(`📝 开始处理Markdown，检测到LaTeX: ${hasLatex}`);
                    
                    // 🔥 关键改进：使用 HTML 标签作为占位符，避免被 Markdown 处理
                    // Step 0: 提取 \[...\] 和 \(...\) 环境（必须最先）
                    processedContent = processedContent.replace(/\\\[[\s\S]*?\\\]/g, (match) => {
                        const idx = latexMathEnvs.length;
                        latexMathEnvs.push(match);
                        const placeholder = `<latex-placeholder-mathenv-${idx}></latex-placeholder-mathenv-${idx}>`;
                        console.log(`🔒 保护 \\[...\\] 公式: ${match.substring(0, 40)}... → 占位符-${idx}`);
                        return placeholder;
                    });
                    
                    processedContent = processedContent.replace(/\\\([\s\S]*?\\\)/g, (match) => {
                        const idx = latexMathEnvs.length;
                        latexMathEnvs.push(match);
                        const placeholder = `<latex-placeholder-paren-${idx}></latex-placeholder-paren-${idx}>`;
                        console.log(`🔒 保护 \\(...\\) 公式: ${match.substring(0, 40)}... → 占位符-${idx}`);
                        return placeholder;
                    });
                    
                    // Step 1: 提取块级公式 $$...$$ (必须在行内公式之前)
                    processedContent = processedContent.replace(/\$\$[\s\S]*?\$\$/g, (match) => {
                        const idx = latexBlocks.length;
                        latexBlocks.push(match);
                        const placeholder = `<latex-placeholder-block-${idx}></latex-placeholder-block-${idx}>`;
                        console.log(`🔒 保护块级公式: ${match.substring(0, 40)}... → 占位符-${idx}`);
                        return placeholder;
                    });
                    
                    // Step 2: 提取行内公式 $...$ (但要避免 $$)
                    // 🔥 改进：更严格的行内公式检测，避免误匹配
                    processedContent = processedContent.replace(/(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)/g, (match) => {
                        // 再次检查，确保不是 $$ 的一部分
                        if (!match.includes('$$')) {
                            const idx = latexInline.length;
                            latexInline.push(match);
                            const placeholder = `<latex-placeholder-inline-${idx}></latex-placeholder-inline-${idx}>`;
                            console.log(`🔒 保护行内公式: ${match.substring(0, 40)}... → 占位符-${idx}`);
                            return placeholder;
                        }
                        return match;
                    });
                    
                    console.log(`✓ 提取完成: ${latexMathEnvs.length} 个Math环境 + ${latexBlocks.length} 个块级 + ${latexInline.length} 个行内`);
                    console.log(`📋 处理后的内容预览: ${processedContent.substring(0, 100)}`);
                    
                    // Step 3: 渲染 Markdown
                    let rendered = marked.parse(processedContent);
                    console.log(`✓ Markdown渲染完成，输出长度: ${rendered.length}`);
                    console.log(`📄 渲染后的HTML预览: ${rendered.substring(0, 100)}`);
                    
                    // 🔥 关键改进：使用简单的字符串替换恢复占位符，避免正则表达式的复杂性
                    // 因为占位符现在是 HTML 标签，不会被 Marked 处理，可以直接替换
                    
                    // Step 4a: 恢复 Math 环境占位符
                    latexMathEnvs.forEach((latex, index) => {
                        // 尝试恢复所有可能的占位符格式
                        const placeholder1 = `<latex-placeholder-mathenv-${index}></latex-placeholder-mathenv-${index}>`;
                        const placeholder2 = `<latex-placeholder-paren-${index}></latex-placeholder-paren-${index}>`;
                        
                        if (rendered.includes(placeholder1)) {
                            rendered = rendered.replace(placeholder1, latex);
                            console.log(`✓ 恢复 Math环境 #${index} (格式1): 成功`);
                        } else if (rendered.includes(placeholder2)) {
                            rendered = rendered.replace(placeholder2, latex);
                            console.log(`✓ 恢复 Math环境 #${index} (格式2): 成功`);
                        } else {
                            console.warn(`⚠️ 未找到 Math环境 #${index} 的占位符: ${placeholder1}`);
                        }
                    });
                    
                    // Step 4b: 恢复块级公式占位符
                    latexBlocks.forEach((latex, index) => {
                        const placeholder = `<latex-placeholder-block-${index}></latex-placeholder-block-${index}>`;
                        if (rendered.includes(placeholder)) {
                            rendered = rendered.replace(placeholder, latex);
                            console.log(`✓ 恢复块级公式 #${index}: 成功，内容: ${latex.substring(0, 50)}`);
                        } else {
                            console.warn(`⚠️ 未找到块级公式 #${index} 的占位符: ${placeholder}`);
                        }
                    });
                    
                    // Step 4c: 恢复行内公式占位符
                    latexInline.forEach((latex, index) => {
                        const placeholder = `<latex-placeholder-inline-${index}></latex-placeholder-inline-${index}>`;
                        if (rendered.includes(placeholder)) {
                            rendered = rendered.replace(placeholder, latex);
                            console.log(`✓ 恢复行内公式 #${index}: 成功，内容: ${latex.substring(0, 50)}`);
                        } else {
                            console.warn(`⚠️ 未找到行内公式 #${index} 的占位符: ${placeholder}`);
                        }
                    });

                    if (hasLatex) {
                        console.log(`✓ Markdown渲染完成，最终输出长度: ${rendered.length}`);
                        // 验证LaTeX公式是否正确恢复到输出中
                        const allLatex = latexMathEnvs.concat(latexBlocks).concat(latexInline);
                        const latexInOutput = allLatex.every(latex => rendered.includes(latex));
                        console.log(`✓ LaTeX恢复验证: ${latexInOutput ? '✅ 成功 - 所有公式已恢复' : '⚠️ 部分失败'}`);
                        if (!latexInOutput) {
                            console.warn('⚠️ 部分LaTeX公式未能正确恢复');
                            allLatex.forEach((latex, idx) => {
                                if (!rendered.includes(latex)) {
                                    console.warn(`  缺失 #${idx}: ${latex.substring(0, 60)}...`);
                                }
                            });
                        }
                    }

                    // 最终修复：处理被Markdown错误包裹的LaTeX公式（如果有遗漏的话）
                    if (hasLatex) {
                        // 修复被code标签包裹的LaTeX公式
                        rendered = rendered.replace(/<code>(\$[^<]+?\$)<\/code>/g, '$1');
                        rendered = rendered.replace(/<code>(\$\$[^<]*?\$\$)<\/code>/g, '$1');
                        rendered = rendered.replace(/<code>\\(?:\(|\[)[^<]*?\\(?:\)|\])<\/code>/g, '$0');
                        
                        // 修复被 em/strong 标签包裹的公式
                        rendered = rendered.replace(/<em>(\$[^<]*?\$)<\/em>/g, '$1');
                        rendered = rendered.replace(/<strong>(\$[^<]*?\$)<\/strong>/g, '$1');

                        console.log(`🔧 执行LaTeX后处理修复`);
                    }

                    return rendered;
                } catch (error) {
                    console.warn('❌ Marked渲染失败:', error);
                    return content.replace(/\n/g, '<br>');
                }
            }
        }
        
        // 如果不是Markdown或没有marked库，返回简单处理
        const simpleResult = content.replace(/\n/g, '<br>');
        console.log(`ℹ️ 内容不是Markdown或没有marked库，使用简单处理`, {
            isMarkdown: isMarkdownContent,
            markedAvailable: typeof marked !== 'undefined',
            result: simpleResult.substring(0, 100)
        });
        return simpleResult;
    }

    isMarkdown(content) {
        const markdownPatterns = [
            /^#{1,6}\s/m,           // 标题
            /\*\*.*?\*\*/,          // 粗体
            /\*[^*\s].*?\*/,        // 斜体
            /`[^`]+`/,              // 行内代码
            /```[\s\S]*?```/,       // 代码块
            /^\s*[-+*]\s/m,         // 无序列表
            /^\s*\d+\.\s/m,         // 有序列表
            /\[.*?\]\(.*?\)/,       // 链接
            /!\[.*?\]\(.*?\)/,      // 图片
            /^>\s/m,                // 引用块
            /^\s*\|.*\|/m,          // 表格
            /^---+$/m               // 分隔线
            // 🔥 移除LaTeX检测，因为现在有专门的LaTeX处理逻辑
        ];

        return markdownPatterns.some(pattern => pattern.test(content));
    }

    // 🔥 新增：检测是否为复杂Markdown（包含结构化元素）
    isComplexMarkdown(content) {
        const complexPatterns = [
            /^#{1,6}\s/m,           // 标题
            /```[\s\S]*?```/,       // 代码块
            /^\s*[-+*]\s/m,         // 无序列表
            /^\s*\d+\.\s/m,         // 有序列表
            /\[.*?\]\(.*?\)/,       // 链接
            /!\[.*?\]\(.*?\)/,      // 图片
            /^>\s/m,                // 引用块
            /^\s*\|.*\|/m,          // 表格
            /^---+$/m               // 分隔线
        ];

        return complexPatterns.some(pattern => pattern.test(content));
    }

    // 🔥 新增：转义正则表达式特殊字符
    _escapeRegex(str) {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    renderMath(element) {
        if (!element) {
            console.warn('⚠️ 元素为空，无法渲染数学公式');
            return;
        }

        if (typeof MathJax === 'undefined') {
            console.warn('⚠️ MathJax 未加载，重试中...');
            // MathJax 还没加载，延迟重试
            setTimeout(() => this.renderMath(element), 500);
            return;
        }

        // 🔥 改进：检查元素是否真的在DOM中
        if (!document.contains(element)) {
            console.warn('⚠️ 元素不在DOM中，无法渲染');
            return;
        }

        // 🔥 强制检测和准备LaTeX内容
        const hasLatexContent = /\$[\s\S]*?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/.test(element.innerHTML);
        console.log('🔄 开始渲染数学公式...');
        console.log(`📝 元素内容: ${element.innerHTML.substring(0, 150)}`);
        console.log(`🔍 检测到LaTeX内容: ${hasLatexContent}`);

        if (!hasLatexContent) {
            console.log('ℹ️ 未检测到LaTeX内容，跳过MathJax渲染');
            return;
        }

        // 🔥 强制标记元素为需要处理的类
        element.classList.add('tex2jax_process');
        element.classList.remove('tex2jax_ignore');

        // 方案1：如果 MathJax.startup.promise 存在，使用最新的API
        if (MathJax.startup && MathJax.startup.promise) {
            console.log('📡 使用 MathJax 3.x API (通过 startup.promise)');
            MathJax.startup.promise
                .then(() => {
                    console.log('✓ MathJax 已准备好');
                    this._performTypesetAsync(element);
                })
                .catch((err) => {
                    console.warn('❌ MathJax.startup.promise 错误:', err);
                    this._performTypesetAsync(element);
                });
        } else if (MathJax.typesetPromise) {
            // 方案2：直接调用 typesetPromise（备用方案）
            console.log('📡 直接使用 typesetPromise');
            this._performTypesetAsync(element);
        } else {
            console.warn('❌ MathJax API 不可用，重试中...');
            setTimeout(() => this.renderMath(element), 500);
        }
    }

    _performTypesetAsync(element) {
        try {
            // 标记此元素应被处理
            element.classList.add('tex2jax_process');
            element.classList.remove('tex2jax_ignore');

            console.log('🎯 调用 MathJax.typesetPromise([element])');
            console.log('📊 渲染前诊断信息:');
            console.log(`  - 元素可见: ${element.offsetHeight > 0 ? '✓' : '✗'}`);
            console.log(`  - 元素宽度: ${element.offsetWidth}px`);
            console.log(`  - 元素高度: ${element.offsetHeight}px`);
            console.log(`  - 计算样式 display: ${window.getComputedStyle(element).display}`);
            console.log(`  - 计算样式 visibility: ${window.getComputedStyle(element).visibility}`);
            console.log(`  - 原始 HTML: ${element.innerHTML.substring(0, 150)}`);

            // 🔥 清除可能的 MathJax 缓存
            if (MathJax.startup && MathJax.startup.document) {
                MathJax.startup.document.state(0);
            }

            // 使用 MathJax 的异步渲染方法
            MathJax.typesetPromise([element])
                .then(() => {
                    console.log('✅ LaTeX 渲染成功');
                    console.log('📊 渲染后诊断信息:');
                    console.log(`  - 元素可见: ${element.offsetHeight > 0 ? '✓' : '✗'}`);
                    console.log(`  - 元素宽度: ${element.offsetWidth}px`);
                    console.log(`  - 元素高度: ${element.offsetHeight}px`);
                    console.log(`  - 计算样式 display: ${window.getComputedStyle(element).display}`);
                    console.log(`  - 计算样式 visibility: ${window.getComputedStyle(element).visibility}`);
                    console.log(`  - 渲染后 HTML: ${element.innerHTML.substring(0, 150)}`);
                    console.log(`  - 子元素数量: ${element.children.length}`);

                    // 🔥 新增：强制重排以显示更新
                    element.offsetHeight; // 触发重排

                    // 🔥 新增：验证 MathJax 容器是否已生成
                    const mjxContainers = element.querySelectorAll('.mjx-container, [role="img"], mjx-container');
                    console.log(`  - MathJax 容器数量: ${mjxContainers.length}`);

                    if (mjxContainers.length === 0) {
                        console.warn('⚠️ 警告：未发现 MathJax 容器！尝试强制重新渲染...');
                        // 🔥 强制全局重新渲染
                        setTimeout(() => {
                            this._performGlobalTypeset();
                        }, 100);
                    } else {
                        mjxContainers.forEach((container, index) => {
                            const display = window.getComputedStyle(container).display;
                            const visibility = window.getComputedStyle(container).visibility;
                            const opacity = window.getComputedStyle(container).opacity;
                            console.log(`    [${index}] display: ${display}, visibility: ${visibility}, opacity: ${opacity}`);

                            // 🔥 检查隐藏的公式
                            if (display === 'none' || visibility === 'hidden' || opacity === '0') {
                                console.warn(`⚠️ 公式 #${index} 被隐藏！强制显示...`);
                                container.style.setProperty('display', 'inline-block', 'important');
                                container.style.setProperty('visibility', 'visible', 'important');
                                container.style.setProperty('opacity', '1', 'important');
                            }
                        });
                    }

                    // 🔥 新增：检查父容器是否有问题
                    const parent = element.parentElement;
                    if (parent) {
                        console.log(`📦 父容器诊断:`);
                        console.log(`  - 父容器可见: ${parent.offsetHeight > 0 ? '✓' : '✗'}`);
                        console.log(`  - 父容器 display: ${window.getComputedStyle(parent).display}`);
                        console.log(`  - 父容器 overflow: ${window.getComputedStyle(parent).overflow}`);
                    }
                })
                .catch((err) => {
                    console.warn('⚠️ MathJax 渲染失败 (会尝试全局重新渲染):', err);
                    // 尝试全局重新渲染
                    this._performGlobalTypeset();
                });
        } catch (error) {
            console.error('❌ 数学排版出错:', error);
            // 尝试全局重新渲染
            this._performGlobalTypeset();
        }
    }

    _performGlobalTypeset() {
        try {
            console.log('🌍 尝试全局 MathJax 重新渲染');
            if (MathJax.typesetPromise) {
                MathJax.typesetPromise()
                    .then(() => {
                        console.log('✅ 全局 MathJax 渲染成功');
                    })
                    .catch(e => {
                        console.warn('❌ 全局 MathJax 渲染也失败:', e);
                    });
            }
        } catch (e) {
            console.error('❌ 全局渲染异常:', e);
        }
    }
}

// 页面加载完成后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 聊天页面DOM内容已加载');
    setTimeout(() => {
        console.log('🚀 开始初始化聊天页面应用');
        window.llmReaderChatApp = new LLMReaderChatApp();
    }, 200);
});