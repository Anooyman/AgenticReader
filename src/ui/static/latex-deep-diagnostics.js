// 🔬 LaTeX 聊天渲染深度诊断脚本
// 将此脚本粘贴到浏览器控制台运行，诊断 LaTeX 渲染问题

console.log("========================================");
console.log("🔬 LaTeX 深度诊断工具已加载");
console.log("========================================");
console.log("");

// 1. 检查 MathJax 状态
console.log("1️⃣  MathJax 加载状态:");
console.log(`   ✓ MathJax: ${typeof MathJax !== 'undefined' ? '已加载' : '❌ 未加载'}`);
if (typeof MathJax !== 'undefined') {
    console.log(`   ✓ typesetPromise: ${typeof MathJax.typesetPromise === 'function' ? '可用' : '❌ 不可用'}`);
    console.log(`   ✓ startup: ${MathJax.startup ? '存在' : '❌ 不存在'}`);
    console.log(`   ✓ startup.promise: ${MathJax.startup && MathJax.startup.promise ? '可用' : '❌ 不可用'}`);
    console.log(`   ✓ version: ${MathJax.version}`);
}
console.log("");

// 2. 检查聊天应用
console.log("2️⃣  聊天应用状态:");
const app = window.llmReaderChatApp;
console.log(`   ✓ 应用对象: ${app ? '已初始化' : '❌ 未初始化'}`);
if (app) {
    console.log(`   ✓ WebSocket: ${app.isConnected ? '已连接' : '❌ 未连接'}`);
    console.log(`   ✓ 当前文档: ${app.config.currentDocName || '❌ 无'}`);
    console.log(`   ✓ 消息数量: ${app.chatHistory.length}`);
}
console.log("");

// 3. 检查 DOM 中的消息
console.log("3️⃣  DOM 消息分析:");
const messageElements = document.querySelectorAll('.chat-message');
console.log(`   ✓ 消息元素数量: ${messageElements.length}`);

if (messageElements.length > 0) {
    console.log("   最后一条消息分析:");
    const lastMsg = messageElements[messageElements.length - 1];
    const contentDiv = lastMsg.querySelector('.tex2jax_process');
    
    console.log(`     - 元素存在: ${contentDiv ? '✓' : '❌'}`);
    if (contentDiv) {
        console.log(`     - 可见: ${contentDiv.offsetHeight > 0 ? '✓' : '❌'}`);
        console.log(`     - 宽度: ${contentDiv.offsetWidth}px`);
        console.log(`     - 高度: ${contentDiv.offsetHeight}px`);
        console.log(`     - display: ${window.getComputedStyle(contentDiv).display}`);
        console.log(`     - visibility: ${window.getComputedStyle(contentDiv).visibility}`);
        console.log(`     - opacity: ${window.getComputedStyle(contentDiv).opacity}`);
        console.log(`     - overflow: ${window.getComputedStyle(contentDiv).overflow}`);
        console.log(`     - HTML长度: ${contentDiv.innerHTML.length}`);
        console.log(`     - HTML预览: ${contentDiv.innerHTML.substring(0, 200)}`);
        
        // 检查 MathJax 容器
        const mjxContainers = contentDiv.querySelectorAll('.mjx-container');
        console.log(`     - MathJax 容器: ${mjxContainers.length}`);
        
        if (mjxContainers.length === 0) {
            console.warn("     ⚠️ 没有 MathJax 容器！检查可能的原因：");
            const hasLatex = /\$|\\\(|\\\[/.test(contentDiv.innerHTML);
            console.warn(`     - 包含 LaTeX 符号: ${hasLatex ? '✓' : '❌'}`);
            
            // 显示原始内容
            console.log(`     - 原始文本内容: ${contentDiv.textContent.substring(0, 200)}`);
        } else {
            mjxContainers.forEach((container, idx) => {
                console.log(`     - 容器 [${idx}]:`);
                console.log(`       * display: ${window.getComputedStyle(container).display}`);
                console.log(`       * visibility: ${window.getComputedStyle(container).visibility}`);
                console.log(`       * 内容: ${container.innerHTML.substring(0, 50)}`);
            });
        }
    }
}
console.log("");

// 4. 检查 CSS 规则
console.log("4️⃣  CSS 样式规则检查:");
const testEl = document.querySelector('.tex2jax_process');
if (testEl) {
    const styles = window.getComputedStyle(testEl);
    const problematicProps = [
        'display',
        'visibility',
        'opacity',
        'height',
        'width',
        'overflow',
        'clip',
        'clip-path'
    ];
    
    problematicProps.forEach(prop => {
        const value = styles[prop];
        const potential = 
            (prop === 'display' && value === 'none') ||
            (prop === 'visibility' && value === 'hidden') ||
            (prop === 'opacity' && parseFloat(value) === 0) ||
            (prop === 'height' && value === '0px') ||
            (prop === 'width' && value === '0px');
        
        console.log(`   ${potential ? '⚠️' : '✓'} ${prop}: ${value}`);
    });
}
console.log("");

// 5. 强制渲染诊断函数
console.log("5️⃣  强制渲染测试:");
console.log("   运行命令: window.forceRenderDiagnostics()");
console.log("");

window.forceRenderDiagnostics = function() {
    console.log("🚀 开始强制渲染诊断...");
    
    const contentDivs = document.querySelectorAll('.tex2jax_process');
    console.log(`📋 发现 ${contentDivs.length} 个内容容器`);
    
    contentDivs.forEach((div, idx) => {
        console.log(`\n📝 容器 [${idx}]:`);
        
        // 显示内容
        const hasLatex = /\$|\\\(|\\\[/.test(div.innerHTML);
        console.log(`   - 包含 LaTeX: ${hasLatex ? '✓' : '❌'}`);
        console.log(`   - 长度: ${div.innerHTML.length}`);
        
        // 强制显示
        div.style.display = 'block !important';
        div.style.visibility = 'visible !important';
        div.style.opacity = '1 !important';
        console.log(`   ✓ 已强制显示样式`);
        
        // 查找隐藏的子元素
        const hidden = div.querySelectorAll('[style*="display: none"], [style*="visibility: hidden"], [style*="opacity: 0"]');
        if (hidden.length > 0) {
            console.warn(`   ⚠️ 发现 ${hidden.length} 个隐藏的子元素`);
            hidden.forEach(el => {
                el.style.display = '';
                el.style.visibility = '';
                el.style.opacity = '';
            });
        }
    });
    
    // 触发全局 MathJax 渲染
    if (MathJax && MathJax.typesetPromise) {
        console.log("\n🎯 调用全局 MathJax 渲染...");
        MathJax.typesetPromise()
            .then(() => console.log("✅ 全局渲染成功"))
            .catch(err => console.error("❌ 全局渲染失败:", err));
    }
};

// 6. 快速修复函数
console.log("6️⃣  快速修复工具:");
console.log("   运行命令: window.quickFixLatex()");
console.log("");

window.quickFixLatex = function() {
    console.log("🔧 应用快速修复...");
    
    // 修复所有 MathJax 容器
    const mjxContainers = document.querySelectorAll('.mjx-container');
    console.log(`📋 找到 ${mjxContainers.length} 个 MathJax 容器`);
    
    mjxContainers.forEach((container, idx) => {
        container.style.display = 'inline-block !important';
        container.style.visibility = 'visible !important';
        container.style.opacity = '1 !important';
        container.style.transform = 'none';
        container.style.clip = 'auto';
    });
    
    // 修复消息容器
    const messageContents = document.querySelectorAll('.message-content');
    console.log(`📋 修复 ${messageContents.length} 个消息容器`);
    
    messageContents.forEach(content => {
        content.style.overflow = 'visible';
        content.style.maxHeight = 'none';
    });
    
    // 强制重排
    document.body.offsetHeight; // 触发重排
    
    console.log("✅ 快速修复完成！检查是否显示");
};

// 7. 导出诊断报告
console.log("7️⃣  导出诊断报告:");
console.log("   运行命令: window.exportDiagnosticsReport()");
console.log("");

window.exportDiagnosticsReport = function() {
    const report = {
        timestamp: new Date().toISOString(),
        mathJax: {
            loaded: typeof MathJax !== 'undefined',
            version: typeof MathJax !== 'undefined' ? MathJax.version : null,
            hasTypesetPromise: typeof MathJax !== 'undefined' && typeof MathJax.typesetPromise === 'function',
            hasStartupPromise: typeof MathJax !== 'undefined' && MathJax.startup && MathJax.startup.promise
        },
        app: {
            initialized: typeof window.llmReaderChatApp !== 'undefined',
            messageCount: window.llmReaderChatApp ? window.llmReaderChatApp.chatHistory.length : 0,
            domMessageCount: document.querySelectorAll('.chat-message').length
        },
        dom: {
            texContainers: document.querySelectorAll('.tex2jax_process').length,
            mjxContainers: document.querySelectorAll('.mjx-container').length
        },
        userAgent: navigator.userAgent,
        viewport: {
            width: window.innerWidth,
            height: window.innerHeight
        }
    };
    
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `latex-diagnostics-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    
    console.log("✅ 诊断报告已导出");
};

// 8. 实时监控
console.log("8️⃣  实时监控工具:");
console.log("   运行命令: window.monitorLatexRendering()");
console.log("");

window.monitorLatexRendering = function(interval = 2000) {
    console.log(`📊 启动实时监控 (每 ${interval}ms 检查一次)`);
    
    const monitor = setInterval(() => {
        const mjxContainers = document.querySelectorAll('.mjx-container');
        const visible = Array.from(mjxContainers).filter(el => 
            window.getComputedStyle(el).display !== 'none' &&
            el.offsetHeight > 0
        ).length;
        
        console.log(`[${new Date().toLocaleTimeString()}] MathJax: ${mjxContainers.length} 容器, ${visible} 可见`);
    }, interval);
    
    console.log("✓ 监控已启动。运行 window.stopMonitoring() 停止");
    window.stopMonitoring = () => {
        clearInterval(monitor);
        console.log("✓ 监控已停止");
    };
};

console.log("========================================");
console.log("🎯 诊断工具已就绪！");
console.log("========================================");
console.log("");
console.log("推荐步骤：");
console.log("1. 运行 forceRenderDiagnostics() 强制诊断");
console.log("2. 运行 quickFixLatex() 快速修复");
console.log("3. 如果有帮助，运行 exportDiagnosticsReport() 导出报告");
console.log("4. 运行 monitorLatexRendering() 实时监控");
console.log("");
