#!/usr/bin/env python3
"""
download_paper.py
Download a paper from arXiv: LaTeX source (tar.gz, extracted) and PDF.

Usage:
  python download_paper.py --arxiv-id 2512.16649 --output-dir ~/paper_cache
  python download_paper.py --arxiv-url https://arxiv.org/abs/2512.16649 --output-dir ./papers

Outputs (printed to stdout, one per line):
  TITLE=<paper title>
  WORKDIR=<absolute path to extracted source directory>
  PDF=<absolute path to pdf file>
"""

import argparse
import re
import shutil
import subprocess
import sys
import importlib.util
import tarfile
from pathlib import Path


# ---------- dependency auto-install ----------

def _install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _ensure(pkg_name, import_name=None):
    if importlib.util.find_spec(import_name or pkg_name) is None:
        print(f"Installing {pkg_name}...", file=sys.stderr)
        _install(pkg_name)

try:
    _ensure("requests")
    _ensure("beautifulsoup4", "bs4")
except Exception as e:
    print(f"Warning: dependency auto-install failed: {e}", file=sys.stderr)

import requests
from bs4 import BeautifulSoup


# ---------- helpers ----------

def extract_arxiv_id(text: str) -> str:
    m = re.search(r'(\d{4}\.\d{4,5}(?:v\d+)?)', text)
    if not m:
        raise ValueError(f"Cannot extract arXiv ID from: {text!r}")
    return m.group(1)


def get_title(arxiv_id: str) -> str:
    url = f"https://arxiv.org/abs/{arxiv_id}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    el = soup.find("h1", class_="title mathjax")
    if not el:
        return arxiv_id
    title = el.get_text(strip=True)
    return re.sub(r"^Title:\s*", "", title)


def download_source(arxiv_id: str, output_dir: Path) -> Path:
    """Download and extract LaTeX source tarball. Returns the extract directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    src_url = f"https://arxiv.org/src/{arxiv_id}"
    resp = requests.get(src_url, stream=True, timeout=60)
    resp.raise_for_status()

    tar_path = output_dir / f"{arxiv_id}.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    with open(tar_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    extract_dir = output_dir / arxiv_id
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)
    tar_path.unlink()

    return extract_dir


def download_pdf(arxiv_id: str, extract_dir: Path) -> Path:
    """Download PDF into the same extract directory."""
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    resp = requests.get(pdf_url, stream=True, timeout=60)
    resp.raise_for_status()

    pdf_path = extract_dir / f"{arxiv_id}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()
    with open(pdf_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return pdf_path


# ---------- main ----------

def parse_args():
    p = argparse.ArgumentParser(description="Download arXiv paper source and PDF")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--arxiv-id",  help="arXiv ID, e.g. 2512.16649")
    group.add_argument("--arxiv-url", help="arXiv URL or any string containing an arXiv ID")
    p.add_argument("--output-dir", required=True,
                   help="Directory to store downloaded files (supports ~)")
    return p.parse_args()


def main():
    args = parse_args()

    raw = args.arxiv_id or args.arxiv_url
    try:
        arxiv_id = extract_arxiv_id(raw)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir).expanduser().resolve()

    print(f"Fetching title for {arxiv_id}...", file=sys.stderr)
    title = get_title(arxiv_id)

    print(f"Downloading source for {arxiv_id}...", file=sys.stderr)
    workdir = download_source(arxiv_id, output_dir)

    print(f"Downloading PDF for {arxiv_id}...", file=sys.stderr)
    pdf_path = download_pdf(arxiv_id, workdir)

    # Machine-readable output
    print(f"TITLE={title}")
    print(f"WORKDIR={workdir}")
    print(f"PDF={pdf_path}")
    print(f"ARXIV_ID={arxiv_id}")


if __name__ == "__main__":
    main()
