import json
import os

# Define the path for the JSON file that will store user progress
DATA_FILE = os.path.join(os.path.dirname(__file__), 'user_progress.json')
MISTAKES_FILE = os.path.join(os.path.dirname(__file__), 'user_mistakes.json')

# Default unlocked nodes (based on the initial state in MockDBService)
DEFAULT_UNLOCKED = ["1"]

def load_progress():
    """
    Load the list of unlocked node IDs from the JSON file.
    If the file doesn't exist or is invalid, return the default unlocked nodes.
    """
    if not os.path.exists(DATA_FILE):
        return list(DEFAULT_UNLOCKED)
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Ensure we return a list
            if isinstance(data, list):
                return data
            return list(DEFAULT_UNLOCKED)
    except Exception as e:
        print(f"Error loading progress: {e}")
        return list(DEFAULT_UNLOCKED)

def save_progress(unlocked_ids):
    """
    Save the list of unlocked node IDs to the JSON file.
    """
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(unlocked_ids, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving progress: {e}")
        return False

def load_mistakes():
    """
    Load the list of mistakes from the JSON file.
    """
    if not os.path.exists(MISTAKES_FILE):
        return []
    
    try:
        with open(MISTAKES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception as e:
        print(f"Error loading mistakes: {e}")
        return []

def save_mistakes(mistakes):
    """
    Save the list of mistakes to the JSON file.
    """
    try:
        with open(MISTAKES_FILE, 'w', encoding='utf-8') as f:
            json.dump(mistakes, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error saving mistakes: {e}")
        return False

