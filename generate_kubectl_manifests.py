import asyncio
import aiohttp
import json
from pathlib import Path

# ---------------- 配置 ----------------
BUCKET_DIR = Path("./bucket")
BUCKET_DIR.mkdir(exist_ok=True)

# 特征版本 (主版本号)
FEATURE_VERSIONS = [
    "1.20",
    "1.21",
    "1.22"
]

ARCHS_BASE = {
    "64bit": "amd64",
    "32bit": "386"
}
ARM64_START_VERSION = (1, 21, 0)    # >=1.21 开始支持 arm64
CONVERT_START_VERSION = (1, 22, 0)  # >=1.22 开始有 kubectl-convert.exe

LATEST_VERSION_FILE = "kubectl.json"
# --------------------------------------

def parse_version(version_str: str):
    """v1.20.15 -> (1,20,15)"""
    return tuple(map(int, version_str.split(".")))

def need_convert(version: str):
    return parse_version(version) >= CONVERT_START_VERSION

def archs_for_version(version: str):
    arches = dict(ARCHS_BASE)
    if parse_version(version) >= ARM64_START_VERSION:
        arches["arm64"] = "arm64"
    return arches

async def fetch_version_file(session: aiohttp.ClientSession, url: str):
    """读取 k8s release 文件内容"""
    async with session.get(url) as resp:
        resp.raise_for_status()
        text = await resp.text()
        return text.strip().lstrip("v")

def generate_manifest_dict(version: str):
    bins = ["kubectl.exe"]
    if need_convert(version):
        bins.append("kubectl-convert.exe")

    arches = archs_for_version(version)
    arch_dict = {
        arch_name: {
            "url": f"https://dl.k8s.io/release/v{version}/kubernetes-client-windows-{folder}.tar.gz",
            "hash": f"https://dl.k8s.io/release/v{version}/kubernetes-client-windows-{folder}.tar.gz.sha256"
        }
        for arch_name, folder in arches.items()
    }

    manifest = {
        "version": version,
        "description": "Control the Kubernetes cluster manager.",
        "homepage": "https://kubernetes.io/docs/reference/kubectl/",
        "license": "Apache-2.0",
        "architecture": arch_dict,
        "extract_dir": "kubernetes/client",
        "bin": [f"bin\\{b}" for b in bins],
        "checkver": {
            "url": "https://dl.k8s.io/release/stable.txt",
            "regex": r"v([\d.]+)"
        },
        "autoupdate": {
            "architecture": {
                arch_name: {
                    "url": f"https://dl.k8s.io/release/v$version/kubernetes-client-windows-{folder}.tar.gz"
                } for arch_name, folder in arches.items()
            },
            "hash": {"url": "$url.sha256"}
        }
    }
    return manifest

def write_manifest(manifest: dict, filename: Path):
    if filename.exists():
        old = json.loads(filename.read_text(encoding="utf-8"))
        if old == manifest:
            print(f"[SKIP] {filename.name} unchanged.")
            return
    filename.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[OK] Generated manifest: {filename.name}")

async def main():
    async with aiohttp.ClientSession() as session:
        # 1️⃣ 最新版本
        latest_version = await fetch_version_file(session, "https://dl.k8s.io/release/stable.txt")
        print(f"[INFO] Latest kubectl version: {latest_version}")
        latest_manifest = generate_manifest_dict(latest_version)
        write_manifest(latest_manifest, BUCKET_DIR / LATEST_VERSION_FILE)

        # 2️⃣ 特征版本
        for major_minor in FEATURE_VERSIONS:
            url = f"https://dl.k8s.io/release/stable-{major_minor}.txt"
            try:
                latest_feature = await fetch_version_file(session, url)
                manifest = generate_manifest_dict(latest_feature)
                filename = BUCKET_DIR / f"kubectl{major_minor}.json"
                write_manifest(manifest, filename)
            except aiohttp.ClientResponseError:
                print(f"[WARN] Could not fetch stable version for {major_minor}, skipping.")

if __name__ == "__main__":
    asyncio.run(main())
