import os
from dotenv import load_dotenv

load_dotenv()

class Config:

    PROJECT_NAME = 'StyleScope AI product search'
    DATA_DIR = 'data/styles.csv'
    IMAGE_DIR='data/images/'
    EMBEDDING_DIR='embeddings/'
    INDEX_DIR = 'indexes/'
    
    GENAI_API_KEY= os.getenv('GEMINI_API_KEY')
    GENAI_API_KEY_1=os.getenv('GEMINI_API_KEY_1')
    SMTP_HOST=os.getenv('SMTP_HOST')
    SMTP_PORT= os.getenv('SMTP_PORT')
    SMTP_USER=os.getenv('SMTP_USER')
    SMTP_PASS=os.getenv('SMTP_PASS')
    SMTP_FROM=os.getenv('SMTP_FROM')


settings = Config()
