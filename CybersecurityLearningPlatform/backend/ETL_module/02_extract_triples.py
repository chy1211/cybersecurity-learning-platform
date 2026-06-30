import json
import os
import sys
# Load backend .env when this script is executed directly.
try:
    from pathlib import Path as _EnvPath
    from dotenv import load_dotenv as _load_dotenv
    for _env_parent in _EnvPath(__file__).resolve().parents:
        _env_file = _env_parent / ".env"
        if _env_file.exists():
            _load_dotenv(_env_file)
            break
except Exception:
    pass
import re
import time
from google import genai
from google.genai import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from prompts import load_prompt

# --- Gemma API 設定 ---
try:
    gemma_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
except Exception as e:
    print(f"初始化 API Client 失敗。錯誤：{e}")
    exit(1)
GEMMA_MODEL_NAME = "gemma-4-31b-it"

CHUNKS_DIR = "Chunks"
RAW_TRIPLES_DIR = "RawTriples"

SYSTEM_PROMPT = load_prompt("etl/extract_triples_system.md")
USER_PROMPT_TEMPLATE = load_prompt("etl/extract_triples_user.md")

def extract_json(text):
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        match_obj = re.search(r'\{.*\}', text, re.DOTALL)
        if match_obj:
            return json.loads(match_obj.group(0))
        return json.loads(text)
    except Exception as e:
        print(f"JSON 解析錯誤: {e}\n原始文字:\n{text}")
        return []

def call_gemma(prompt):
    while True:
        try:
            response = gemma_client.models.generate_content(
                model=GEMMA_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    thinking_config=types.ThinkingConfig(thinking_level="high"),
                    temperature=0.1,
                )
            )
            return response.text
        except Exception as e:
            if "500" in str(e) or "429" in str(e):
                print(f"  -> Gemma API Error, waiting 5 seconds: {e}")
                time.sleep(5)
            else:
                raise e

def get_chunk_files(chunks_dir):
    chunk_files = []
    for root, _, filenames in os.walk(chunks_dir):
        for f in filenames:
            if f.endswith('.json'):
                chunk_files.append(os.path.join(root, f))
    return chunk_files

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if not os.path.exists(CHUNKS_DIR):
        print(f"找不到輸入資料夾: {os.path.abspath(CHUNKS_DIR)}")
        return

    chunk_files = get_chunk_files(CHUNKS_DIR)
    
    print(f"\n開始進行萃取 (總共 {len(chunk_files)} 個區塊檔案，使用 {GEMMA_MODEL_NAME})...")
    total_triples = 0
    
    for i, file_path in enumerate(chunk_files):
        rel_path = os.path.relpath(file_path, CHUNKS_DIR)
        source_filename = os.path.dirname(rel_path)
        chunk_basename = os.path.basename(rel_path)
        
        output_folder = os.path.join(RAW_TRIPLES_DIR, source_filename)
        os.makedirs(output_folder, exist_ok=True)
        output_file_path = os.path.join(output_folder, chunk_basename)
        
        if os.path.exists(output_file_path):
            print(f"[{i+1}/{len(chunk_files)}] 略過: {source_filename} -> {chunk_basename} (已存在)")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            chunk = json.load(f)
            
        print(f"[{i+1}/{len(chunk_files)}] 處理: {source_filename} -> {chunk_basename} ...")
        user_prompt = USER_PROMPT_TEMPLATE.format(chunk_text=chunk['text'])

        try:
            gemma_response_text = call_gemma(user_prompt)
            triples = extract_json(gemma_response_text)
            
            if not isinstance(triples, list):
                print(f"  -> 回傳格式非陣列，跳過")
                triples = []

            for idx, t in enumerate(triples):
                t['source_id'] = chunk['source_id']
                t['source_file'] = chunk['source_file']
                t['source_index'] = idx + 1

            with open(output_file_path, "w", encoding="utf-8") as f:
                json.dump(triples, f, ensure_ascii=False, indent=2)

            total_triples += len(triples)
            print(f"  -> 成功萃取 {len(triples)} 筆三元組。")

        except Exception as e:
            print(f"  -> 處理失敗: {e}")

    print("\n======================================")
    print(f"萃取完成！總共取得 {total_triples} 筆原始候選三元組。")
    print(f"結果已分資料夾儲存至: {os.path.abspath(RAW_TRIPLES_DIR)}")
    print("======================================")

if __name__ == "__main__":
    main()

