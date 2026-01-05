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
    """v1.20.15 -> (1,20,15) 或 v1.20.15-rc.0 -> (1,20,15,0)"""
    # 移除 -rc 等预发布标识符，用于排序
    base_version = version_str.split('-')[0]
    return tuple(map(int, base_version.split(".")))

def need_convert(version: str):
    return parse_version(version) >= CONVERT_START_VERSION

def archs_for_version(version: str):
    arches = dict(ARCHS_BASE)
    if parse_version(version) >= ARM64_START_VERSION:
        arches["arm64"] = "arm64"
    return arches

async def fetch_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, timeout=30) as resp:
        resp.raise_for_status()
        return await resp.text()


async def fetch_version_file(session: aiohttp.ClientSession, url: str):
    """读取 k8s release 文件内容"""
    text = await fetch_text(session, url)
    return text.strip().lstrip("v")


async def fetch_sha256(session: aiohttp.ClientSession, url: str) -> str:
    """获取 K8s 官方 sha256 内容"""
    txt = await fetch_text(session, url)
    # 官方文件格式：<hash> <filename>
    return txt.strip().split()[0]


async def fetch_github_tags_for_version(session: aiohttp.ClientSession, major_minor: str) -> list:
    """从 GitHub API 获取指定版本范围的 tags"""
    url = "https://api.github.com/repos/kubernetes/kubernetes/tags"
    tags = []
    page = 1

    while True:
        async with session.get(f"{url}?per_page=100&page={page}", timeout=30) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if not data:
                break

            # 过滤出匹配的版本
            for tag in data:
                tag_name = tag.get("name", "").lstrip("v")
                if tag_name.startswith(f"{major_minor}."):
                    tags.append(tag_name)

            page += 1
            # 限制最多获取 10 页，避免过多请求但确保获取足够版本
            if page > 10:
                break

    return tags


async def get_latest_feature_version_from_github(session: aiohttp.ClientSession, major_minor: str) -> str:
    """从 GitHub 获取指定主版本号的最新版本"""
    matching_versions = await fetch_github_tags_for_version(session, major_minor)

    if not matching_versions:
        raise ValueError(f"No tags found for version {major_minor}")

    # 排序并返回最新版本
    matching_versions.sort(key=parse_version, reverse=True)
    latest_version = matching_versions[0]
    print(f"[INFO] Found {len(matching_versions)} versions for {major_minor}, latest is {latest_version}")
    return latest_version


async def generate_manifest_dict(session: aiohttp.ClientSession, version: str):

    bins = ["kubectl.exe"]
    if need_convert(version):
        bins.append("kubectl-convert.exe")

    arches = archs_for_version(version)
    arch_dict = {}
    for arch_name, folder in arches.items():
        try:
            hash_256 = await fetch_sha256(session, f"https://dl.k8s.io/release/v{version}/kubernetes-client-windows-{folder}.tar.gz.sha256")
            arch_dict[arch_name] = {
                "url": f"https://dl.k8s.io/release/v{version}/kubernetes-client-windows-{folder}.tar.gz",
                "hash": hash_256
            }
            print(f"[INFO] Added {arch_name} architecture for version {version}")
        except aiohttp.ClientResponseError as e:
            print(f"[WARN] Skipping {arch_name} architecture for version {version}: {e}")
            continue

    # 为 autoupdate 创建架构映射，只包含实际可用的架构
    autoupdate_arches = {}
    for arch_name, folder in arches.items():
        # 检查这个架构是否在实际的 arch_dict 中（即是否成功获取了 hash）
        if arch_name in arch_dict:
            autoupdate_arches[arch_name] = {
                "url": f"https://dl.k8s.io/release/v$version/kubernetes-client-windows-{folder}.tar.gz"
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
            "architecture": autoupdate_arches,
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
        latest_manifest = await generate_manifest_dict(session, latest_version)
        write_manifest(latest_manifest, BUCKET_DIR / LATEST_VERSION_FILE)

        # 2️⃣ 特征版本
        for major_minor in FEATURE_VERSIONS:
            url = f"https://dl.k8s.io/release/stable-{major_minor}.txt"
            try:
                latest_feature = await fetch_version_file(session, url)
                print(f"[INFO] Found stable version for {major_minor}: {latest_feature}")
            except aiohttp.ClientResponseError as e:
                print(f"[WARN] Could not fetch stable version for {major_minor} from {url}, trying GitHub API...")
                try:
                    latest_feature = await get_latest_feature_version_from_github(session, major_minor)
                    print(f"[INFO] Found version for {major_minor} from GitHub: {latest_feature}")
                except Exception as github_e:
                    print(f"[ERROR] Could not fetch version for {major_minor} from GitHub either: {github_e}, skipping.")
                    continue

            try:
                manifest = await generate_manifest_dict(session, latest_feature)
                # 检查是否有可用的架构
                if not manifest["architecture"]:
                    print(f"[WARN] No architectures available for {major_minor} version {latest_feature}, skipping manifest generation.")
                    continue
                filename = BUCKET_DIR / f"kubectl{major_minor}.json"
                write_manifest(manifest, filename)
            except Exception as e:
                print(f"[ERROR] Failed to generate manifest for {major_minor} version {latest_feature}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
