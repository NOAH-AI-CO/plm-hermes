import traceback
import pandas as pd
import numpy
numpy.NaN = numpy.nan
import pandas_ta as ta
import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List
from ..core.interfaces import Analyzer, LLMModel, PromptTemplate, DataSource
from ..prompts.analysis_prompts import TechnicalAnalysisPrompt
from ..prompts.analysis_prompts_en import TechnicalAnalysisPromptEn

class TechnicalAnalyzer(Analyzer):
    def __init__(self, model: LLMModel, data_source: DataSource, language: str = 'zh-CN'):
        """Initialize technical analyzer with LLM model and data source"""
        self.model = model
        self.data_source = data_source
        self.language = language
        self.prompt_template = TechnicalAnalysisPrompt() if language == 'zh-CN' else TechnicalAnalysisPromptEn()
        self.output_dir = None

    def set_output_dir(self, output_dir: str):
        """Set output directory for analysis results"""
        self.output_dir = output_dir

    def _save_indicators(self, df: pd.DataFrame, symbol: str):
        """Save technical indicators to CSV file
        
        Args:
            df: DataFrame with technical indicators
            symbol: Stock symbol
        """
        try:
            # Create data directory if it doesn't exist
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            
            # Select only the indicator columns
            indicator_columns = [
                'MA5', 'MA10', 'MA20', 'MA50', 'MA200',
                'RSI', 'Williams', 'ADX',
                'MACD_12_26_9', 'MACDs_12_26_9', 'MACDh_12_26_9',
                'BBU_20_2.0', 'BBM_20_2.0', 'BBL_20_2.0', 'BBB_20_2.0', 'BBP_20_2.0',
                'Volume_Change', 'Volume_MA5', 'Volume_MA20',
                'Price_Change'
            ]
            
            # Filter existing columns only
            available_indicators = [col for col in indicator_columns if col in df.columns]
            indicators_df = df[available_indicators]
            
            # Add date as a column (it's currently the index)
            indicators_df = indicators_df.reset_index()
            
            # Save to CSV
            filepath = os.path.join(data_dir, 'technical_indicators.csv')
            indicators_df.to_csv(filepath, index=False)
            print(f"技术指标数据已保存至：{filepath}")
            
        except Exception as e:
            print(f"Warning: Failed to save technical indicators: {str(e)}")

    async def _get_indicators(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """Get technical indicators from FMP API"""
        df = df.copy()
        
        try:
            # Get indicators from FMP
            indicators = await self.data_source.get_all_technical_indicators(symbol)
            
            # Add moving averages
            df['MA5'] = indicators['sma'].loc[df.index]['sma']
            df['MA10'] = (await self.data_source.get_technical_indicator(symbol, 'sma', period=10)).loc[df.index]['sma']
            df['MA20'] = (await self.data_source.get_technical_indicator(symbol, 'sma', period=20)).loc[df.index]['sma']
            df['MA50'] = (await self.data_source.get_technical_indicator(symbol, 'sma', period=50)).loc[df.index]['sma']
            df['MA200'] = (await self.data_source.get_technical_indicator(symbol, 'sma', period=200)).loc[df.index]['sma']
            
            # Add RSI
            df['RSI'] = indicators['rsi'].loc[df.index]['rsi']
            
            # Add Williams %R
            df['Williams'] = indicators['williams'].loc[df.index]['williams']
            
            # Add ADX
            df['ADX'] = indicators['adx'].loc[df.index]['adx']
            
            # Calculate MACD (as it's not directly available from FMP)
            macd = ta.macd(df['Close'])
            df = pd.concat([df, macd], axis=1)
            
            # Calculate Bollinger Bands (as they're not directly available from FMP)
            rolling_mean = df['Close'].rolling(window=20).mean()
            rolling_std = df['Close'].rolling(window=20).std()
            df['BBU_20_2.0'] = rolling_mean + (rolling_std * 2)
            df['BBM_20_2.0'] = rolling_mean
            df['BBL_20_2.0'] = rolling_mean - (rolling_std * 2)
            df['BBB_20_2.0'] = (df['BBU_20_2.0'] - df['BBL_20_2.0']) / df['BBM_20_2.0']
            df['BBP_20_2.0'] = (df['Close'] - df['BBL_20_2.0']) / (df['BBU_20_2.0'] - df['BBL_20_2.0'])
            
            # Volume analysis
            df['Volume_Change'] = df['Volume'].pct_change() * 100
            df['Volume_MA5'] = df['Volume'].rolling(window=5).mean()
            df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
            
            # Price changes
            df['Price_Change'] = df['Close'].pct_change() * 100
            
            # Save indicators to CSV
            self._save_indicators(df, symbol)
            
            return df
            
        except Exception as e:
            print(f"Warning: Failed to get FMP indicators: {str(e)}")
            print("Falling back to local calculations...")
            df = self._calculate_indicators_local(df)
            
            # Save locally calculated indicators
            self._save_indicators(df, symbol)
            
            return df
    
    def _calculate_indicators_local(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators locally (fallback method)"""
        df = df.copy()
        
        # Moving averages
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA50'] = df['Close'].rolling(window=50).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()
        
        # RSI
        df['RSI'] = ta.rsi(df['Close'], length=14)
        
        # MACD
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)
        
        # Bollinger Bands
        rolling_mean = df['Close'].rolling(window=20).mean()
        rolling_std = df['Close'].rolling(window=20).std()
        df['BBU_20_2.0'] = rolling_mean + (rolling_std * 2)
        df['BBM_20_2.0'] = rolling_mean
        df['BBL_20_2.0'] = rolling_mean - (rolling_std * 2)
        df['BBB_20_2.0'] = (df['BBU_20_2.0'] - df['BBL_20_2.0']) / df['BBM_20_2.0']
        df['BBP_20_2.0'] = (df['Close'] - df['BBL_20_2.0']) / (df['BBU_20_2.0'] - df['BBL_20_2.0'])
        
        # Volume analysis
        df['Volume_Change'] = df['Volume'].pct_change() * 100
        df['Volume_MA5'] = df['Volume'].rolling(window=5).mean()
        df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
        
        # Price changes
        df['Price_Change'] = df['Close'].pct_change() * 100
        
        return df

    def _prepare_data_summary(self, df: pd.DataFrame, news_data: List[Dict[str, Any]], tweets_data: str) -> str:
        """Prepare data summary for analysis"""
        latest = df.iloc[-1]
        
        summary = f"""### 价格与趋势
    - 最新价格: {latest['Close']:.2f}
    - 日涨跌幅: {latest['Price_Change']:.1f}%
    - 5日涨跌幅: {((latest['Close'] / df['Close'].iloc[-6] - 1) * 100):.1f}%
- 区间涨跌幅: {((latest['Close'] / df['Close'].iloc[0] - 1) * 100):.1f}%
- 50日均线: {latest['MA50']:.2f}
- 200日均线: {latest['MA200']:.2f}

### 技术指标
- RSI(14): {latest['RSI']:.1f}
- ADX: {latest.get('ADX', numpy.nan):.1f}
- Williams %R: {latest.get('Williams', numpy.nan):.1f}
- MACD: {latest['MACD_12_26_9']:.3f}
- MACD信号线: {latest['MACDs_12_26_9']:.3f}
- MACD柱状: {latest['MACDh_12_26_9']:.3f}

### 成交量分析
- 日成交量: {latest['Volume']:,.0f}
- 5日均量: {df['Volume'].tail(5).mean():,.0f}

### 布林带
- 上轨: {latest['BBU_20_2.0']:.2f}
- 中轨: {latest['BBM_20_2.0']:.2f}
- 下轨: {latest['BBL_20_2.0']:.2f}

### 最近新闻与公告
"""
        # Add news and press releases if available
        if news_data:
            summary += "\n#### 公司新闻和公告\n"
            for article in news_data[:30]:  # Show latest 30 news and press releases
                date = article['publishedDate'].split()[0]  # Get date only
                summary += f"- {date} | {article['title']}\n  {article['summary']}\nSource: {article['source']}\n"
                if 'url' in article:
                    summary += f"Url: {article['url']}\n"
                summary += "\n"
        else:
            summary += "无最新新闻和公告\n"

        summary += f"""

### 最近社交媒体信息
{tweets_data}

### 最近数据
{df.tail(20).to_string()}"""
        
        return summary

    async def analyze(self, data: Dict[str, Any], only_return_data: bool = False) -> str:
        """Analyze technical data and return insights"""
        try:
            symbol = data['symbol']
            price_data = data['price_data']
            latest_price = data['latest_price']
            
            print("\n处理技术数据...")
            print("- 计算技术指标")
            # Get technical indicators
            df = await self._get_indicators(symbol, price_data)
            
            print("- 获取最新新闻和公告")
            # Get latest news and press releases
            news_data = await self.data_source.get_stock_news(symbol, limit=100)  # Get latest 100 news articles
            press_releases = await self.data_source.get_press_releases(symbol, limit=100)  # Get latest 100 press releases
            
            # Combine news and press releases, sort by date
            all_updates = news_data + press_releases
            all_updates.sort(key=lambda x: x['publishedDate'], reverse=True)

            # 只保留最近半年的新闻
            all_updates = [update for update in all_updates if update['publishedDate'] > (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')]
            
            # print(f"DEBUG:all_updates: {all_updates}")

            # remove duplicated news and press releases, defined as same title, the title should be uppercase
            unique_updates = []
            unique_titles = set()
            for article in all_updates:
                if article['title'].upper() not in unique_titles:
                    unique_updates.append(article)
                    unique_titles.add(article['title'].upper())
            all_updates = unique_updates
            all_updates.sort(key=lambda x: x['publishedDate'], reverse=True)

            # # Get tweets data
            # tweets = await self.data_source.get_tweets(symbol)
            # latest_tweets = tweets.get('latest', [])
            # top_tweets = tweets.get('top', [])

            # # combine latest_tweets and top_tweets, remove duplicated tweets, defined as same text
            # unique_tweets = []
            # unique_texts = set()
            # for tweet in latest_tweets + top_tweets:
            #     if tweet['text'] not in unique_texts:
            #         unique_tweets.append(tweet)
            #         unique_texts.add(tweet['text'])

            # # only keep the time and text of the tweets
            # clean_tweets = [{'publishedDate': tweet['created_at'], 'text': tweet['text']} for tweet in unique_tweets]
            # clean_tweets_str = "\n".join([f"- {tweet['publishedDate']} | {tweet['text']}" for tweet in clean_tweets])
            clean_tweets_str = "" # 暂时不使用社交媒体信息

            print("- 准备数据摘要")
            # Prepare data summary
            data_summary = self._prepare_data_summary(df, all_updates, clean_tweets_str)

            if only_return_data:
                return data_summary
            
            print("- 生成分析提示")
            # Generate prompt
            prompt = self.prompt_template.format(
                symbol=symbol,
                data_summary=data_summary
            )
            
            # Save prompt to file
            prompt_dir = os.path.join(self.output_dir, "prompts")
            os.makedirs(prompt_dir, exist_ok=True)
            prompt_file = os.path.join(prompt_dir, 'technical_analysis_prompt.txt')
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"- 分析提示已保存至：{prompt_file}")
            
            print("- 调用 AI 模型进行分析")

            # Get analysis from LLM
            analysis = await self.model.generate(prompt)
            analysis = analysis.replace('```markdown', '').replace('```', '')
            
            print("- 技术分析完成")
            return {
                'analysis': analysis,
                'raw_data': data_summary
            }
            
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"Technical analysis failed: {str(e)}") 