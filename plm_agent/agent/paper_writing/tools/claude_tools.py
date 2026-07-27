"""
Claude Tools for Statistical Analysis

This module defines the tools that Claude can use to perform statistical analysis on data.
Each tool corresponds to a function in utils/statistical_analysis.py.

This file belongs to the Tools layer, which is at the same level as Analyzer layer.
"""

from typing import Optional, List, Dict, Any, Union
import pandas as pd
import json

# ============================================================================
# 单变量统计分析工具
# ============================================================================

# 均值计算工具
calculate_mean_tool = {
    "name": "calculate_mean",
    "description": "Calculate mean (average) for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate mean for"
            }
        },
        "required": ["column_name"]
    }
}

# 中位数计算工具
calculate_median_tool = {
    "name": "calculate_median",
    "description": "Calculate median (50th percentile) for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate median for"
            }
        },
        "required": ["column_name"]
    }
}

# 标准差计算工具
calculate_std_tool = {
    "name": "calculate_std",
    "description": "Calculate standard deviation for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate standard deviation for"
            }
        },
        "required": ["column_name"]
    }
}

# 方差计算工具
calculate_variance_tool = {
    "name": "calculate_variance",
    "description": "Calculate variance for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate variance for"
            }
        },
        "required": ["column_name"]
    }
}

# 最小值计算工具
calculate_min_tool = {
    "name": "calculate_min",
    "description": "Calculate minimum value for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate minimum for"
            }
        },
        "required": ["column_name"]
    }
}

# 最大值计算工具
calculate_max_tool = {
    "name": "calculate_max",
    "description": "Calculate maximum value for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate maximum for"
            }
        },
        "required": ["column_name"]
    }
}

# 求和计算工具
calculate_sum_tool = {
    "name": "calculate_sum",
    "description": "Calculate sum for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate sum for"
            }
        },
        "required": ["column_name"]
    }
}

# 计数计算工具
calculate_count_tool = {
    "name": "calculate_count",
    "description": "Calculate count of non-null values for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to count non-null values for"
            }
        },
        "required": ["column_name"]
    }
}

# 分位数计算工具
calculate_quantile_tool = {
    "name": "calculate_quantile",
    "description": "Calculate specific quantile for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate quantile for"
            },
            "q": {
                "type": "number",
                "description": "Quantile to calculate (0.0 to 1.0, e.g., 0.25 for 25th percentile)",
                "minimum": 0.0,
                "maximum": 1.0
            }
        },
        "required": ["column_name", "q"]
    }
}

# 偏度计算工具
calculate_skewness_tool = {
    "name": "calculate_skewness",
    "description": "Calculate skewness for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate skewness for"
            }
        },
        "required": ["column_name"]
    }
}

# 峰度计算工具
calculate_kurtosis_tool = {
    "name": "calculate_kurtosis",
    "description": "Calculate kurtosis for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate kurtosis for"
            }
        },
        "required": ["column_name"]
    }
}

# 缺失值计数工具
count_missing_values_tool = {
    "name": "count_missing_values",
    "description": "Count missing values for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to count missing values for"
            }
        },
        "required": ["column_name"]
    }
}

# 唯一值计数工具
count_unique_values_tool = {
    "name": "count_unique_values",
    "description": "Count unique values for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to count unique values for"
            }
        },
        "required": ["column_name"]
    }
}

# IQR异常值检测工具
detect_outliers_iqr_tool = {
    "name": "detect_outliers_iqr",
    "description": "Detect outliers using IQR method for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to detect outliers for"
            }
        },
        "required": ["column_name"]
    }
}

# Z-score异常值检测工具
detect_outliers_zscore_tool = {
    "name": "detect_outliers_zscore",
    "description": "Detect outliers using Z-score method for a single numerical column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to detect outliers for"
            },
            "threshold": {
                "type": "number",
                "description": "Z-score threshold for outlier detection (default: 3)",
                "default": 3.0
            }
        },
        "required": ["column_name"]
    }
}

# 唯一值获取工具
get_unique_values_tool = {
    "name": "get_unique_values",
    "description": "Get unique values for a single column as a list of strings",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to get unique values for"
            }
        },
        "required": ["column_name"]
    }
}

# 众数获取工具
get_mode_tool = {
    "name": "get_mode",
    "description": "Get mode (most frequent value) for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to get mode for"
            }
        },
        "required": ["column_name"]
    }
}

# 唯一值百分比工具
get_percentage_of_unique_values_tool = {
    "name": "get_percentage_of_unique_values",
    "description": "Get percentage of each unique value for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to get percentage distribution for"
            }
        },
        "required": ["column_name"]
    }
}

# 平均文本长度计算工具
calculate_avg_text_length_tool = {
    "name": "calculate_avg_text_length",
    "description": "Calculate average text length for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to calculate average text length for"
            }
        },
        "required": ["column_name"]
    }
}

# 最小日期获取工具
get_min_date_tool = {
    "name": "get_min_date",
    "description": "Get minimum date for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to get minimum date for"
            }
        },
        "required": ["column_name"]
    }
}

# 最大日期获取工具
get_max_date_tool = {
    "name": "get_max_date",
    "description": "Get maximum date for a single column",
    "input_schema": {
        "type": "object",
        "properties": {
            "column_name": {
                "type": "string",
                "description": "Column name to get maximum date for"
            }
        },
        "required": ["column_name"]
    }
}

# ============================================================================
# 多变量统计分析工具
# ============================================================================

# 相关性矩阵计算工具
calculate_correlation_matrix_tool = {
    "name": "calculate_correlation_matrix",
    "description": "Calculate correlation matrix for multiple numerical columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate correlations for"
            }
        },
        "required": ["columns"]
    }
}

# 相关性系数和p值计算工具
calculate_correlation_with_p_values_tool = {
    "name": "calculate_correlation_with_p_values",
    "description": "Calculate correlation coefficients and p-values for multiple numerical columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate correlations for"
            }
        },
        "required": ["columns"]
    }
}

# 分组均值计算工具
calculate_group_means_by_category_tool = {
    "name": "calculate_group_means_by_category",
    "description": "Calculate group means for multiple value columns by a categorical group column",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column to group by"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate means for"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# 分组标准差计算工具
calculate_group_stds_by_category_tool = {
    "name": "calculate_group_stds_by_category",
    "description": "Calculate group standard deviations for multiple value columns by a categorical group column",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column to group by"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate standard deviations for"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# t检验计算工具
calculate_t_tests_for_multiple_variables_tool = {
    "name": "calculate_t_tests_for_multiple_variables",
    "description": "Calculate t-tests for multiple variables between two groups",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column with exactly 2 groups"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to perform t-tests on"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# ANOVA计算工具
calculate_anova_for_multiple_variables_tool = {
    "name": "calculate_anova_for_multiple_variables",
    "description": "Calculate one-way ANOVA for multiple variables across multiple groups",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column to group by"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to perform ANOVA on"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# 卡方检验计算工具
calculate_chi_square_tests_for_multiple_pairs_tool = {
    "name": "calculate_chi_square_tests_for_multiple_pairs",
    "description": "Calculate chi-square tests for multiple pairs of categorical variables",
    "input_schema": {
        "type": "object",
        "properties": {
            "cat_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of categorical columns to test"
            }
        },
        "required": ["cat_cols"]
    }
}

# 列联表计算工具
calculate_contingency_tables_tool = {
    "name": "calculate_contingency_tables",
    "description": "Calculate contingency tables for multiple pairs of categorical variables",
    "input_schema": {
        "type": "object",
        "properties": {
            "cat_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of categorical columns to create contingency tables for"
            }
        },
        "required": ["cat_cols"]
    }
}

# 协方差矩阵计算工具
calculate_covariance_matrix_tool = {
    "name": "calculate_covariance_matrix",
    "description": "Calculate covariance matrix for multiple numerical columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate covariance for"
            }
        },
        "required": ["columns"]
    }
}

# 多列异常值检测工具
calculate_outliers_for_multiple_columns_tool = {
    "name": "calculate_outliers_for_multiple_columns",
    "description": "Detect outliers for multiple numerical columns using IQR method",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to detect outliers for"
            }
        },
        "required": ["columns"]
    }
}

# 缺失值汇总工具
calculate_missing_values_summary_tool = {
    "name": "calculate_missing_values_summary",
    "description": "Calculate missing values summary for multiple columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of columns to analyze missing values for"
            }
        },
        "required": ["columns"]
    }
}

# Mann-Whitney U检验工具
calculate_mann_whitney_u_tests_tool = {
    "name": "calculate_mann_whitney_u_tests",
    "description": "Calculate Mann-Whitney U tests for multiple variables between two groups",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column with exactly 2 groups"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to perform Mann-Whitney U tests on"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# Kruskal-Wallis检验工具
calculate_kruskal_wallis_tests_tool = {
    "name": "calculate_kruskal_wallis_tests",
    "description": "Calculate Kruskal-Wallis tests for multiple variables across multiple groups",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column to group by"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to perform Kruskal-Wallis tests on"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# 正态性检验工具
calculate_normality_tests_tool = {
    "name": "calculate_normality_tests",
    "description": "Calculate normality tests (Shapiro-Wilk) for multiple numerical columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to test for normality"
            }
        },
        "required": ["columns"]
    }
}

# 方差齐性检验工具
calculate_variance_homogeneity_tests_tool = {
    "name": "calculate_variance_homogeneity_tests",
    "description": "Calculate Levene's test for variance homogeneity across groups for multiple variables",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column to group by"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to test for variance homogeneity"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# 置信区间计算工具
calculate_confidence_intervals_tool = {
    "name": "calculate_confidence_intervals",
    "description": "Calculate confidence intervals for multiple numerical columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate confidence intervals for"
            },
            "confidence_level": {
                "type": "number",
                "description": "Confidence level (default: 0.95)",
                "default": 0.95,
                "minimum": 0.5,
                "maximum": 0.99
            }
        },
        "required": ["columns"]
    }
}

# Spearman相关性计算工具
calculate_spearman_correlations_tool = {
    "name": "calculate_spearman_correlations",
    "description": "Calculate Spearman rank correlations for multiple numerical columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate Spearman correlations for"
            }
        },
        "required": ["columns"]
    }
}

# 自相关计算工具
calculate_autocorrelation_tool = {
    "name": "calculate_autocorrelation",
    "description": "Calculate autocorrelation for multiple numerical columns",
    "input_schema": {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate autocorrelation for"
            },
            "max_lag": {
                "type": "integer",
                "description": "Maximum lag to calculate (default: 10)",
                "default": 10,
                "minimum": 1
            }
        },
        "required": ["columns"]
    }
}

# 条件概率计算工具
calculate_conditional_probabilities_tool = {
    "name": "calculate_conditional_probabilities",
    "description": "Calculate conditional probabilities for multiple pairs of categorical variables",
    "input_schema": {
        "type": "object",
        "properties": {
            "cat_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of categorical columns to calculate conditional probabilities for"
            }
        },
        "required": ["cat_cols"]
    }
}

# 效应量计算工具
calculate_effect_sizes_for_multiple_variables_tool = {
    "name": "calculate_effect_sizes_for_multiple_variables",
    "description": "Calculate Cohen's d effect sizes for multiple variables between two groups",
    "input_schema": {
        "type": "object",
        "properties": {
            "group_col": {
                "type": "string",
                "description": "Categorical column with exactly 2 groups"
            },
            "value_cols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of numerical columns to calculate effect sizes for"
            }
        },
        "required": ["group_col", "value_cols"]
    }
}

# ============================================================================
# Batch Tool 定义
# ============================================================================

batch_tool = {
    "name": "batch_tool",
    "description": "Invoke multiple statistical analysis tools simultaneously for parallel processing",
    "input_schema": {
        "type": "object",
        "properties": {
            "invocations": {
                "type": "array",
                "description": "The tool calls to invoke in parallel",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The name of the tool to invoke"
                        },
                        "arguments": {
                            "type": "object",
                            "description": "The arguments to the tool (as object, not string)"
                        }
                    },
                    "required": ["name", "arguments"]
                }
            },
            "concurrent": {
                "type": "boolean",
                "description": "Whether to execute tools concurrently (default: true)",
                "default": True
            }
        },
        "required": ["invocations"]
    }
}

# 工具分类

UNIVARIATE_STATISTICAL_TOOLS = [
    calculate_mean_tool,
    calculate_median_tool,
    calculate_std_tool,
    calculate_variance_tool,
    calculate_min_tool,
    calculate_max_tool,
    calculate_sum_tool,
    calculate_count_tool,
    calculate_quantile_tool,
    calculate_skewness_tool,
    calculate_kurtosis_tool,
    count_missing_values_tool,
    count_unique_values_tool,
    detect_outliers_iqr_tool,
    detect_outliers_zscore_tool,
    get_unique_values_tool,
    get_mode_tool,
    get_percentage_of_unique_values_tool,
    calculate_avg_text_length_tool,
    get_min_date_tool,
    get_max_date_tool,
]

MULTIVARIATE_STATISTICAL_TOOLS = [
    calculate_correlation_matrix_tool,
    calculate_correlation_with_p_values_tool,
    calculate_group_means_by_category_tool,
    calculate_group_stds_by_category_tool,
    calculate_t_tests_for_multiple_variables_tool,
    calculate_anova_for_multiple_variables_tool,
    calculate_chi_square_tests_for_multiple_pairs_tool,
    calculate_contingency_tables_tool,
    calculate_covariance_matrix_tool,
    calculate_outliers_for_multiple_columns_tool,
    calculate_missing_values_summary_tool,
    calculate_mann_whitney_u_tests_tool,
    calculate_kruskal_wallis_tests_tool,
    calculate_normality_tests_tool,
    calculate_variance_homogeneity_tests_tool,
    calculate_confidence_intervals_tool,
    calculate_spearman_correlations_tool,
    calculate_autocorrelation_tool,
    calculate_conditional_probabilities_tool,
    calculate_effect_sizes_for_multiple_variables_tool,
]

STATISTICAL_TOOLS = UNIVARIATE_STATISTICAL_TOOLS + MULTIVARIATE_STATISTICAL_TOOLS + [batch_tool]

# 工具名称到函数名的映射
TOOL_FUNCTION_MAPPING = {
    # 单变量工具
    "calculate_mean": "calculate_mean",
    "calculate_median": "calculate_median",
    "calculate_std": "calculate_std",
    "calculate_variance": "calculate_variance",
    "calculate_min": "calculate_min",
    "calculate_max": "calculate_max",
    "calculate_sum": "calculate_sum",
    "calculate_count": "calculate_count",
    "calculate_quantile": "calculate_quantile",
    "calculate_skewness": "calculate_skewness",
    "calculate_kurtosis": "calculate_kurtosis",
    "count_missing_values": "count_missing_values",
    "count_unique_values": "count_unique_values",
    "detect_outliers_iqr": "detect_outliers_iqr",
    "detect_outliers_zscore": "detect_outliers_zscore",
    "get_unique_values": "get_unique_values",
    "get_mode": "get_mode",
    "get_percentage_of_unique_values": "get_percentage_of_unique_values",
    "calculate_avg_text_length": "calculate_avg_text_length",
    "get_min_date": "get_min_date",
    "get_max_date": "get_max_date",
    
    # 多变量工具
    "calculate_correlation_matrix": "calculate_correlation_matrix",
    "calculate_correlation_with_p_values": "calculate_correlation_with_p_values",
    "calculate_group_means_by_category": "calculate_group_means_by_category",
    "calculate_group_stds_by_category": "calculate_group_stds_by_category",
    "calculate_t_tests_for_multiple_variables": "calculate_t_tests_for_multiple_variables",
    "calculate_anova_for_multiple_variables": "calculate_anova_for_multiple_variables",
    "calculate_chi_square_tests_for_multiple_pairs": "calculate_chi_square_tests_for_multiple_pairs",
    "calculate_contingency_tables": "calculate_contingency_tables",
    "calculate_covariance_matrix": "calculate_covariance_matrix",
    "calculate_outliers_for_multiple_columns": "calculate_outliers_for_multiple_columns",
    "calculate_missing_values_summary": "calculate_missing_values_summary",
    "calculate_mann_whitney_u_tests": "calculate_mann_whitney_u_tests",
    "calculate_kruskal_wallis_tests": "calculate_kruskal_wallis_tests",
    "calculate_normality_tests": "calculate_normality_tests",
    "calculate_variance_homogeneity_tests": "calculate_variance_homogeneity_tests",
    "calculate_confidence_intervals": "calculate_confidence_intervals",
    "calculate_spearman_correlations": "calculate_spearman_correlations",
    "calculate_autocorrelation": "calculate_autocorrelation",
    "calculate_conditional_probabilities": "calculate_conditional_probabilities",
    "calculate_effect_sizes_for_multiple_variables": "calculate_effect_sizes_for_multiple_variables",
    "batch_tool": "process_batch_tool"
}

def process_tool_call(tool_name: str, tool_input: dict, df: pd.DataFrame) -> Dict[str, Any]:
    try:
        from ..utils.statistical_analysis import (
            # 单变量统计函数
            calculate_mean, calculate_median, calculate_std, calculate_variance,
            calculate_min, calculate_max, calculate_sum, calculate_count,
            calculate_quantile, calculate_skewness, calculate_kurtosis,
            count_missing_values, count_unique_values, detect_outliers_iqr,
            detect_outliers_zscore, get_unique_values, get_mode,
            get_percentage_of_unique_values, calculate_avg_text_length,
            get_min_date, get_max_date,
            
            # 多变量统计函数
            calculate_correlation_matrix, calculate_correlation_with_p_values,
            calculate_group_means_by_category, calculate_group_stds_by_category,
            calculate_t_tests_for_multiple_variables, calculate_anova_for_multiple_variables,
            calculate_chi_square_tests_for_multiple_pairs, calculate_contingency_tables,
            calculate_covariance_matrix, calculate_outliers_for_multiple_columns,
            calculate_missing_values_summary, calculate_mann_whitney_u_tests,
            calculate_kruskal_wallis_tests, calculate_normality_tests,
            calculate_variance_homogeneity_tests, calculate_confidence_intervals,
            calculate_spearman_correlations, calculate_autocorrelation,
            calculate_conditional_probabilities, calculate_effect_sizes_for_multiple_variables
        )
        
        # 单变量统计工具处理
        if tool_name == "calculate_mean":
            result = calculate_mean(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_median":
            result = calculate_median(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_std":
            result = calculate_std(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_variance":
            result = calculate_variance(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_min":
            result = calculate_min(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_max":
            result = calculate_max(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_sum":
            result = calculate_sum(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_count":
            result = calculate_count(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_quantile":
            result = calculate_quantile(df, tool_input["column_name"], tool_input["q"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_skewness":
            result = calculate_skewness(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_kurtosis":
            result = calculate_kurtosis(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "count_missing_values":
            result = count_missing_values(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "count_unique_values":
            result = count_unique_values(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "detect_outliers_iqr":
            result = detect_outliers_iqr(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "detect_outliers_zscore":
            threshold = tool_input.get("threshold", 3.0)
            result = detect_outliers_zscore(df, tool_input["column_name"], threshold)
            return {"success": True, "result": result}
            
        elif tool_name == "get_unique_values":
            result = get_unique_values(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "get_mode":
            result = get_mode(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "get_percentage_of_unique_values":
            result = get_percentage_of_unique_values(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_avg_text_length":
            result = calculate_avg_text_length(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "get_min_date":
            result = get_min_date(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        elif tool_name == "get_max_date":
            result = get_max_date(df, tool_input["column_name"])
            return {"success": True, "result": result}
            
        # 多变量统计工具处理
        elif tool_name == "calculate_correlation_matrix":
            result = calculate_correlation_matrix(df, tool_input["columns"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_correlation_with_p_values":
            result = calculate_correlation_with_p_values(df, tool_input["columns"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_group_means_by_category":
            result = calculate_group_means_by_category(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_group_stds_by_category":
            result = calculate_group_stds_by_category(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_t_tests_for_multiple_variables":
            result = calculate_t_tests_for_multiple_variables(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_anova_for_multiple_variables":
            result = calculate_anova_for_multiple_variables(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_chi_square_tests_for_multiple_pairs":
            result = calculate_chi_square_tests_for_multiple_pairs(df, tool_input["cat_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_contingency_tables":
            result = calculate_contingency_tables(df, tool_input["cat_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_covariance_matrix":
            result = calculate_covariance_matrix(df, tool_input["columns"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_outliers_for_multiple_columns":
            result = calculate_outliers_for_multiple_columns(df, tool_input["columns"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_missing_values_summary":
            result = calculate_missing_values_summary(df, tool_input["columns"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_mann_whitney_u_tests":
            result = calculate_mann_whitney_u_tests(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_kruskal_wallis_tests":
            result = calculate_kruskal_wallis_tests(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_normality_tests":
            result = calculate_normality_tests(df, tool_input["columns"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_variance_homogeneity_tests":
            result = calculate_variance_homogeneity_tests(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_confidence_intervals":
            confidence_level = tool_input.get("confidence_level", 0.95)
            result = calculate_confidence_intervals(df, tool_input["columns"], confidence_level)
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_spearman_correlations":
            result = calculate_spearman_correlations(df, tool_input["columns"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_autocorrelation":
            max_lag = tool_input.get("max_lag", 10)
            result = calculate_autocorrelation(df, tool_input["columns"], max_lag)
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_conditional_probabilities":
            result = calculate_conditional_probabilities(df, tool_input["cat_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "calculate_effect_sizes_for_multiple_variables":
            result = calculate_effect_sizes_for_multiple_variables(df, tool_input["group_col"], tool_input["value_cols"])
            return {"success": True, "result": result}
            
        elif tool_name == "batch_tool":
            # 处理批量工具调用
            return process_tool_call_with_batch(tool_name, tool_input, df)
            
        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}
            
    except ImportError as e:
        return {"success": False, "error": f"Could not import statistical_analysis module: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"Error executing tool {tool_name}: {str(e)}"}

def process_tool_call_with_batch(tool_name: str, tool_input: dict, df: pd.DataFrame) -> Dict[str, Any]:
    """Process tool calls with batch tool"""
    if tool_name == "batch_tool":
        results = {}
        for invocation in tool_input["invocations"]:
            invocation_name = invocation["name"]
            invocation_args = invocation["arguments"]
            # 如果arguments是字符串，则解析为JSON
            if isinstance(invocation_args, str):
                invocation_args = json.loads(invocation_args)
            results[invocation_name] = process_tool_call(invocation_name, invocation_args, df)
        return {"success": True, "batch_results": results}
    else:
        return process_tool_call(tool_name, tool_input, df)