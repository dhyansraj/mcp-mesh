"""Data validation utilities for the data processor agent."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    """Represents a validation issue found in data."""

    severity: ValidationSeverity
    message: str
    column: Optional[str] = None
    row: Optional[int] = None
    value: Optional[Any] = None


@dataclass
class ValidationResult:
    """Result of data validation containing issues and summary."""

    is_valid: bool
    issues: List[ValidationIssue]
    total_rows: int
    total_columns: int

    @property
    def error_count(self) -> int:
        """Count of error-level issues."""
        return len(
            [
                i
                for i in self.issues
                if i.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            ]
        )

    @property
    def warning_count(self) -> int:
        """Count of warning-level issues."""
        return len([i for i in self.issues if i.severity == ValidationSeverity.WARNING])


class ValidationError(Exception):
    """Exception raised when validation fails critically."""

    def __init__(self, message: str, issues: List[ValidationIssue]):
        super().__init__(message)
        self.issues = issues


class DataValidator:
    """Validates data quality and structure."""

    def __init__(self, max_file_size_mb: int = 100, max_rows: int = 100000):
        self.max_file_size_mb = max_file_size_mb
        self.max_rows = max_rows

    def validate_dataframe(
        self, df: pd.DataFrame, schema: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """Validate a pandas DataFrame."""
        issues = []

        # Check size limits
        if len(df) > self.max_rows:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"DataFrame has {len(df)} rows, exceeds limit of {self.max_rows}",
                )
            )

        # Check for empty DataFrame
        if df.empty:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING, message="DataFrame is empty"
                )
            )

        # Check for duplicate columns
        if len(df.columns) != len(set(df.columns)):
            duplicates = [col for col in df.columns if list(df.columns).count(col) > 1]
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"Duplicate columns found: {duplicates}",
                )
            )

        # Check for missing values
        for col in df.columns:
            missing_count = df[col].isnull().sum()
            if missing_count > 0:
                missing_percent = (missing_count / len(df)) * 100
                severity = (
                    ValidationSeverity.WARNING
                    if missing_percent < 50
                    else ValidationSeverity.ERROR
                )
                issues.append(
                    ValidationIssue(
                        severity=severity,
                        message=f"Column '{col}' has {missing_count} missing values ({missing_percent:.1f}%)",
                        column=col,
                    )
                )

        # Validate against schema if provided
        if schema:
            issues.extend(self._validate_schema(df, schema))

        # Check for data type consistency
        issues.extend(self._check_data_types(df))

        is_valid = not any(
            issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            for issue in issues
        )

        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            total_rows=len(df),
            total_columns=len(df.columns),
        )

    def _validate_schema(
        self, df: pd.DataFrame, schema: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Validate DataFrame against a schema definition."""
        issues = []

        # Check required columns
        required_columns = schema.get("required_columns", [])
        missing_columns = set(required_columns) - set(df.columns)
        if missing_columns:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"Missing required columns: {list(missing_columns)}",
                )
            )

        # Check column types
        column_types = schema.get("column_types", {})
        for col, expected_type in column_types.items():
            if col in df.columns:
                actual_type = str(df[col].dtype)
                if not self._is_compatible_type(actual_type, expected_type):
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            message=f"Column '{col}' has type '{actual_type}', expected '{expected_type}'",
                            column=col,
                        )
                    )

        return issues

    def _check_data_types(self, df: pd.DataFrame) -> List[ValidationIssue]:
        """Check for data type consistency issues."""
        issues = []

        for col in df.columns:
            # Check for mixed types in object columns
            if df[col].dtype == "object":
                unique_types = set(
                    type(val).__name__ for val in df[col].dropna().iloc[:1000]
                )
                if len(unique_types) > 1:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            message=f"Column '{col}' contains mixed data types: {list(unique_types)}",
                            column=col,
                        )
                    )

        return issues

    def _is_compatible_type(self, actual: str, expected: str) -> bool:
        """Check if actual data type is compatible with expected type."""
        type_mappings = {
            "int": ["int64", "int32", "int16", "int8"],
            "float": ["float64", "float32", "int64", "int32"],
            "string": ["object"],
            "datetime": ["datetime64[ns]", "object"],
            "bool": ["bool"],
        }

        return actual in type_mappings.get(expected, [expected])

    def validate_file_size(self, file_path: str) -> ValidationResult:
        """Validate file size constraints."""
        import os

        issues = []
        size_mb = os.path.getsize(file_path) / (1024 * 1024)

        if size_mb > self.max_file_size_mb:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message=f"File size {size_mb:.1f}MB exceeds limit of {self.max_file_size_mb}MB",
                )
            )

        return ValidationResult(
            is_valid=len(issues) == 0, issues=issues, total_rows=0, total_columns=0
        )
