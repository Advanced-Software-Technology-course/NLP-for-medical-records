
Full Dataset (3623 records) Download Link:
https://drive.google.com/drive/folders/1C6dK69TQUvsitFMatMBgtuHS4oVO2SYS?usp=drive_link

Originally From:
https://huggingface.co/datasets/ekacare/eka-medical-asr-evaluation-dataset

Automatic local download:
python scripts/download_eka_audio.py --config all --split test

This writes audio files to:
data/eka_dataset_audio/downloads/<config>/<split>/

The script downloads the Parquet shards from Hugging Face and extracts the embedded audio bytes directly, so it does not need TorchCodec.
