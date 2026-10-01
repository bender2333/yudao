import json
import os

DATA_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subway_data.json")


def load_subway_data(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
