# -*- coding: utf-8 -*-
"""
统一提示词加载器
从 prompts/ 目录加载提示词模板文件
"""

import os
from typing import Optional

# 获取 prompts 目录的绝对路径 (loader.py is in backend/prompts/, prompts are in backend/prompts/)
PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_prompt(category: str, name: str, lang: str = 'en') -> str:
    """Load an explicit instruction language. Missing variants fail visibly."""
    file_path = os.path.join(PROMPTS_DIR, category, f"{name}_{lang}.txt")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Missing explicit prompt template: {category}/{name}_{lang}.txt")
    with open(file_path, 'r', encoding='utf-8') as f:
        return f"[Template: {category}.{name}@{lang}-v2]\n" + f.read().strip()


def load_prompt_with_fallback(category: str, name: str, lang: str = 'en', fallback_lang: str = 'en') -> str:
    """Compatibility signature; never silently change instruction language."""
    return load_prompt(category, name, lang)


def format_prompt(template: str, **kwargs) -> str:
    """
    格式化提示词模板

    Args:
        template: 提示词模板字符串
        **kwargs: 格式化参数

    Returns:
        格式化后的提示词

    Example:
        prompt = format_prompt("Hello {name}, you are {age} years old", name="John", age=30)
    """
    return template.format(**kwargs)
