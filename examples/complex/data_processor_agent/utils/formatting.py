"""Data formatting and display utilities for the data processor agent."""

import pandas as pd
from typing import Dict, Any, List
from datetime import datetime, timedelta
import json


def format_size(size_bytes: int) -> str:
    """Format byte size in human-readable format."""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


class DataFormatter:
    """Formats data for display and export."""
    
    @staticmethod
    def format_summary(df: pd.DataFrame) -> Dict[str, Any]:
        """Generate a formatted summary of DataFrame statistics."""
        summary = {
            "shape": {
                "rows": len(df),
                "columns": len(df.columns)
            },
            "memory_usage": format_size(df.memory_usage(deep=True).sum()),
            "data_types": df.dtypes.value_counts().to_dict(),
            "missing_values": {
                "total": df.isnull().sum().sum(),
                "by_column": df.isnull().sum().to_dict()
            },
            "numeric_summary": {},
            "categorical_summary": {}
        }
        
        # Numeric columns summary
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            numeric_stats = df[numeric_cols].describe()
            summary["numeric_summary"] = {
                col: {
                    "mean": round(numeric_stats.loc['mean', col], 2),
                    "std": round(numeric_stats.loc['std', col], 2),
                    "min": numeric_stats.loc['min', col],
                    "max": numeric_stats.loc['max', col],
                    "median": round(numeric_stats.loc['50%', col], 2)
                }
                for col in numeric_cols
            }
        
        # Categorical columns summary
        categorical_cols = df.select_dtypes(include=['object']).columns
        for col in categorical_cols:
            unique_count = df[col].nunique()
            most_frequent = df[col].mode().iloc[0] if not df[col].mode().empty else None
            summary["categorical_summary"][col] = {
                "unique_values": unique_count,
                "most_frequent": most_frequent,
                "unique_ratio": round(unique_count / len(df), 3)
            }
        
        return summary
    
    @staticmethod
    def format_validation_report(validation_result) -> Dict[str, Any]:
        """Format validation result for display."""
        from .validation import ValidationSeverity
        
        issues_by_severity = {}
        for severity in ValidationSeverity:
            issues_by_severity[severity.value] = [
                {
                    "message": issue.message,
                    "column": issue.column,
                    "row": issue.row,
                    "value": str(issue.value) if issue.value is not None else None
                }
                for issue in validation_result.issues
                if issue.severity == severity
            ]
        
        return {
            "is_valid": validation_result.is_valid,
            "summary": {
                "total_issues": len(validation_result.issues),
                "errors": validation_result.error_count,
                "warnings": validation_result.warning_count,
                "data_shape": {
                    "rows": validation_result.total_rows,
                    "columns": validation_result.total_columns
                }
            },
            "issues": issues_by_severity
        }
    
    @staticmethod
    def format_processing_result(
        original_shape: tuple,
        processed_shape: tuple,
        processing_time: float,
        operations: List[str]
    ) -> Dict[str, Any]:
        """Format data processing result for display."""
        return {
            "processing_summary": {
                "original_shape": {"rows": original_shape[0], "columns": original_shape[1]},
                "processed_shape": {"rows": processed_shape[0], "columns": processed_shape[1]},
                "rows_changed": processed_shape[0] - original_shape[0],
                "columns_changed": processed_shape[1] - original_shape[1],
                "processing_time": format_duration(processing_time),
                "operations_applied": operations
            },
            "efficiency": {
                "rows_per_second": int(processed_shape[0] / processing_time) if processing_time > 0 else 0,
                "data_reduction_percent": round(
                    (1 - (processed_shape[0] * processed_shape[1]) / (original_shape[0] * original_shape[1])) * 100, 2
                ) if original_shape[0] * original_shape[1] > 0 else 0
            }
        }
    
    @staticmethod
    def to_display_table(df: pd.DataFrame, max_rows: int = 10, max_cols: int = 10) -> str:
        """Convert DataFrame to formatted display table."""
        display_df = df.iloc[:max_rows, :max_cols].copy()
        
        # Truncate long strings
        for col in display_df.select_dtypes(include=['object']).columns:
            display_df[col] = display_df[col].astype(str).apply(
                lambda x: x[:50] + "..." if len(x) > 50 else x
            )
        
        return display_df.to_string(index=True, max_cols=max_cols)
    
    @staticmethod
    def export_metadata(df: pd.DataFrame, processing_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate metadata for export operations."""
        return {
            "export_timestamp": datetime.now().isoformat(),
            "data_info": {
                "shape": df.shape,
                "columns": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "memory_usage": format_size(df.memory_usage(deep=True).sum())
            },
            "processing_info": processing_info,
            "agent_info": {
                "name": "data-processor",
                "version": "1.0.0"
            }
        }