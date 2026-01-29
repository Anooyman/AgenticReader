/**
 * 配置管理页面
 */

class ConfigManager {
    constructor() {
        console.log('[Config] ConfigManager 初始化...');
        this.config = null;
        this.init();
    }

    async init() {
        console.log('[Config] 开始初始化...');
        this.setupEventListeners();
        await this.loadConfig();
        console.log('[Config] 初始化完成');
    }

    setupEventListeners() {
        console.log('[Config] 设置事件监听器...');

        // 提供商选择
        const providerSelect = document.getElementById('provider-select');
        if (providerSelect) {
            providerSelect.addEventListener('change', (e) => {
                console.log('[Config] 提供商变更:', e.target.value);
                this.updateProviderInfo(e.target.value);
            });
        } else {
            console.error('[Config] 未找到 provider-select 元素');
        }

        // PDF质量预设选择
        const pdfPreset = document.getElementById('pdf-preset');
        if (pdfPreset) {
            pdfPreset.addEventListener('change', (e) => {
                console.log('[Config] PDF预设变更:', e.target.value);
                this.updatePresetInfo(e.target.value);
            });
        } else {
            console.error('[Config] 未找到 pdf-preset 元素');
        }

        // 保存配置
        const saveBtn = document.getElementById('save-config-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => {
                console.log('[Config] 点击保存按钮');
                this.saveConfig();
            });
            console.log('[Config] 保存按钮事件已绑定');
        } else {
            console.error('[Config] 未找到 save-config-btn 元素');
        }

        // 重置配置
        const resetBtn = document.getElementById('reset-config-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                console.log('[Config] 点击重置按钮');
                this.resetConfig();
            });
            console.log('[Config] 重置按钮事件已绑定');
        } else {
            console.error('[Config] 未找到 reset-config-btn 元素');
        }
    }

    async loadConfig() {
        console.log('[Config] 开始加载配置...');
        try {
            UIComponents.showLoading('加载配置...');

            const response = await fetch('/api/v1/config');
            console.log('[Config] 配置响应状态:', response.status);
            const data = await response.json();
            console.log('[Config] 加载的配置数据:', data);

            this.config = data;

            // 填充表单
            document.getElementById('provider-select').value = data.provider || 'openai';
            document.getElementById('pdf-preset').value = data.pdf_preset || 'high';
            document.getElementById('auto-save-outputs').checked = data.auto_save_outputs !== false;
            document.getElementById('enable-notifications').checked = data.enable_notifications !== false;
            document.getElementById('log-level').value = data.log_level || 'INFO';

            console.log('[Config] 表单已填充');

            // 更新信息显示
            this.updateProviderInfo(data.provider || 'openai');
            this.updatePresetInfo(data.pdf_preset || 'high');

            UIComponents.hideLoading();
            console.log('[Config] 配置加载完成');
        } catch (error) {
            console.error('[Config] 加载配置错误:', error);
            UIComponents.hideLoading();
            Utils.notify('加载配置失败: ' + error.message, 'error');
        }
    }

    updateProviderInfo(provider) {
        const infoDiv = document.getElementById('provider-info');
        const providerInfo = {
            'azure': '<p><strong>Azure OpenAI</strong> - 使用 Microsoft Azure 托管的 OpenAI 服务</p><p>需要配置: CHAT_API_KEY, CHAT_AZURE_ENDPOINT, CHAT_DEPLOYMENT_NAME</p>',
            'openai': '<p><strong>OpenAI</strong> - 使用 OpenAI 官方 API</p><p>需要配置: OPENAI_API_KEY, OPENAI_MODEL_NAME (默认: gpt-3.5-turbo)</p>',
            'ollama': '<p><strong>Ollama</strong> - 使用本地运行的 Ollama 模型</p><p>需要配置: OLLAMA_BASE_URL (默认: http://localhost:11434), OLLAMA_MODEL_NAME</p>',
            'gemini': '<p><strong>Gemini</strong> - 使用 Google Generative AI 服务</p><p>需要配置: GEMINI_API_KEY, GEMINI_MODEL_NAME (默认: gemini-1.5-pro), GEMINI_BASE_URL (可选)</p>'
        };

        infoDiv.innerHTML = providerInfo[provider] || providerInfo['openai'];
    }

    updatePresetInfo(preset) {
        const infoDiv = document.getElementById('preset-info');
        const presetInfo = {
            'fast': {
                dpi: 150,
                quality: 'low',
                desc: '快速处理，适合预览和测试'
            },
            'balanced': {
                dpi: 200,
                quality: 'medium',
                desc: '平衡速度和质量，适合一般文档'
            },
            'high': {
                dpi: 300,
                quality: 'high',
                desc: '高质量OCR效果，推荐用于重要文档'
            },
            'ultra': {
                dpi: 600,
                quality: 'ultra',
                desc: '超高质量，适合扫描件或图片质量较差的文档'
            }
        };

        const info = presetInfo[preset] || presetInfo['high'];
        infoDiv.innerHTML =
            '<strong>当前设置详情:</strong><br>' +
            '📐 DPI: ' + info.dpi + '<br>' +
            '🎨 质量: ' + info.quality + '<br>' +
            '📝 说明: ' + info.desc;
    }

    async saveConfig() {
        console.log('[Config] 开始保存配置...');
        try {
            UIComponents.showLoading('保存配置...');

            // 保存提供商配置
            const providerConfig = {
                provider: document.getElementById('provider-select').value,
                pdf_preset: document.getElementById('pdf-preset').value
            };
            console.log('[Config] 提供商配置:', providerConfig);

            const providerResponse = await fetch('/api/v1/config/provider', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(providerConfig)
            });

            console.log('[Config] 提供商响应状态:', providerResponse.status);
            if (!providerResponse.ok) {
                const errorText = await providerResponse.text();
                console.error('[Config] 提供商保存失败:', errorText);
                throw new Error('保存提供商配置失败');
            }

            const providerData = await providerResponse.json();
            console.log('[Config] 提供商保存成功:', providerData);

            // 保存系统配置
            const systemConfig = {
                auto_save_outputs: document.getElementById('auto-save-outputs').checked,
                enable_notifications: document.getElementById('enable-notifications').checked,
                log_level: document.getElementById('log-level').value
            };
            console.log('[Config] 系统配置:', systemConfig);

            const systemResponse = await fetch('/api/v1/config/system', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(systemConfig)
            });

            console.log('[Config] 系统响应状态:', systemResponse.status);
            if (!systemResponse.ok) {
                const errorText = await systemResponse.text();
                console.error('[Config] 系统保存失败:', errorText);
                throw new Error('保存系统配置失败');
            }

            const systemData = await systemResponse.json();
            console.log('[Config] 系统保存成功:', systemData);

            UIComponents.hideLoading();
            this.showStatus('✅ 配置保存成功', 'success');
            Utils.notify('配置保存成功', 'success');
            console.log('[Config] 配置保存完成');

        } catch (error) {
            console.error('[Config] 保存配置错误:', error);
            UIComponents.hideLoading();
            this.showStatus('❌ 保存失败: ' + error.message, 'error');
            Utils.notify('保存配置失败: ' + error.message, 'error');
        }
    }

    async resetConfig() {
        const confirmed = await UIComponents.confirm(
            '确定要重置所有配置为默认值吗？',
            '确认重置'
        );

        if (!confirmed) return;

        try {
            UIComponents.showLoading('重置配置...');

            const response = await fetch('/api/v1/config/reset', {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error('重置配置失败');
            }

            const data = await response.json();

            UIComponents.hideLoading();
            this.showStatus('✅ 配置已重置为默认值', 'success');
            Utils.notify('配置已重置为默认值', 'success');

            // 重新加载配置
            await this.loadConfig();

        } catch (error) {
            UIComponents.hideLoading();
            this.showStatus('❌ 重置失败: ' + error.message, 'error');
            Utils.notify('重置配置失败: ' + error.message, 'error');
        }
    }

    showStatus(message, type) {
        const statusDiv = document.getElementById('config-status');
        statusDiv.textContent = message;
        statusDiv.className = 'status-message ' + type;
        statusDiv.style.display = 'block';

        // 3秒后自动隐藏
        setTimeout(() => {
            statusDiv.style.display = 'none';
        }, 3000);
    }
}

// 初始化
const configManager = new ConfigManager();
