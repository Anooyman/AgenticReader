/**
 * LLMReader 配置页面 JavaScript
 * 管理LLM提供商设置、PDF处理参数和系统配置
 */

class LLMReaderConfigApp {
    constructor() {
        this.config = {
            provider: 'openai',
            pdfPreset: 'high',
            autoSaveOutputs: true,
            enableNotifications: true,
            logLevel: 'INFO'
        };

        // API基础URL配置 - 自动检测当前协议和主机
        this.apiBase = `${window.location.protocol}//${window.location.host}`;

        this.init();
    }

    // 获取完整的API URL
    getApiUrl(endpoint) {
        return `${this.apiBase}${endpoint}`;
    }

    async init() {
        console.log('🚀 配置页面初始化开始');

        // 初始化UI组件
        this.initProviderSelection();
        this.initQualityPresets();
        this.initEventListeners();

        // 加载当前配置
        await this.loadConfig();

        console.log('✅ 配置页面初始化完成');
    }

    /* === 初始化方法 === */

    initProviderSelection() {
        const providerSelect = document.getElementById('provider-select');

        providerSelect.addEventListener('change', (e) => {
            this.config.provider = e.target.value;
            this.updateProviderDetails(e.target.value);
        });

        // 初始化显示第一个提供商的详情
        this.updateProviderDetails(providerSelect.value);
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

    initEventListeners() {
        // 保存配置按钮
        document.getElementById('save-config-btn').addEventListener('click', () => {
            this.saveConfig();
        });

        // 重置配置按钮
        document.getElementById('reset-config-btn').addEventListener('click', () => {
            this.resetConfig();
        });

        // 测试连接按钮
        document.getElementById('test-connection-btn').addEventListener('click', () => {
            this.testConnection();
        });

        // 系统配置变更
        document.getElementById('auto-save-outputs').addEventListener('change', (e) => {
            this.config.autoSaveOutputs = e.target.checked;
        });

        document.getElementById('enable-notifications').addEventListener('change', (e) => {
            this.config.enableNotifications = e.target.checked;
        });

        document.getElementById('log-level').addEventListener('change', (e) => {
            this.config.logLevel = e.target.value;
        });
    }

    /* === 提供商详情显示 === */

    updateProviderDetails(provider) {
        const detailsContainer = document.getElementById('provider-details');

        const providerConfigs = {
            azure: {
                name: 'Azure OpenAI',
                envVars: [
                    'CHAT_API_KEY - Azure OpenAI API密钥',
                    'CHAT_AZURE_ENDPOINT - Azure OpenAI服务端点',
                    'CHAT_MODEL_NAME - 模型名称 (如: gpt-4)',
                    'CHAT_DEPLOYMENT_NAME - 部署名称',
                    'CHAT_API_VERSION - API版本'
                ],
                description: 'Microsoft Azure提供的OpenAI服务，提供企业级的安全性和可靠性。'
            },
            openai: {
                name: 'OpenAI',
                envVars: [
                    'OPENAI_API_KEY - OpenAI API密钥',
                    'OPENAI_MODEL_NAME - 模型名称 (如: gpt-4)',
                    'OPENAI_BASE_URL - 自定义API基础URL (可选)'
                ],
                description: 'OpenAI官方API服务，支持最新的GPT模型。'
            },
            ollama: {
                name: 'Ollama',
                envVars: [
                    'OLLAMA_BASE_URL - Ollama服务地址 (如: http://localhost:11434)',
                    'OLLAMA_MODEL_NAME - 本地模型名称',
                    '无需API密钥 - 本地运行'
                ],
                description: '本地运行的开源LLM服务，支持多种开源模型，无需外部API。'
            }
        };

        const config = providerConfigs[provider];

        detailsContainer.innerHTML = `
            <div class="provider-config-card">
                <h4>📋 ${config.name} 配置要求</h4>
                <p class="provider-description">${config.description}</p>

                <h5>🔑 所需环境变量:</h5>
                <ul class="env-vars-list">
                    ${config.envVars.map(envVar => `<li><code>${envVar}</code></li>`).join('')}
                </ul>

                <div class="config-note">
                    <strong>💡 配置提示:</strong>
                    <p>请在 .env 文件中设置这些环境变量，或在系统环境变量中配置。</p>
                    ${provider === 'ollama' ? '<p><strong>Ollama提示:</strong> 请确保Ollama服务正在运行，默认端口为11434。</p>' : ''}
                </div>
            </div>
        `;
    }

    /* === API调用方法 === */

    async loadConfig() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/config'));
            const config = await response.json();

            // 更新本地配置
            this.config = {
                ...this.config,
                provider: config.provider || 'openai',
                pdfPreset: config.pdf_preset || 'high'
            };

            // 更新UI
            document.getElementById('provider-select').value = this.config.provider;
            document.getElementById('pdf-preset').value = this.config.pdfPreset;
            document.getElementById('auto-save-outputs').checked = this.config.autoSaveOutputs;
            document.getElementById('enable-notifications').checked = this.config.enableNotifications;
            document.getElementById('log-level').value = this.config.logLevel;

            // 更新提供商详情
            this.updateProviderDetails(this.config.provider);

            // 触发预设信息更新
            const presetEvent = new Event('change');
            document.getElementById('pdf-preset').dispatchEvent(presetEvent);

            this.showStatus('success', '配置加载成功');
        } catch (error) {
            console.error('加载配置失败:', error);
            this.showStatus('error', '加载配置失败');
        }
    }

    async saveConfig() {
        try {
            const response = await fetch(this.getApiUrl('/api/v1/config/provider'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    provider: this.config.provider,
                    pdf_preset: this.config.pdfPreset,
                    auto_save_outputs: this.config.autoSaveOutputs,
                    enable_notifications: this.config.enableNotifications,
                    log_level: this.config.logLevel
                })
            });

            const result = await response.json();

            if (result.status === 'success') {
                this.showStatus('success', '配置保存成功');

                // 保存到本地存储
                this.saveToLocalStorage();
            } else {
                this.showStatus('error', result.detail || '保存配置失败');
            }
        } catch (error) {
            console.error('保存配置失败:', error);
            this.showStatus('error', '保存配置失败');
        }
    }

    async testConnection() {
        const testBtn = document.getElementById('test-connection-btn');
        const testResults = document.getElementById('test-results');
        const testOutput = document.getElementById('test-output');

        // 显示测试状态
        testBtn.disabled = true;
        testBtn.textContent = '🔄 测试中...';

        testResults.style.display = 'block';
        testOutput.innerHTML = `
            <div class="test-item">
                <span class="test-status testing">⏳</span>
                <span class="test-name">正在测试 ${this.config.provider.toUpperCase()} 连接...</span>
            </div>
        `;

        try {
            const response = await fetch(this.getApiUrl('/api/v1/config/test'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    provider: this.config.provider
                })
            });

            const result = await response.json();

            if (result.status === 'success') {
                testOutput.innerHTML = `
                    <div class="test-item">
                        <span class="test-status success">✅</span>
                        <span class="test-name">连接测试成功</span>
                        <div class="test-details">
                            <p>提供商: ${this.config.provider}</p>
                            <p>响应时间: ${result.response_time || 'N/A'}</p>
                            <p>模型版本: ${result.model_info || 'N/A'}</p>
                        </div>
                    </div>
                `;
                this.showStatus('success', '连接测试成功');
            } else {
                testOutput.innerHTML = `
                    <div class="test-item">
                        <span class="test-status error">❌</span>
                        <span class="test-name">连接测试失败</span>
                        <div class="test-details error">
                            <p>错误信息: ${result.detail || '未知错误'}</p>
                        </div>
                    </div>
                `;
                this.showStatus('error', '连接测试失败: ' + (result.detail || '未知错误'));
            }
        } catch (error) {
            console.error('测试连接失败:', error);
            testOutput.innerHTML = `
                <div class="test-item">
                    <span class="test-status error">❌</span>
                    <span class="test-name">连接测试失败</span>
                    <div class="test-details error">
                        <p>网络错误: ${error.message}</p>
                    </div>
                </div>
            `;
            this.showStatus('error', '网络错误，请检查连接');
        } finally {
            // 恢复按钮状态
            testBtn.disabled = false;
            testBtn.textContent = '🔗 测试连接';
        }
    }

    resetConfig() {
        if (confirm('确定要重置所有配置为默认值吗？此操作不可撤销。')) {
            // 重置为默认配置
            this.config = {
                provider: 'openai',
                pdfPreset: 'high',
                autoSaveOutputs: true,
                enableNotifications: true,
                logLevel: 'INFO'
            };

            // 更新UI
            document.getElementById('provider-select').value = this.config.provider;
            document.getElementById('pdf-preset').value = this.config.pdfPreset;
            document.getElementById('auto-save-outputs').checked = this.config.autoSaveOutputs;
            document.getElementById('enable-notifications').checked = this.config.enableNotifications;
            document.getElementById('log-level').value = this.config.logLevel;

            // 更新提供商详情
            this.updateProviderDetails(this.config.provider);

            // 触发预设信息更新
            const presetEvent = new Event('change');
            document.getElementById('pdf-preset').dispatchEvent(presetEvent);

            this.showStatus('info', '配置已重置为默认值');
        }
    }

    /* === 本地存储方法 === */

    saveToLocalStorage() {
        try {
            localStorage.setItem('llmreader_config', JSON.stringify(this.config));
            console.log('💾 配置已保存到本地存储');
        } catch (error) {
            console.error('保存到本地存储失败:', error);
        }
    }

    loadFromLocalStorage() {
        try {
            const savedConfig = localStorage.getItem('llmreader_config');
            if (savedConfig) {
                const config = JSON.parse(savedConfig);
                this.config = { ...this.config, ...config };
                console.log('📖 从本地存储加载配置');
                return true;
            }
        } catch (error) {
            console.error('从本地存储加载配置失败:', error);
        }
        return false;
    }

    /* === UI辅助方法 === */

    showStatus(type, message) {
        const statusElement = document.getElementById('config-status');

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
}

// 页面加载完成后初始化应用
document.addEventListener('DOMContentLoaded', () => {
    console.log('📄 配置页面DOM内容已加载');
    setTimeout(() => {
        console.log('🚀 开始初始化配置页面应用');
        window.llmReaderConfigApp = new LLMReaderConfigApp();
    }, 200);
});