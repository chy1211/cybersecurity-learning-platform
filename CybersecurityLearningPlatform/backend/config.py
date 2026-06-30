import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config:
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
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
    NVIDIA_MODEL = os.getenv('NVIDIA_MODEL', 'meta/llama-3.3-70b-instruct')

    # provider options: 'openai', 'groq', 'lm_studio', 'nvidia'
    LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'openai') 
    GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama3-70b-8192')
    LM_STUDIO_MODEL = os.getenv('LM_STUDIO_MODEL', 'openai/gpt-oss-20b')
    NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')
