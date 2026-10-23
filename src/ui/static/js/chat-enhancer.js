/**
 * Enhanced Chat UI Utilities
 * 提供额外的UI交互增强功能
 */

class ChatUIEnhancer {
    constructor() {
        this.init();
    }

    init() {
        this.enhanceCodeBlocks();
        this.addMessageHoverEffects();
    }

    /**
     * 增强代码块功能
     */
    enhanceCodeBlocks() {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) { // Element node
                        const codeBlocks = node.querySelectorAll ? 
                            node.querySelectorAll('pre code') : [];
                        
                        codeBlocks.forEach((codeBlock) => {
                            this.addCopyButton(codeBlock.parentElement);
                        });
                    }
                });
            });
        });

        const messagesContainer = document.getElementById('messages');
        if (messagesContainer) {
            observer.observe(messagesContainer, {
                childList: true,
                subtree: true
            });
        }
    }

    /**
     * 为代码块添加复制按钮
     */
    addCopyButton(preElement) {
        if (preElement.querySelector('.code-copy-btn')) return;

        const copyButton = document.createElement('button');
        copyButton.className = 'code-copy-btn';
        copyButton.innerHTML = '📋 复制';
        copyButton.style.cssText = `
            position: absolute;
            top: 0.5rem;
            right: 0.5rem;
            padding: 0.25rem 0.75rem;
            background: rgba(102, 126, 234, 0.8);
            color: white;
            border: none;
            border-radius: 0.375rem;
            cursor: pointer;
            font-size: 0.75rem;
            opacity: 0;
            transition: all 0.2s ease;
            z-index: 10;
        `;

        preElement.style.position = 'relative';
        preElement.appendChild(copyButton);

        preElement.addEventListener('mouseenter', () => {
            copyButton.style.opacity = '1';
        });

        preElement.addEventListener('mouseleave', () => {
            copyButton.style.opacity = '0';
        });

        copyButton.addEventListener('click', async (e) => {
            e.stopPropagation();
            const code = preElement.querySelector('code').textContent;
            
            try {
                await navigator.clipboard.writeText(code);
                copyButton.innerHTML = '✓ 已复制';
                copyButton.style.background = 'rgba(16, 185, 129, 0.8)';
                
                setTimeout(() => {
                    copyButton.innerHTML = '📋 复制';
                    copyButton.style.background = 'rgba(102, 126, 234, 0.8)';
                }, 2000);
            } catch (err) {
                console.error('Failed to copy:', err);
                copyButton.innerHTML = '✗ 失败';
                setTimeout(() => {
                    copyButton.innerHTML = '📋 复制';
                }, 2000);
            }
        });
    }

    /**
     * 添加消息悬停效果
     */
    addMessageHoverEffects() {
        const messagesContainer = document.getElementById('messages');
        if (!messagesContainer) return;

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.classList && node.classList.contains('message')) {
                        this.enhanceMessage(node);
                    }
                });
            });
        });

        observer.observe(messagesContainer, {
            childList: true
        });

        // 增强现有消息
        messagesContainer.querySelectorAll('.message').forEach((msg) => {
            this.enhanceMessage(msg);
        });
    }

    /**
     * 增强单个消息
     */
    enhanceMessage(messageElement) {
        const bubble = messageElement.querySelector('.bubble');
        if (!bubble) return;

        // 添加平滑显示动画
        messageElement.style.opacity = '0';
        messageElement.style.transform = 'translateY(20px)';
        
        setTimeout(() => {
            messageElement.style.transition = 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)';
            messageElement.style.opacity = '1';
            messageElement.style.transform = 'translateY(0)';
        }, 10);
    }
}

// 初始化增强功能
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        new ChatUIEnhancer();
    });
} else {
    new ChatUIEnhancer();
}

// 导出工具类供其他脚本使用
if (typeof window !== 'undefined') {
    window.ChatUIEnhancer = ChatUIEnhancer;
}
