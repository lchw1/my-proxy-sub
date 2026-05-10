import asyncio
import os
import tarfile
import urllib.request
import subprocess

async def download_mihomo():
    if not os.path.exists("mihomo"):
        print("Downloading Mihomo...")
        url = "https://github.com/MetaCubeX/mihomo/releases/download/v1.18.3/mihomo-linux-amd64-v1.18.3.gz"
        urllib.request.urlretrieve(url, "mihomo.gz")
        subprocess.run(["gunzip", "-f", "mihomo.gz"])
        os.chmod("mihomo", 0o755)
        print("Mihomo downloaded and extracted.")

if __name__ == "__main__":
    asyncio.run(download_mihomo())
