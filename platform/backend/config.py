import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config:
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
    FLASK_HOST = os.getenv('FLASK_HOST', '127.0.0.1')
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000').split(',')
        if origin.strip()
    ]
    RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', 10))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv('RATE_LIMIT_WINDOW_SECONDS', 60))
    LLM_TIMEOUT_SECONDS = float(os.getenv('LLM_TIMEOUT_SECONDS', 60))
    LLM_MAX_RETRIES = int(os.getenv('LLM_MAX_RETRIES', 2))
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    GROQ_API_KEY = os.getenv('GROQ_API_KEY')
    LM_STUDIO_BASE_URL = os.getenv('LM_STUDIO_BASE_URL', 'http://localhost:1234/v1')

    # NVIDIA API keys are intentionally read only from environment variables.
    # Do not hard-code real credentials in this repository.
    NVIDIA_API_KEY_1 = os.getenv('NVIDIA_API_KEY_1')
    NVIDIA_API_KEY_2 = os.getenv('NVIDIA_API_KEY_2')
    NVIDIA_API_KEY_3 = os.getenv('NVIDIA_API_KEY_3')
    NVIDIA_API_KEY_4 = os.getenv('NVIDIA_API_KEY_4')
    NVIDIA_API_KEY_5 = os.getenv('NVIDIA_API_KEY_5')
    NVIDIA_API_KEY_6 = os.getenv('NVIDIA_API_KEY_6')

    # 動態掃描 NVIDIA_API_KEY_<N>（與 .env 註記一致），有幾把就用幾把；
    # 寫死 1~6 會漏掉後來新增的金鑰。
    NVIDIA_API_KEYS = [
        value
        for value in (
            os.getenv(f'NVIDIA_API_KEY_{index}') for index in range(1, 33)
        )
        if value
    ]
    NVIDIA_MODEL = os.getenv('NVIDIA_MODEL', 'meta/llama-3.3-70b-instruct')

    # provider options: 'openai', 'groq', 'lm_studio', 'nvidia'
    LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'openai') 
    GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama3-70b-8192')
    LM_STUDIO_MODEL = os.getenv('LM_STUDIO_MODEL', 'openai/gpt-oss-20b')
    NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')
