"""
providers.py - LLM provider abstraction layer

This module provides a unified interface for different LLM providers:
- Azure OpenAI
- OpenAI
- Ollama (local models)
- Gemini (Google Generative AI)

Classes:
    LLMProviderBase: Abstract base class defining the provider interface
    AzureLLMProvider: Azure OpenAI implementation
    OpenAILLMProvider: OpenAI implementation
    OllamaLLMProvider: Ollama local model implementation
    GeminiLLMProvider: Gemini (Google Generative AI) implementation
"""
from abc import ABC, abstractmethod
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings, ChatOpenAI, OpenAIEmbeddings
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from google.api_core.client_options import ClientOptions

from src.config.settings import LLM_CONFIG, LLM_EMBEDDING_CONFIG


class LLMProviderBase(ABC):
    """
    LLM Provider 抽象基类，定义统一接口。
    """
    @abstractmethod
    def get_chat_model(self, **kwargs):
        """获取聊天模型实例"""
        pass

    @abstractmethod
    def get_embedding_model(self, **kwargs):
        """获取嵌入模型实例"""
        pass


class AzureLLMProvider(LLMProviderBase):
    """Azure OpenAI Provider 实现"""

    def get_chat_model(self, **kwargs):
        """
        获取 Azure OpenAI 聊天模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            AzureChatOpenAI: Azure OpenAI 聊天模型实例
        """
        return AzureChatOpenAI(
            openai_api_key=kwargs.get("openai_api_key", LLM_CONFIG.get("api_key")),
            openai_api_version=kwargs.get("openai_api_version", LLM_CONFIG.get("api_version")),
            azure_endpoint=kwargs.get("azure_endpoint", LLM_CONFIG.get("azure_endpoint")),
            deployment_name=kwargs.get("deployment_name", LLM_CONFIG.get("deployment_name")),
            model_name=kwargs.get("model_name", LLM_CONFIG.get("model_name")),
            temperature=kwargs.get("temperature", 0.7),
            max_retries=kwargs.get("max_retries", 5)
        )

    def get_embedding_model(self, **kwargs):
        """
        获取 Azure OpenAI 嵌入模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            AzureOpenAIEmbeddings: Azure OpenAI 嵌入模型实例
        """
        return AzureOpenAIEmbeddings(
            openai_api_key=kwargs.get("openai_api_key", LLM_EMBEDDING_CONFIG.get("api_key")),
            openai_api_version=kwargs.get("openai_api_version", LLM_EMBEDDING_CONFIG.get("api_version")),
            azure_endpoint=kwargs.get("azure_endpoint", LLM_EMBEDDING_CONFIG.get("azure_endpoint")),
            deployment=kwargs.get("deployment", LLM_EMBEDDING_CONFIG.get("deployment")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("model")),
            max_retries=kwargs.get("max_retries", 5)
        )


class OpenAILLMProvider(LLMProviderBase):
    """OpenAI Provider 实现"""

    def get_chat_model(self, **kwargs):
        """
        获取 OpenAI 聊天模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            ChatOpenAI: OpenAI 聊天模型实例
        """
        return ChatOpenAI(
            model=kwargs.get("model_name", LLM_CONFIG.get("openai_model_name")),
            openai_api_key=kwargs.get("openai_api_key", LLM_CONFIG.get("openai_api_key")),
            base_url=kwargs.get("openai_base_url", LLM_CONFIG.get("openai_base_url")),
            temperature=kwargs.get("temperature", 0.7),
            max_retries=kwargs.get("max_retries", 5)
        )

    def get_embedding_model(self, **kwargs):
        """
        获取 OpenAI 嵌入模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            OpenAIEmbeddings: OpenAI 嵌入模型实例
        """
        return OpenAIEmbeddings(
            openai_api_key=kwargs.get("openai_api_key", LLM_EMBEDDING_CONFIG.get("openai_api_key")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("openai_model", "text-embedding-ada-002")),
            max_retries=kwargs.get("max_retries", 5)
        )


class OllamaLLMProvider(LLMProviderBase):
    """Ollama (本地模型) Provider 实现"""

    def get_chat_model(self, **kwargs):
        """
        获取 Ollama 聊天模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            ChatOllama: Ollama 聊天模型实例
        """
        return ChatOllama(
            base_url=kwargs.get("base_url", LLM_CONFIG.get("ollama_base_url", "http://localhost:11434")),
            model=kwargs.get("model", LLM_CONFIG.get("ollama_model_name", "llama3")),
            temperature=kwargs.get("temperature", 0.7)
        )

    def get_embedding_model(self, **kwargs):
        """
        获取 Ollama 嵌入模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            OllamaEmbeddings: Ollama 嵌入模型实例
        """
        return OllamaEmbeddings(
            base_url=kwargs.get("base_url", LLM_EMBEDDING_CONFIG.get("ollama_base_url", "http://localhost:11434")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("ollama_model", "llama3")),
        )


class GeminiLLMProvider(LLMProviderBase):
    """Gemini (Google Generative AI) Provider 实现"""

    def get_chat_model(self, **kwargs):
        """
        获取 Gemini 聊天模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            ChatGoogleGenerativeAI: Gemini 聊天模型实例
        """
        base_url = kwargs.get("base_url", LLM_CONFIG.get("gemini_base_url"))
        
        config = {
            "google_api_key": kwargs.get("google_api_key", LLM_CONFIG.get("gemini_api_key")),
            "model": kwargs.get("model_name", LLM_CONFIG.get("gemini_model_name", "gemini-1.5-pro")),
            "temperature": kwargs.get("temperature", 0.7),
            "max_retries": kwargs.get("max_retries", 5)
        }
        
        if base_url:
            config["client_options"] = ClientOptions(api_endpoint=base_url)
        
        return ChatGoogleGenerativeAI(**config)

    def get_embedding_model(self, **kwargs):
        """
        获取 Gemini 嵌入模型

        Args:
            **kwargs: 模型配置参数，可覆盖默认配置

        Returns:
            GoogleGenerativeAIEmbeddings: Gemini 嵌入模型实例
        """
        base_url = kwargs.get("base_url", LLM_EMBEDDING_CONFIG.get("gemini_base_url"))
        
        config = {
            "google_api_key": kwargs.get("google_api_key", LLM_EMBEDDING_CONFIG.get("gemini_api_key")),
            "model": kwargs.get("model", LLM_EMBEDDING_CONFIG.get("gemini_embedding_model", "text-embedding-004"))
        }
        
        if base_url:
            config["client_options"] = ClientOptions(api_endpoint=base_url)
        
        return GoogleGenerativeAIEmbeddings(**config)
