"""
Statistical Analysis Utility Functions

Comprehensive statistical analysis tools for data analysis and research
"""

import pandas as pd
import numpy as np
import scipy
from scipy import stats
from typing import Dict, List, Any, Optional, Union, Tuple
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# 数据读取
# ============================================================================

def read_csv_file(file_path: str, **kwargs) -> pd.DataFrame:
    """
    Read CSV file and return DataFrame
    
    Args:
        file_path: Path to CSV file
        **kwargs: Additional arguments for pd.read_csv
        
    Returns:
        pandas DataFrame
    """
    try:
        df = pd.read_csv(file_path, **kwargs)
        logger.info(f"Successfully read CSV file: {file_path}, shape: {df.shape}")
        return df
    except Exception as e:
        logger.error(f"Error reading CSV file {file_path}: {e}")
        raise

# ============================================================================
# 单变量统计分析函数
# ============================================================================

def calculate_mean(df: pd.DataFrame, column_name: str) -> float:
    """Calculate mean for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate mean.")
    return float(df[column_name].mean())


def calculate_median(df: pd.DataFrame, column_name: str) -> float:
    """Calculate median for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate median.")
    return float(df[column_name].median())


def calculate_std(df: pd.DataFrame, column_name: str) -> float:
    """Calculate standard deviation for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate standard deviation.")
    return float(df[column_name].std())


def calculate_variance(df: pd.DataFrame, column_name: str) -> float:
    """Calculate variance for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate variance.")
    return float(df[column_name].var())


def calculate_min(df: pd.DataFrame, column_name: str) -> float:
    """Calculate minimum value for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate minimum.")
    return float(df[column_name].min())


def calculate_max(df: pd.DataFrame, column_name: str) -> float:
    """Calculate maximum value for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate maximum.")
    return float(df[column_name].max())


def calculate_sum(df: pd.DataFrame, column_name: str) -> float:
    """Calculate sum for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate sum.")
    return float(df[column_name].sum())


def calculate_count(df: pd.DataFrame, column_name: str) -> int:
    """Calculate count of non-null values for a single column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    return int(df[column_name].count())


def calculate_quantile(df: pd.DataFrame, column_name: str, q: float) -> float:
    """Calculate quantile for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate quantile.")
    return float(df[column_name].quantile(q))


def calculate_skewness(df: pd.DataFrame, column_name: str) -> float:
    """Calculate skewness for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate skewness.")
    return float(df[column_name].skew())


def calculate_kurtosis(df: pd.DataFrame, column_name: str) -> float:
    """Calculate kurtosis for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot calculate kurtosis.")
    return float(df[column_name].kurtosis())


def count_missing_values(df: pd.DataFrame, column_name: str) -> int:
    """Count missing values for a single column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    return int(df[column_name].isnull().sum())


def count_unique_values(df: pd.DataFrame, column_name: str) -> int:
    """Count unique values for a single column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    return int(df[column_name].nunique())


def detect_outliers_iqr(df: pd.DataFrame, column_name: str) -> List[int]:
    """Detect outliers using IQR method for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot detect outliers.")
    Q1 = df[column_name].quantile(0.25)
    Q3 = df[column_name].quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    outliers = df[(df[column_name] < lower_bound) | (df[column_name] > upper_bound)]
    return outliers.index.tolist()


def detect_outliers_zscore(df: pd.DataFrame, column_name: str, threshold: float = 3) -> List[int]:
    """Detect outliers using Z-score method for a single numerical column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    if not pd.api.types.is_numeric_dtype(df[column_name]):
        raise ValueError(f"Column '{column_name}' is not numerical. Cannot detect outliers.")
    z_scores = np.abs((df[column_name] - df[column_name].mean()) / df[column_name].std())
    outliers = df[z_scores > threshold]
    return outliers.index.tolist()


def get_unique_values(df: pd.DataFrame, column_name: str) -> List[str]:
    """Get unique values for a single column as a list of strings"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    
    unique_vals = df[column_name].dropna().unique()
    return [str(val) for val in unique_vals]


def get_mode(df: pd.DataFrame, column_name: str) -> Optional[str]:
    """Get mode (most frequent value) for a single column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    
    mode_values = df[column_name].mode()
    if len(mode_values) == 0:
        return None
    return str(mode_values.iloc[0])


def get_percentage_of_unique_values(df: pd.DataFrame, column_name: str) -> Dict[str, float]:
    """Get percentage of each unique value for a single column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    
    value_counts = df[column_name].value_counts()
    total_count = len(df[column_name].dropna())
    percentages = {}
    
    for value, count in value_counts.items():
        percentages[str(value)] = (count / total_count) * 100
    
    return percentages


def calculate_avg_text_length(df: pd.DataFrame, column_name: str) -> float:
    """Calculate average text length for a text column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    
    # Convert to string and calculate length
    text_lengths = df[column_name].astype(str).str.len()
    return float(text_lengths.mean())


def get_min_date(df: pd.DataFrame, column_name: str) -> str:
    """Get minimum date for a date column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    
    try:
        # Try to convert to datetime
        df[column_name] = pd.to_datetime(df[column_name], errors='coerce')
        min_date = df[column_name].min()
        if pd.isna(min_date):
            return "No valid dates found"
        return str(min_date)
    except Exception as e:
        return f"Error processing dates: {str(e)}"


def get_max_date(df: pd.DataFrame, column_name: str) -> str:
    """Get maximum date for a date column"""
    if column_name not in df.columns:
        raise ValueError(f"Column '{column_name}' not found in dataframe")
    
    try:
        # Try to convert to datetime
        df[column_name] = pd.to_datetime(df[column_name], errors='coerce')
        max_date = df[column_name].max()
        if pd.isna(max_date):
            return "No valid dates found"
        return str(max_date)
    except Exception as e:
        return f"Error processing dates: {str(e)}"


# ============================================================================
# 多变量统计分析函数
# ============================================================================

def calculate_correlation_matrix(df: pd.DataFrame, columns: List[str]) -> Dict[str, Dict[str, float]]:
    """Calculate correlation matrix for multiple numerical columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical columns found in the provided list")
    
    corr_matrix = df[numerical_cols].corr()
    return corr_matrix.to_dict()


def calculate_correlation_with_p_values(df: pd.DataFrame, columns: List[str]) -> List[Dict[str, Any]]:
    """Calculate correlation coefficients and p-values for multiple numerical columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if len(numerical_cols) < 2:
        raise ValueError("Need at least 2 numerical columns for correlation analysis")
    
    results = []
    for i, col1 in enumerate(numerical_cols):
        for col2 in numerical_cols[i+1:]:
            # Remove rows with NaN values for this pair
            valid_data = df[[col1, col2]].dropna()
            if len(valid_data) < 3:
                continue
            
            corr_coef, p_value = stats.pearsonr(valid_data[col1], valid_data[col2])
            results.append({
                'variable1': col1,
                'variable2': col2,
                'correlation': float(corr_coef),
                'p_value': float(p_value),
                'sample_size': len(valid_data)
            })
    
    return results


def calculate_group_means_by_category(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, float]]:
    """Calculate group means for multiple value columns by a categorical group column"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    results = {}
    for col in numerical_cols:
        group_means = df.groupby(group_col)[col].mean()
        results[col] = group_means.to_dict()
    
    return results


def calculate_group_stds_by_category(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, float]]:
    """Calculate group standard deviations for multiple value columns by a categorical group column"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    results = {}
    for col in numerical_cols:
        group_stds = df.groupby(group_col)[col].std()
        results[col] = group_stds.to_dict()
    
    return results


def calculate_t_tests_for_multiple_variables(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate t-tests for multiple variables between two groups"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    # Check if group column has exactly 2 unique values
    unique_groups = df[group_col].dropna().unique()
    if len(unique_groups) != 2:
        raise ValueError(f"Group column must have exactly 2 unique values, found {len(unique_groups)}")
    
    results = {}
    for col in numerical_cols:
        group1_data = df[df[group_col] == unique_groups[0]][col].dropna()
        group2_data = df[df[group_col] == unique_groups[1]][col].dropna()
        
        if len(group1_data) == 0 or len(group2_data) == 0:
            results[col] = {
                'error': 'Insufficient data for t-test',
                'group1_count': len(group1_data),
                'group2_count': len(group2_data)
            }
            continue
        
        try:
            t_stat, p_value = stats.ttest_ind(group1_data, group2_data)
            results[col] = {
                't_statistic': float(t_stat),
                'p_value': float(p_value),
                'group1_mean': float(group1_data.mean()),
                'group2_mean': float(group2_data.mean()),
                'group1_std': float(group1_data.std()),
                'group2_std': float(group2_data.std()),
                'group1_count': len(group1_data),
                'group2_count': len(group2_data)
            }
        except Exception as e:
            results[col] = {
                'error': str(e),
                'group1_count': len(group1_data),
                'group2_count': len(group2_data)
            }
    
    return results


def calculate_anova_for_multiple_variables(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate one-way ANOVA for multiple variables across multiple groups"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    results = {}
    for col in numerical_cols:
        # Get data for each group
        groups_data = []
        group_names = []
        
        for group_name in df[group_col].dropna().unique():
            group_data = df[df[group_col] == group_name][col].dropna()
            if len(group_data) > 0:
                groups_data.append(group_data.values)
                group_names.append(str(group_name))
        
        if len(groups_data) < 2:
            results[col] = {
                'error': 'Insufficient groups for ANOVA',
                'group_count': len(groups_data)
            }
            continue
        
        try:
            f_stat, p_value = stats.f_oneway(*groups_data)
            results[col] = {
                'f_statistic': float(f_stat),
                'p_value': float(p_value),
                'group_count': len(groups_data),
                'groups': group_names
            }
        except Exception as e:
            results[col] = {
                'error': str(e),
                'group_count': len(groups_data)
            }
    
    return results


def calculate_chi_square_tests_for_multiple_pairs(df: pd.DataFrame, cat_cols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate chi-square tests for multiple pairs of categorical variables"""
    if not all(col in df.columns for col in cat_cols):
        missing_cols = [col for col in cat_cols if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    results = {}
    for i, col1 in enumerate(cat_cols):
        for col2 in cat_cols[i+1:]:
            key = f"{col1}_vs_{col2}"
            
            # Create contingency table
            contingency_table = pd.crosstab(df[col1], df[col2])
            
            if contingency_table.shape[0] < 2 or contingency_table.shape[1] < 2:
                results[key] = {
                    'error': 'Insufficient categories for chi-square test',
                    'table_shape': contingency_table.shape
                }
                continue
            
            try:
                chi2_stat, p_value, dof, expected = stats.chi2_contingency(contingency_table)
                results[key] = {
                    'chi2_statistic': float(chi2_stat),
                    'p_value': float(p_value),
                    'degrees_of_freedom': int(dof),
                    'contingency_table': contingency_table.to_dict()
                }
            except Exception as e:
                results[key] = {
                    'error': str(e),
                    'contingency_table': contingency_table.to_dict()
                }
    
    return results


def calculate_contingency_tables(df: pd.DataFrame, cat_cols: List[str]) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Calculate contingency tables for multiple pairs of categorical variables"""
    if not all(col in df.columns for col in cat_cols):
        missing_cols = [col for col in cat_cols if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    results = {}
    for i, col1 in enumerate(cat_cols):
        for col2 in cat_cols[i+1:]:
            key = f"{col1}_vs_{col2}"
            contingency_table = pd.crosstab(df[col1], df[col2])
            results[key] = contingency_table.to_dict()
    
    return results


def calculate_covariance_matrix(df: pd.DataFrame, columns: List[str]) -> Dict[str, Dict[str, float]]:
    """Calculate covariance matrix for multiple numerical columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical columns found in the provided list")
    
    cov_matrix = df[numerical_cols].cov()
    return cov_matrix.to_dict()


def calculate_outliers_for_multiple_columns(df: pd.DataFrame, columns: List[str]) -> Dict[str, List[int]]:
    """Detect outliers for multiple numerical columns using IQR method"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical columns found in the provided list")
    
    results = {}
    for col in numerical_cols:
        results[col] = detect_outliers_iqr(df, col)
    
    return results


def calculate_missing_values_summary(df: pd.DataFrame, columns: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate missing values summary for multiple columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    results = {}
    for col in columns:
        missing_count = df[col].isnull().sum()
        total_count = len(df)
        missing_percentage = (missing_count / total_count) * 100
        
        results[col] = {
            'missing_count': int(missing_count),
            'total_count': int(total_count),
            'missing_percentage': float(missing_percentage)
        }
    
    return results


def calculate_mann_whitney_u_tests(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate Mann-Whitney U tests for multiple variables between two groups"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    # Check if group column has exactly 2 unique values
    unique_groups = df[group_col].dropna().unique()
    if len(unique_groups) != 2:
        raise ValueError(f"Group column must have exactly 2 unique values, found {len(unique_groups)}")
    
    results = {}
    for col in numerical_cols:
        group1_data = df[df[group_col] == unique_groups[0]][col].dropna()
        group2_data = df[df[group_col] == unique_groups[1]][col].dropna()
        
        if len(group1_data) == 0 or len(group2_data) == 0:
            results[col] = {
                'error': 'Insufficient data for Mann-Whitney U test',
                'group1_count': len(group1_data),
                'group2_count': len(group2_data)
            }
            continue
        
        try:
            u_stat, p_value = stats.mannwhitneyu(group1_data, group2_data, alternative='two-sided')
            results[col] = {
                'u_statistic': float(u_stat),
                'p_value': float(p_value),
                'group1_median': float(group1_data.median()),
                'group2_median': float(group2_data.median()),
                'group1_count': len(group1_data),
                'group2_count': len(group2_data)
            }
        except Exception as e:
            results[col] = {
                'error': str(e),
                'group1_count': len(group1_data),
                'group2_count': len(group2_data)
            }
    
    return results


def calculate_kruskal_wallis_tests(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate Kruskal-Wallis tests for multiple variables across multiple groups"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    results = {}
    for col in numerical_cols:
        # Get data for each group
        groups_data = []
        group_names = []
        
        for group_name in df[group_col].dropna().unique():
            group_data = df[df[group_col] == group_name][col].dropna()
            if len(group_data) > 0:
                groups_data.append(group_data.values)
                group_names.append(str(group_name))
        
        if len(groups_data) < 2:
            results[col] = {
                'error': 'Insufficient groups for Kruskal-Wallis test',
                'group_count': len(groups_data)
            }
            continue
        
        try:
            h_stat, p_value = stats.kruskal(*groups_data)
            results[col] = {
                'h_statistic': float(h_stat),
                'p_value': float(p_value),
                'group_count': len(groups_data),
                'groups': group_names
            }
        except Exception as e:
            results[col] = {
                'error': str(e),
                'group_count': len(groups_data)
            }
    
    return results


def calculate_normality_tests(df: pd.DataFrame, columns: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate normality tests (Shapiro-Wilk) for multiple numerical columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical columns found in the provided list")
    
    results = {}
    for col in numerical_cols:
        data = df[col].dropna()
        
        if len(data) < 3:
            results[col] = {
                'error': 'Insufficient data for normality test (need at least 3 observations)',
                'sample_size': len(data)
            }
            continue
        
        if len(data) > 5000:
            # Shapiro-Wilk is limited to 5000 observations
            data = data.sample(n=5000, random_state=42)
        
        try:
            w_stat, p_value = stats.shapiro(data)
            results[col] = {
                'w_statistic': float(w_stat),
                'p_value': float(p_value),
                'sample_size': len(data),
                'is_normal': p_value > 0.05
            }
        except Exception as e:
            results[col] = {
                'error': str(e),
                'sample_size': len(data)
            }
    
    return results


def calculate_variance_homogeneity_tests(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Calculate Levene's test for variance homogeneity across groups for multiple variables"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    results = {}
    for col in numerical_cols:
        # Get data for each group
        groups_data = []
        group_names = []
        
        for group_name in df[group_col].dropna().unique():
            group_data = df[df[group_col] == group_name][col].dropna()
            if len(group_data) > 0:
                groups_data.append(group_data.values)
                group_names.append(str(group_name))
        
        if len(groups_data) < 2:
            results[col] = {
                'error': 'Insufficient groups for variance homogeneity test',
                'group_count': len(groups_data)
            }
            continue
        
        try:
            w_stat, p_value = stats.levene(*groups_data)
            results[col] = {
                'w_statistic': float(w_stat),
                'p_value': float(p_value),
                'group_count': len(groups_data),
                'groups': group_names,
                'variances_homogeneous': p_value > 0.05
            }
        except Exception as e:
            results[col] = {
                'error': str(e),
                'group_count': len(groups_data)
            }
    
    return results


def calculate_confidence_intervals(df: pd.DataFrame, columns: List[str], confidence_level: float = 0.95) -> Dict[str, Dict[str, Any]]:
    """Calculate confidence intervals for multiple numerical columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical columns found in the provided list")
    
    results = {}
    for col in numerical_cols:
        data = df[col].dropna()
        
        if len(data) < 2:
            results[col] = {
                'error': 'Insufficient data for confidence interval calculation',
                'sample_size': len(data)
            }
            continue
        
        try:
            mean_val = data.mean()
            std_val = data.std()
            n = len(data)
            
            # Calculate standard error
            se = std_val / np.sqrt(n)
            
            # Calculate t-value for confidence level
            alpha = 1 - confidence_level
            t_value = stats.t.ppf(1 - alpha/2, df=n-1)
            
            # Calculate confidence interval
            margin_of_error = t_value * se
            ci_lower = mean_val - margin_of_error
            ci_upper = mean_val + margin_of_error
            
            results[col] = {
                'mean': float(mean_val),
                'std': float(std_val),
                'sample_size': int(n),
                'confidence_level': float(confidence_level),
                'ci_lower': float(ci_lower),
                'ci_upper': float(ci_upper),
                'margin_of_error': float(margin_of_error)
            }
        except Exception as e:
            results[col] = {
                'error': str(e),
                'sample_size': len(data)
            }
    
    return results


def calculate_spearman_correlations(df: pd.DataFrame, columns: List[str]) -> List[Dict[str, Any]]:
    """Calculate Spearman rank correlations for multiple numerical columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if len(numerical_cols) < 2:
        raise ValueError("Need at least 2 numerical columns for correlation analysis")
    
    results = []
    for i, col1 in enumerate(numerical_cols):
        for col2 in numerical_cols[i+1:]:
            # Remove rows with NaN values for this pair
            valid_data = df[[col1, col2]].dropna()
            if len(valid_data) < 3:
                continue
            
            corr_coef, p_value = stats.spearmanr(valid_data[col1], valid_data[col2])
            results.append({
                'variable1': col1,
                'variable2': col2,
                'spearman_correlation': float(corr_coef),
                'p_value': float(p_value),
                'sample_size': len(valid_data)
            })
    
    return results


def calculate_autocorrelation(df: pd.DataFrame, columns: List[str], max_lag: int = 10) -> Dict[str, List[float]]:
    """Calculate autocorrelation for multiple numerical columns"""
    if not all(col in df.columns for col in columns):
        missing_cols = [col for col in columns if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    # Select only numerical columns
    numerical_cols = [col for col in columns if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical columns found in the provided list")
    
    results = {}
    for col in numerical_cols:
        data = df[col].dropna()
        
        if len(data) < max_lag + 1:
            results[col] = []
            continue
        
        autocorr = []
        for lag in range(1, min(max_lag + 1, len(data))):
            # Calculate autocorrelation for this lag
            corr = np.corrcoef(data[:-lag], data[lag:])[0, 1]
            if not np.isnan(corr):
                autocorr.append(float(corr))
            else:
                autocorr.append(0.0)
        
        results[col] = autocorr
    
    return results


def calculate_conditional_probabilities(df: pd.DataFrame, cat_cols: List[str]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Calculate conditional probabilities for multiple pairs of categorical variables"""
    if not all(col in df.columns for col in cat_cols):
        missing_cols = [col for col in cat_cols if col not in df.columns]
        raise ValueError(f"Columns not found in dataframe: {missing_cols}")
    
    results = {}
    for i, col1 in enumerate(cat_cols):
        for col2 in cat_cols[i+1:]:
            key = f"{col1}_given_{col2}"
            
            # Calculate conditional probabilities
            conditional_probs = {}
            for val2 in df[col2].dropna().unique():
                subset = df[df[col2] == val2]
                if len(subset) > 0:
                    val_counts = subset[col1].value_counts()
                    total_count = len(subset)
                    probs = {}
                    for val1, count in val_counts.items():
                        probs[str(val1)] = count / total_count
                    conditional_probs[str(val2)] = probs
            
            results[key] = conditional_probs
    
    return results


def calculate_effect_sizes_for_multiple_variables(df: pd.DataFrame, group_col: str, value_cols: List[str]) -> Dict[str, Dict[str, float]]:
    """Calculate Cohen's d effect sizes for multiple variables between two groups"""
    if group_col not in df.columns:
        raise ValueError(f"Group column '{group_col}' not found in dataframe")
    
    if not all(col in df.columns for col in value_cols):
        missing_cols = [col for col in value_cols if col not in df.columns]
        raise ValueError(f"Value columns not found in dataframe: {missing_cols}")
    
    # Select only numerical value columns
    numerical_cols = [col for col in value_cols if pd.api.types.is_numeric_dtype(df[col])]
    if not numerical_cols:
        raise ValueError("No numerical value columns found")
    
    # Check if group column has exactly 2 unique values
    unique_groups = df[group_col].dropna().unique()
    if len(unique_groups) != 2:
        raise ValueError(f"Group column must have exactly 2 unique values, found {len(unique_groups)}")
    
    results = {}
    for col in numerical_cols:
        group1_data = df[df[group_col] == unique_groups[0]][col].dropna()
        group2_data = df[df[group_col] == unique_groups[1]][col].dropna()
        
        if len(group1_data) == 0 or len(group2_data) == 0:
            results[col] = {'error': 'Insufficient data for effect size calculation'}
            continue
        
        try:
            # Calculate pooled standard deviation
            n1, n2 = len(group1_data), len(group2_data)
            var1, var2 = group1_data.var(), group2_data.var()
            pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
            
            # Calculate Cohen's d
            mean_diff = group1_data.mean() - group2_data.mean()
            cohens_d = mean_diff / pooled_std
            
            results[col] = {
                'cohens_d': float(cohens_d),
                'group1_mean': float(group1_data.mean()),
                'group2_mean': float(group2_data.mean()),
                'pooled_std': float(pooled_std)
            }
        except Exception as e:
            results[col] = {'error': str(e)}
    
    return results 


from typing import Union, Tuple, Optional

StrOrTupleStr = Union[str, Tuple[str, str]]

def nicely_join(words: list, wrap_with: StrOrTupleStr = '',
                prefix: StrOrTupleStr = '', suffix: StrOrTupleStr = '',
                separator: str = ', ', last_separator: Optional[str] = None, empty_str: str = ''):
    """
    Concatenate a list of words with commas and an 'and' at the end.

    wrap_with: if str: wrap each word with the provided string. if tuple: wrap each word with the first string
    on the left and the second string on the right.

    prefix: if str: add the provided string before the concatenated words. if tuple the first string is for singular
    and the second string is for plural.

    suffix: if str: add the provided string after the concatenated words. if tuple the first string is for singular
    and the second string is for plural.
    """

    def format_noun(noun: StrOrTupleStr, num: int):
        if isinstance(noun, str):
            pass
        elif isinstance(noun, tuple):
            if num_words == 1:
                noun = noun[0]
            else:
                noun = noun[1]
        else:
            raise ValueError(f'prefix must be either str or tuple, not {type(prefix)}')
        if '{}' in noun:
            noun = noun.format(num)
        if '[s]' in noun:
            noun = noun.replace('[s]', 's' if num_words > 1 else '')
        return noun

    # wrap each word with the provided string:
    if isinstance(wrap_with, str):
        words = [wrap_with + str(word) + wrap_with for word in words]
    elif isinstance(wrap_with, tuple):
        words = [wrap_with[0] + str(word) + wrap_with[1] for word in words]
    elif wrap_with is not None:
        raise ValueError(f'wrap_with must be either str or tuple, not {type(wrap_with)}')

    num_words = len(words)

    # concatenate the words:
    last_separator = last_separator or separator
    if num_words == 0:
        return empty_str
    elif num_words == 1:
        s = words[0]
    elif num_words == 2:
        s = words[0] + last_separator + words[1]
    else:
        s = separator.join(words[:-1]) + last_separator + words[-1]

    return format_noun(prefix, num_words) + s + format_noun(suffix, num_words)


class NiceList(list):
    """
    A list that can be printed nicely.
    """
    def __init__(self, *args, wrap_with: StrOrTupleStr = '', prefix: StrOrTupleStr = '',
                 suffix: StrOrTupleStr = '', separator: str = ', ', last_separator: Optional[str] = None,
                 empty_str: str = ''):
        super().__init__(*args)
        self.wrap_with = wrap_with
        self.prefix = prefix
        self.suffix = suffix
        self.separator = separator
        self.last_separator = last_separator
        self.empty_str = empty_str

    def __str__(self):
        return nicely_join(self, self.wrap_with, self.prefix, self.suffix, self.separator, self.last_separator,
                           )

    def __repr__(self):
        return str(self)