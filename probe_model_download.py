"""Read at most 1 MiB to compare download routes; does not change system proxy."""
from concurrent.futures import ThreadPoolExecutor
import time
import requests

URL="https://modelscope.cn/models/Systran/faster-whisper-small/resolve/master/model.bin"

def probe(direct):
    session=requests.Session()
    session.trust_env=not direct
    start=time.monotonic()
    size=0
    try:
        with session.get(URL,headers={"Range":"bytes=0-1048575"},stream=True,timeout=(8,10)) as response:
            response.raise_for_status()
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>=1048576:break
        print("direct" if direct else "configured route", "seconds",round(time.monotonic()-start,2),"bytes",size,flush=True)
    except Exception as exc:
        print("direct" if direct else "configured route",type(exc).__name__,flush=True)
    finally:
        session.close()

if __name__=="__main__":
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(probe,[False,True]))
