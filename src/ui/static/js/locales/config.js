/**
 * /config page locale strings (English).
 *
 * Sources covered:
 *   - src/ui/templates/config.html  (section headers, form labels, options, buttons)
 *   - src/ui/static/js/config.js    (provider notes, PDF preset details, model
 *     registry list/overview, test-connection results, toast/status messages)
 *   - error text coming from src/ui/static/js/api.js (errorText) and
 *     src/ui/backend/api/v1/config.py (HTTPException detail) for this page.
 *
 * Discipline: model names, provider ids and environment-variable names are
 * never translated — patterns only rewrite the surrounding label text.
 * Note: strings rendered inside <code> (e.g. the model name in the overview
 * list) are skipped by i18n.js by design, so they stay as-is.
 */
(function () {
    I18N.register({
        lang: 'en',
        exact: {
            /* ---------- Page chrome / section headers ---------- */
            '⚙️ 配置管理': '⚙️ Configuration',
            '管理 LLM 提供商、PDF 处理参数和系统配置': 'Manage LLM providers, PDF processing parameters, and system settings',
            '🤖 LLM 提供商配置': '🤖 LLM Provider Configuration',
            '🧩 模型管理': '🧩 Model Management',
            '📄 PDF 处理配置': '📄 PDF Processing',
            '🔧 系统配置': '🔧 System Configuration',

            /* ---------- Provider selection ---------- */
            '选择 LLM 提供商:': 'Select LLM provider:',
            '⚠️ 请确保在 .env 文件或环境变量中配置相应的 API 密钥与模型信息':
                '⚠️ Make sure the matching API keys and model information are configured in the .env file or environment variables',
            '当前提供商说明:': 'Current provider:',
            'OpenAI - 使用 OpenAI 官方 API': 'OpenAI - Uses the official OpenAI API',

            /* ---------- Model registry ---------- */
            '添加模型': 'Add model',
            '＋ 添加模型': '＋ Add model',
            '保存模型配置': 'Save model configuration',
            '显示名 *': 'Display name *',
            '模型名 *': 'Model name *',
            'Base URL（可选，覆盖默认）': 'Base URL (optional, overrides the default)',
            'API Key（可选，覆盖默认）': 'API Key (optional, overrides the default)',
            'API Key（已保存）': 'API Key (saved)',
            'API Key（已保存，留空保留原值）': 'API Key (saved — leave blank to keep the stored value)',
            '测试连接': 'Test connection',
            '保存条目': 'Save entry',
            '显示名': 'Display name',
            '留空沿用环境变量': 'Leave blank to inherit the environment variable',
            '如 GPT-6 via Trend': 'e.g. GPT-6 via Trend',
            '如 gpt-6-luna': 'e.g. gpt-6-luna',
            '当前': 'Current',
            '设为当前': 'Set as current',
            '复制为条目': 'Copy as entry',
            '把这条默认配置登记为可编辑条目': 'Register this default configuration as an editable entry',
            '自定义 Base URL': 'Custom Base URL',
            '使用条目自己的 API Key': 'Uses this entry\'s own API Key',
            '🔑 自定义 Key': '🔑 Custom key',
            '（注册表选定后未选中条目时的兜底）': '(fallback used when the registry has a current model and this entry is not selected)',
            '该 Provider 还没有登记新模型——上面这条就是它现在实际生效的配置，可直接"添加模型"在它基础上继续补充。':
                'This Provider has no registered models yet — the entry above is what is actually in effect right now. Use "Add model" to extend it from there.',
            '来自 .env / 默认值': 'From .env / defaults',
            '未配置': 'Not configured',
            '(未配置)': '(not configured)',
            '条目已暂存，记得点"保存模型配置"落盘':
                'Entry staged locally — remember to click "Save model configuration" to persist it',
            '条目已删除（未落盘），记得点"保存模型配置"':
                'Entry deleted (not persisted yet) — remember to click "Save model configuration"',
            '显示名和模型名都是必填项': 'Both display name and model name are required',
            '✅ 模型配置已保存并生效（下一次 LLM 调用起使用）':
                '✅ Model configuration saved and applied (used from the next LLM call onward)',
            '模型配置已保存': 'Model configuration saved',
            '⏳ 正在测试连接...': '⏳ Testing connection...',
            '⚠️ 该条目已保存自定义 API Key（出于安全不回显）。如需测试，请在输入框重新粘贴 Key，或保存后直接对话验证。':
                '⚠️ This entry already stores a custom API Key (not shown again for security). To test it, paste the Key into the field again, or save and verify it directly in a chat.',
            '(空)': '(empty)',
            '未知错误': 'Unknown error',

            /* ---------- PDF preset ---------- */
            'PDF转图片质量预设:': 'PDF-to-image quality preset:',
            '🚀 快速 (150 DPI + 低质量)': '🚀 Fast (150 DPI + low quality)',
            '⚖️ 平衡 (200 DPI + 中质量)': '⚖️ Balanced (200 DPI + medium quality)',
            '🎯 高质量 (300 DPI + 高质量)': '🎯 High quality (300 DPI + high quality)',
            '💎 超高质量 (600 DPI + 极致)': '💎 Ultra (600 DPI + maximum)',
            '当前设置详情:': 'Current settings:',
            '快速处理，适合预览和测试': 'Fast processing, ideal for previews and testing',
            '平衡速度和质量，适合一般文档': 'Balances speed and quality, good for everyday documents',
            '高质量OCR效果，推荐用于重要文档': 'High-quality OCR results, recommended for important documents',
            '超高质量，适合扫描件或图片质量较差的文档': 'Very high quality, suited to scans or documents with poor image quality',

            /* ---------- System configuration ---------- */
            '启用后，系统会自动将生成的摘要保存到 data/output 目录':
                'When enabled, the system automatically saves generated summaries to the data/output directory',
            '文档处理完成后显示桌面通知': 'Show a desktop notification once document processing finishes',
            '日志级别:': 'Log level:',
            'INFO - 一般信息': 'INFO - General information',
            'DEBUG - 详细调试': 'DEBUG - Detailed debug',
            'WARNING - 警告信息': 'WARNING - Warning messages',
            'ERROR - 错误信息': 'ERROR - Error messages',
            '调试模式会输出更详细的处理信息': 'Debug mode outputs more detailed processing information',

            /* ---------- Action buttons ---------- */
            '💾 保存配置': '💾 Save configuration',
            '🔄 重置为默认': '🔄 Reset to defaults',
            '← 返回主页': '← Back to home',

            /* ---------- Loading / success / reset feedback ---------- */
            '加载配置...': 'Loading configuration...',
            '保存配置...': 'Saving configuration...',
            '重置配置...': 'Resetting configuration...',
            '保存模型配置...': 'Saving model configuration...',
            '✅ 配置保存成功': '✅ Configuration saved successfully',
            '配置保存成功': 'Configuration saved successfully',
            '✅ 配置已重置为默认值': '✅ Configuration reset to defaults',
            '配置已重置为默认值': 'Configuration reset to defaults',
            '确定要重置所有配置为默认值吗？': 'Reset all settings to their default values?',
            '确认重置': 'Confirm reset',
            '确认': 'Confirm',

            /* ---------- Error text from api.js (config endpoints) ---------- */
            '加载模型列表失败': 'Failed to load the model list',
            '保存提供商配置失败': 'Failed to save provider configuration',
            '保存系统配置失败': 'Failed to save system configuration',
            '重置配置失败': 'Failed to reset configuration',
            '保存模型列表失败': 'Failed to save the model list',
            '模型测试请求失败': 'Model test request failed',

            /* ---------- Error / status text from the config API ---------- */
            '配置已更新': 'Configuration updated',
            '系统配置已更新': 'System configuration updated',
            '模型注册表已更新': 'Model registry updated',
            '同一 provider 下的模型显示名不能重复': 'Model display names must be unique within the same provider',
            '缺少模型名': 'Model name is missing',
        },
        patterns: [
            /* Multi-line / indented DOM text in config.html */
            { re: /^\s*按 Provider 登记多个模型[\s\S]*$/, repl:
                'Register multiple models per Provider (display name + model name, with optional Base URL / API Key overrides); pick one "current model" per Provider. When nothing is configured, the environment-variable defaults are used.' },
            { re: /^\s*自动保存输出文件 \(摘要 MD\/PDF 文件\)\s*$/, repl:
                'Auto-save output files (summary MD / PDF files)' },
            { re: /^\s*启用处理完成通知\s*$/, repl:
                'Enable processing-complete notifications' },

            /* Provider descriptions: "- 使用 …" and the "需要配置: ENV…" line */
            { re: /^(\s*)- 使用 Microsoft Azure 托管的 OpenAI 服务$/, repl: '$1- Uses the OpenAI service hosted on Microsoft Azure' },
            { re: /^(\s*)- 使用 OpenAI 官方 API$/, repl: '$1- Uses the official OpenAI API' },
            { re: /^(\s*)- 使用本地运行的 Ollama 模型$/, repl: '$1- Uses Ollama models running locally' },
            { re: /^(\s*)- 使用 Google Generative AI 服务$/, repl: '$1- Uses the Google Generative AI service' },
            { re: /^\s*需要配置: (.*)$/, repl: 'Needs configuration: $1' },
            { re: /\(默认: /g, repl: '(default: ' },
            { re: /\(可选\)/g, repl: '(optional)' },

            /* PDF preset detail block (built as separate lines with <br>) */
            { re: /^\s*🎨 质量:\s*/, repl: '🎨 Quality: ' },
            { re: /^\s*📝 说明:\s*/, repl: '📝 Notes: ' },
            { re: /快速处理，适合预览和测试/g, repl: 'Fast processing, ideal for previews and testing' },
            { re: /平衡速度和质量，适合一般文档/g, repl: 'Balances speed and quality, good for everyday documents' },
            { re: /高质量OCR效果，推荐用于重要文档/g, repl: 'High-quality OCR results, recommended for important documents' },
            { re: /超高质量，适合扫描件或图片质量较差的文档/g, repl: 'Very high quality, suited to scans or documents with poor image quality' },

            /* Model registry: overview row, default row, effective-model note */
            { re: /⚙️ \.env \/ 默认值/, repl: '⚙️ .env / Defaults' },
            { re: /^来自注册表: /, repl: 'From registry: ' },
            { re: /^当前生效模型: /, repl: 'Effective model: ' },

            /* Model registry: entry form titles and placeholders */
            { re: /^编辑模型: /, repl: 'Edit model: ' },
            { re: /^如 /, repl: 'e.g. ' },
            { re: / \/ 变体A$/, repl: ' / Variant A' },

            /* Model registry: status lines that interpolate a model name */
            { re: /^显示名 "(.*)" 已存在$/, repl: 'Display name "$1" already exists' },
            { re: /^当前模型已切换为 "(.*)"（未落盘），记得点"保存模型配置"$/, repl:
                'Current model switched to "$1" (not persisted yet) — remember to click "Save model configuration"' },

            /* Test-connection results */
            { re: /✅ 连接成功，模型回复: /, repl: '✅ Connection succeeded. Model reply: ' },
            { re: /❌ 连接失败: /, repl: '❌ Connection failed: ' },
            { re: /❌ 测试请求失败: /, repl: '❌ Test request failed: ' },
            { re: /未知错误/g, repl: 'Unknown error' },

            /* Save / load / reset failures, incl. nested "outer: inner" text */
            { re: /加载配置失败: /, repl: 'Failed to load configuration: ' },
            { re: /加载模型列表失败: /, repl: 'Failed to load the model list: ' },
            { re: /^保存配置失败: /, repl: 'Failed to save configuration: ' },
            { re: /^重置配置失败: /, repl: 'Failed to reset configuration: ' },
            { re: /^❌ 保存失败: /, repl: '❌ Save failed: ' },
            { re: /^❌ 重置失败: /, repl: '❌ Reset failed: ' },
            { re: /^保存失败: /, repl: 'Save failed: ' },
            { re: /保存提供商配置失败/g, repl: 'Failed to save provider configuration' },
            { re: /保存系统配置失败/g, repl: 'Failed to save system configuration' },
            { re: /重置配置失败/g, repl: 'Failed to reset configuration' },
            { re: /加载模型列表失败/g, repl: 'Failed to load the model list' },
            { re: /保存模型列表失败/g, repl: 'Failed to save the model list' },
            { re: /模型测试请求失败/g, repl: 'Model test request failed' },

            /* Backend validation errors for the model registry */
            { re: /^不支持的 provider: (.*)（可选: (.*)）$/, repl: 'Unsupported provider: $1 (available: $2)' },
            { re: /^不支持的 provider: /, repl: 'Unsupported provider: ' },
            { re: /^current 指向的 (.*?) 不在 items 里$/, repl: '"current" points to $1, which is not among the entries' },
            { re: / 缺少模型名$/, repl: ' is missing a model name' },
            { re: /^app_config\.json 当前不可读(.*)，为避免抹掉其余配置键已拒绝本次写入$/, repl:
                'app_config.json is currently unreadable$1; this write was rejected to avoid wiping other configuration keys' },

            /* Success messages as they may arrive nested inside an error line */
            { re: /系统配置已更新/g, repl: 'System configuration updated' },
            { re: /模型注册表已更新/g, repl: 'Model registry updated' },
            { re: /配置已更新/g, repl: 'Configuration updated' },
        ],
    });
})();
