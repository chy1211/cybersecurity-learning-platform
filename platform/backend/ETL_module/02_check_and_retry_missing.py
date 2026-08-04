import json
import os
import subprocess

CHUNKS_DIR = "Chunks"
RAW_TRIPLES_DIR = "RawTriples"


def classify_raw_file(file_path):
    if not os.path.exists(file_path):
        return "missing"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return "empty"
        data = json.loads(content)
        if isinstance(data, list) and len(data) == 0:
            return "empty"
        return "ok"
    except (OSError, json.JSONDecodeError):
        return "invalid"


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if not os.path.exists(CHUNKS_DIR):
        print(f"找不到 {CHUNKS_DIR} 目錄，請先執行 01_chunk_data.py")
        return

    missing_files = []
    count_missing = 0
    count_empty = 0
    count_invalid = 0

    # 比對 Chunks 和 RawTriples 目錄
    for root, _, filenames in os.walk(CHUNKS_DIR):
        for f in filenames:
            if f.endswith('.json'):
                chunk_file = os.path.join(root, f)
                rel_path = os.path.relpath(chunk_file, CHUNKS_DIR)
                raw_file = os.path.join(RAW_TRIPLES_DIR, rel_path)

                status = classify_raw_file(raw_file)
                if status != "ok":
                    missing_files.append(rel_path)
                    if status == "missing":
                        count_missing += 1
                    elif status == "empty":
                        count_empty += 1
                    else:
                        count_invalid += 1

    if not missing_files:
        print("🎉 所有 Chunks 皆已成功產生對應的 RawTriples，無需重跑！")
        return

    print(f"⚠️ 發現 {len(missing_files)} 個未處理或失敗的 Chunks：")
    print(f"   - 檔案不存在: {count_missing}")
    print(f"   - 空陣列/空檔: {count_empty}")
    print(f"   - 解析失敗: {count_invalid}")
    for mf in missing_files[:20]:  # 最多顯示 20 筆避免洗版
        print(f" - {mf}")
    if len(missing_files) > 20:
        print(f" ...以及其他 {len(missing_files) - 20} 筆。")

    print("\n🚀 準備呼叫 02_extract_triples.py 進行補跑 (它會自動略過已存在的檔案)...")
    print("=" * 50)

    # 直接呼叫 02_extract_triples.py，因為它已經具備 skip 機制
    try:
        subprocess.run(["python", "02_extract_triples.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 執行 02_extract_triples.py 時發生錯誤: {e}")
    except FileNotFoundError:
        print("\n❌ 找不到 python 指令，請確認環境變數或以虛擬環境執行。")

    print("\n✅ 補跑腳本執行結束。您可以再次執行此程式檢查是否還有遺漏。")


if __name__ == "__main__":
    main()
