import aiohttp
import asyncio
import json
import os

# ---------------- CONFIG ----------------
bucket_dir = "bucket"
os.makedirs(bucket_dir, exist_ok=True)

archs = {
    "64bit": "amd64",
    "arm64": "arm64",
    "32bit": "386",
    "x86": "x86"
}

# 控制最大并发请求数
MAX_CONCURRENT_REQUESTS = 5

# ---------------- HELPERS ----------------
sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def fetch(session, url):
    """异步抓取 URL 内容"""
    async with sem:
        try:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.text()
        except Exception as e:
            print(f"Fetch failed {url}: {e}")
            return None

async def generate_manifest(session, version):
    """生成单个版本 manifest"""
    ver = version.lstrip("v")
    arch_dict = {}

    tasks = []
    for name, suffix in archs.items():
        url = f"https://dl.k8s.io/release/{version}/bin/windows/{suffix}/kubectl.exe"
        hash_url = f"https://dl.k8s.io/release/{version}/bin/windows/{suffix}/kubectl.exe.sha256"
        tasks.append(fetch(session, hash_url))

    results = await asyncio.gather(*tasks)
    for idx, content in enumerate(results):
        if content:
            name = list(archs.keys())[idx]
            suffix = list(archs.values())[idx]
            url = f"https://dl.k8s.io/release/{version}/bin/windows/{suffix}/kubectl.exe"
            arch_dict[name] = {"url": url, "hash": content.strip()}

    if not arch_dict:
        print(f"{version} - No valid architectures found, skipping")
        return

    manifest = {
        "version": ver,
        "description": "Kubernetes kubectl CLI",
        "homepage": "https://kubernetes.io/",
        "license": "Apache-2.0",
        "architecture": arch_dict,
        "bin": ["kubectl.exe"]
    }

    filename = os.path.join(bucket_dir, f"kubectl@{ver}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Generated manifest: {filename}")

# ---------------- GITHUB RELEASES ----------------
async def get_all_versions():
    """抓取 kubernetes/kubernetes Releases，返回 tag 列表"""
    versions = []
    page = 1
    per_page = 100

    async with aiohttp.ClientSession(headers={"User-Agent": "python"}) as session:
        while True:
            url = f"https://api.github.com/repos/kubernetes/kubernetes/releases?per_page={per_page}&page={page}"
            async with sem:
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            print(f"GitHub API error {resp.status}")
                            break
                        data = await resp.json()
                        if not data:
                            break
                        for rel in data:
                            tag = rel["tag_name"]
                            if tag.startswith("v") and len(tag.split(".")) == 3:
                                versions.append(tag)
                        print(f"Page {page} fetched, {len(data)} releases")
                        page += 1
                except Exception as e:
                    print(f"GitHub fetch failed: {e}")
                    await asyncio.sleep(10)
    return versions

# ---------------- MAIN ----------------
async def main():
    versions = await get_all_versions()
    print(f"Found {len(versions)} valid kubectl versions")
    async with aiohttp.ClientSession(headers={"User-Agent": "python"}) as session:
        tasks = [generate_manifest(session, v) for v in versions]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
