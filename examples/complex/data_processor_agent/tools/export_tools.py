"""Data export tools for various formats."""

import pandas as pd
import json
from typing import Dict, Any, Optional
from pathlib import Path
import tempfile
import time

try:
    from ..utils.formatting import DataFormatter
    from ..config.settings import get_settings
except ImportError:
    from utils.formatting import DataFormatter
    from config.settings import get_settings


class DataExporter:
    """Handles exporting data to various formats."""
    
    def __init__(self):
        self.settings = get_settings()
        self.formatter = DataFormatter()
        self.supported_formats = self.settings.export.supported_formats
    
    def export_data(
        self, 
        df: pd.DataFrame, 
        format_type: str, 
        include_metadata: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Export DataFrame to specified format."""
        start_time = time.time()
        
        if format_type.lower() not in self.supported_formats:
            return {
                "error": f"Unsupported format: {format_type}",
                "supported_formats": self.supported_formats
            }
        
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(
                suffix=f'.{format_type.lower()}', 
                delete=False
            ) as temp_file:
                temp_path = temp_file.name
            
            # Export based on format
            if format_type.lower() == 'csv':
                result = self._export_csv(df, temp_path, **kwargs)
            elif format_type.lower() == 'json':
                result = self._export_json(df, temp_path, **kwargs)
            elif format_type.lower() == 'xlsx':
                result = self._export_excel(df, temp_path, **kwargs)
            elif format_type.lower() == 'parquet':
                result = self._export_parquet(df, temp_path, **kwargs)
            else:
                return {"error": f"Export method not implemented for: {format_type}"}
            
            # Get file info
            file_path = Path(temp_path)
            file_size = file_path.stat().st_size
            
            processing_time = time.time() - start_time
            
            export_result = {
                "success": True,
                "file_path": str(file_path),
                "format": format_type.lower(),
                "file_size": self.formatter._format_size(file_size),
                "file_size_bytes": file_size,
                "export_time": round(processing_time, 3),
                "rows_exported": len(df),
                "columns_exported": len(df.columns)
            }
            
            # Add format-specific results
            export_result.update(result)
            
            # Add metadata if requested
            if include_metadata:
                export_result["metadata"] = self.formatter.export_metadata(
                    df=df,
                    processing_info={
                        "export_format": format_type,
                        "export_time": processing_time,
                        "file_size": file_size
                    }
                )
            
            return export_result
            
        except Exception as e:
            return {
                "error": f"Export failed: {str(e)}",
                "format": format_type
            }
    
    def _export_csv(self, df: pd.DataFrame, file_path: str, **kwargs) -> Dict[str, Any]:
        """Export to CSV format."""
        default_kwargs = {
            'index': False,
            'encoding': 'utf-8'
        }
        default_kwargs.update(kwargs)
        
        df.to_csv(file_path, **default_kwargs)
        
        return {
            "format_options": default_kwargs,
            "delimiter": default_kwargs.get('sep', ','),
            "encoding": default_kwargs.get('encoding', 'utf-8')
        }
    
    def _export_json(self, df: pd.DataFrame, file_path: str, **kwargs) -> Dict[str, Any]:
        """Export to JSON format."""
        orient = kwargs.get('orient', 'records')
        indent = kwargs.get('indent', 2)
        
        df.to_json(file_path, orient=orient, indent=indent)
        
        return {
            "format_options": {
                "orient": orient,
                "indent": indent
            },
            "json_structure": orient
        }
    
    def _export_excel(self, df: pd.DataFrame, file_path: str, **kwargs) -> Dict[str, Any]:
        """Export to Excel format."""
        sheet_name = kwargs.get('sheet_name', 'Data')
        index = kwargs.get('index', False)
        
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=index)
            
            # Add summary sheet if requested
            if kwargs.get('include_summary', False):
                summary_df = pd.DataFrame([
                    ['Total Rows', len(df)],
                    ['Total Columns', len(df.columns)],
                    ['Export Date', pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')]
                ], columns=['Metric', 'Value'])
                
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
        
        return {
            "format_options": {
                "sheet_name": sheet_name,
                "index": index,
                "include_summary": kwargs.get('include_summary', False)
            },
            "excel_engine": "openpyxl"
        }
    
    def _export_parquet(self, df: pd.DataFrame, file_path: str, **kwargs) -> Dict[str, Any]:
        """Export to Parquet format."""
        engine = kwargs.get('engine', 'pyarrow')
        compression = kwargs.get('compression', 'snappy')
        
        df.to_parquet(file_path, engine=engine, compression=compression)
        
        return {
            "format_options": {
                "engine": engine,
                "compression": compression
            },
            "parquet_engine": engine
        }
    
    def export_summary_report(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Export a comprehensive summary report as JSON."""
        start_time = time.time()
        
        # Generate comprehensive summary
        summary = self.formatter.format_summary(df)
        
        # Add additional report sections
        report = {
            "report_metadata": {
                "generated_at": pd.Timestamp.now().isoformat(),
                "agent": "data-processor",
                "version": "1.0.0"
            },
            "data_summary": summary,
            "column_details": {}
        }
        
        # Detailed column analysis
        for col in df.columns:
            col_info = {
                "data_type": str(df[col].dtype),
                "non_null_count": int(df[col].count()),
                "null_count": int(df[col].isnull().sum()),
                "null_percentage": round(df[col].isnull().sum() / len(df) * 100, 2),
                "unique_count": int(df[col].nunique()),
                "unique_percentage": round(df[col].nunique() / len(df) * 100, 2)
            }
            
            # Add type-specific info
            if df[col].dtype in ['int64', 'float64']:
                col_info.update({
                    "min": float(df[col].min()) if df[col].count() > 0 else None,
                    "max": float(df[col].max()) if df[col].count() > 0 else None,
                    "mean": float(df[col].mean()) if df[col].count() > 0 else None,
                    "std": float(df[col].std()) if df[col].count() > 0 else None
                })
            else:
                # Categorical info
                if df[col].count() > 0:
                    most_frequent = df[col].mode()
                    col_info.update({
                        "most_frequent_value": str(most_frequent.iloc[0]) if not most_frequent.empty else None,
                        "most_frequent_count": int(df[col].value_counts().iloc[0]) if df[col].count() > 0 else 0
                    })
            
            report["column_details"][col] = col_info
        
        # Create temporary file for report
        with tempfile.NamedTemporaryFile(
            mode='w', 
            suffix='.json', 
            delete=False,
            encoding='utf-8'
        ) as temp_file:
            json.dump(report, temp_file, indent=2, default=str)
            temp_path = temp_file.name
        
        processing_time = time.time() - start_time
        file_size = Path(temp_path).stat().st_size
        
        return {
            "success": True,
            "report_path": temp_path,
            "report_type": "comprehensive_summary",
            "file_size": self.formatter._format_size(file_size),
            "generation_time": round(processing_time, 3),
            "sections": list(report.keys())
        }
    
    def get_export_options(self, format_type: str) -> Dict[str, Any]:
        """Get available export options for a specific format."""
        options = {
            "csv": {
                "sep": "Field separator (default: ',')",
                "index": "Include row indices (default: False)",
                "encoding": "File encoding (default: 'utf-8')",
                "quoting": "Quote style for strings"
            },
            "json": {
                "orient": "JSON structure: 'records', 'index', 'values', 'split', 'table' (default: 'records')",
                "indent": "Indentation for pretty printing (default: 2)"
            },
            "xlsx": {
                "sheet_name": "Excel sheet name (default: 'Data')",
                "index": "Include row indices (default: False)",
                "include_summary": "Add summary sheet (default: False)"
            },
            "parquet": {
                "engine": "Parquet engine: 'pyarrow', 'fastparquet' (default: 'pyarrow')",
                "compression": "Compression: 'snappy', 'gzip', 'brotli' (default: 'snappy')"
            }
        }
        
        if format_type.lower() not in options:
            return {
                "error": f"Unknown format: {format_type}",
                "supported_formats": list(options.keys())
            }
        
        return {
            "format": format_type.lower(),
            "options": options[format_type.lower()],
            "example_usage": f"Use these options as keyword arguments when exporting to {format_type}"
        }