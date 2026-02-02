/**
 * Enhanced Chat UI Utilities
 * 提供额外的UI交互增强功能
 */

class ChatUIEnhancer {
    constructor() {
        this.init();
    }

    init() {
        this.addScrollToTopButton();
        this.enhanceCodeBlocks();
        this.addMessageHoverEffects();
    }

    /**
     * 添加滚动到顶部按钮
     */
    addScrollToTopButton() {
        const messagesContainer = document.getElementById('messages');
        if (!messagesContainer) return;

        const scrollButton = document.createElement('button');
        scrollButton.className = 'scroll-to-top-btn';
        scrollButton.innerHTML = '↑';
        scrollButton.style.cssText = `
            position: fixed;
            bottom: 100px;
            right: 30px;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
            cursor: pointer;
            opacity: 0;
            transition: opacity 0.3s ease, transform 0.3s ease;
            z-index: 100;
            display: none;
            font-size: 1.5rem;
        `;

        document.body.appendChild(scrollButton);

        // 监听滚动事件
        messagesContainer.addEventListener('scroll', () => {
            if (messagesContainer.scrollTop > 300) {
                scrollButton.style.display = 'block';
                setTimeout(() => scrollButton.style.opacity = '1', 10);
            } else {
                scrollButton.style.opacity = '0';
                setTimeout(() => scrollButton.style.display = 'none', 300);
            }
        });

        // 点击滚动到顶部
        scrollButton.addEventListener('click', () => {
            messagesContainer.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        });

        scrollButton.addEventListener('mouseenter', () => {
            scrollButton.style.transform = 'translateY(-4px)';
        });

        scrollButton.addEventListener('mouseleave', () => {
            scrollButton.style.transform = 'translateY(0)';
        });
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

    /**
     * 显示自定义Toast通知
     */
    static showToast(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast-notification ${type}`;
        
        const icons = {
            success: '✓',
            error: '✗',
            info: 'ℹ',
            warning: '⚠'
        };

        toast.innerHTML = `
            <span style="font-size: 1.25rem;">${icons[type] || icons.info}</span>
            <span>${message}</span>
        `;

        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'toast-slide-in 0.3s ease-out reverse';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    /**
     * 添加打字机效果
     */
    static typeWriter(element, text, speed = 30) {
        let i = 0;
        element.textContent = '';
        
        return new Promise((resolve) => {
            const timer = setInterval(() => {
                if (i < text.length) {
                    element.textContent += text.charAt(i);
                    i++;
                } else {
                    clearInterval(timer);
                    resolve();
                }
            }, speed);
        });
    }

    /**
     * 创建加载动画点
     */
    static createLoadingDots() {
        const container = document.createElement('span');
        container.className = 'loading-dots';
        
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement('span');
            container.appendChild(dot);
        }
        
        return container;
    }

    /**
     * 添加页面引用点击高亮效果
     */
    static highlightPageReference(element) {
        element.style.transition = 'all 0.3s ease';
        element.style.transform = 'scale(1.1)';
        element.style.boxShadow = '0 0 10px rgba(102, 126, 234, 0.5)';
        
        setTimeout(() => {
            element.style.transform = 'scale(1)';
            element.style.boxShadow = 'none';
        }, 300);
    }

    /**
     * 平滑滚动到特定消息
     */
    static scrollToMessage(messageId, highlight = true) {
        const message = document.getElementById(messageId);
        if (!message) return;

        message.scrollIntoView({
            behavior: 'smooth',
            block: 'center'
        });

        if (highlight) {
            message.style.animation = 'none';
            setTimeout(() => {
                message.style.animation = 'highlight-pulse 1s ease-in-out';
            }, 10);
        }
    }
}

// 添加高亮脉冲动画CSS（避免重复添加）
if (!document.getElementById('chat-enhancer-styles')) {
    const style = document.createElement('style');
    style.id = 'chat-enhancer-styles';
    style.textContent = `
        @keyframes highlight-pulse {
            0%, 100% { 
                background: transparent; 
            }
            50% { 
                background: rgba(102, 126, 234, 0.1); 
            }
        }

        @keyframes toast-slide-in {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
    `;
    document.head.appendChild(style);
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
