"""Statistical analysis tools for data processing."""

import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

try:
    from ..config.settings import get_settings
    from ..utils.formatting import DataFormatter
except ImportError:
    from config.settings import get_settings
    from utils.formatting import DataFormatter


class StatisticalAnalyzer:
    """Provides statistical analysis capabilities for data."""

    def __init__(self):
        self.settings = get_settings()
        self.formatter = DataFormatter()

    def descriptive_statistics(
        self, df: pd.DataFrame, columns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generate descriptive statistics for numeric columns."""
        start_time = time.time()

        # Select columns to analyze
        if columns:
            numeric_cols = [
                col
                for col in columns
                if col in df.columns and df[col].dtype in ["int64", "float64"]
            ]
        else:
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        if not numeric_cols:
            return {
                "error": "No numeric columns found for analysis",
                "available_columns": list(df.columns),
                "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
            }

        results = {}

        for col in numeric_cols:
            series = df[col].dropna()

            if len(series) == 0:
                results[col] = {"error": "No non-null values found"}
                continue

            # Basic statistics
            stats_dict = {
                "count": len(series),
                "mean": float(series.mean()),
                "median": float(series.median()),
                "mode": (
                    float(series.mode().iloc[0]) if not series.mode().empty else None
                ),
                "std": float(series.std()),
                "variance": float(series.var()),
                "min": float(series.min()),
                "max": float(series.max()),
                "range": float(series.max() - series.min()),
                "skewness": float(series.skew()),
                "kurtosis": float(series.kurtosis()),
                "q1": float(series.quantile(0.25)),
                "q3": float(series.quantile(0.75)),
                "iqr": float(series.quantile(0.75) - series.quantile(0.25)),
            }

            # Additional statistics
            stats_dict.update(
                {
                    "coefficient_of_variation": (
                        stats_dict["std"] / stats_dict["mean"]
                        if stats_dict["mean"] != 0
                        else None
                    ),
                    "null_count": int(df[col].isnull().sum()),
                    "null_percentage": float(df[col].isnull().sum() / len(df) * 100),
                    "outliers_iqr": self._count_outliers_iqr(series),
                    "outliers_zscore": self._count_outliers_zscore(series),
                }
            )

            results[col] = stats_dict

        processing_time = time.time() - start_time

        return {
            "statistics": results,
            "metadata": {
                "analyzed_columns": numeric_cols,
                "total_columns": len(df.columns),
                "total_rows": len(df),
                "processing_time_seconds": round(processing_time, 3),
            },
        }

    def correlation_analysis(
        self, df: pd.DataFrame, method: str = "pearson"
    ) -> Dict[str, Any]:
        """Compute correlation matrix for numeric columns."""
        start_time = time.time()

        numeric_df = df.select_dtypes(include=[np.number])

        if numeric_df.shape[1] < 2:
            return {
                "error": "Need at least 2 numeric columns for correlation analysis",
                "numeric_columns_found": list(numeric_df.columns),
            }

        # Compute correlation matrix
        if method.lower() == "pearson":
            corr_matrix = numeric_df.corr(method="pearson")
        elif method.lower() == "spearman":
            corr_matrix = numeric_df.corr(method="spearman")
        elif method.lower() == "kendall":
            corr_matrix = numeric_df.corr(method="kendall")
        else:
            return {
                "error": f"Unsupported correlation method: {method}. Use 'pearson', 'spearman', or 'kendall'"
            }

        # Find strongest correlations
        strong_correlations = []
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                col1, col2 = corr_matrix.columns[i], corr_matrix.columns[j]
                corr_value = corr_matrix.iloc[i, j]

                if abs(corr_value) > 0.5:  # Strong correlation threshold
                    strong_correlations.append(
                        {
                            "column1": col1,
                            "column2": col2,
                            "correlation": round(float(corr_value), 4),
                            "strength": self._correlation_strength(abs(corr_value)),
                        }
                    )

        # Sort by absolute correlation value
        strong_correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)

        processing_time = time.time() - start_time

        return {
            "correlation_matrix": corr_matrix.round(4).to_dict(),
            "strong_correlations": strong_correlations,
            "method": method,
            "metadata": {
                "columns_analyzed": list(numeric_df.columns),
                "matrix_size": corr_matrix.shape,
                "processing_time_seconds": round(processing_time, 3),
            },
        }

    def distribution_analysis(self, df: pd.DataFrame, column: str) -> Dict[str, Any]:
        """Analyze the distribution of a specific column."""
        if column not in df.columns:
            return {"error": f"Column '{column}' not found in DataFrame"}

        series = df[column].dropna()

        if len(series) == 0:
            return {"error": f"No non-null values found in column '{column}'"}

        start_time = time.time()

        # Basic distribution info
        result = {
            "column": column,
            "data_type": str(df[column].dtype),
            "sample_size": len(series),
            "null_count": int(df[column].isnull().sum()),
        }

        if df[column].dtype in ["int64", "float64"]:
            # Numeric distribution analysis
            result.update(self._analyze_numeric_distribution(series))
        else:
            # Categorical distribution analysis
            result.update(self._analyze_categorical_distribution(series))

        processing_time = time.time() - start_time
        result["processing_time_seconds"] = round(processing_time, 3)

        return result

    def outlier_detection(
        self, df: pd.DataFrame, columns: Optional[List[str]] = None, method: str = "iqr"
    ) -> Dict[str, Any]:
        """Detect outliers in numeric columns."""
        start_time = time.time()

        if columns:
            numeric_cols = [
                col
                for col in columns
                if col in df.columns and df[col].dtype in ["int64", "float64"]
            ]
        else:
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

        if not numeric_cols:
            return {"error": "No numeric columns found for outlier detection"}

        outlier_results = {}

        for col in numeric_cols:
            series = df[col].dropna()

            if method.lower() == "iqr":
                outliers = self._detect_outliers_iqr(series)
            elif method.lower() == "zscore":
                outliers = self._detect_outliers_zscore(series)
            else:
                outlier_results[col] = {"error": f"Unsupported method: {method}"}
                continue

            outlier_results[col] = {
                "total_values": len(series),
                "outlier_count": len(outliers),
                "outlier_percentage": round(len(outliers) / len(series) * 100, 2),
                "outlier_indices": outliers.tolist(),
                "outlier_values": series.iloc[outliers].tolist(),
                "method": method,
            }

        processing_time = time.time() - start_time

        return {
            "outliers": outlier_results,
            "metadata": {
                "method": method,
                "columns_analyzed": numeric_cols,
                "processing_time_seconds": round(processing_time, 3),
            },
        }

    def _analyze_numeric_distribution(self, series: pd.Series) -> Dict[str, Any]:
        """Analyze numeric distribution."""
        # Histogram bins
        hist, bins = np.histogram(series, bins=min(50, len(series.unique())))

        # Normality tests
        shapiro_stat, shapiro_p = (
            stats.shapiro(series[:5000]) if len(series) <= 5000 else (None, None)
        )

        return {
            "distribution_type": "numeric",
            "histogram": {"bins": bins.tolist(), "counts": hist.tolist()},
            "percentiles": {
                f"p{p}": float(series.quantile(p / 100))
                for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]
            },
            "normality_test": (
                {
                    "shapiro_wilk_statistic": (
                        float(shapiro_stat) if shapiro_stat else None
                    ),
                    "shapiro_wilk_p_value": float(shapiro_p) if shapiro_p else None,
                    "is_normal": bool(shapiro_p > 0.05) if shapiro_p else None,
                }
                if shapiro_stat
                else None
            ),
        }

    def _analyze_categorical_distribution(self, series: pd.Series) -> Dict[str, Any]:
        """Analyze categorical distribution."""
        value_counts = series.value_counts()

        return {
            "distribution_type": "categorical",
            "unique_values": int(series.nunique()),
            "most_frequent": {
                "value": str(value_counts.index[0]),
                "count": int(value_counts.iloc[0]),
                "percentage": round(value_counts.iloc[0] / len(series) * 100, 2),
            },
            "least_frequent": {
                "value": str(value_counts.index[-1]),
                "count": int(value_counts.iloc[-1]),
                "percentage": round(value_counts.iloc[-1] / len(series) * 100, 2),
            },
            "value_counts": value_counts.head(20).to_dict(),  # Top 20 values
            "entropy": float(
                -np.sum(
                    (value_counts / len(series)) * np.log2(value_counts / len(series))
                )
            ),
        }

    def _count_outliers_iqr(self, series: pd.Series) -> int:
        """Count outliers using IQR method."""
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        return int(((series < lower_bound) | (series > upper_bound)).sum())

    def _count_outliers_zscore(self, series: pd.Series, threshold: float = 3.0) -> int:
        """Count outliers using Z-score method."""
        z_scores = np.abs(stats.zscore(series))
        return int((z_scores > threshold).sum())

    def _detect_outliers_iqr(self, series: pd.Series) -> np.ndarray:
        """Detect outlier indices using IQR method."""
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        return np.where((series < lower_bound) | (series > upper_bound))[0]

    def _detect_outliers_zscore(
        self, series: pd.Series, threshold: float = 3.0
    ) -> np.ndarray:
        """Detect outlier indices using Z-score method."""
        z_scores = np.abs(stats.zscore(series))
        return np.where(z_scores > threshold)[0]

    def _correlation_strength(self, abs_corr: float) -> str:
        """Classify correlation strength."""
        if abs_corr >= 0.9:
            return "very strong"
        elif abs_corr >= 0.7:
            return "strong"
        elif abs_corr >= 0.5:
            return "moderate"
        elif abs_corr >= 0.3:
            return "weak"
        else:
            return "very weak"
