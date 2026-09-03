"""Synthetic data generation and ground-truth builder package."""

from src.generator.data_generator import (
    SyntheticFinanceDataset,
    generate_all_synthetic_data,
)

__all__ = [
    "SyntheticFinanceDataset",
    "generate_all_synthetic_data",
]
