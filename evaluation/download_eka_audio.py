from __future__ import annotations

import argparse
import csv
import re
import subprocess
import tempfile
from pathlib import Path
from collections import deque

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, list_repo_files


REPO_ID = "ekacare/eka-medical-asr-evaluation-dataset"
DEFAULT_CONFIGS = ["en"]


def _sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")
    return cleaned.strip("_") or "sample"


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text or "", flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _resolve_metadata_csv(repo_root: Path) -> Path:
    candidates = [
        repo_root / "evaluation" / "medical_asr_dataset" / "metadata.csv",
        repo_root / "evaluation" / "metadata.csv",
        repo_root / "data" / "eka_dataset_audio" / "audio_sample" / "metadata.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find metadata.csv for transcript matching.")


def _load_metadata_targets(metadata_csv: Path) -> list[dict]:
    targets = []
    with open(metadata_csv, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "audio_path" not in reader.fieldnames or "transcript" not in reader.fieldnames:
            raise RuntimeError(
                f"metadata.csv must contain audio_path and transcript columns, found: {reader.fieldnames}"
            )

        for row in reader:
            audio_path = (row.get("audio_path") or "").strip()
            transcript = (row.get("transcript") or "").strip()
            if not audio_path or not transcript:
                continue

            file_name = Path(audio_path).name
            number_match = re.search(r"audio_(\d+)\.", file_name)
            number = int(number_match.group(1)) if number_match else None
            targets.append(
                {
                    "audio_path": audio_path,
                    "file_name": file_name,
                    "number": number,
                    "normalized_transcript": _normalize_text(transcript),
                }
            )

    return targets


def _build_target_map(targets: list[dict]) -> dict[str, deque]:
    mapping: dict[str, deque] = {}
    for target in sorted(targets, key=lambda item: (item["number"] is None, item["number"] or 0, item["file_name"])):
        key = target["normalized_transcript"]
        mapping.setdefault(key, deque()).append(target)
    return mapping


def _convert_audio_to_wav(audio_bytes: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        source_path = temp_dir_path / "input.m4a"
        source_path.write_bytes(bytes(audio_bytes))

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "ffmpeg failed").strip())


def _write_sample_audio(audio_bytes: bytes, destination: Path, overwrite: bool) -> bool:
    if destination.exists() and not overwrite:
        return False

    _convert_audio_to_wav(audio_bytes, destination)
    return True


def _list_parquet_shards(config_name: str, split: str) -> list[str]:
    shard_prefix = f"{config_name}/{split}-"
    return [
        filename
        for filename in list_repo_files(REPO_ID, repo_type="dataset")
        if filename.startswith(shard_prefix) and filename.endswith(".parquet")
    ]


def download_dataset_audio(
    config_name: str,
    split: str,
    metadata_csv: Path,
    output_dir: Path,
    overwrite: bool,
    limit: int | None = None,
) -> int:
    targets = _load_metadata_targets(metadata_csv)
    target_map = _build_target_map(targets)
    target_dir = output_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    matched_targets = set()
    shard_files = _list_parquet_shards(config_name, split)
    if not shard_files:
        raise FileNotFoundError(f"No parquet shards found for {config_name}/{split}")

    for shard_name in shard_files:
        shard_path = hf_hub_download(REPO_ID, repo_type="dataset", filename=shard_name)
        table = pq.read_table(shard_path, columns=["file_name", "audio", "text"])
        rows = table.to_pylist()

        for row in rows:
            if limit is not None and written >= limit:
                return written

            transcript_key = _normalize_text(row.get("text") or "")
            target_queue = target_map.get(transcript_key)
            if not target_queue:
                continue

            target = target_queue.popleft()
            matched_targets.add(target["file_name"])
            destination = target_dir / target["file_name"]
            if _write_sample_audio(row.get("audio") or b"", destination, overwrite=overwrite):
                written += 1

    unmatched = [target for target in targets if target["file_name"] not in matched_targets]
    if unmatched:
        print(f"[WARN] Unmatched metadata rows: {len(unmatched)}")
        print("[WARN] First few unmatched:", [item["file_name"] for item in unmatched[:10]])

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download EKA medical ASR dataset audio from Hugging Face and save it locally."
    )
    parser.add_argument(
        "--config",
        default="all",
        help="Dataset config to download, e.g. en, hi, or all (default: all).",
    )
    parser.add_argument(
        "--split",
        default="test",
        help="Dataset split to download (default: test).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "data" / "eka_dataset_audio" / "wav"),
        help="Directory to write audio files into.",
    )
    parser.add_argument(
        "--metadata-csv",
        default=None,
        help="CSV with audio_path and transcript columns used to choose the output audio_<number>.wav names.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files if they already exist.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of audio files to write per config.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    metadata_csv = Path(args.metadata_csv).expanduser().resolve() if args.metadata_csv else _resolve_metadata_csv(repo_root)

    configs = DEFAULT_CONFIGS if args.config == "all" else [args.config]
    total_written = 0

    for config_name in configs:
        try:
            written = download_dataset_audio(
                config_name=config_name,
                split=args.split,
                metadata_csv=metadata_csv,
                output_dir=output_dir,
                overwrite=args.overwrite,
                limit=args.limit,
            )
        except Exception as exc:
            print(f"[ERROR] {config_name}/{args.split}: {exc}")
            continue

        total_written += written
        print(f"[OK] {config_name}/{args.split}: wrote {written} audio file(s)")

    print(f"Finished. Output directory: {output_dir}")
    print(f"Metadata CSV: {metadata_csv}")
    print(f"Total files written: {total_written}")


if __name__ == "__main__":
    main()