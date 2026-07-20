"""信托登记规则库与规则引擎后端。"""
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")
