# CLI 入口
from app.scanner import scan_once

if __name__ == '__main__':
    import json
    print(json.dumps(scan_once(), ensure_ascii=False, indent=2))
