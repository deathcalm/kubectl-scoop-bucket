import requests
import os
import json

# ---------------- CONFIG ----------------
bucket_dir = "bucket"
os.makedirs(bucket_dir, exist_ok=True)

archs = {
    "64bit": "amd64",
    "arm64": "arm64",
    "32bit": "386",
    "x86": "x86"
}

# ---------------- HELPER ----------------
def get_all_versions():
    versions = []
    page = 1
    per_page = 100
    while True:
        url = f"https://api.github.com/repos/kubernetes/kubernetes/releases?per_page={per_page}&page={page}"
        r = requests.get(url, headers={"User-Agent": "python"})
        if r.status_code != 200:
            print(f"Warning: GitHub API failed, status {r.status_code}")
            break
        data = r.json()
        if not data:
            break
        for rel in data:
            tag = rel["tag_name"]
            if tag.startswith("v") and len(tag.split(".")) == 3:
                versions.append(tag)
        page += 1
    return versions

def generate_manifest(version):
    ver = version.lstrip("v")
    arch_dict = {}
    for name, suffix in archs.items():
        url = f"https://dl.k8s.io/release/{version}/bin/windows/{suffix}/kubectl.exe"
        hash_url = f"https://dl.k8s.io/release/{version}/bin/windows/{suffix}/kubectl.exe.sha256"
        try:
            r = requests.get(hash_url, timeout=10)
            r.raise_for_status()
            arch_dict[name] = {"url": url, "hash": r.text.strip()}
        except:
            continue

    if not arch_dict:
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

# ---------------- MAIN ----------------
if __name__ == "__main__":
    versions = get_all_versions()
    print(f"Found {len(versions)} valid kubectl versions.")
    for v in versions:
        generate_manifest(v)
