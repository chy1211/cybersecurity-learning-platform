import json
import os
import tempfile
import threading

# Define the path for the JSON file that will store user progress
DATA_FILE = os.path.join(os.path.dirname(__file__), 'user_progress.json')
MISTAKES_FILE = os.path.join(os.path.dirname(__file__), 'user_mistakes.json')

# Default unlocked nodes (based on the initial state in MockDBService)
DEFAULT_UNLOCKED = ["1"]
_FILE_LOCK = threading.RLock()


def _atomic_write_json(path, data):
    directory = os.path.dirname(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=directory, prefix='.tmp-',
            suffix='.json', delete=False
        ) as handle:
            temp_path = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        return True
    except Exception as exc:
        print(f"Error saving local demo data: {exc}")
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass

def load_progress():
    """
    Load the list of unlocked node IDs from the JSON file.
    If the file doesn't exist or is invalid, return the default unlocked nodes.
    """
    with _FILE_LOCK:
        if not os.path.exists(DATA_FILE):
            return list(DEFAULT_UNLOCKED)
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else list(DEFAULT_UNLOCKED)
        except Exception as e:
            print(f"Error loading progress: {e}")
            return list(DEFAULT_UNLOCKED)

def save_progress(unlocked_ids):
    """
    Save the list of unlocked node IDs to the JSON file.
    """
    with _FILE_LOCK:
        return _atomic_write_json(DATA_FILE, unlocked_ids)

def load_mistakes():
    """
    Load the list of mistakes from the JSON file.
    """
    with _FILE_LOCK:
        if not os.path.exists(MISTAKES_FILE):
            return []
        try:
            with open(MISTAKES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            print(f"Error loading mistakes: {e}")
            return []

def save_mistakes(mistakes):
    """
    Save the list of mistakes to the JSON file.
    """
    with _FILE_LOCK:
        return _atomic_write_json(MISTAKES_FILE, mistakes)

