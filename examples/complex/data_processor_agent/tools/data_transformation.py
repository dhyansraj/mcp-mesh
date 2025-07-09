"""Data transformation and processing tools."""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Union
import time

try:
    from ..utils.formatting import DataFormatter
    from ..config.settings import get_settings
except ImportError:
    from utils.formatting import DataFormatter
    from config.settings import get_settings


class DataTransformer:
    """Handles data transformation and processing operations."""
    
    def __init__(self):
        self.settings = get_settings()
        self.formatter = DataFormatter()
    
    def filter_data(
        self, 
        df: pd.DataFrame, 
        conditions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Filter DataFrame based on conditions."""
        start_time = time.time()
        original_shape = df.shape
        
        filtered_df = df.copy()
        applied_operations = []
        
        for condition in conditions:
            column = condition.get('column')
            operator = condition.get('operator')
            value = condition.get('value')
            
            if not all([column, operator, value is not None]):
                continue
                
            if column not in filtered_df.columns:
                continue
            
            try:
                if operator == 'eq':
                    filtered_df = filtered_df[filtered_df[column] == value]
                elif operator == 'ne':
                    filtered_df = filtered_df[filtered_df[column] != value]
                elif operator == 'gt':
                    filtered_df = filtered_df[filtered_df[column] > value]
                elif operator == 'gte':
                    filtered_df = filtered_df[filtered_df[column] >= value]
                elif operator == 'lt':
                    filtered_df = filtered_df[filtered_df[column] < value]
                elif operator == 'lte':
                    filtered_df = filtered_df[filtered_df[column] <= value]
                elif operator == 'contains':
                    filtered_df = filtered_df[filtered_df[column].astype(str).str.contains(str(value), na=False)]
                elif operator == 'startswith':
                    filtered_df = filtered_df[filtered_df[column].astype(str).str.startswith(str(value), na=False)]
                elif operator == 'endswith':
                    filtered_df = filtered_df[filtered_df[column].astype(str).str.endswith(str(value), na=False)]
                elif operator == 'in':
                    if isinstance(value, list):
                        filtered_df = filtered_df[filtered_df[column].isin(value)]
                elif operator == 'notnull':
                    filtered_df = filtered_df[filtered_df[column].notnull()]
                elif operator == 'isnull':
                    filtered_df = filtered_df[filtered_df[column].isnull()]
                
                applied_operations.append(f"Filter {column} {operator} {value}")
                
            except Exception as e:
                # Skip invalid conditions
                continue
        
        processing_time = time.time() - start_time
        
        return {
            "dataframe": filtered_df,
            "result": self.formatter.format_processing_result(
                original_shape=original_shape,
                processed_shape=filtered_df.shape,
                processing_time=processing_time,
                operations=applied_operations
            )
        }
    
    def sort_data(
        self, 
        df: pd.DataFrame, 
        sort_columns: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Sort DataFrame by specified columns."""
        start_time = time.time()
        original_shape = df.shape
        
        columns = []
        ascending = []
        applied_operations = []
        
        for sort_spec in sort_columns:
            column = sort_spec.get('column')
            direction = sort_spec.get('direction', 'asc')
            
            if column and column in df.columns:
                columns.append(column)
                ascending.append(direction.lower() == 'asc')
                applied_operations.append(f"Sort by {column} ({direction})")
        
        if not columns:
            return {
                "dataframe": df,
                "result": {"message": "No valid sort columns specified"}
            }
        
        sorted_df = df.sort_values(by=columns, ascending=ascending)
        processing_time = time.time() - start_time
        
        return {
            "dataframe": sorted_df,
            "result": self.formatter.format_processing_result(
                original_shape=original_shape,
                processed_shape=sorted_df.shape,
                processing_time=processing_time,
                operations=applied_operations
            )
        }
    
    def aggregate_data(
        self, 
        df: pd.DataFrame, 
        group_by: List[str], 
        aggregations: Dict[str, List[str]]
    ) -> Dict[str, Any]:
        """Group and aggregate data."""
        start_time = time.time()
        original_shape = df.shape
        
        # Validate group_by columns
        valid_group_cols = [col for col in group_by if col in df.columns]
        if not valid_group_cols:
            raise ValueError("No valid grouping columns specified")
        
        # Validate aggregation columns and functions
        valid_aggs = {}
        for col, funcs in aggregations.items():
            if col in df.columns:
                valid_funcs = []
                for func in funcs:
                    if func in ['sum', 'mean', 'count', 'min', 'max', 'std', 'var', 'median']:
                        valid_funcs.append(func)
                if valid_funcs:
                    valid_aggs[col] = valid_funcs
        
        if not valid_aggs:
            raise ValueError("No valid aggregation functions specified")
        
        # Perform aggregation
        grouped = df.groupby(valid_group_cols)
        agg_result = grouped.agg(valid_aggs)
        
        # Flatten column names
        if isinstance(agg_result.columns, pd.MultiIndex):
            agg_result.columns = ['_'.join(col).strip() for col in agg_result.columns.values]
        
        agg_df = agg_result.reset_index()
        
        processing_time = time.time() - start_time
        applied_operations = [
            f"Group by: {', '.join(valid_group_cols)}",
            f"Aggregate: {valid_aggs}"
        ]
        
        return {
            "dataframe": agg_df,
            "result": self.formatter.format_processing_result(
                original_shape=original_shape,
                processed_shape=agg_df.shape,
                processing_time=processing_time,
                operations=applied_operations
            )
        }
    
    def clean_data(self, df: pd.DataFrame, operations: List[str]) -> Dict[str, Any]:
        """Clean data using specified operations."""
        start_time = time.time()
        original_shape = df.shape
        
        cleaned_df = df.copy()
        applied_operations = []
        
        for operation in operations:
            if operation == 'drop_duplicates':
                before_count = len(cleaned_df)
                cleaned_df = cleaned_df.drop_duplicates()
                after_count = len(cleaned_df)
                applied_operations.append(f"Removed {before_count - after_count} duplicate rows")
            
            elif operation == 'drop_empty_rows':
                before_count = len(cleaned_df)
                cleaned_df = cleaned_df.dropna(how='all')
                after_count = len(cleaned_df)
                applied_operations.append(f"Removed {before_count - after_count} empty rows")
            
            elif operation == 'drop_empty_columns':
                before_count = len(cleaned_df.columns)
                cleaned_df = cleaned_df.dropna(axis=1, how='all')
                after_count = len(cleaned_df.columns)
                applied_operations.append(f"Removed {before_count - after_count} empty columns")
            
            elif operation == 'trim_strings':
                string_cols = cleaned_df.select_dtypes(include=['object']).columns
                for col in string_cols:
                    cleaned_df[col] = cleaned_df[col].astype(str).str.strip()
                applied_operations.append(f"Trimmed whitespace from {len(string_cols)} string columns")
            
            elif operation == 'standardize_case':
                string_cols = cleaned_df.select_dtypes(include=['object']).columns
                for col in string_cols:
                    cleaned_df[col] = cleaned_df[col].astype(str).str.lower()
                applied_operations.append(f"Standardized case for {len(string_cols)} string columns")
            
            elif operation == 'fill_numeric_nulls':
                numeric_cols = cleaned_df.select_dtypes(include=[np.number]).columns
                for col in numeric_cols:
                    mean_val = cleaned_df[col].mean()
                    null_count = cleaned_df[col].isnull().sum()
                    cleaned_df[col] = cleaned_df[col].fillna(mean_val)
                    if null_count > 0:
                        applied_operations.append(f"Filled {null_count} null values in {col} with mean")
        
        processing_time = time.time() - start_time
        
        return {
            "dataframe": cleaned_df,
            "result": self.formatter.format_processing_result(
                original_shape=original_shape,
                processed_shape=cleaned_df.shape,
                processing_time=processing_time,
                operations=applied_operations
            )
        }
    
    def select_columns(self, df: pd.DataFrame, columns: List[str]) -> Dict[str, Any]:
        """Select specific columns from DataFrame."""
        start_time = time.time()
        original_shape = df.shape
        
        # Filter to existing columns
        valid_columns = [col for col in columns if col in df.columns]
        missing_columns = [col for col in columns if col not in df.columns]
        
        if not valid_columns:
            raise ValueError("No valid columns specified")
        
        selected_df = df[valid_columns].copy()
        processing_time = time.time() - start_time
        
        applied_operations = [f"Selected columns: {valid_columns}"]
        if missing_columns:
            applied_operations.append(f"Missing columns ignored: {missing_columns}")
        
        return {
            "dataframe": selected_df,
            "result": self.formatter.format_processing_result(
                original_shape=original_shape,
                processed_shape=selected_df.shape,
                processing_time=processing_time,
                operations=applied_operations
            )
        }
    
    def add_calculated_column(
        self, 
        df: pd.DataFrame, 
        column_name: str, 
        expression: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """Add a calculated column based on an expression."""
        start_time = time.time()
        original_shape = df.shape
        
        result_df = df.copy()
        
        try:
            # Simple expression evaluation - support basic operations
            # This is a simplified version - in production, use safer evaluation
            if '+' in expression:
                parts = expression.split('+')
                if len(parts) == 2 and all(part.strip() in df.columns for part in parts):
                    col1, col2 = parts[0].strip(), parts[1].strip()
                    result_df[column_name] = df[col1] + df[col2]
                    operation_desc = f"Added column '{column_name}' = {col1} + {col2}"
                else:
                    raise ValueError("Invalid addition expression")
            
            elif '-' in expression:
                parts = expression.split('-')
                if len(parts) == 2 and all(part.strip() in df.columns for part in parts):
                    col1, col2 = parts[0].strip(), parts[1].strip()
                    result_df[column_name] = df[col1] - df[col2]
                    operation_desc = f"Added column '{column_name}' = {col1} - {col2}"
                else:
                    raise ValueError("Invalid subtraction expression")
            
            elif '*' in expression:
                parts = expression.split('*')
                if len(parts) == 2 and all(part.strip() in df.columns for part in parts):
                    col1, col2 = parts[0].strip(), parts[1].strip()
                    result_df[column_name] = df[col1] * df[col2]
                    operation_desc = f"Added column '{column_name}' = {col1} * {col2}"
                else:
                    raise ValueError("Invalid multiplication expression")
            
            elif '/' in expression:
                parts = expression.split('/')
                if len(parts) == 2 and all(part.strip() in df.columns for part in parts):
                    col1, col2 = parts[0].strip(), parts[1].strip()
                    result_df[column_name] = df[col1] / df[col2]
                    operation_desc = f"Added column '{column_name}' = {col1} / {col2}"
                else:
                    raise ValueError("Invalid division expression")
            
            else:
                raise ValueError(f"Unsupported expression: {expression}")
            
            processing_time = time.time() - start_time
            
            return {
                "dataframe": result_df,
                "result": self.formatter.format_processing_result(
                    original_shape=original_shape,
                    processed_shape=result_df.shape,
                    processing_time=processing_time,
                    operations=[operation_desc + (f" - {description}" if description else "")]
                )
            }
            
        except Exception as e:
            raise ValueError(f"Failed to add calculated column: {str(e)}")