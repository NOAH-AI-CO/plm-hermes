import argparse
import asyncio
from datetime import datetime
from .models.composite_model import CompositeModel
from .data_sources.fmp_source import FMPDataSource
from .data_sources.polygon_source import PolygonOptionsSource
from .data_sources.twitter_source import TwitterDataSource
from .data_sources.composite_source import CompositeDataSource
from .core.analyzer import StockAnalyzer
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='生物医药股票分析工具')
    parser.add_argument('symbol', type=str, help='股票代码 (例如: AAPL, 600000.SS, 000001.SZ)')
    parser.add_argument('--period', type=str, default='6mo', 
                      help='分析周期 (默认: 6mo, 可选: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max)')
    parser.add_argument('--year', type=int, default=None, 
                      help='期权分析目标年份 (默认: 当前年份+1)')
    parser.add_argument('--test', action='store_true',
                      help='启用测试模式 (使用测试模型，token限制2000)')
    parser.add_argument('--one-step', action='store_true',
                      help='一步分析模式，用一次llm调用分析所有内容')
    parser.add_argument('--two-step', action='store_true',
                      help='两步分析模式，用两次llm调用分析所有内容,一个专门分析催化剂具体事件的成功率，一个结合前者的分析结果和其他数据，生成最终报告')
    args = parser.parse_args()
    
    try:
        print("\n生物医药股票分析工具")
        print("=" * 50)
        
        print(f"\n开始分析 {args.symbol}...")
        print(f"分析周期: {args.period}")
        if args.year:
            print(f"期权分析年份: {args.year}")
        
        # Initialize components
        print("\n初始化分析组件...")
        print("- 初始化 LLM 模型")

        # Create output directory
        print("- 创建输出目录")
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"./bio_quant/outputs/{args.symbol}_{current_time}"
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize composite model with fallback chain
        model = CompositeModel(test_mode=args.test)
        
        print("- 初始化数据源")
        # Create individual data sources
        fmp_source = FMPDataSource()  # Primary source for stock data and technical indicators
        polygon_source = PolygonOptionsSource()  # Source for options data
        twitter_source = TwitterDataSource()  # Source for tweets data
        
        # Create composite data source
        data_source = CompositeDataSource(
            primary_source=fmp_source,
            options_source=polygon_source,
            twitter_source=twitter_source
        )
        
        # Set output directory for data sources
        data_source.set_output_dir(output_dir)
        
        # Create analyzer
        print("- 初始化分析器")
        analyzer = StockAnalyzer(
            symbol=args.symbol,
            llm_model=model,
            data_source=data_source,
            period=args.period,
            target_year=args.year,
            output_dir=output_dir,
            one_step=args.one_step,
            two_step=args.two_step
        )
        
        # Run analysis
        print("\n开始执行分析...")
        results = await analyzer.analyze()
        
        print("\n分析完成！分析报告已保存至以下目录：")
        print(f"{output_dir}/")
        print("- technical_analysis_result.md: 技术分析报告")
        print("- financial_analysis_result.md: 财务分析报告")
        print("- options_analysis_result.md: 期权分析报告（如果可用）")
        print("- investment_report.md: 综合投资报告")
        print(f"- {output_dir}/investment_report.pdf: PDF格式综合报告")
        
    except Exception as e:
        print(f"\n程序运行出错：{str(e)}")
        
    print("\n" + "=" * 50)

if __name__ == "__main__":
    asyncio.run(main())