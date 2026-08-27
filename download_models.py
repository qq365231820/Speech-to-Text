"""Download only the two selected models from their publishers, verifying hashes."""
import hashlib
import os
from pathlib import Path
import time
import requests
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent / "models"
MODELS = [
    ("Systran/faster-whisper-small", "faster-whisper-small", ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]),
    ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen", ["qwen2.5-1.5b-instruct-q4_k_m.gguf"]),
]

def sha256(path):
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()

def download(repo,revision,name,destination,metadata):
    destination.parent.mkdir(parents=True,exist_ok=True)
    expected=metadata.get("lfs",{}).get("sha256")
    size=metadata.get("size",metadata.get("lfs",{}).get("size"))
    if destination.exists():
        if (expected and sha256(destination)==expected) or (not expected and destination.stat().st_size==size):
            print(f"Verified existing: {name}",flush=True)
            return
        raise RuntimeError(f"Existing model is not the expected file: {destination}")
    partial=destination.with_suffix(destination.suffix+".part")
    if partial.exists() and size and partial.stat().st_size==size:
        if expected and sha256(partial)==expected:
            os.replace(partial,destination)
            print(f"Verified completed partial: {name}",flush=True)
            return
    url=f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
    if "--modelscope" in sys.argv:
        mirror=f"https://modelscope.cn/models/{repo}/resolve/master/{name}"
        if expected:
            check=requests.head(mirror,timeout=20)
            check.raise_for_status()
            if check.headers.get("X-Linked-Etag","").strip('"')!=expected:
                raise RuntimeError("ModelScope copy differs from publisher SHA256; refusing to mix downloads")
        url=mirror
        print(f"Using ModelScope, publisher hash checked: {name}",flush=True)
    for attempt in range(5):
        offset=partial.stat().st_size if partial.exists() else 0
        headers={"Range":f"bytes={offset}-"} if offset else {}
        try:
            with requests.get(url,params={"download":"true","t":int(time.time())},headers=headers,stream=True,timeout=(15,60)) as response:
                response.raise_for_status()
                if offset and response.status_code==206 and not response.headers.get("Content-Range","").startswith(f"bytes {offset}-"):
                    raise RuntimeError("Server returned an incorrect resume range")
                if offset and response.status_code!=206:
                    offset=0
                current=offset
                reported=time.monotonic()
                with partial.open("ab" if offset else "wb") as stream:
                    for block in response.iter_content(1024*1024):
                        stream.write(block)
                        current+=len(block)
                        if time.monotonic()-reported>10:
                            print(f"{name}: {current/1e6:.1f} / {(size or 0)/1e6:.1f} MB",flush=True)
                            reported=time.monotonic()
            if size and partial.stat().st_size!=size:
                raise RuntimeError("Downloaded size mismatch")
            if expected and sha256(partial)!=expected:
                raise RuntimeError("SHA256 mismatch")
            os.replace(partial,destination)
            print(f"Verified download: {name} ({destination.stat().st_size/1e6:.1f} MB)",flush=True)
            return
        except (requests.RequestException,OSError) as exc:
            print(f"Retry {attempt+1}: {name}: {type(exc).__name__}",flush=True)
    raise RuntimeError(f"Download failed: {name}")

def download_model(spec):
    repo,folder,names=spec
    response=requests.get(f"https://huggingface.co/api/models/{repo}",params={"blobs":"true"},timeout=30)
    response.raise_for_status()
    info=response.json()
    files={item["rfilename"]:item for item in info["siblings"]}
    print(f"Publisher: {repo}; revision: {info['sha']}",flush=True)
    for name in names:
        download(repo,info["sha"],name,ROOT/folder/name,files[name])

def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(download_model,MODELS))

if __name__=="__main__": main()
