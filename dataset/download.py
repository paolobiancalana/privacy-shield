"""Download datasets from HuggingFace and save as Parquet in data/raw/.

Usage:
    python -m dataset.download
    python -m dataset.download --datasets ai4privacy_500k,multinerd
    python -m dataset.download --output-dir data/raw
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

from datasets import load_dataset, DatasetDict, Dataset, concatenate_datasets

logger = logging.getLogger(__name__)


@dataclass
class DatasetSpec:
    """Specification for a HuggingFace dataset to download."""

    short_name: str
    hf_name: str
    # "column" = filter rows by lang column; "split_name" = select splits by suffix
    lang_strategy: str | None = None  # "column" or "split_name"
    lang_filter: str | None = None
    en_sample_ratio: float | None = None


DATASET_SPECS: dict[str, DatasetSpec] = {
    "ai4privacy_500k": DatasetSpec(
        short_name="ai4privacy_500k",
        hf_name="ai4privacy/open-pii-masking-500k-ai4privacy",
    ),
    "ai4privacy_400k": DatasetSpec(
        short_name="ai4privacy_400k",
        hf_name="ai4privacy/pii-masking-400k",
    ),
    "multinerd": DatasetSpec(
        short_name="multinerd",
        hf_name="Babelscape/multinerd",
        lang_strategy="split_name",
        lang_filter="it",
        en_sample_ratio=0.20,
    ),
    "wikineural": DatasetSpec(
        short_name="wikineural",
        hf_name="Babelscape/wikineural",
        lang_strategy="split_name",
        lang_filter="it",
        en_sample_ratio=0.20,
    ),
    "humadex": DatasetSpec(
        short_name="humadex",
        hf_name="HUMADEX/italian_ner_dataset",
    ),
}


def _filter_by_split_name(
    ds: DatasetDict,
    spec: DatasetSpec,
) -> DatasetDict:
    """For datasets where language is in the split name (e.g. train_it, test_en).

    Consolidates per-language splits into standard train/val/test splits.
    """
    lang = spec.lang_filter
    result: dict[str, Dataset] = {}

    # Collect target language splits
    for split_name, split_ds in ds.items():
        if f"_{lang}" in split_name:
            # Normalize: train_it -> train, val_it -> val, test_it -> test
            canonical = split_name.replace(f"_{lang}", "")
            result[canonical] = split_ds
            logger.info(
                "%s: %s -> %s (%d rows)",
                spec.short_name, split_name, canonical, len(split_ds),
            )

    # Sample English splits
    if spec.en_sample_ratio and spec.en_sample_ratio > 0:
        for split_name, split_ds in ds.items():
            if "_en" in split_name:
                canonical = split_name.replace("_en", "")
                sample_n = int(len(split_ds) * spec.en_sample_ratio)
                en_sampled = split_ds.shuffle(seed=42).select(range(sample_n))
                logger.info(
                    "%s: sampled %d/%d English rows from %s",
                    spec.short_name, sample_n, len(split_ds), split_name,
                )
                if canonical in result:
                    result[canonical] = concatenate_datasets([result[canonical], en_sampled])
                else:
                    result[canonical] = en_sampled

    if not result:
        logger.warning("%s: no splits matched lang=%s, returning all", spec.short_name, lang)
        return ds

    return DatasetDict(result)


def _filter_by_column(
    ds: Dataset | DatasetDict,
    spec: DatasetSpec,
) -> Dataset | DatasetDict:
    """Filter dataset rows by a language column value."""

    def _filter_split(split: Dataset) -> Dataset:
        lang_col = None
        for candidate in ("lang", "language", "Language"):
            if candidate in split.column_names:
                lang_col = candidate
                break

        if lang_col is None:
            logger.warning(
                "No language column found in %s (columns: %s), returning unfiltered",
                spec.short_name, split.column_names,
            )
            return split

        target = split.filter(lambda row: row[lang_col] == spec.lang_filter)
        logger.info("%s: %d rows for lang=%s", spec.short_name, len(target), spec.lang_filter)

        if spec.en_sample_ratio and spec.en_sample_ratio > 0:
            en_split = split.filter(lambda row: row[lang_col] == "en")
            if len(en_split) > 0:
                sample_n = int(len(en_split) * spec.en_sample_ratio)
                en_sampled = en_split.shuffle(seed=42).select(range(sample_n))
                logger.info(
                    "%s: sampled %d/%d English rows (%.0f%%)",
                    spec.short_name, len(en_sampled), len(en_split),
                    spec.en_sample_ratio * 100,
                )
                target = concatenate_datasets([target, en_sampled])

        return target

    if isinstance(ds, DatasetDict):
        return DatasetDict({name: _filter_split(split) for name, split in ds.items()})
    return _filter_split(ds)


def _apply_language_filter(
    ds: Dataset | DatasetDict,
    spec: DatasetSpec,
) -> Dataset | DatasetDict:
    """Apply language filtering based on the strategy specified in the spec."""
    if spec.lang_filter is None or spec.lang_strategy is None:
        return ds

    if spec.lang_strategy == "split_name" and isinstance(ds, DatasetDict):
        return _filter_by_split_name(ds, spec)
    else:
        return _filter_by_column(ds, spec)


def download_dataset(spec: DatasetSpec, output_dir: Path) -> None:
    """Download a single dataset and save as Parquet."""
    dest = output_dir / spec.short_name
    dest.mkdir(parents=True, exist_ok=True)

    logger.info("Loading %s from %s ...", spec.short_name, spec.hf_name)
    try:
        ds = load_dataset(spec.hf_name)
    except Exception:
        # Retry with verification disabled (handles stale metadata on HF)
        logger.warning("Standard load failed for %s, retrying without verification", spec.hf_name)
        try:
            ds = load_dataset(spec.hf_name, verification_mode="no_checks")
        except Exception:
            logger.exception("Failed to load %s", spec.hf_name)
            return

    ds = _apply_language_filter(ds, spec)

    if isinstance(ds, DatasetDict):
        for split_name, split_ds in ds.items():
            out_path = dest / f"{split_name}.parquet"
            split_ds.to_parquet(str(out_path))
            logger.info(
                "  %s/%s: %d rows, %d columns -> %s",
                spec.short_name, split_name, len(split_ds),
                len(split_ds.column_names), out_path,
            )
    else:
        out_path = dest / "data.parquet"
        ds.to_parquet(str(out_path))
        logger.info(
            "  %s: %d rows, %d columns -> %s",
            spec.short_name, len(ds), len(ds.column_names), out_path,
        )

    # Print statistics
    if isinstance(ds, DatasetDict):
        total = sum(len(s) for s in ds.values())
        splits = list(ds.keys())
        cols = ds[splits[0]].column_names if splits else []
    else:
        total = len(ds)
        splits = ["data"]
        cols = ds.column_names

    print(f"\n{'=' * 60}")
    print(f"Dataset: {spec.short_name}")
    print(f"  Total rows:  {total:,}")
    print(f"  Columns:     {cols}")
    print(f"  Splits:      {splits}")
    print(f"  Saved to:    {dest}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download HuggingFace datasets for Privacy Shield training."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="Output directory for raw datasets (default: data/raw)",
    )
    parser.add_argument(
        "--datasets",
        type=str,
        default=None,
        help="Comma-separated list of dataset short names to download (default: all)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.datasets:
        names = [n.strip() for n in args.datasets.split(",")]
        specs = []
        for name in names:
            if name not in DATASET_SPECS:
                logger.error("Unknown dataset: %s (available: %s)", name, list(DATASET_SPECS.keys()))
                continue
            specs.append(DATASET_SPECS[name])
    else:
        specs = list(DATASET_SPECS.values())

    args.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading %d dataset(s) to %s", len(specs), args.output_dir)
    for spec in specs:
        download_dataset(spec, args.output_dir)

    logger.info("All downloads complete.")


if __name__ == "__main__":
    main()
