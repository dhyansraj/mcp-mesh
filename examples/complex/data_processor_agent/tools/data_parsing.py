"""Data parsing tools for various file formats."""

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

import pandas as pd

try:
    from ..config.settings import get_settings
    from ..utils.formatting import format_size
    from ..utils.validation import DataValidator, ValidationResult
except ImportError:
    from config.settings import get_settings
    from utils.formatting import format_size
    from utils.validation import DataValidator, ValidationResult


class DataParser:
    """Handles parsing of various data formats into pandas DataFrames."""

    def __init__(self):
        self.settings = get_settings()
        self.validator = DataValidator(
            max_file_size_mb=self.settings.processing.max_file_size_mb,
            max_rows=self.settings.processing.max_rows,
        )
        self.supported_formats = [".csv", ".json", ".xlsx", ".parquet", ".tsv"]

    def parse_file(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """Parse a data file and return DataFrame with validation results."""
        file_path = Path(file_path)

        # Validate file exists
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Validate file size
        size_validation = self.validator.validate_file_size(str(file_path))
        if not size_validation.is_valid:
            raise ValueError(
                f"File validation failed: {size_validation.issues[0].message}"
            )

        # Determine file format
        file_extension = file_path.suffix.lower()
        if file_extension not in self.supported_formats:
            raise ValueError(
                f"Unsupported file format: {file_extension}. Supported: {self.supported_formats}"
            )

        # Parse based on format
        try:
            if file_extension == ".csv":
                df = self._parse_csv(file_path, **kwargs)
            elif file_extension == ".json":
                df = self._parse_json(file_path, **kwargs)
            elif file_extension == ".xlsx":
                df = self._parse_excel(file_path, **kwargs)
            elif file_extension == ".parquet":
                df = self._parse_parquet(file_path, **kwargs)
            elif file_extension == ".tsv":
                df = self._parse_tsv(file_path, **kwargs)
            else:
                raise ValueError(f"Parser not implemented for: {file_extension}")

            # Validate parsed data
            validation_result = self.validator.validate_dataframe(df)

            return {
                "dataframe": df,
                "validation": validation_result,
                "metadata": {
                    "file_path": str(file_path),
                    "file_size": format_size(file_path.stat().st_size),
                    "format": file_extension,
                    "shape": df.shape,
                    "columns": list(df.columns),
                    "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                },
            }

        except Exception as e:
            raise ValueError(f"Failed to parse {file_extension} file: {str(e)}")

    def parse_string(self, data: str, format_type: str, **kwargs) -> Dict[str, Any]:
        """Parse data from a string."""
        format_type = format_type.lower()

        if format_type == "csv":
            df = pd.read_csv(io.StringIO(data), **kwargs)
        elif format_type == "json":
            if data.strip().startswith("["):
                # JSON array
                json_data = json.loads(data)
                df = pd.DataFrame(json_data)
            else:
                # JSON lines
                lines = data.strip().split("\n")
                json_data = [json.loads(line) for line in lines if line.strip()]
                df = pd.DataFrame(json_data)
        elif format_type == "tsv":
            df = pd.read_csv(io.StringIO(data), sep="\t", **kwargs)
        else:
            raise ValueError(f"Unsupported string format: {format_type}")

        validation_result = self.validator.validate_dataframe(df)

        return {
            "dataframe": df,
            "validation": validation_result,
            "metadata": {
                "source": "string",
                "format": format_type,
                "data_size": format_size(len(data.encode("utf-8"))),
                "shape": df.shape,
                "columns": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            },
        }

    def _parse_csv(self, file_path: Path, **kwargs) -> pd.DataFrame:
        """Parse CSV file."""
        default_kwargs = {
            "encoding": "utf-8",
            "low_memory": False,
            "nrows": self.settings.processing.max_rows,
        }
        default_kwargs.update(kwargs)

        return pd.read_csv(file_path, **default_kwargs)

    def _parse_json(self, file_path: Path, **kwargs) -> pd.DataFrame:
        """Parse JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return pd.DataFrame(data)
        elif isinstance(data, dict):
            # Try to find the main data array
            if "data" in data:
                return pd.DataFrame(data["data"])
            elif "records" in data:
                return pd.DataFrame(data["records"])
            elif "results" in data:
                return pd.DataFrame(data["results"])
            else:
                # Treat dict as single record
                return pd.DataFrame([data])
        else:
            raise ValueError("JSON must contain array or object with data array")

    def _parse_excel(self, file_path: Path, **kwargs) -> pd.DataFrame:
        """Parse Excel file."""
        default_kwargs = {"nrows": self.settings.processing.max_rows}
        default_kwargs.update(kwargs)

        return pd.read_excel(file_path, **default_kwargs)

    def _parse_parquet(self, file_path: Path, **kwargs) -> pd.DataFrame:
        """Parse Parquet file."""
        return pd.read_parquet(file_path, **kwargs)

    def _parse_tsv(self, file_path: Path, **kwargs) -> pd.DataFrame:
        """Parse TSV file."""
        default_kwargs = {
            "sep": "\t",
            "encoding": "utf-8",
            "low_memory": False,
            "nrows": self.settings.processing.max_rows,
        }
        default_kwargs.update(kwargs)

        return pd.read_csv(file_path, **default_kwargs)

    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """Get information about a file without parsing it."""
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        stat = file_path.stat()

        return {
            "file_path": str(file_path),
            "file_name": file_path.name,
            "file_size": format_size(stat.st_size),
            "file_size_bytes": stat.st_size,
            "format": file_path.suffix.lower(),
            "supported": file_path.suffix.lower() in self.supported_formats,
            "modified_time": stat.st_mtime,
            "can_parse": stat.st_size
            <= self.settings.processing.max_file_size_mb * 1024 * 1024,
        }
