import os
from typing import Optional, List, Dict, Any
from llama_cpp import Llama
from src.logger import log
from src.providers.llm.base import BaseLlmProvider

class LlamaCppProvider(BaseLlmProvider):
    """基于 llama.cpp 的本地 LLM Provider"""
    
    def __init__(self, config: dict):
        super().__init__(name="llama_cpp", config=config)
        llm_config = config.get('llm', {})
        llama_config = llm_config.get('llama_cpp', {})
        
        # 添加调试日志
        log.debug("初始化 LlamaCppProvider:")
        log.debug(f"配置信息: {llama_config}")
        
        self.model_dir = os.path.abspath(llama_config.get('model_dir', 'models/gguf'))
        self.models_config = llama_config.get('models', [])
        self.default_model = llama_config.get('default_model')
        
        # 验证配置
        if not self.models_config:
            log.error("未找到模型配置")
        else:
            log.debug(f"找到 {len(self.models_config)} 个模型配置")
            for model in self.models_config:
                log.debug(f"模型: {model.get('name')} -> {model.get('path')}")

    def initialize(self) -> bool:
        """初始化默认模型"""
        try:
            # 添加详细的调试日志
            log.debug("开始初始化模型:")
            log.debug(f"模型目录: {self.model_dir}")
            log.debug(f"默认模型: {self.default_model}")
            
            # 检查模型目录是否存在
            if not os.path.exists(self.model_dir):
                log.error(f"模型目录不存在: {self.model_dir}")
                return False
                
            model_config = next(
                (m for m in self.models_config if m['name'] == self.default_model),
                self.models_config[0] if self.models_config else None
            )
            
            if not model_config:
                log.error("未找到可用的模型配置")
                return False

            self.current_model_config = model_config
            model_path = os.path.join(self.model_dir, model_config['path'])
            
            # 检查模型文件
            if not os.path.exists(model_path):
                log.error(f"模型文件不存在: {model_path}")
                log.error(f"当前目录文件列表:")
                if os.path.exists(self.model_dir):
                    files = os.listdir(self.model_dir)
                    for file in files:
                        log.error(f"- {file}")
                return False

            log.info(f"加载模型: {model_path}")
            self.model = Llama(
                model_path=model_path,
                n_ctx=model_config.get('n_ctx', 2048),
                n_gpu_layers=model_config.get('n_gpu_layers', -1),
                n_threads=model_config.get('n_threads', 8),
                n_batch=model_config.get('n_batch', 512)
            )
            log.info("模型加载成功")
            return True
            
        except Exception as e:
            log.error(f"初始化模型失败: {e}")
            return False

    def generate(self, prompt: str, **kwargs) -> Optional[str]:
        """使用指定模型生成文本"""
        if not self.model:
            log.error("模型未初始化")
            return None

        try:
            response = self.model(
                prompt,
                max_tokens=kwargs.get('max_tokens', 512),
                temperature=kwargs.get('temperature', 
                                    self.current_model_config.get('temperature', 0.7)),
                top_p=kwargs.get('top_p', 
                               self.current_model_config.get('top_p', 0.95)),
                repeat_penalty=kwargs.get('repeat_penalty',
                                       self.current_model_config.get('repeat_penalty', 1.1)),
                top_k=kwargs.get('top_k',
                               self.current_model_config.get('top_k', 40))
            )
            
            if response and "choices" in response:
                return response["choices"][0]["text"].strip()
            return None
            
        except Exception as e:
            log.error(f"生成文本时出错: {e}")
            return None

    def chat(self, messages: List[Dict[str, Any]], **kwargs) -> Optional[str]:
        """实现聊天方法"""
        if not messages:
            return None
            
        # 将消息列表转换为单个提示文本
        prompt = "\n".join([
            f"{msg.get('role', 'user')}: {msg.get('content', '')}"
            for msg in messages
        ])
        
        return self.generate(prompt, **kwargs)

    def get_name(self) -> str:
        return "llama_cpp"