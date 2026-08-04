import argparse
import json
import os
import pdfplumber
from transformers import AutoTokenizer

SOURCE_DIR = os.getenv("SOURCE_DATA_DIR", "SourceData")
CHUNKS_DIR = os.getenv("CHUNKS_DIR", "Chunks")
CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
SUPPORTED_EXTENSIONS = ('.pdf', '.json')
QUESTION_CORPUS_TYPE = "question_chunks_v1"


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        dest="source_dirs",
        action="append",
        help="Input directory. May be repeated or contain comma-separated paths.",
    )
    parser.add_argument(
        "--manifest",
        help="UTF-8 text file with one input file path per line.",
    )
    return parser.parse_args(argv)


def is_supported_input(path):
    return path.lower().endswith(SUPPORTED_EXTENSIONS)


def get_files_to_process(source_dir):
    files = []
    for root, _, filenames in os.walk(source_dir):
        for f in filenames:
            if is_supported_input(f):
                files.append(os.path.join(root, f))
    return files


def split_source_dirs(source_dirs):
    dirs = []
    for value in source_dirs or []:
        for part in value.split(","):
            part = part.strip()
            if part:
                dirs.append(part)
    return dirs


def resolve_path(path, base_dir):
    return path if os.path.isabs(path) else os.path.join(base_dir, path)


def get_manifest_files(manifest_path):
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    files = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            path = resolve_path(entry, manifest_dir)
            if os.path.isfile(path) and is_supported_input(path):
                files.append(path)
    return files


def resolve_input_files(source_dirs=None, manifest_path=None, script_dir=None):
    script_dir = script_dir or os.getcwd()
    files = []

    for source_dir in split_source_dirs(source_dirs):
        path = resolve_path(source_dir, script_dir)
        if os.path.isdir(path):
            files.extend(get_files_to_process(path))
        elif os.path.isfile(path) and is_supported_input(path):
            files.append(path)

    if manifest_path:
        manifest_file = resolve_path(manifest_path, script_dir)
        files.extend(get_manifest_files(manifest_file))

    return files


def is_question_corpus(data):
    return (
        isinstance(data, dict)
        and data.get("corpus_type") == QUESTION_CORPUS_TYPE
        and isinstance(data.get("chunks"), list)
    )


def normalize_question_chunks(data, filename):
    chunks = []
    for item in data["chunks"]:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        text = item.get("text")
        if not source_id or text is None:
            continue
        chunks.append({
            "source_id": str(source_id),
            "source_file": str(item.get("source_file") or filename),
            "text": str(text),
        })
    return chunks


def chunk_file(file_path, tokenizer):
    filename = os.path.basename(file_path)
    text = ""

    if file_path.lower().endswith('.pdf'):
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
        except Exception as e:
            print(f"讀取 PDF 失敗 {file_path}: {e}")
            return []
    elif file_path.lower().endswith('.json'):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if is_question_corpus(data):
                    return normalize_question_chunks(data, filename)
                text = json.dumps(data, ensure_ascii=False)
        except Exception as e:
            print(f"讀取 JSON 失敗 {file_path}: {e}")
            return []

    tokens = tokenizer.encode(text)
    chunks = []
    start = 0
    chunk_idx = 1

    while start < len(tokens):
        end = min(start + CHUNK_SIZE_TOKENS, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = tokenizer.decode(chunk_tokens, skip_special_tokens=True)
        chunks.append({
            "source_id": f"chunk_{chunk_idx}",
            "source_file": filename,
            "text": chunk_text
        })
        chunk_idx += 1
        start += (CHUNK_SIZE_TOKENS - CHUNK_OVERLAP_TOKENS)

    return chunks


def main(argv=None):
    args = parse_args(argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    source_dir = SOURCE_DIR if os.path.isabs(SOURCE_DIR) else os.path.join(script_dir, SOURCE_DIR)
    chunks_dir = CHUNKS_DIR if os.path.isabs(CHUNKS_DIR) else os.path.join(script_dir, CHUNKS_DIR)

    print("初始化 Tokenizer (google/gemma-4-31B-it)...")
    tokenizer = AutoTokenizer.from_pretrained("google/gemma-4-31B-it")

    if not args.source_dirs and not args.manifest and not os.path.isdir(source_dir):
        print(f"來源資料夾不存在: {source_dir}")
        print("請在環境變數 SOURCE_DATA_DIR 或 backend/.env 中設定本機 PDF/JSON 來源資料夾。")
        return

    if args.source_dirs or args.manifest:
        files = resolve_input_files(args.source_dirs, args.manifest, script_dir)
    else:
        files = get_files_to_process(source_dir)
    print(f"找到 {len(files)} 個檔案需要處理。")

    os.makedirs(chunks_dir, exist_ok=True)
    total_chunks = 0

    for file_path in files:
        filename = os.path.basename(file_path)
        print(f"正在處理檔案: {filename}")
        chunks = chunk_file(file_path, tokenizer)

        if not chunks:
            continue

        # 為這個來源檔案建立專屬資料夾
        source_folder = os.path.join(chunks_dir, filename)
        os.makedirs(source_folder, exist_ok=True)

        for chunk in chunks:
            chunk_file_path = os.path.join(source_folder, f"{chunk['source_id']}.json")
            with open(chunk_file_path, "w", encoding="utf-8") as f:
                json.dump(chunk, f, ensure_ascii=False, indent=2)
            total_chunks += 1

        print(f"  -> 產生了 {len(chunks)} 個 chunks 並存入 {source_folder}。")

    print(f"\n======================================")
    print(f"分塊完成！總共產生 {total_chunks} 個 chunks。")
    print(f"結果已分資料夾儲存至: {os.path.abspath(chunks_dir)}")
    print("======================================")


if __name__ == "__main__":
    main()
