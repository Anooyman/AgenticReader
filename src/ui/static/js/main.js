/**
 * LLMReader POC UI - 主JavaScript文件
 * 处理前端交互、WebSocket通信和UI状态管理
 */

class LLMReaderApp {
    constructor() {
        this.config = {
            provider: 'openai',
            pdfPreset: 'high',
            currentDocName: null,
            hasPdfReader: false,
            hasWebReader: false
        };

        this.websocket = null;
        this.isConnected = false;
        this.chatHistory = [];

        // 聊天会话管理
        this.currentChatId = null;
        this.chatSessions = new Map(); // 存储所有聊天会话

        // API基础URL配置 - 自动检测当前协议和主机
        this.apiBase = `${window.location.protocol}//${window.location.host}`;

        // 🔥 新增：缓存状态管理，避免重复加载
        this.loadedContent = {
            pdfReader: null,      // 记录已初始化的PDF文档名
            summary: null,        // 记录已加载摘要的文档名
            lastLoadTime: null    // 记录最后一次加载时间
        };

        // 异步初始化 - 使用 Promise 处理，避免构造函数中的未处理异步调用
        this.init().catch(error => {
            console.error('❌ 应用初始化失败:', error);
        });
    }

    // 获取完整的API URL
    getApiUrl(endpoint) {
        return `${this.apiBase}${endpoint}`;
    }

    async init() {
        try {
            console.log('🚀 应用初始化开始');

            // 初始化UI组件 - 这些不依赖API调用，应该先完成
            console.log('📋 初始化标签页');
            this.initTabs();

            console.log('📁 初始化文件上传');
            this.initFileUpload();

            console.log('⚙️ 初始化质量预设');
            this.initQualityPresets();

            console.log('🔗 初始化事件监听器');
            this.initEventListeners();

            console.log('🔄 初始化页面状态同步');
            this.initPageStateSync();

            console.log('💬 初始化聊天入口');
            this.initChatEntry();

            // 加载初始配置 - 这个可能失败，但不应该阻止UI初始化
            console.log('📖 加载配置');
            try {
                await this.loadConfig();
                console.log('✅ 配置加载成功');
            } catch (configError) {
                console.error('❌ 配置加载失败，使用默认配置:', configError);
                // 即使配置加载失败，也要确保基本功能可用
                this.updateDocumentStatus();
                this.updateSessionStatus();
            }

            // 加载聊天会话 - 🔥 改为从后端加载
            console.log('📋 加载聊天会话');
            await this.loadChatSessionsFromBackend();

            // 如果没有会话数据，创建一个示例会话便于测试和调试
            if (this.chatSessions.size === 0) {
                console.log('⚠️ 未发现任何会话数据，这可能是数据丢失的结果');
                console.log('💡 提示：会话数据可能在服务器重启或状态不一致检查中被清除');
                console.log('📄 当前可用的PDF文档:', this.config.currentDocName);
            }

            console.log('✅ 应用初始化完成');

        } catch (error) {
            console.error('❌ 应用初始化过程中发生严重错误:', error);
            // 即使发生错误，也要确保基本的文件上传功能可用
            console.log('🔧 尝试恢复基本功能...');
            this.initFileUpload();
            this.initTabs();
        }
    }

    /* === 初始化方法 === */

    initTabs() {
        const tabBtns = document.querySelectorAll('.tab-btn');
        const tabContents = document.querySelectorAll('.tab-content');

        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.getAttribute('data-tab');

                // 更新按钮状态
                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // 更新内容显示
                tabContents.forEach(content => {
                    content.classList.remove('active');
                    if (content.id === `${tabId}-tab`) {
                        content.classList.add('active');
                    }
                });
            });
        });
    }

    initFileUpload() {
        // 等待DOM完全加载后再获取元素
        let retryCount = 0;
        const maxRetries = 50; // 最大重试50次 (5秒)

        const waitForElements = () => {
            const uploadZone = document.getElementById('pdf-upload-zone');
            const fileInput = document.getElementById('pdf-file-input');
            const processPdfBtn = document.getElementById('process-pdf-btn');

            // 检查元素是否存在
            if (!uploadZone || !fileInput || !processPdfBtn) {
                retryCount++;
                if (retryCount < maxRetries) {
                    console.log(`⏳ 等待DOM元素加载... (${retryCount}/${maxRetries})`);
                    setTimeout(waitForElements, 100); // 100ms后重试
                } else {
                    console.log('⚠️ PDF上传元素未找到，跳过文件上传初始化 (可能不在主页面)');
                }
                return;
            }

            console.log('✅ 所有元素找到，开始绑定事件');
            console.log('📊 元素检查:', {
                uploadZone: uploadZone?.id,
                fileInput: fileInput?.id,
                processPdfBtn: processPdfBtn?.id
            });
            this.bindFileUploadEvents(uploadZone, fileInput, processPdfBtn);
        };

        waitForElements();
    }

    bindFileUploadEvents(uploadZone, fileInput, processPdfBtn) {

        // 点击上传区域
        uploadZone.addEventListener('click', (e) => {
            console.log('👆 上传区域被点击');
            console.log(`📊 事件详情: type=${e.type}, target=${e.target.tagName}, isTrusted=${e.isTrusted}`);

            // 检查是否点击的是input元素本身，如果是则不需要阻止默认行为
            if (e.target === fileInput) {
                console.log('🎯 直接点击了文件输入元素，保持默认行为');
                return;
            }

            console.log('🔄 准备触发fileInput.click()...');

            try {
                fileInput.click();
                console.log('✅ fileInput.click() 调用完成');
            } catch (error) {
                console.error('❌ 触发文件选择失败:', error);
                this.showStatus('error', '文件选择触发失败', 'pdf');
            }
        });

        // 文件选择
        fileInput.addEventListener('change', (e) => {
            console.log('📁 文件选择事件触发');
            const file = e.target.files[0];
            console.log('📄 选择的文件:', file);
            if (file && file.type === 'application/pdf') {
                console.log('✅ PDF文件有效，调用handleFileSelect');
                this.handleFileSelect(file);
            } else if (file) {
                console.log('❌ 文件类型无效:', file.type);
                this.showStatus('error', '请选择PDF文件', 'pdf');
            }
        });

        // 拖拽上传
        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadZone.classList.add('dragover');
        });

        uploadZone.addEventListener('dragleave', () => {
            uploadZone.classList.remove('dragover');
        });

        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('dragover');

            const files = e.dataTransfer.files;
            if (files.length > 0) {
                const file = files[0];
                if (file.type === 'application/pdf') {
                    this.handleFileSelect(file);
                } else {
                    this.showStatus('error', '请选择PDF文件', 'pdf');
                }
            }
        });

        // 处理PDF按钮
        processPdfBtn.addEventListener('click', () => {
            console.log('🔍 PDF处理按钮被点击');
            console.log('📄 按钮状态:', !processPdfBtn.disabled);
            console.log('📁 文件输入:', fileInput.files.length);
            this.processPdf();
        });

        console.log('✅ 文件上传事件绑定完成');
        console.log('🔗 已绑定的事件:');
        console.log('  - 上传区域点击事件');
        console.log('  - 文件选择change事件');
        console.log('  - 拖拽事件 (dragover, dragleave, drop)');
        console.log('  - 处理按钮点击事件');
    }

    initQualityPresets() {
        const presetSelect = document.getElementById('pdf-preset');
        const presetInfo = document.getElementById('preset-info');

        const presetDetails = {
            fast: {
                dpi: 150,
                quality: 'low',
                desc: '处理速度最快，适合快速预览文档内容'
            },
            balanced: {
                dpi: 200,
                quality: 'medium',
                desc: '速度和质量的良好平衡，适合一般文档'
            },
            high: {
                dpi: 300,
                quality: 'high',
                desc: '高质量OCR效果，推荐用于重要文档'
            },
            ultra: {
                dpi: 600,
                quality: 'ultra',
                desc: '最高质量，适合需要精细处理的文档'
            }
        };

        presetSelect.addEventListener('change', (e) => {
            const preset = e.target.value;
            const details = presetDetails[preset];

            this.config.pdfPreset = preset;

            presetInfo.innerHTML = `
                <strong>当前设置详情:</strong><br>
                📐 DPI: ${details.dpi}<br>
                🎨 质量: ${details.quality}<br>
                📝 说明: ${details.desc}
            `;
        });
    }

    initChatEntry() {
        // 初始化总结区域
        this.initSummaryTabs();
        this.initExpandableContent();

        // 监听文档状态变化
        this.updateChatEntryStatus();
    }

    initSummaryTabs() {
        const summaryTabBtns = document.querySelectorAll('.summary-tab-btn');
        const summaryTabContents = document.querySelectorAll('.summary-tab-content');

        summaryTabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const summaryType = btn.getAttribute('data-summary');

                // 更新按钮状态
                summaryTabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // 更新内容显示
                summaryTabContents.forEach(content => {
                    content.classList.remove('active');
                    if (content.id === `${summaryType}-summary`) {
                        content.classList.add('active');
                    }
                });

                // 加载总结内容
                if (this.config.currentDocName) {
                    this.loadSummary(summaryType);
                }
            });
        });
    }

    initExpandableContent() {
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('content-header') || e.target.parentElement.classList.contains('content-header')) {
                const header = e.target.classList.contains('content-header') ? e.target : e.target.parentElement;
                const targetId = header.getAttribute('data-target');
                const content = document.getElementById(targetId);

                if (content) {
                    const isExpanded = content.classList.contains('expanded');

                    if (isExpanded) {
                        content.classList.remove('expanded');
                        content.classList.add('collapsed');
                        header.classList.remove('expanded');
                    } else {
                        content.classList.remove('collapsed');
                        content.classList.add('expanded');
                        header.classList.add('expanded');
                    }
                }
            }
        });
    }

    initEventListeners() {
        // Web URL处理
        const processWebBtn = document.getElementById('process-web-btn');
        processWebBtn.addEventListener('click', () => {
            this.processWebUrl();
        });

        // 主页面会话管理按钮
        const newSessionMainBtn = document.getElementById('new-session-main-btn');
        const viewSessionsMainBtn = document.getElementById('view-sessions-main-btn');

        if (newSessionMainBtn) {
            newSessionMainBtn.addEventListener('click', () => {
                this.createNewGlobalSession();
            });
        }

        if (viewSessionsMainBtn) {
            viewSessionsMainBtn.addEventListener('click', () => {
                this.showSessionsModal();
            });
        }

        // 模态框事件
        this.initSessionsModal();
    }

    initPageStateSync() {
        // 🔥 新增：监听localStorage变化，实现页面间状态同步
        window.addEventListener('storage', (e) => {
            if (e.key === 'llmreader_document_state') {
                console.log('🔄 主页面检测到文档状态变化，同步状态');
                this.syncStateFromOtherPage(e.newValue);
            }
        });

        // 🔥 新增：监听页面焦点变化，当用户返回主页面时重新检查状态
        window.addEventListener('focus', () => {
            console.log('🔄 主页面获得焦点，检查状态同步');
            this.checkStateConsistency();
        });

        // 定期检查状态一致性（备用机制）
        setInterval(() => {
            this.checkStateConsistency();
        }, 3000); // 每3秒检查一次
    }

    syncStateFromOtherPage(newValue) {
        if (!newValue) return;

        try {
            const newState = JSON.parse(newValue);
            console.log('🔄 主页面同步其他页面的状态变化:', newState);

            // 检查是否有实质性变化
            const hasDocumentChange = newState.currentDocName !== this.config.currentDocName;
            const hasSessionChange = newState.currentChatId !== this.currentChatId;

            if (hasDocumentChange || hasSessionChange) {
                console.log('📄 检测到状态变化，更新主页面状态');

                // 更新配置状态
                this.config = { ...this.config, ...newState };

                // 🔥 关键：恢复聊天会话ID
                if (newState.currentChatId) {
                    this.currentChatId = newState.currentChatId;
                    console.log('🔄 主页面恢复聊天会话ID:', this.currentChatId);
                }

                // 更新UI状态
                this.updateDocumentStatus();
                this.updateSessionStatus();
                this.updateChatEntryStatus();

                // 如果有新文档状态，显示相关UI
                if (newState.currentDocName && newState.hasPdfReader) {
                    this.showSummarySection();
                    // 延迟加载摘要，避免阻塞
                    setTimeout(() => {
                        this.loadSummary('brief').catch(error => {
                            console.log('⚠️ 摘要加载失败，但状态已同步');
                        });
                    }, 1000);
                }

                console.log('✅ 主页面状态同步完成');
            }
        } catch (error) {
            console.error('主页面同步状态失败:', error);
        }
    }

    checkStateConsistency() {
        try {
            const savedState = this.loadDocumentStateFromLocal();
            if (savedState) {
                // 检查当前状态是否与本地存储一致
                const hasDocumentMismatch = savedState.currentDocName !== this.config.currentDocName;
                const hasSessionMismatch = savedState.currentChatId !== this.currentChatId;

                if (hasDocumentMismatch || hasSessionMismatch) {
                    console.log('🔄 检测到状态不一致，进行同步:', {
                        currentDoc: this.config.currentDocName,
                        savedDoc: savedState.currentDocName,
                        currentSession: this.currentChatId,
                        savedSession: savedState.currentChatId
                    });
                    this.syncStateFromOtherPage(JSON.stringify(savedState));
                }
            }
        } catch (error) {
            console.warn('⚠️ 状态一致性检查失败:', error);
        }
    }


    /* === API调用方法 === */

    async loadConfig() {
        try {
            // 首先检查本地存储的文档状态
            const savedDocState = this.loadDocumentStateFromLocal();

            const response = await fetch(this.getApiUrl('/api/v1/config'));
            const config = await response.json();

            // 映射后端的下划线命名到前端的驼峰命名
            const mappedConfig = {
                ...config,
                currentDocName: config.current_doc_name,
                hasPdfReader: config.has_pdf_reader,
                hasWebReader: config.has_web_reader,
                pdfPreset: config.pdf_preset
            };

            this.config = { ...this.config, ...mappedConfig };

            // 如果有保存的文档状态，恢复 documentType
            if (savedDocState && savedDocState.documentType) {
                this.config.documentType = savedDocState.documentType;
                console.log(`📝 恢复文档类型: ${savedDocState.documentType}`);
            }

            // 🔥 新增：延迟加载策略 - 只显示UI，不自动加载PDF内容
            if (savedDocState && savedDocState.currentDocName) {
                console.log('🔄 检测到本地存储的文档状态:', savedDocState.currentDocName);
                console.log('📊 延迟加载策略：只恢复UI状态，不自动加载PDF内容');

                // 🔥 关键修复：只恢复配置状态，不触发内容加载
                this.config = { ...this.config, ...savedDocState };

                // 🔥 关键修复：确保恢复聊天会话ID，避免重新创建
                if (savedDocState.currentChatId) {
                    this.currentChatId = savedDocState.currentChatId;
                    console.log('🔄 恢复聊天会话ID:', this.currentChatId);
                }

                // 🔥 新增：显示session可用状态，但标记为"待加载"
                this.showSummarySection();
                this.updateChatEntryStatus();
                this.updateDocumentStatus();
                this.updateSessionStatus();

                // 🔥 新增：显示文档状态但提示需要选择会话来加载
                this.showSessionAvailableHint(savedDocState.currentDocName);

            } else if (this.config.currentDocName) {
                // 如果没有本地状态但服务器有配置，也采用延迟加载
                console.log('📄 检测到服务器配置状态，采用延迟加载策略:', this.config.currentDocName);
                this.showSummarySection();
                this.updateChatEntryStatus();
                this.showSessionAvailableHint(this.config.currentDocName);
            }

            // 更新UI
            this.updateDocumentStatus();
            this.updateSessionStatus();

        } catch (error) {
            console.error('加载配置失败:', error);
        }
    }

    async updateProvider(provider) {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/config/provider'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    provider: provider,
                    pdf_preset: this.config.pdfPreset
                })
            });

            const result = await response.json();
            if (result.status === 'success') {
                this.config.provider = provider;
                this.showStatus('success', `LLM提供商已更新为: ${provider}`, 'config');
            }
        } catch (error) {
            console.error('更新提供商失败:', error);
            this.showStatus('error', '更新提供商失败', 'config');
        }
    }

    async processPdf() {
        console.log('🚀 processPdf() 方法被调用');
        const fileInput = document.getElementById('pdf-file-input');
        const saveOutputsElement = document.getElementById('save-outputs');
        const processPdfBtn = document.getElementById('process-pdf-btn');

        // 检查元素是否存在
        if (!fileInput) {
            console.error('❌ 找不到文件输入元素 #pdf-file-input');
            this.showStatus('error', '文件输入组件未找到', 'pdf');
            return;
        }

        if (!saveOutputsElement) {
            console.error('❌ 找不到保存设置元素 #save-outputs');
            this.showStatus('error', '保存设置组件未找到', 'pdf');
            return;
        }

        const saveOutputs = saveOutputsElement.checked;
        console.log('📁 文件输入检查:', fileInput.files.length);

        if (!fileInput.files.length) {
            console.log('❌ 没有选择文件');
            this.showStatus('warning', '请先选择PDF文件', 'pdf');
            return;
        }

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        // 开始处理状态
        this.showProcessingStatus('正在处理PDF文件，请耐心等待...', 'pdf');

        // 禁用处理按钮
        if (processPdfBtn) {
            processPdfBtn.disabled = true;
            processPdfBtn.textContent = '处理中...';
        }

        try {
            // 首先更新PDF预设配置
            await this.updateProvider(this.config.provider);

            const response = await fetch(this.getApiUrl('/api/v1/pdf/upload'), {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (response.ok && result.status === 'processing') {
                this.config.currentDocName = result.doc_name;

                // 保存文档状态到本地存储（初始状态）
                this.saveDocumentStateToLocal();

                // 显示正在处理状态
                this.showProcessingStatus(result.message, 'pdf');

                // 开始轮询处理状态
                this.pollPdfProcessingStatus(result.doc_name);

                // 更新基本状态
                this.updateDocumentStatus();
            } else {
                this.hideProcessingStatus('pdf');
                this.showStatus('error', result.detail || result.message || '处理PDF失败', 'pdf');
            }
        } catch (error) {
            console.error('处理PDF失败:', error);
            this.hideProcessingStatus('pdf');
            this.showStatus('error', '处理PDF时发生错误', 'pdf');

            // 恢复处理按钮（仅在异常情况下）
            if (processPdfBtn) {
                processPdfBtn.disabled = false;
                processPdfBtn.textContent = '🚀 开始处理 PDF';
            }
        }
    }

    async processWebUrl() {
        const urlInput = document.getElementById('web-url-input');
        const saveOutputs = document.getElementById('web-save-outputs').checked;
        const processWebBtn = document.getElementById('process-web-btn');
        const url = urlInput.value.trim();

        if (!url || !(url.startsWith('http://') || url.startsWith('https://'))) {
            this.showStatus('warning', '请输入有效的URL (以http://或https://开头)', 'web');
            return;
        }

        // 开始处理状态
        this.showProcessingStatus('正在处理网页内容，请耐心等待...', 'web');

        // 禁用处理按钮
        if (processWebBtn) {
            processWebBtn.disabled = true;
            processWebBtn.textContent = '处理中...';
        }

        try {
            const response = await fetch(this.getApiUrl('/api/v1/web/process'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: url,
                    save_outputs: saveOutputs
                })
            });

            const result = await response.json();

            if (response.ok && result.status === 'success') {
                this.config.currentDocName = result.doc_name;
                this.config.hasWebReader = true;
                this.config.hasPdfReader = false; // 明确标记为 Web 模式
                this.config.documentType = 'web'; // 添加文档类型标记

                // 🔥 关键修复：确保在Web处理完成后创建基于文档的固定聊天会话ID
                if (!this.currentChatId) {
                    this.currentChatId = this.generateDocumentSessionId(result.doc_name);
                    console.log('🔑 Web处理完成时生成基于文档的固定聊天会话ID:', this.currentChatId);
                }

                // 初始化 Web 阅读器的聊天服务
                try {
                    const initResponse = await fetch(this.getApiUrl(`/api/v1/web/initialize/${result.doc_name}`), {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ url: url })
                    });

                    const initResult = await initResponse.json();
                    if (initResult.status === 'success') {
                        console.log('✅ Web聊天服务初始化成功');
                    } else {
                        console.warn('⚠️ Web聊天服务初始化失败:', initResult.message);
                    }
                } catch (initError) {
                    console.error('❌ 初始化Web聊天服务时出错:', initError);
                }

                // 保存文档状态到本地存储
                this.saveDocumentStateToLocal();

                // 隐藏处理状态，显示成功消息
                this.hideProcessingStatus('web');
                this.showStatus('success', result.message, 'web');

                this.updateDocumentStatus();
                this.updateSessionStatus(); // 🔥 新增：更新会话状态显示
                this.updateChatEntryStatus(); // 更新聊天入口状态
                this.showSummarySection();
                this.loadSummary('brief'); // 加载默认总结（会根据文档类型调用不同API）
            } else {
                this.hideProcessingStatus('web');
                this.showStatus('error', result.detail || '处理网页内容失败', 'web');
            }
        } catch (error) {
            console.error('处理网页内容失败:', error);
            this.hideProcessingStatus('web');
            this.showStatus('error', '处理网页内容时发生错误', 'web');
        } finally {
            // 恢复处理按钮
            if (processWebBtn) {
                processWebBtn.disabled = false;
                processWebBtn.textContent = '🚀 开始处理 URL';
            }
        }
    }

    async loadSummary(summaryType) {
        if (!this.config.currentDocName) return;

        try {
            // 根据文档类型选择不同的 API 端点
            const documentType = this.config.documentType || (this.config.hasPdfReader ? 'pdf' : 'web');
            const apiEndpoint = documentType === 'web'
                ? `/api/v1/web/summary/${this.config.currentDocName}?summary_type=${summaryType}`
                : `/api/v1/pdf/summary/${this.config.currentDocName}?summary_type=${summaryType}`;

            console.log(`📖 加载${documentType}摘要: ${apiEndpoint}`);

            const response = await fetch(this.getApiUrl(apiEndpoint));
            const result = await response.json();

            const summaryElement = document.getElementById(`${summaryType}-summary-text`);

            if (result.status === 'success') {
                // 渲染Markdown内容
                const renderedContent = this.renderMarkdown(result.content);
                summaryElement.innerHTML = renderedContent;
                // 重新渲染数学公式
                this.renderMath(summaryElement);
            } else {
                summaryElement.innerHTML = `<p style="color: #6c757d; font-style: italic;">${result.message}</p>`;
            }
        } catch (error) {
            console.error('加载总结失败:', error);
            const summaryElement = document.getElementById(`${summaryType}-summary-text`);
            summaryElement.innerHTML = '<p style="color: #dc3545;">加载总结时发生错误</p>';
        }
    }

    async checkPdfProcessingStatus(docName) {
        try {
            const response = await fetch(this.getApiUrl(`/api/v1/pdf/status/${docName}`));
            const result = await response.json();

            console.log('📊 PDF处理状态:', result);
            return result;
        } catch (error) {
            console.error('检查PDF状态失败:', error);
            return { status: 'error', message: '无法检查处理状态' };
        }
    }

    async pollPdfProcessingStatus(docName, maxAttempts = 30, interval = 2000) {
        let attempts = 0;
        const processPdfBtn = document.getElementById('process-pdf-btn');

        const poll = async () => {
            attempts++;
            console.log(`🔄 检查PDF处理状态 (第${attempts}次)`);

            const status = await this.checkPdfProcessingStatus(docName);

            // 更新处理状态显示
            if (status.status === 'processing') {
                this.showProcessingStatus(status.message || '正在处理PDF文件...', 'pdf');
            } else if (status.status === 'completed') {
                console.log('✅ PDF处理完成');
                this.hideProcessingStatus('pdf');
                this.showStatus('success', 'PDF处理完成！', 'pdf');

                // 更新配置状态
                this.config.hasPdfReader = status.has_json;
                this.config.hasWebReader = false; // 明确标记为 PDF 模式
                this.config.documentType = 'pdf'; // 添加文档类型标记

                // 🔥 关键修复：确保在PDF处理完成后创建基于文档的固定聊天会话ID
                if (!this.currentChatId) {
                    this.currentChatId = this.generateDocumentSessionId(docName);
                    console.log('🔑 PDF处理完成时生成基于文档的固定聊天会话ID:', this.currentChatId);
                }

                this.saveDocumentStateToLocal();

                // 更新UI状态
                this.updateDocumentStatus();
                this.updateSessionStatus(); // 🔥 新增：更新会话状态显示
                this.updateChatEntryStatus();
                this.showSummarySection();
                this.loadSummary('brief');

                // 恢复处理按钮
                if (processPdfBtn) {
                    processPdfBtn.disabled = false;
                    processPdfBtn.textContent = '🚀 开始处理 PDF';
                }

                return; // 处理完成，停止轮询
            } else if (status.status === 'error') {
                console.error('❌ PDF处理失败:', status.message);
                this.hideProcessingStatus('pdf');
                this.showStatus('error', status.message || 'PDF处理失败', 'pdf');

                // 恢复处理按钮
                if (processPdfBtn) {
                    processPdfBtn.disabled = false;
                    processPdfBtn.textContent = '🚀 开始处理 PDF';
                }

                return; // 处理失败，停止轮询
            }

            // 继续轮询
            if (attempts < maxAttempts) {
                setTimeout(poll, interval);
            } else {
                console.warn('⚠️ PDF处理状态检查超时');
                this.hideProcessingStatus('pdf');
                this.showStatus('warning', 'PDF处理时间较长，请稍后查看', 'pdf');

                // 恢复处理按钮
                if (processPdfBtn) {
                    processPdfBtn.disabled = false;
                    processPdfBtn.textContent = '🚀 开始处理 PDF';
                }
            }
        };

        poll();
    }


    async clearChat() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/chat/clear'), {
                method: 'POST'
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.chatHistory = [];
                this.clearChatMessages();
                this.showStatus('info', '聊天历史已清空', 'chat');

                // 同时清除本地存储的文档状态
                this.clearDocumentStateFromLocal();

                // 🔥 新增：清除内容缓存 - 清空聊天时也清除缓存
                this.clearContentCache();
                console.log('🗑️ 清空聊天时清除内容缓存');

                // 重置配置和UI状态
                this.config.currentDocName = null;
                this.config.hasPdfReader = false;
                this.config.hasWebReader = false;
                this.updateDocumentStatus();
                this.updateChatEntryStatus();

                // 隐藏总结区域
                const summarySection = document.getElementById('summary-section');
                summarySection.style.display = 'none';
            }
        } catch (error) {
            console.error('清空聊天失败:', error);
        }
    }

    /* === UI更新方法 === */

    handleFileSelect(file) {
        console.log('🎯 handleFileSelect() 被调用，文件:', file.name);
        const uploadZone = document.getElementById('pdf-upload-zone');
        const processPdfBtn = document.getElementById('process-pdf-btn');

        // 只更新显示元素，保留原有的input元素和事件绑定
        const uploadIcon = uploadZone.querySelector('.upload-icon');
        const uploadText = uploadZone.querySelector('.upload-text');

        if (uploadIcon) {
            uploadIcon.textContent = '📄';
        }

        if (uploadText) {
            uploadText.innerHTML = `
                已选择文件: ${file.name}
                <br>
                <span style="font-size: 0.875rem; color: #6c757d; margin-top: 0.5rem;">
                    文件大小: ${(file.size / 1024 / 1024).toFixed(2)} MB
                </span>
            `;
        }

        processPdfBtn.disabled = false;
        console.log('✅ 按钮状态已更新为可用，input元素和事件绑定已保留');
    }

    showStatus(type, message, target = 'general') {
        const statusElements = {
            pdf: document.getElementById('pdf-status'),
            web: document.getElementById('web-status'),
            chat: document.getElementById('chat-messages'),
            config: document.getElementById('pdf-status') // 使用PDF状态区域显示配置信息
        };

        // 对于config类型，使用PDF状态区域显示，同时在控制台记录
        if (target === 'config') {
            console.log(`[${type.toUpperCase()}] ${message}`);
            const statusElement = statusElements[target];
            if (statusElement) {
                statusElement.className = `status-message ${type}`;
                statusElement.textContent = message;
                statusElement.style.display = 'block';

                // 自动隐藏成功和信息消息
                if (type === 'success' || type === 'info') {
                    setTimeout(() => {
                        statusElement.style.display = 'none';
                    }, 5000);
                }
            }
            return;
        }

        const statusElement = statusElements[target];
        if (!statusElement) return;

        if (target === 'chat') {
            this.addStatusMessage(message);
            return;
        }

        statusElement.className = `status-message ${type}`;
        statusElement.textContent = message;
        statusElement.style.display = 'block';

        // 自动隐藏成功和信息消息
        if (type === 'success' || type === 'info') {
            setTimeout(() => {
                statusElement.style.display = 'none';
            }, 5000);
        }
    }

    showProcessingStatus(message, target) {
        const statusElements = {
            pdf: document.getElementById('pdf-status'),
            web: document.getElementById('web-status')
        };

        const statusElement = statusElements[target];
        if (!statusElement) return;

        // 创建持续处理状态显示
        statusElement.className = 'status-message processing';
        statusElement.innerHTML = `
            <div class="processing-container">
                <div class="processing-spinner"></div>
                <span class="processing-text">${message}</span>
            </div>
        `;
        statusElement.style.display = 'block';

        // 添加处理状态标记
        statusElement.setAttribute('data-processing', 'true');
    }

    hideProcessingStatus(target) {
        const statusElements = {
            pdf: document.getElementById('pdf-status'),
            web: document.getElementById('web-status')
        };

        const statusElement = statusElements[target];
        if (!statusElement) return;

        // 移除处理状态标记
        statusElement.removeAttribute('data-processing');

        // 暂时隐藏状态元素，为后续的成功/错误消息做准备
        statusElement.style.display = 'none';
    }

    updateDocumentStatus() {
        const statusElement = document.getElementById('current-doc-status');

        if (this.config.currentDocName) {
            statusElement.textContent = `当前文档: ${this.config.currentDocName}`;
            statusElement.style.color = '#28a745'; // 绿色
        } else {
            statusElement.textContent = '当前文档: 未处理';
            statusElement.style.color = '#6c757d'; // 灰色
        }
    }

    updateSessionStatus() {
        const sessionStatusElement = document.getElementById('main-session-info');
        if (sessionStatusElement) {
            let sessionStatusText = sessionStatusElement.querySelector('.session-status');

            // 如果找不到.session-status元素，重建正确的HTML结构
            if (!sessionStatusText) {
                console.log('🔧 重建会话状态HTML结构');
                sessionStatusElement.innerHTML = '<p class="session-status">当前会话: 未创建</p>';
                sessionStatusText = sessionStatusElement.querySelector('.session-status');
            }

            if (sessionStatusText) {
                if (this.currentChatId) {
                    const currentSession = this.chatSessions.get(this.currentChatId);
                    if (currentSession && currentSession.messages && currentSession.messages.length > 0) {
                        // 有具体的会话消息，显示会话标题
                        const sessionTitle = this.generateSessionTitle(currentSession.messages);
                        sessionStatusText.textContent = `当前会话: ${sessionTitle}`;
                        sessionStatusText.style.color = 'var(--success-color)';
                    } else if (this.config.currentDocName) {
                        // 有文档但没有消息，显示文档相关的会话状态
                        sessionStatusText.textContent = `当前会话: ${this.config.currentDocName} - 准备就绪`;
                        sessionStatusText.style.color = 'var(--primary-color)';
                    } else {
                        // 有会话ID但没有文档和消息
                        sessionStatusText.textContent = '当前会话: 新会话';
                        sessionStatusText.style.color = 'var(--primary-color)';
                    }
                } else {
                    sessionStatusText.textContent = '当前会话: 未创建';
                    sessionStatusText.style.color = 'var(--text-muted)';
                }
            }
        } else {
            console.warn('⚠️ 找不到#main-session-info元素');
        }
    }

    showSessionRestorationStatus(message) {
        const sessionStatusElement = document.getElementById('main-session-info');
        if (sessionStatusElement) {
            // 在会话信息区域显示加载状态
            const originalContent = sessionStatusElement.innerHTML;
            sessionStatusElement.innerHTML = `
                <div class="session-restoration-status">
                    <div class="loading-spinner"></div>
                    <span class="loading-text">${message}</span>
                </div>
            `;
            sessionStatusElement.setAttribute('data-original-content', originalContent);
            sessionStatusElement.classList.add('loading');
        }
    }

    hideSessionRestorationStatus() {
        const sessionStatusElement = document.getElementById('main-session-info');
        if (sessionStatusElement) {
            const originalContent = sessionStatusElement.getAttribute('data-original-content');
            if (originalContent) {
                sessionStatusElement.innerHTML = originalContent;
                sessionStatusElement.removeAttribute('data-original-content');
            }
            sessionStatusElement.classList.remove('loading');
            // 重新更新会话状态显示
            this.updateSessionStatus();
        }
    }

    updateConnectionStatus(status, message) {
        const indicator = document.getElementById('status-indicator');
        const text = document.getElementById('status-text');

        indicator.className = `status-indicator ${status}`;
        text.textContent = message;
    }

    enableChatInput() {
        const chatInput = document.getElementById('chat-input');
        const sendBtn = document.getElementById('send-btn');

        chatInput.disabled = false;
        sendBtn.disabled = false;
        chatInput.placeholder = '请输入你的问题…';
    }

    disableChatInput() {
        const chatInput = document.getElementById('chat-input');
        const sendBtn = document.getElementById('send-btn');

        chatInput.disabled = true;
        sendBtn.disabled = true;
        chatInput.placeholder = '连接中断，请等待重连...';
    }

    showSummarySection() {
        const summarySection = document.getElementById('summary-section');
        summarySection.style.display = 'block';
    }

    showSessionAvailableHint(docName) {
        // 在摘要区域显示提示信息，说明有可用session但需要手动选择
        const summaryTypes = ['brief', 'detailed'];
        summaryTypes.forEach(type => {
            const summaryElement = document.getElementById(`${type}-summary-text`);
            if (summaryElement) {
                summaryElement.innerHTML = `
                    <div class="session-available-hint" style="
                        padding: 1rem;
                        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                        border: 2px dashed #6c757d;
                        border-radius: 8px;
                        text-align: center;
                        color: #495057;
                        margin: 1rem 0;
                    ">
                        <h4 style="margin: 0 0 0.5rem 0; color: #495057;">📋 检测到已有会话</h4>
                        <p style="margin: 0 0 1rem 0;">
                            文档 <strong>${docName}</strong> 有可用的会话记录
                        </p>
                        <p style="margin: 0; font-size: 0.9rem; color: #6c757d;">
                            💡 点击右上角"查看会话"按钮选择会话来加载PDF内容和对话历史
                        </p>
                    </div>
                `;
            }
        });

        // 更新聊天入口状态提示
        const chatEntryStatus = document.getElementById('chat-entry-status');
        if (chatEntryStatus) {
            chatEntryStatus.classList.remove('ready');
            chatEntryStatus.innerHTML = `
                <span class="status-text">📋 检测到 ${docName} 的历史会话，请选择会话来加载内容</span>
            `;
        }

        console.log('💡 显示会话可用提示:', docName);
    }

    clearAllCacheAndUI() {
        console.log('🧹 开始清除所有缓存和UI显示');

        // 隐藏总结区域
        const summarySection = document.getElementById('summary-section');
        if (summarySection) {
            summarySection.style.display = 'none';
            console.log('📄 总结区域已隐藏');
        }

        // 清除总结内容缓存
        const summaryTypes = ['brief', 'detailed'];
        summaryTypes.forEach(type => {
            const summaryElement = document.getElementById(`${type}-summary-text`);
            if (summaryElement) {
                summaryElement.innerHTML = '';
                console.log(`🗑️ 已清除${type}总结内容`);
            }
        });

        // 重置聊天入口状态
        this.updateChatEntryStatus();

        // 清除PDF查看器相关状态（如果有）
        this.resetPdfViewerState();

        console.log('✅ 所有缓存和UI显示已清除');
    }

    resetPdfViewerState() {
        // 重置PDF查看器状态
        if (this.pdfViewerState) {
            this.pdfViewerState = {
                currentPage: 1,
                totalPages: 0,
                pdfUrl: null,
                images: []
            };
        }

        // 清除PDF查看器内容（如果存在）
        const pdfViewerContainer = document.getElementById('pdf-viewer-container');
        if (pdfViewerContainer) {
            pdfViewerContainer.style.display = 'none';
        }

        console.log('📄 PDF查看器状态已重置');
    }

    /* === 内容缓存管理方法 === */

    shouldReloadContent(docName) {
        if (!docName) return false;

        // 检查是否已经加载过相同的文档
        const pdfReaderCached = this.loadedContent.pdfReader === docName;
        const summaryCached = this.loadedContent.summary === docName;

        // 如果上次加载时间超过30分钟，强制重新加载
        const MAX_CACHE_TIME = 30 * 60 * 1000; // 30分钟
        const now = Date.now();
        const isExpired = this.loadedContent.lastLoadTime && (now - this.loadedContent.lastLoadTime > MAX_CACHE_TIME);

        console.log('🔍 缓存状态检查:', {
            docName,
            pdfReaderCached,
            summaryCached,
            isExpired,
            lastLoadTime: this.loadedContent.lastLoadTime ? new Date(this.loadedContent.lastLoadTime).toLocaleTimeString() : 'never'
        });

        // 如果文档已缓存且未过期，不需要重新加载
        if (pdfReaderCached && summaryCached && !isExpired) {
            console.log('✅ 内容已缓存且未过期，跳过重新加载');
            return false;
        }

        console.log('🔄 需要重新加载内容:', {
            reason: !pdfReaderCached ? 'PDF阅读器未缓存' :
                   !summaryCached ? '摘要未缓存' :
                   isExpired ? '缓存已过期' : '未知原因'
        });
        return true;
    }

    async loadPdfContentIfNeeded(docName) {
        try {
            console.log('🔄 开始条件性加载PDF内容:', docName);
            this.showSessionRestorationStatus('正在重新初始化PDF阅读器...');

            // 检查PDF阅读器是否需要重新初始化
            if (this.loadedContent.pdfReader !== docName) {
                console.log('🔄 正在重新初始化PDF阅读器...');

                // 调用后端API重新初始化PDF阅读器
                const response = await fetch(this.getApiUrl(`/api/v1/pdf/reinitialize/${docName}`), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                const result = await response.json();

                if (response.ok && result.status === 'success') {
                    console.log('✅ PDF阅读器重新初始化成功:', result.message);
                    this.loadedContent.pdfReader = docName;

                    // 🔥 关键修复：更新本地配置状态
                    this.config.hasPdfReader = true;
                    this.config.hasWebReader = this.config.hasWebReader || false;

                    // 🔥 重要：保存更新后的状态到本地存储，确保状态一致性
                    this.saveDocumentStateToLocal();
                } else if (result.status === 'needs_processing') {
                    console.warn('⚠️ PDF需要重新处理:', result.message);
                    this.hideSessionRestorationStatus();
                    this.showStatus('warning', `PDF ${docName} 需要重新处理`, 'config');
                    return;
                } else {
                    console.error('❌ PDF重新初始化失败:', result);
                    this.hideSessionRestorationStatus();
                    this.showStatus('error', `PDF重新初始化失败: ${result.message || '未知错误'}`, 'config');
                    return;
                }
            } else {
                console.log('✅ PDF阅读器已缓存，跳过重新初始化');
            }

            // 检查摘要是否需要重新加载
            if (this.loadedContent.summary !== docName) {
                console.log('🔄 正在加载文档摘要...');
                this.showSessionRestorationStatus('正在加载文档摘要...');

                try {
                    await this.loadSummary('brief');
                    this.loadedContent.summary = docName;
                    console.log('✅ 摘要加载成功');
                } catch (summaryError) {
                    console.warn('⚠️ 摘要加载失败，但继续执行:', summaryError);
                    // 尝试加载缓存的摘要
                    try {
                        await this.loadSummary('brief');
                        console.log('✅ 摘要加载成功（使用缓存）');
                    } catch (cachedSummaryError) {
                        console.log('⚠️ 摘要加载失败，但状态已恢复');
                    }
                }
            } else {
                console.log('✅ 摘要已缓存，跳过重新加载');
            }

            // 更新缓存时间戳
            this.loadedContent.lastLoadTime = Date.now();

            // 🔥 重要：更新所有UI状态，确保界面正确显示
            this.updateDocumentStatus();
            this.updateSessionStatus();
            this.updateChatEntryStatus();

            // 加载完成后隐藏提示
            this.hideSessionRestorationStatus();
            console.log('✅ PDF内容加载完成，所有UI状态已更新');

        } catch (error) {
            console.error('❌ 加载PDF内容失败:', error);
            this.hideSessionRestorationStatus();
            this.showStatus('error', `PDF内容加载失败: ${error.message}`, 'config');
        }
    }

    clearContentCache() {
        console.log('🗑️ 清除内容缓存');
        this.loadedContent = {
            pdfReader: null,
            summary: null,
            lastLoadTime: null
        };
    }

    updateChatEntryStatus() {
        const chatEntryBtn = document.getElementById('enter-chat-btn');
        const chatEntryStatus = document.getElementById('chat-entry-status');
        const newChatBtn = document.getElementById('new-chat-btn');

        // 更严格的检查：需要文档名 AND PDF/Web Reader已处理
        const isDocumentReady = this.config.currentDocName &&
                               (this.config.hasPdfReader || this.config.hasWebReader);

        console.log('🔍 检查聊天入口状态:', {
            currentDocName: this.config.currentDocName,
            hasPdfReader: this.config.hasPdfReader,
            hasWebReader: this.config.hasWebReader,
            isDocumentReady: isDocumentReady
        });

        if (isDocumentReady) {
            // 文档已处理，启用聊天模式
            chatEntryBtn.classList.remove('btn-secondary');
            chatEntryBtn.classList.add('btn-primary');
            chatEntryBtn.style.pointerEvents = 'auto';
            chatEntryBtn.style.opacity = '1';

            // 显示 New Chat 按钮
            if (newChatBtn) {
                newChatBtn.style.display = 'flex';
            }

            // 🔥 关键修复：确保有基于文档的固定聊天会话ID
            if (!this.currentChatId) {
                this.currentChatId = this.generateDocumentSessionId(this.config.currentDocName);
                console.log('🔑 文档就绪时生成基于文档的固定聊天会话ID:', this.currentChatId);
                // 保存文档状态到本地存储
                this.saveDocumentStateToLocal();
            }

            chatEntryStatus.classList.add('ready');
            chatEntryStatus.innerHTML = `
                <span class="status-text">✅ 文档已处理完成，可以开始智能问答</span>
            `;
        } else {
            // 未处理文档，禁用聊天模式
            chatEntryBtn.classList.remove('btn-primary');
            chatEntryBtn.classList.add('btn-secondary');
            chatEntryBtn.style.pointerEvents = 'none';
            chatEntryBtn.style.opacity = '0.6';

            // 隐藏 New Chat 按钮
            if (newChatBtn) {
                newChatBtn.style.display = 'none';
            }

            chatEntryStatus.classList.remove('ready');
            chatEntryStatus.innerHTML = `
                <span class="status-text">📄 请先处理文档后再进入聊天模式</span>
            `;
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

        console.log('🔑 为文档生成固定会话ID:', docName, '->', sessionId);
        return sessionId;
    }

    getCurrentChatId() {
        if (!this.currentChatId) {
            // 🔥 关键修复：如果有文档，基于文档名生成固定的会话ID
            if (this.config.currentDocName) {
                this.currentChatId = this.generateDocumentSessionId(this.config.currentDocName);
                console.log('🔑 基于文档生成固定聊天会话ID:', this.currentChatId);
            } else {
                this.currentChatId = this.generateUUID();
                console.log('🆕 生成随机聊天会话ID:', this.currentChatId);
            }
        }
        return this.currentChatId;
    }

    createNewChat() {
        // 保存当前会话（如果存在）
        if (this.currentChatId) {
            this.saveChatSession(this.currentChatId);
        }

        // 创建新会话
        this.currentChatId = this.generateUUID();
        this.chatHistory = [];

        console.log('🆕 创建新聊天会话:', this.currentChatId);

        // 保存会话信息到本地存储
        this.saveChatSessionsToLocal();

        // 清空聊天UI
        this.clearChatMessages();

        return this.currentChatId;
    }

    isMeaningfulSession() {
        // 如果没有文档，会话无意义
        if (!this.config.currentDocName) return false;

        // 如果没有聊天历史，会话无意义
        if (!this.chatHistory.length) return false;

        // 检查是否有实质性对话 - 只要有用户消息就认为是有意义的会话
        const userMessages = this.chatHistory.filter(([role, content]) =>
            role === 'user' && content.trim().length >= 3);

        // 只要有至少一条用户消息就保存会话
        return userMessages.length > 0;
    }

    saveChatSession(chatId) {
        // 只保存有意义的会话
        if (!chatId || !this.isMeaningfulSession()) {
            console.log('⏭️ 跳过保存无意义会话:', chatId, '文档:', this.config.currentDocName, '消息数:', this.chatHistory.length);
            return;
        }

        const sessionData = {
            chatId: chatId,
            docName: this.config.currentDocName,
            messages: [...this.chatHistory],
            timestamp: Date.now(),
            hasPdfReader: this.config.hasPdfReader,
            hasWebReader: this.config.hasWebReader,
            provider: this.config.provider,
            pdfPreset: this.config.pdfPreset
        };

        this.chatSessions.set(chatId, sessionData);
        console.log('💾 保存有意义聊天会话:', chatId, '消息数量:', this.chatHistory.length);
    }

    loadChatSession(chatId) {
        const sessionData = this.chatSessions.get(chatId);
        if (!sessionData) {
            console.log('❌ 聊天会话不存在:', chatId);
            return false;
        }

        this.currentChatId = chatId;
        this.chatHistory = [...sessionData.messages];

        console.log('📖 加载聊天会话:', chatId, '消息数量:', this.chatHistory.length);

        // 重新加载聊天消息到UI
        this.reloadChatMessages();

        return true;
    }

    reloadChatMessages() {
        this.clearChatMessages();
        if (this.chatHistory.length > 0) {
            // 重新加载所有消息 - 注意: 传递 addToHistory = false 避免重复添加到历史记录
            this.chatHistory.forEach(([role, content, timestamp]) => {
                this.addChatMessage(role, content, timestamp, false, false);
            });

            // 滚动到底部
            const chatMessages = document.getElementById('chat-messages');
            if (chatMessages) {
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }
    }

    /* === 本地状态持久化方法 === */

    saveDocumentStateToLocal() {
        const documentState = {
            currentDocName: this.config.currentDocName,
            hasPdfReader: this.config.hasPdfReader,
            hasWebReader: this.config.hasWebReader,
            documentType: this.config.documentType, // 保存文档类型
            provider: this.config.provider,
            pdfPreset: this.config.pdfPreset,
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

    saveChatSessionsToLocal() {
        try {
            // 保存当前会话（只保存有意义的）
            if (this.currentChatId) {
                this.saveChatSession(this.currentChatId);
            }

            // 将Map转换为可序列化的对象
            const sessionsObj = {};
            this.chatSessions.forEach((value, key) => {
                sessionsObj[key] = value;
            });

            localStorage.setItem('llmreader_chat_sessions', JSON.stringify(sessionsObj));
            console.log('💾 聊天会话已保存到本地存储，会话数量:', this.chatSessions.size);
        } catch (error) {
            console.error('保存聊天会话失败:', error);
        }
    }

    async loadChatSessionsFromBackend() {
        try {
            console.log('📖 从后端加载聊天会话...');
            const response = await fetch(this.getApiUrl('/api/v1/sessions/list'));
            const result = await response.json();

            if (response.ok && result.sessions) {
                console.log('✅ 成功从后端加载会话:', result);

                // 清空本地会话缓存
                this.chatSessions.clear();

                // 加载会话到本地缓存
                Object.entries(result.sessions).forEach(([chatId, sessionData]) => {
                    this.chatSessions.set(chatId, sessionData);
                });

                console.log('📖 从后端加载聊天会话成功，会话数量:', this.chatSessions.size);
            } else {
                console.warn('⚠️ 从后端加载会话失败:', result);
            }
        } catch (error) {
            console.error('❌ 从后端加载聊天会话失败:', error);
        }
    }

    // 保留原方法作为备用
    loadChatSessionsFromLocal() {
        try {
            const sessionsData = localStorage.getItem('llmreader_chat_sessions');
            if (!sessionsData) return;

            const sessionsObj = JSON.parse(sessionsData);

            // 清理过期会话（7天）
            const MAX_AGE = 7 * 24 * 60 * 60 * 1000; // 7天
            const now = Date.now();

            this.chatSessions.clear();

            Object.entries(sessionsObj).forEach(([chatId, sessionData]) => {
                if (now - sessionData.timestamp < MAX_AGE) {
                    this.chatSessions.set(chatId, sessionData);
                }
            });

            console.log('📖 从本地存储加载聊天会话，有效会话数量:', this.chatSessions.size);
        } catch (error) {
            console.error('加载聊天会话失败:', error);
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
                console.log('🔄 恢复聊天会话ID:', this.currentChatId);
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

    /* === 聊天相关方法 === */

    sendMessage() {
        const chatInput = document.getElementById('chat-input');
        const message = chatInput.value.trim();

        if (!message || !this.isConnected) return;

        // 清空输入框
        chatInput.value = '';

        // 通过WebSocket发送消息
        this.websocket.send(JSON.stringify({
            message: message
        }));
    }

    clearChatMessages() {
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = `
            <div class="welcome-message">
                <p>暂无对话历史，请开始提问...</p>
            </div>
        `;
    }

    addChatMessage(role, content, timestamp, shouldScroll = true, addToHistory = true) {
        const chatMessages = document.getElementById('chat-messages');

        // 移除欢迎消息
        const welcomeMessage = chatMessages.querySelector('.welcome-message');
        if (welcomeMessage) {
            welcomeMessage.remove();
        }

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
        const renderedContent = this.renderMarkdown(content);
        contentDiv.innerHTML = renderedContent;

        const timeDiv = document.createElement('div');
        timeDiv.className = 'message-time';
        timeDiv.textContent = new Date(timestamp).toLocaleTimeString();

        messageContent.appendChild(contentDiv);
        messageContent.appendChild(timeDiv);

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(messageContent);

        chatMessages.appendChild(messageDiv);

        // 只有在需要时才添加到聊天历史（避免重复添加）
        if (addToHistory) {
            this.chatHistory.push([role, content, timestamp]);

            // 保存会话到本地存储
            this.saveChatSessionsToLocal();
        }

        if (shouldScroll) {
            // 滚动到底部
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        // 渲染数学公式 - 延迟确保DOM已更新和Markdown已渲染完成
        setTimeout(() => {
            console.log('准备渲染数学公式...');
            this.renderMath(contentDiv);
        }, 300);
    }

    addStatusMessage(message) {
        const chatMessages = document.getElementById('chat-messages');

        const statusDiv = document.createElement('div');
        statusDiv.className = 'status-message-chat';
        statusDiv.textContent = message;

        chatMessages.appendChild(statusDiv);

        // 滚动到底部
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // 5秒后移除状态消息
        setTimeout(() => {
            if (statusDiv.parentNode) {
                statusDiv.remove();
            }
        }, 5000);
    }

    handleProgressUpdate(data) {
        // 更新PDF状态区域
        const pdfStatus = document.getElementById('pdf-status');
        if (pdfStatus) {
            pdfStatus.className = `status-message info`;
            pdfStatus.textContent = data.message;
            pdfStatus.style.display = 'block';
        }

        // 同时在聊天区域显示进度
        this.addStatusMessage(data.message);

        console.log(`[${data.stage}] ${data.message}`);
    }

    showNotification(data) {
        // 创建通知弹窗
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(data.title, {
                body: data.message,
                icon: '/static/favicon.ico'
            });
        }

        // 创建页面内弹窗
        const notification = document.createElement('div');
        notification.className = 'notification-popup';
        notification.innerHTML = `
            <div class="notification-content">
                <h3>🎉 ${data.title}</h3>
                <p>${data.message.replace(/\n/g, '<br>')}</p>
                <button onclick="this.parentElement.parentElement.remove()" class="btn btn-primary btn-sm">确定</button>
            </div>
        `;

        document.body.appendChild(notification);

        // 自动关闭
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 8000);

        // 请求通知权限（如果还没有）
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
    }

    /* === Markdown和数学公式渲染 === */

    renderMarkdown(content) {
        // 检查内容是否为Markdown格式
        if (typeof content !== 'string') {
            return content;
        }

        // 检查是否包含LaTeX数学公式
        const hasLatex = /\$.*\$|\\\(.*\\\)|\\\[[\s\S]*\\\]|\$\$[\s\S]*\$\$/.test(content);

        // 如果内容包含Markdown语法，则渲染
        if (this.isMarkdown(content)) {
            if (typeof marked !== 'undefined') {
                try {
                    // 配置marked选项，禁用sanitizer以保护LaTeX
                    marked.setOptions({
                        breaks: true,
                        gfm: true,
                        sanitize: false,
                        smartLists: true,
                        smartypants: false, // 关闭智能标点，避免影响LaTeX
                        headerIds: false,
                        mangle: false
                    });

                    // 如果包含LaTeX，我们需要小心处理
                    // 即使包含LaTeX，也尝试渲染markdown，因为marked可以处理大部分情况
                    const rendered = marked.parse(content);

                    if (hasLatex) {
                        console.log('检测到LaTeX内容，Markdown已渲染，LaTeX将在后续处理');
                    }

                    return rendered;
                } catch (error) {
                    console.warn('Marked渲染失败:', error);
                    return content.replace(/\n/g, '<br>');
                }
            }
        }

        // 如果不是Markdown或marked未加载，返回原内容（处理换行）
        return content.replace(/\n/g, '<br>');
    }

    isMarkdown(content) {
        // 简单检测是否包含Markdown语法或LaTeX数学公式
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
            /^---+$/m,              // 分隔线
            /\$.*?\$/,              // 行内LaTeX数学公式
            /\$\$[\s\S]*?\$\$/,     // 块级LaTeX数学公式
            /\\\(.*?\\\)/,          // 行内LaTeX数学公式(另一种格式)
            /\\\[[\s\S]*?\\\]/      // 块级LaTeX数学公式(另一种格式)
        ];

        return markdownPatterns.some(pattern => pattern.test(content));
    }

    renderMath(element) {
        // 确保MathJax已加载并且element存在
        if (typeof MathJax !== 'undefined' && MathJax.typesetPromise && element) {
            console.log('开始渲染LaTeX:', element.textContent.substring(0, 100) + '...');

            // 重新处理MathJax
            MathJax.startup.document.clear();
            MathJax.startup.document.updateDocument();

            MathJax.typesetPromise([element]).then(() => {
                console.log('LaTeX渲染成功');
            }).catch((err) => {
                console.warn('MathJax渲染失败:', err);
                // 尝试重新渲染整个文档
                MathJax.typesetPromise().catch(e => console.warn('全局MathJax渲染失败:', e));
            });
        } else {
            console.warn('MathJax未加载或element为空');
        }
    }

    /* === PDF查看器功能 === */

    async loadPdfViewer() {
        console.log('🔧 [DEBUG] loadPdfViewer方法被调用 - 版本已修复，如果看到此消息说明使用的是新版本');

        if (!this.config.currentDocName) {
            console.log('📄 没有当前文档名，跳过PDF查看器加载');
            return;
        }

        const pdfViewerContainer = document.getElementById('pdf-viewer-container');
        if (!pdfViewerContainer) {
            console.log('📄 PDF查看器容器不存在，跳过PDF查看器加载（当前页面不需要PDF查看器）');
            return;
        }
        pdfViewerContainer.style.display = 'block';

        // 初始化PDF查看器状态
        this.pdfViewerState = {
            currentPage: 1,
            totalPages: 0,
            pdfUrl: null,
            images: []
        };

        // 尝试加载PDF文件
        try {
            await this.tryLoadPdfFile();
        } catch (error) {
            console.log('无法加载PDF文件，尝试加载图片:', error);
            await this.tryLoadPdfImages();
        }

        // 绑定控制按钮事件
        this.bindPdfViewerEvents();
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
        const response = await fetch(this.getApiUrl(`/api/v1/pdf/images/${this.config.currentDocName}`));
        const result = await response.json();

        if (result.status === 'success') {
            this.pdfViewerState.images = result.images;
            this.pdfViewerState.totalPages = result.images.length;
            this.displayPdfImages();
        } else {
            this.displayNoPdfContent();
        }
    }

    displayPdfFile() {
        const content = document.getElementById('pdf-viewer-content');
        if (!content) {
            console.log('📄 PDF查看器内容容器不存在，跳过PDF文件显示');
            return;
        }
        content.innerHTML = `
            <embed src="${this.pdfViewerState.pdfUrl}"
                   type="application/pdf"
                   class="pdf-embedded">
        `;

        // 更新页面信息（PDF文件模式下不显示页码控制）
        const pageInfo = document.getElementById('pdf-page-info');
        const prevBtn = document.getElementById('pdf-prev-page');
        const nextBtn = document.getElementById('pdf-next-page');

        if (pageInfo) pageInfo.textContent = 'PDF文件模式';
        if (prevBtn) prevBtn.style.display = 'none';
        if (nextBtn) nextBtn.style.display = 'none';
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
        const content = document.getElementById('pdf-viewer-content');
        if (!content) {
            console.log('📄 PDF查看器内容容器不存在，跳过页面更新');
            return;
        }

        const currentImage = this.pdfViewerState.images[this.pdfViewerState.currentPage - 1];

        if (currentImage) {
            content.innerHTML = `
                <div class="pdf-page-display">
                    <img src="${this.getApiUrl(currentImage.url)}"
                         alt="PDF第${currentImage.page}页"
                         class="pdf-page-image">
                </div>
            `;
        }

        // 更新页面信息和按钮状态
        this.updatePdfControls();
    }

    updatePdfControls() {
        const pageInfo = document.getElementById('pdf-page-info');
        const prevBtn = document.getElementById('pdf-prev-page');
        const nextBtn = document.getElementById('pdf-next-page');

        if (!pageInfo || !prevBtn || !nextBtn) {
            console.log('📄 PDF控制元素不存在，跳过控制更新');
            return;
        }

        pageInfo.textContent = `第 ${this.pdfViewerState.currentPage} 页 / 共 ${this.pdfViewerState.totalPages} 页`;

        prevBtn.disabled = this.pdfViewerState.currentPage <= 1;
        nextBtn.disabled = this.pdfViewerState.currentPage >= this.pdfViewerState.totalPages;

        prevBtn.style.display = 'inline-block';
        nextBtn.style.display = 'inline-block';
    }

    displayNoPdfContent() {
        const content = document.getElementById('pdf-viewer-content');
        if (!content) {
            console.log('📄 PDF查看器内容容器不存在，跳过无内容显示');
            return;
        }
        content.innerHTML = `
            <div style="text-align: center; color: var(--text-muted); padding: 2rem;">
                <p>📄 PDF内容不可用</p>
                <p>请检查文件是否已正确处理</p>
            </div>
        `;

        const pageInfo = document.getElementById('pdf-page-info');
        const prevBtn = document.getElementById('pdf-prev-page');
        const nextBtn = document.getElementById('pdf-next-page');

        if (pageInfo) pageInfo.textContent = '无内容';
        if (prevBtn) prevBtn.style.display = 'none';
        if (nextBtn) nextBtn.style.display = 'none';
    }

    bindPdfViewerEvents() {
        const prevBtn = document.getElementById('pdf-prev-page');
        const nextBtn = document.getElementById('pdf-next-page');

        if (!prevBtn || !nextBtn) {
            console.log('📄 PDF控制按钮不存在，跳过事件绑定');
            return;
        }

        prevBtn.addEventListener('click', () => {
            if (this.pdfViewerState.currentPage > 1) {
                this.pdfViewerState.currentPage--;
                this.updatePdfPage();
            }
        });

        nextBtn.addEventListener('click', () => {
            if (this.pdfViewerState.currentPage < this.pdfViewerState.totalPages) {
                this.pdfViewerState.currentPage++;
                this.updatePdfPage();
            }
        });
    }

    /* === 全局会话管理方法 === */

    async createNewGlobalSession() {
        // 保存当前会话到历史（如果存在且有消息）
        if (this.currentChatId && this.chatHistory.length > 0) {
            this.saveChatSession(this.currentChatId);
            console.log('💾 保存当前会话到历史:', this.currentChatId);
        }

        try {
            // 调用后端API清除聊天历史 - 新会话需要全新开始
            const response = await fetch(this.getApiUrl('/api/v1/chat/clear'), {
                method: 'POST'
            });

            if (response.ok) {
                console.log('✅ 后端聊天历史已清除');
            } else {
                console.warn('⚠️ 清除后端聊天历史失败');
            }

            // 🔥 新增：同时清除后端配置状态，确保文档状态完全重置
            try {
                const configResponse = await fetch(this.getApiUrl('/api/v1/config/clear'), {
                    method: 'POST'
                });

                if (configResponse.ok) {
                    console.log('✅ 后端配置状态已清除');
                } else {
                    console.warn('⚠️ 清除后端配置状态失败');
                }
            } catch (configError) {
                console.warn('⚠️ 清除后端配置状态时发生错误:', configError);
            }

        } catch (error) {
            console.warn('⚠️ 清除后端聊天历史时发生错误:', error);
        }

        // 重置全局状态 - 这是全局级别的新建会话
        this.currentChatId = this.generateUUID();
        this.chatHistory = [];

        // 重置文档状态 - 新会话需要重新选择文档
        this.config.currentDocName = null;
        this.config.hasPdfReader = false;
        this.config.hasWebReader = false;

        console.log('🌟 创建全局新会话:', this.currentChatId);
        console.log('🔄 重置文档状态，需要重新加载文档');

        // 🔥 新增：清除内容缓存 - 只有在新建会话时才清除
        this.clearContentCache();
        console.log('🗑️ 新建会话时清除内容缓存');

        // 清除UI缓存和显示
        this.clearAllCacheAndUI();

        // 清除本地存储的文档状态
        this.clearDocumentStateFromLocal();

        // 更新UI显示
        this.updateDocumentStatus();
        this.updateSessionStatus();

        // 保存新状态到本地存储（空状态）
        this.saveDocumentStateToLocal();
        this.saveChatSessionsToLocal();

        this.showStatus('success', '已创建新的全局会话，所有状态已完全清除', 'config');

        return this.currentChatId;
    }

    generateSessionTitle(messages) {
        if (!messages || messages.length === 0) {
            return '新对话';
        }

        // 找到第一条用户消息作为标题
        const firstUserMessage = messages.find(([role]) => role === 'user');
        if (firstUserMessage) {
            const content = firstUserMessage[1];
            // 截取前20个字符作为标题
            return content.length > 20 ? content.substring(0, 20) + '...' : content;
        }

        return '新对话';
    }

    /* === 会话模态框管理 === */

    initSessionsModal() {
        const modal = document.getElementById('sessions-modal');
        const closeBtn = document.getElementById('close-sessions-modal');
        const newSessionModalBtn = document.getElementById('new-session-modal-btn');
        const clearAllSessionsModalBtn = document.getElementById('clear-all-sessions-modal-btn');

        // 关闭模态框
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this.hideSessionsModal();
            });
        }

        // 点击遮罩层关闭模态框
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.hideSessionsModal();
                }
            });
        }

        // 模态框内的新建会话按钮
        if (newSessionModalBtn) {
            newSessionModalBtn.addEventListener('click', () => {
                this.createNewGlobalSession();
                this.hideSessionsModal();
            });
        }

        // 清空所有会话按钮
        if (clearAllSessionsModalBtn) {
            clearAllSessionsModalBtn.addEventListener('click', () => {
                this.clearAllSessions();
            });
        }
    }

    showSessionsModal() {
        console.log('🔍 尝试显示会话模态框...');
        console.log('📊 当前会话数量:', this.chatSessions.size);
        console.log('📋 会话详情:', Array.from(this.chatSessions.keys()));

        // 调试会话数据
        this.chatSessions.forEach((sessionData, chatId) => {
            console.log(`📂 会话 ${chatId}:`, {
                docName: sessionData.docName,
                messageCount: sessionData.messages?.length || 0,
                timestamp: new Date(sessionData.timestamp).toLocaleString()
            });
        });

        const modal = document.getElementById('sessions-modal');
        if (modal) {
            console.log('✅ 找到模态框元素，开始渲染会话列表');
            // 渲染会话列表
            this.renderMainSessionsList();
            modal.style.display = 'flex';
            console.log('✅ 模态框已显示');
        } else {
            console.error('❌ 找不到sessions-modal元素');
        }
    }

    hideSessionsModal() {
        const modal = document.getElementById('sessions-modal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    renderMainSessionsList() {
        const sessionsList = document.getElementById('main-sessions-list');
        if (!sessionsList) return;

        if (this.chatSessions.size === 0) {
            sessionsList.innerHTML = `
                <div class="empty-message">
                    <p>暂无聊天会话</p>
                    <p>点击"新建会话"开始对话</p>
                </div>
            `;
            return;
        }

        // 按时间戳排序会话（最新的在前）
        const sortedSessions = Array.from(this.chatSessions.entries()).sort((a, b) => {
            return b[1].timestamp - a[1].timestamp;
        });

        const sessionItems = sortedSessions.map(([chatId, sessionData]) => {
            const isActive = chatId === this.currentChatId;
            const sessionTitle = this.generateSessionTitle(sessionData.messages);
            const sessionPreview = this.generateSessionPreview(sessionData.messages);
            const timeDisplay = this.formatRelativeTime(sessionData.timestamp);

            return `
                <div class="session-item ${isActive ? 'active' : ''}" data-chat-id="${chatId}">
                    <div class="session-info">
                        <h4 class="session-title">${sessionTitle}</h4>
                        <div class="session-meta">
                            <span class="session-doc">${sessionData.docName || '无文档'}</span>
                            <span class="session-time">${timeDisplay}</span>
                        </div>
                        ${sessionPreview ? `<div class="session-preview">${sessionPreview}</div>` : ''}
                    </div>
                    <div class="session-actions">
                        <button class="session-action-btn" data-action="switch" data-chat-id="${chatId}">
                            切换
                        </button>
                        <button class="session-action-btn delete" data-action="delete" data-chat-id="${chatId}">
                            删除
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        sessionsList.innerHTML = sessionItems;

        // 每次渲染后重新绑定事件，因为HTML内容已更新
        this.bindMainSessionEvents();
    }

    bindMainSessionEvents() {
        const sessionsList = document.getElementById('main-sessions-list');
        if (!sessionsList) return;

        // 移除之前的事件监听器（如果存在）
        if (this.mainSessionEventHandler) {
            sessionsList.removeEventListener('click', this.mainSessionEventHandler);
        }

        // 创建新的事件处理器
        this.mainSessionEventHandler = async (e) => {
            console.log('🖱️ 会话列表点击事件:', e.target);
            const sessionItem = e.target.closest('.session-item');
            const actionBtn = e.target.closest('.session-action-btn');

            console.log('📋 事件分析:', {
                sessionItem: !!sessionItem,
                actionBtn: !!actionBtn,
                targetClass: e.target.className,
                targetTag: e.target.tagName
            });

            if (actionBtn) {
                e.stopPropagation();
                const action = actionBtn.getAttribute('data-action');
                const chatId = actionBtn.getAttribute('data-chat-id');
                console.log(`🔘 点击动作按钮: ${action}, 会话ID: ${chatId}`);

                if (action === 'switch') {
                    // 立即关闭弹窗
                    this.hideSessionsModal();

                    // 在主页面显示加载状态
                    this.showStatus('info', '正在切换会话，重新加载文档...', 'config');

                    try {
                        const success = await this.switchToSession(chatId);
                        if (!success) {
                            this.showStatus('error', '会话切换失败', 'config');
                        }
                    } catch (error) {
                        console.error('❌ 会话切换失败:', error);
                        this.showStatus('error', `会话切换失败: ${error.message}`, 'config');
                    }
                } else if (action === 'delete') {
                    this.deleteSession(chatId);
                }
            } else if (sessionItem) {
                const chatId = sessionItem.getAttribute('data-chat-id');
                console.log(`📂 点击会话项: 会话ID ${chatId}`);

                // 立即关闭弹窗
                this.hideSessionsModal();

                // 在主页面显示加载状态
                this.showStatus('info', '正在切换会话，重新加载文档...', 'config');

                try {
                    console.log('🔄 开始切换会话...');
                    const success = await this.switchToSession(chatId);
                    if (!success) {
                        this.showStatus('error', '会话切换失败', 'config');
                    }
                } catch (error) {
                    console.error('❌ 会话切换失败:', error);
                    this.showStatus('error', `会话切换失败: ${error.message}`, 'config');
                }
            } else {
                console.log('⚠️ 既不是动作按钮也不是会话项的点击');
            }
        };

        // 绑定事件监听器
        sessionsList.addEventListener('click', this.mainSessionEventHandler);
        console.log('✅ 会话列表事件监听器已绑定');
    }

    async switchToSession(chatId) {
        console.log('🔄 开始切换到会话:', chatId);

        // 保存当前会话（如果有消息）
        if (this.currentChatId && this.chatHistory.length > 0) {
            this.saveChatSession(this.currentChatId);
        }

        // 加载指定会话
        const sessionData = this.chatSessions.get(chatId);
        if (!sessionData) {
            console.error('❌ 会话不存在:', chatId);
            this.showStatus('error', '会话不存在', 'config');
            return false;
        }

        console.log('🔄 切换到会话:', chatId, '文档:', sessionData.docName);

        // 恢复会话状态
        this.currentChatId = chatId;
        // 🔥 修复消息格式 - 确保从后端加载的消息格式正确
        this.chatHistory = sessionData.messages ? sessionData.messages.map(msg => {
            // 如果是后端格式的消息对象，转换为数组格式
            if (msg.role && msg.content && msg.timestamp) {
                return [msg.role, msg.content, msg.timestamp];
            }
            // 如果已经是数组格式，直接使用
            return msg;
        }) : [];

        // 恢复文档状态
        if (sessionData.docName) {
            this.config.currentDocName = sessionData.docName;
            this.config.hasPdfReader = sessionData.hasPdfReader || false;
            this.config.hasWebReader = sessionData.hasWebReader || false;
            this.config.provider = sessionData.provider || this.config.provider;

            console.log('📄 恢复完整文档状态:', {
                docName: sessionData.docName,
                hasPdfReader: this.config.hasPdfReader,
                hasWebReader: this.config.hasWebReader
            });

            // 🔥 根据文档类型选择不同的初始化方式
            try {
                let response, result;
                
                if (this.config.hasWebReader) {
                    // Web Reader 初始化
                    console.log('🔄 正在重新初始化 Web 阅读器...');
                    this.showStatus('info', `正在重新初始化 Web: ${sessionData.docName}...`, 'config');

                    // 调用后端API重新初始化 Web 阅读器
                    response = await fetch(this.getApiUrl(`/api/v1/web/initialize/${sessionData.docName}`), {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ url: null })
                    });
                    
                    result = await response.json();
                } else {
                    // PDF Reader 初始化
                    console.log('🔄 正在重新初始化 PDF 阅读器...');
                    this.showStatus('info', `正在重新初始化 PDF: ${sessionData.docName}...`, 'config');

                    // 调用后端API重新初始化PDF阅读器
                    response = await fetch(this.getApiUrl(`/api/v1/pdf/reinitialize/${sessionData.docName}`), {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    });
                    
                    result = await response.json();
                }

                if (response.ok && result.status === 'success') {
                    const readerType = this.config.hasWebReader ? 'Web' : 'PDF';
                    console.log(`✅ ${readerType}阅读器重新初始化成功:`, result.message);

                    // 更新配置状态（保持原有状态）
                    this.config.hasPdfReader = sessionData.hasPdfReader || false;
                    this.config.hasWebReader = sessionData.hasWebReader || false;

                    // 🔥 关键修复：保存状态到localStorage，确保状态同步
                    this.saveDocumentStateToLocal();
                    console.log('💾 会话切换后状态已保存到localStorage');

                    // 立即更新UI状态
                    this.updateDocumentStatus();
                    this.updateSessionStatus();
                    this.updateChatEntryStatus();

                    this.showStatus('info', '正在加载摘要信息...', 'config');

                    // 显示总结区域并加载总结内容
                    this.showSummarySection();
                    console.log('🔄 开始加载摘要内容...');

                    // 加载简要总结
                    await this.loadSummary('brief');

                    // 强制展开摘要内容，确保用户能看到结果
                    setTimeout(() => {
                        const briefContent = document.getElementById('brief-content');
                        const contentHeader = document.querySelector('[data-target="brief-content"]');
                        if (briefContent && contentHeader) {
                            briefContent.classList.remove('collapsed');
                            briefContent.classList.add('expanded');
                            contentHeader.classList.add('expanded');
                            console.log('✅ 摘要内容已强制展开');
                        }
                    }, 1000);

                    // 再次强制更新聊天入口状态，确保按钮可用
                    setTimeout(() => {
                        this.updateChatEntryStatus();
                        console.log('🔄 延迟更新聊天入口状态');
                    }, 1500);

                    console.log('✅ 总结区域已显示并加载');

                    // 显示明确的完成提示
                    this.showStatus('success', `✅ 会话切换完成: ${sessionData.docName} 已重新加载，可以开始聊天`, 'config');

                } else if (result.status === 'needs_processing') {
                    const readerType = this.config.hasWebReader ? 'Web内容' : 'PDF';
                    console.warn(`⚠️ ${readerType}需要重新处理:`, result.message);
                    this.showStatus('warning', `${readerType} ${sessionData.docName} 需要重新处理`, 'config');
                    return false;
                } else {
                    const readerType = this.config.hasWebReader ? 'Web' : 'PDF';
                    console.error(`❌ ${readerType}重新初始化失败:`, result);
                    // 🔥 降级处理：即使API失败，也尝试恢复基本状态
                    console.log('🔄 API失败，尝试降级处理恢复基本状态...');

                    // 设置基本配置状态
                    this.config.hasPdfReader = sessionData.hasPdfReader || false;
                    this.config.hasWebReader = sessionData.hasWebReader || false;

                    // 保存状态到localStorage
                    this.saveDocumentStateToLocal();

                    // 更新UI状态
                    this.updateDocumentStatus();
                    this.updateSessionStatus();
                    this.updateChatEntryStatus();

                    // 尝试加载摘要（可能会成功）
                    try {
                        this.showSummarySection();
                        await this.loadSummary('brief');
                        this.showStatus('warning', `⚠️ 会话已切换但${readerType}初始化有问题，部分功能可能受限`, 'config');
                    } catch (summaryError) {
                        console.error('摘要加载也失败:', summaryError);
                        this.showStatus('warning', `⚠️ 会话已切换，但文档状态恢复不完整，请重新处理文档`, 'config');
                    }

                    return true; // 返回true表示至少基本状态已恢复
                }

            } catch (error) {
                const readerType = this.config.hasWebReader ? 'Web' : 'PDF';
                console.error(`❌ ${readerType}自动加载失败:`, error);
                // 🔥 降级处理：即使API请求失败，也尝试恢复基本状态
                console.log('🔄 API请求失败，尝试降级处理恢复基本状态...');

                // 设置基本配置状态
                this.config.hasPdfReader = sessionData.hasPdfReader || false;
                this.config.hasWebReader = sessionData.hasWebReader || false;

                // 保存状态到localStorage
                this.saveDocumentStateToLocal();

                // 更新UI状态
                this.updateDocumentStatus();
                this.updateSessionStatus();
                this.updateChatEntryStatus();

                // 尝试显示摘要区域（可能会成功）
                try {
                    this.showSummarySection();
                    this.showStatus('warning', `⚠️ 会话已切换但网络异常，请检查${readerType}处理状态`, 'config');
                } catch (summaryError) {
                    console.error('显示摘要区域失败:', summaryError);
                    this.showStatus('warning', `⚠️ 会话已切换，但界面恢复不完整，请刷新页面`, 'config');
                }

                return true; // 返回true表示至少基本状态已恢复
            }
        } else {
            // 清空文档状态
            this.config.currentDocName = null;
            this.config.hasPdfReader = false;
            this.config.hasWebReader = false;
        }

        // 保存状态到本地存储
        this.saveDocumentStateToLocal();
        console.log('✅ 文档状态已保存到本地');

        // 🔥 新增：触发存储事件，通知其他页面状态变化
        try {
            // 手动触发storage事件，因为同一页面的localStorage变化不会自动触发
            window.dispatchEvent(new StorageEvent('storage', {
                key: 'llmreader_document_state',
                newValue: localStorage.getItem('llmreader_document_state'),
                storageArea: localStorage
            }));
            console.log('📢 已通知其他页面状态变化');
        } catch (eventError) {
            console.warn('触发存储事件失败:', eventError);
        }

        console.log('✅ 会话切换完成，所有UI已更新');
        return true;
    }

    async deleteSession(chatId) {
        // 防止重复执行删除操作
        if (this.deletingSession === chatId) {
            console.log('⚠️ 正在删除会话，忽略重复操作:', chatId);
            return;
        }

        if (confirm('确定要删除这个会话吗？')) {
            this.deletingSession = chatId; // 标记正在删除的会话
            console.log('🗑️ 开始删除会话:', chatId);

            try {
                // 🔥 关键：调用后端API删除会话及其对应的JSON文件
                console.log('📤 调用后端API删除会话文件...');
                const deleteResponse = await fetch(this.getApiUrl(`/api/v1/sessions/${chatId}`), {
                    method: 'DELETE'
                });

                if (deleteResponse.ok) {
                    console.log('✅ 后端会话文件已删除:', chatId);
                } else {
                    const errorData = await deleteResponse.json();
                    console.warn('⚠️ 后端删除会话失败:', errorData);
                    this.showStatus('error', `删除会话失败: ${errorData.detail || '未知错误'}`, 'config');
                    this.deletingSession = null;
                    return;
                }
            } catch (error) {
                console.error('❌ 调用后端删除API失败:', error);
                this.showStatus('error', `删除会话失败: ${error.message}`, 'config');
                this.deletingSession = null;
                return;
            }

            // 从内存中删除会话
            this.chatSessions.delete(chatId);
            console.log('🗑️ 从内存中删除会话:', chatId);

            // 如果删除的是当前会话，清除当前会话状态
            if (this.currentChatId === chatId) {
                try {
                    // 调用后端API清除聊天历史
                    const response = await fetch(this.getApiUrl('/api/v1/chat/clear'), {
                        method: 'POST'
                    });

                    if (response.ok) {
                        console.log('✅ 删除当前会话时后端聊天历史已清除');
                    } else {
                        console.warn('⚠️ 删除当前会话时清除后端聊天历史失败');
                    }
                } catch (error) {
                    console.warn('⚠️ 删除当前会话时清除后端聊天历史发生错误:', error);
                }

                // 清除当前会话状态，但不自动创建新会话
                this.currentChatId = null;
                this.chatHistory = [];

                console.log('🔄 已清除当前会话状态，用户可手动创建新会话');
            }

            // 保存更新后的会话列表到本地存储
            this.saveChatSessionsToLocal();

            // 更新会话列表显示
            this.renderMainSessionsList();
            this.updateSessionStatus();

            console.log('✅ 会话删除完成，文件和内存都已清理');
            this.showStatus('success', '会话已删除（包括本地JSON文件）', 'config');

            // 清除删除标志
            this.deletingSession = null;
        } else {
            // 用户取消删除，清除标志
            this.deletingSession = null;
        }
    }

    async clearAllSessions() {
        if (confirm('确定要清空所有聊天会话吗？这将删除所有历史对话记录。')) {
            try {
                // 调用后端API清除聊天历史
                const response = await fetch(this.getApiUrl('/api/v1/chat/clear'), {
                    method: 'POST'
                });

                if (response.ok) {
                    console.log('✅ 后端聊天历史已清除');
                } else {
                    console.warn('⚠️ 清除后端聊天历史失败');
                }

                // 🔥 调用后端清除会话数据
                try {
                    const sessionsResponse = await fetch(this.getApiUrl('/api/v1/sessions/clear'), {
                        method: 'DELETE'
                    });
                    if (sessionsResponse.ok) {
                        console.log('✅ 后端会话数据已清除');
                    }
                } catch (sessionError) {
                    console.warn('⚠️ 清除后端会话数据失败:', sessionError);
                }

                // 清除所有会话数据
                this.chatSessions.clear();

                // 🔥 新增：清除内容缓存 - 清空所有会话时也清除缓存
                this.clearContentCache();
                console.log('🗑️ 清空所有会话时清除内容缓存');

                // 创建新的全局会话
                this.createNewGlobalSession();

                // 清除本地存储
                localStorage.removeItem('llmreader_chat_sessions');

                console.log('🗑️ 已清空所有聊天会话');

                // 更新会话列表显示
                this.renderMainSessionsList();
                this.updateSessionStatus();

                this.showStatus('success', '所有会话已清空', 'config');
            } catch (error) {
                console.error('清空会话时发生错误:', error);
                this.showStatus('error', '清空会话失败', 'config');
            }
        }
    }

    generateSessionPreview(messages) {
        if (!messages || messages.length === 0) {
            return '';
        }

        // 找到最后一条assistant消息作为预览
        const lastAssistantMessage = [...messages].reverse().find(([role]) => role === 'assistant');
        if (lastAssistantMessage) {
            const content = lastAssistantMessage[1];
            // 截取前40个字符作为预览
            return content.length > 40 ? content.substring(0, 40) + '...' : content;
        }

        return '';
    }

    formatRelativeTime(timestamp) {
        const now = Date.now();
        const diff = now - timestamp;

        const minutes = Math.floor(diff / (1000 * 60));
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));

        if (minutes < 1) {
            return '刚刚';
        } else if (minutes < 60) {
            return `${minutes}分钟前`;
        } else if (hours < 24) {
            return `${hours}小时前`;
        } else if (days < 7) {
            return `${days}天前`;
        } else {
            return new Date(timestamp).toLocaleDateString();
        }
    }
}

// 确保页面完全加载后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 DOM内容已加载');
    // 稍微延迟一下确保所有元素都渲染完成
    setTimeout(async () => {
        try {
            console.log('🚀 开始初始化LLMReaderApp');
            window.llmReaderApp = new LLMReaderApp();
            console.log('✅ LLMReaderApp 已创建');
        } catch (error) {
            console.error('❌ 创建 LLMReaderApp 失败:', error);
            // 显示错误信息给用户
            const body = document.body;
            if (body) {
                const errorDiv = document.createElement('div');
                errorDiv.style.cssText = 'position: fixed; top: 10px; right: 10px; background: #dc3545; color: white; padding: 10px; border-radius: 5px; z-index: 9999;';
                errorDiv.textContent = '应用初始化失败，请刷新页面重试';
                body.appendChild(errorDiv);

                // 5秒后移除错误提示
                setTimeout(() => {
                    if (errorDiv.parentNode) {
                        errorDiv.parentNode.removeChild(errorDiv);
                    }
                }, 5000);
            }
        }
    }, 200);
});