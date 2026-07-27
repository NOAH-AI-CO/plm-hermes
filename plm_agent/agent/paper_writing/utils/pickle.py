
import pickle
from pathlib import Path

def save_cached_results(results: dict, filename: str = "cached_analysis_results.pkl"):
    """保存分析结果到缓存文件"""
    try:
        with open(filename, 'wb') as f:
            pickle.dump(results, f)
        print(f"分析结果已保存到缓存文件: {filename}")
    except Exception as e:
        print(f"保存缓存失败: {e}")

def load_cached_results(filename: str = "cached_analysis_results.pkl"):
    """从缓存文件加载分析结果"""
    try:
        if Path(filename).exists():
            with open(filename, 'rb') as f:
                results = pickle.load(f)
            print(f"从缓存文件加载结果: {filename}")
            return results
        else:
            print(f"缓存文件不存在: {filename}")
            return None
    except Exception as e:
        print(f"加载缓存失败: {e}")
        return None