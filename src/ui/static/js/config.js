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

            const data = await API.config.get();
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
            'openai': '<p><strong>OpenAI</strong> - 使用 OpenAI 官方 API</p><p>需要配置: OPENAI_API_KEY, OPENAI_MODEL_NAME (默认: gpt-6-luna)</p>',
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

            const providerData = await API.config.saveProvider(providerConfig);
            console.log('[Config] 提供商保存成功:', providerData);

            // 保存系统配置
            const systemConfig = {
                auto_save_outputs: document.getElementById('auto-save-outputs').checked,
                enable_notifications: document.getElementById('enable-notifications').checked,
                log_level: document.getElementById('log-level').value
            };
            console.log('[Config] 系统配置:', systemConfig);

            const systemData = await API.config.saveSystem(systemConfig);
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

            await API.config.reset();

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

/**
 * 模型注册表管理（/config 页"模型管理"卡片）
 *
 * 数据模型与 DSH 的 provider+model 组合方式类似：每个 provider 下可登记
 * 多个模型条目（显示名 + 模型名 + 可选 base_url/api_key 覆盖），并选择
 * 一个作为"当前模型"。前端维护 workingRegistry（可编辑副本），"保存模型
 * 配置"时整表提交；api_key 从后端拿不到明文（打码为 has_api_key），编辑
 * 带 key 的条目时留空即表示"保留原值"。
 */
class ModelRegistryManager {
    constructor(configManager) {
        this.configManager = configManager;
        this.provider = 'openai';
        // {current: string|null, items: [{name, model, base_url, api_key, has_api_key}]}
        this.workingRegistry = {};
        this.effective = {};          // 后端报告的各 provider 实际生效模型名
        this.envDefaults = {};        // 各 provider 从 .env/代码默认值解析出的内置配置
        this.editingName = null;      // 正在编辑的条目名；null=新增
        this.init();
    }

    async init() {
        this.setupEventListeners();
        await this.loadRegistry();
    }

    setupEventListeners() {
        document.getElementById('models-provider-select').addEventListener('change', (e) => {
            this.provider = e.target.value;
            this.editingName = null;
            this.hideEntryForm();
            this.renderOverview();
            this.renderList();
        });

        document.getElementById('add-model-btn').addEventListener('click', () => {
            this.openEntryForm(null);
        });

        document.getElementById('save-models-btn').addEventListener('click', () => {
            this.saveRegistry();
        });

        document.getElementById('model-form-save-btn').addEventListener('click', () => {
            this.saveEntryForm();
        });

        document.getElementById('model-form-cancel-btn').addEventListener('click', () => {
            this.hideEntryForm();
        });

        document.getElementById('model-form-test-btn').addEventListener('click', () => {
            this.testConnection();
        });
    }

    async loadRegistry() {
        try {
            const data = await API.config.getModels();
            this.workingRegistry = data.registry || {};
            this.effective = data.effective || {};
            this.envDefaults = data.env_defaults || {};
            this.renderOverview();
            this.renderList();
        } catch (error) {
            console.error('[Models] 加载模型注册表失败:', error);
            this.showModelsStatus('加载模型列表失败: ' + error.message, 'error');
        }
    }

    /** 概览：四个 provider 现在各自实际生效的是什么模型 */
    renderOverview() {
        const overviewDiv = document.getElementById('model-overview');
        if (!overviewDiv) return;
        const names = { openai: 'OpenAI', azure: 'Azure OpenAI', ollama: 'Ollama', gemini: 'Gemini' };
        let html = '';
        for (const provider of Object.keys(names)) {
            const entry = this.workingRegistry[provider];
            const usingRegistry = entry && entry.current;
            const model = this.effective[provider] || '(未配置)';
            const isDefault = !usingRegistry && this.envDefaults[provider];
            html +=
                '<div class="model-overview-item' + (provider === this.provider ? ' active' : '') +
                '" data-provider="' + provider + '">' +
                '  <span class="model-overview-name">' + names[provider] + '</span>' +
                '  <code>' + this.escapeHtml(model) + '</code>' +
                '  <span class="model-overview-src">' +
                (usingRegistry ? '来自注册表: ' + this.escapeHtml(entry.current)
                               : (isDefault ? '来自 .env / 默认值' : '未配置')) +
                '  </span>' +
                '</div>';
        }
        overviewDiv.innerHTML = html;

        overviewDiv.querySelectorAll('.model-overview-item').forEach((el) => {
            el.addEventListener('click', () => {
                const provider = el.getAttribute('data-provider');
                document.getElementById('models-provider-select').value = provider;
                this.provider = provider;
                this.editingName = null;
                this.hideEntryForm();
                this.renderOverview();
                this.renderList();
            });
        });
    }

    /** 当前 provider 的可编辑条目数组（无注册时为空数组） */
    getItems() {
        const entry = this.workingRegistry[this.provider];
        return (entry && entry.items) ? entry.items : [];
    }

    getCurrent() {
        const entry = this.workingRegistry[this.provider];
        return entry ? entry.current : null;
    }

    renderList() {
        const listDiv = document.getElementById('model-registry-list');
        const items = this.getItems();
        const current = this.getCurrent();
        const effectiveModel = this.effective[this.provider];
        const defaults = this.envDefaults[this.provider] || {};
        const hasRegistryCurrent = !!current;

        // 首行：内置默认条目（来自 .env / 代码默认值）。只读——它是没注册
        // 任何条目时的实际生效配置；注册表选定了当前模型后它退回"兜底"角色。
        let html =
            '<div class="model-item model-item-default' + (hasRegistryCurrent ? '' : ' model-item-current') + '">' +
            '  <div class="model-item-main">' +
            '    <div class="model-item-title">⚙️ .env / 默认值' +
            (hasRegistryCurrent ? '' : ' <span class="model-badge">当前</span>') +
            '    </div>' +
            '    <div class="model-item-sub">' +
            '      <code>' + this.escapeHtml(defaults.model || '(未配置)') + '</code>' +
            (defaults.base_url ? ' · ' + this.escapeHtml(defaults.base_url) : '') +
            (hasRegistryCurrent ? ' <span class="model-fallback-note">（注册表选定后未选中条目时的兜底）</span>' : '') +
            '    </div>' +
            '  </div>' +
            '  <div class="model-item-actions">' +
            '    <button class="btn btn-secondary btn-sm model-clone-btn" title="把这条默认配置登记为可编辑条目">复制为条目</button>' +
            '  </div>' +
            '</div>';

        if (items.length === 0) {
            listDiv.innerHTML = html +
                '<div class="model-registry-empty">该 Provider 还没有登记新模型——上面这条就是它' +
                '现在实际生效的配置，可直接"添加模型"在它基础上继续补充。</div>';
            listDiv.querySelector('.model-clone-btn')
                .addEventListener('click', () => this.cloneDefaultEntry());
            return;
        }

        for (const item of items) {
            const isCurrent = item.name === current;
            html +=
                '<div class="model-item' + (isCurrent ? ' model-item-current' : '') + '" data-name="' + this.escapeAttr(item.name) + '">' +
                '  <div class="model-item-main">' +
                '    <div class="model-item-title">' + this.escapeHtml(item.name) +
                (isCurrent ? ' <span class="model-badge">当前</span>' : '') +
                '    </div>' +
                '    <div class="model-item-sub">' +
                '      <code>' + this.escapeHtml(item.model) + '</code>' +
                (item.base_url ? ' · <span title="自定义 Base URL">' + this.escapeHtml(item.base_url) + '</span>' : '') +
                (item.has_api_key ? ' · <span title="使用条目自己的 API Key">🔑 自定义 Key</span>' : '') +
                '    </div>' +
                '  </div>' +
                '  <div class="model-item-actions">' +
                (isCurrent ? '' : '    <button class="btn btn-secondary btn-sm model-use-btn">设为当前</button>') +
                '    <button class="btn btn-secondary btn-sm model-edit-btn">编辑</button>' +
                '    <button class="btn btn-secondary btn-sm model-delete-btn">删除</button>' +
                '  </div>' +
                '</div>';
        }
        html += '<div class="model-effective-note">当前生效模型: <code>' +
                this.escapeHtml(effectiveModel || '(未配置)') + '</code></div>';
        listDiv.innerHTML = html;

        // 条目级按钮
        listDiv.querySelectorAll('.model-item[data-name]').forEach((row) => {
            const name = row.getAttribute('data-name');
            const useBtn = row.querySelector('.model-use-btn');
            if (useBtn) useBtn.addEventListener('click', () => this.setCurrent(name));
            row.querySelector('.model-edit-btn').addEventListener('click', () => this.openEntryForm(name));
            row.querySelector('.model-delete-btn').addEventListener('click', () => this.deleteItem(name));
        });
        listDiv.querySelector('.model-clone-btn')
            .addEventListener('click', () => this.cloneDefaultEntry());
    }

    /** 把内置默认条目复制成一条可编辑的新条目（模型名/Base URL 预填好） */
    cloneDefaultEntry() {
        const defaults = this.envDefaults[this.provider] || {};
        this.openEntryForm(null);
        const nameInput = document.getElementById('model-form-name');
        nameInput.value = '';
        nameInput.placeholder = defaults.model ? ('如 ' + defaults.model + ' / 变体A') : '显示名';
        document.getElementById('model-form-model').value = defaults.model || '';
        document.getElementById('model-form-base-url').value = defaults.base_url || '';
    }

    openEntryForm(editName) {
        this.editingName = editName;
        const form = document.getElementById('model-entry-form');
        const title = document.getElementById('model-form-title');
        const apiKeyLabel = document.getElementById('model-form-apikey-label');

        document.getElementById('model-test-result').innerHTML = '';

        if (editName) {
            const item = this.getItems().find((it) => it.name === editName);
            if (!item) return;
            title.textContent = '编辑模型: ' + editName;
            document.getElementById('model-form-name').value = item.name;
            document.getElementById('model-form-model').value = item.model;
            document.getElementById('model-form-base-url').value = item.base_url || '';
            document.getElementById('model-form-api-key').value = '';
            apiKeyLabel.textContent = 'API Key（已保存' + (item.has_api_key ? '，留空保留原值' : '') + '）';
        } else {
            title.textContent = '添加模型';
            document.getElementById('model-form-name').value = '';
            document.getElementById('model-form-model').value = '';
            document.getElementById('model-form-base-url').value = '';
            document.getElementById('model-form-api-key').value = '';
            apiKeyLabel.textContent = 'API Key（可选，覆盖默认）';
        }

        form.style.display = 'block';
        document.getElementById('model-form-name').focus();
    }

    hideEntryForm() {
        document.getElementById('model-entry-form').style.display = 'none';
        this.editingName = null;
    }

    /** 从表单收集条目；返回 {entry, apiKeyTouched}，校验失败返回 null 并提示 */
    collectEntryForm() {
        const name = document.getElementById('model-form-name').value.trim();
        const model = document.getElementById('model-form-model').value.trim();
        const baseUrl = document.getElementById('model-form-base-url').value.trim();
        const apiKey = document.getElementById('model-form-api-key').value;

        if (!name || !model) {
            this.showModelsStatus('显示名和模型名都是必填项', 'error');
            return null;
        }

        // 重名检查（编辑时允许保留自己的名字）
        const duplicate = this.getItems().some(
            (it) => it.name === name && it.name !== this.editingName);
        if (duplicate) {
            this.showModelsStatus('显示名 "' + name + '" 已存在', 'error');
            return null;
        }

        return {
            entry: { name, model, base_url: baseUrl || null, api_key: apiKey || null },
            apiKeyTouched: apiKey.length > 0,
        };
    }

    saveEntryForm() {
        const collected = this.collectEntryForm();
        if (!collected) return;
        const { entry, apiKeyTouched } = collected;
        const items = this.getItems();

        if (this.editingName) {
            const idx = items.findIndex((it) => it.name === this.editingName);
            if (idx === -1) return;
            // api_key 打码策略：留空 = 保留原值（若有）；填了 = 覆盖
            const keepKey = items[idx].has_api_key && !apiKeyTouched;
            const replacement = {
                name: entry.name, model: entry.model, base_url: entry.base_url,
                api_key: keepKey ? items[idx].api_key : entry.api_key,
                has_api_key: keepKey || apiKeyTouched,
            };
            items[idx] = replacement;
            // 编辑中的条目若正被选为 current，跟随改名
            if (this.getCurrent() === this.editingName) {
                this.workingRegistry[this.provider].current = entry.name;
            }
        } else {
            items.push({ ...entry, has_api_key: apiKeyTouched });
        }

        this.hideEntryForm();
        this.renderList();
        this.showModelsStatus('条目已暂存，记得点"保存模型配置"落盘', 'success');
    }

    deleteItem(name) {
        const entry = this.workingRegistry[this.provider];
        const items = this.getItems();
        const idx = items.findIndex((it) => it.name === name);
        if (idx === -1) return;

        items.splice(idx, 1);
        // 删除的是当前选中项 → 回退 env/默认值语义
        if (entry && entry.current === name) {
            entry.current = null;
        }
        this.renderOverview();
        this.renderList();
        this.showModelsStatus('条目已删除（未落盘），记得点"保存模型配置"', 'success');
    }

    setCurrent(name) {
        if (!this.workingRegistry[this.provider]) {
            this.workingRegistry[this.provider] = { current: null, items: [] };
        }
        this.workingRegistry[this.provider].current = name;
        this.renderOverview();
        this.renderList();
        this.showModelsStatus('当前模型已切换为 "' + name + '"（未落盘），记得点"保存模型配置"', 'success');
    }

    async saveRegistry() {
        try {
            UIComponents.showLoading('保存模型配置...');
            const items = this.getItems().map(({ name, model, base_url, api_key }) => (
                { name, model, base_url, api_key }));
            const payload = {
                provider: this.provider,
                current: this.getCurrent(),
                items,
            };
            const result = await API.config.saveModels(payload);
            // 用后端清洗后的注册表刷新本地副本（has_api_key 等以服务端为准）
            this.workingRegistry = result.registry || {};
            this.hideEntryForm();
            this.renderList();
            await this.loadRegistry();   // 再拉一次 effective，展示最新生效值
            this.showModelsStatus('✅ 模型配置已保存并生效（下一次 LLM 调用起使用）', 'success');
            Utils.notify('模型配置已保存', 'success');
        } catch (error) {
            console.error('[Models] 保存失败:', error);
            this.showModelsStatus('保存失败: ' + error.message, 'error');
        } finally {
            UIComponents.hideLoading();
        }
    }

    async testConnection() {
        const collected = this.collectEntryForm();
        if (!collected) return;
        const { entry, apiKeyTouched } = collected;
        const resultDiv = document.getElementById('model-test-result');
        resultDiv.innerHTML = '<span class="model-testing">⏳ 正在测试连接...</span>';

        // 编辑模式下留空 api_key 表示保留原值——测试也应带着原值测
        let apiKey = entry.api_key;
        if (!apiKey && this.editingName) {
            const existing = this.getItems().find((it) => it.name === this.editingName);
            if (existing && existing.has_api_key) {
                // 后端没有明文 key；这里只提示用户该条目将用已保存的 key 测试
                resultDiv.innerHTML = '<span class="model-test-fail">⚠️ 该条目已保存自定义 API Key' +
                    '（出于安全不回显）。如需测试，请在输入框重新粘贴 Key，或保存后直接对话验证。</span>';
                return;
            }
        }

        try {
            const result = await API.config.testModel({
                provider: this.provider,
                model: entry.model,
                base_url: entry.base_url,
                api_key: apiKey,
            });
            if (result.ok) {
                resultDiv.innerHTML = '<span class="model-test-ok">✅ 连接成功，模型回复: ' +
                    this.escapeHtml(result.reply || '(空)') + '</span>';
            } else {
                resultDiv.innerHTML = '<span class="model-test-fail">❌ 连接失败: ' +
                    this.escapeHtml(result.error || '未知错误') + '</span>';
            }
        } catch (error) {
            resultDiv.innerHTML = '<span class="model-test-fail">❌ 测试请求失败: ' +
                this.escapeHtml(error.message) + '</span>';
        }
    }

    showModelsStatus(message, type) {
        const statusDiv = document.getElementById('models-status');
        statusDiv.textContent = message;
        statusDiv.className = 'status-message ' + type;
        statusDiv.style.display = 'block';
        if (type === 'success') {
            setTimeout(() => { statusDiv.style.display = 'none'; }, 4000);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    escapeAttr(text) {
        return this.escapeHtml(text).replace(/"/g, '&quot;');
    }
}

// 初始化
const configManager = new ConfigManager();
const modelRegistryManager = new ModelRegistryManager(configManager);
