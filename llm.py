import os, time, httpx
BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")
KEY = os.getenv("LLM_API_KEY", "dummy")

def chat(system, user, timeout=120):
    err = None
    for i in range(3):  # 1 try + 2 retries
        try:
            r = httpx.post(f"{BASE}/chat/completions", timeout=timeout,
                headers={"Authorization": f"Bearer {KEY}"},
                json={"model": MODEL, "temperature": 0.1,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            err = e; time.sleep(1.5)
    raise RuntimeError(f"LLM unavailable: {err}")

def healthy():
    try:
        return httpx.get(f"{BASE}/models", timeout=3, headers={"Authorization": f"Bearer {KEY}"}).status_code < 500
    except Exception:
        return False
