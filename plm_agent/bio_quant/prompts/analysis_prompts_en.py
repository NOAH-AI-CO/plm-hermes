from ..core.interfaces import PromptTemplate
from datetime import datetime
import pytz
import json

class TechnicalAnalysisPromptEn(PromptTemplate):
    """Technical analysis prompt template"""
    
    def __init__(self):
      self.template = """Please perform a comprehensive technical analysis for {symbol}. Here is the latest technical data and market information:

{data_summary}

### Analysis Requirements (Strictly Follow)
1. All conclusions must cite data sources, format examples:
   - [Price data: 36.04@2024-03-01]
   - [MACD: 0.5@2024-03-01]
   - [News: FDA approval@2024-02-28]

2. Analyze in this priority order:
⚠️ Trend direction > Support/Resistance > Volume anomalies > Technical indicators

3. Must include:
   | Analysis Dimension | Output Requirements                     |
   |-------------------|-----------------------------------------|
   | Short-term trend  | Clear direction + confidence + timeframe |
   | Key support/resistance | 3 price levels + formation basis    |
   | Risk warnings     | At least 2 clear trigger conditions     |

### Prohibited Items (Important!)
❌ Do not use any data not provided
❌ No ambiguous statements (must specify time/values)
❌ Do not omit data source citations

### Analysis Framework
1. Core Conclusions (Top)
   - Highlight 3 most critical conclusions with ⚠️ symbol
   - Each conclusion must include:
     [Data evidence] + [Time range] + [Confidence level]

2. Detailed Analysis
   - Start each paragraph with [Data source] label
   - Technical indicator analysis must include:
     Indicator name + value + calculation logic

3. Scenario Prediction (Must include, output in report format)
   ``` 
   if break through 'key resistance level' then bullish to 'target price'
   elif fall below 'key support level' then bearish to 'target price'
   else maintain oscillation range ['support level'-'resistance level']
   ```

### Self-Check List (Must verify each item after generation)
[ ] Do all values have data source citations?
[ ] Are 3 clear key conclusions included?
[ ] Are three scenario analyses included?
[ ] Are items that cannot be analyzed marked?"""

    def format(self, **kwargs) -> str:
        """Format prompt template with parameters"""
        return self.template.format(**kwargs)

class FinancialAnalysisPromptEn(PromptTemplate):
   def format(self, symbol: str, financial_data: str, latest_price: float) -> str:
      eastern = pytz.timezone('US/Eastern')
      current_time = datetime.now(eastern)
        
      prompt = f"""
translate this prompt to english

GitHub Copilot: # {symbol} Financial Analysis Request

Below is the content I need you to analyze and the results I would like you to produce. Please answer in English, maintaining objectivity and caution in your analysis. If data is insufficient to support any conclusion, please clearly indicate this.

## Basic Information
- Current US Eastern Time: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
- Current Stock Price: {latest_price}

## Available Financial Data
```json
{financial_data}
```

## Analysis Requirements (Strict Adherence)

### Data Standards
⚠️ All data references must use the standard format:
- Financial statement data → [Statement type: Value@time] Example: [Balance Sheet: Cash $1.2B@2023-Q4]
- Conference call content → [Meeting date: Summary] Example: [2024-02-28 meeting: Q2 revenue expected to grow 15%]
- Industry comparison data → [Source: Value@time] Example: [Industry average: PE 25@2024-03]

### 1. Revenue Structure Analysis
```
【Must Include】
1. Product revenue composition change analysis (time range must be noted)
2. Regional revenue strategic significance (specific regions must be noted)
3. Revenue diversification score (1-5 points, scoring basis must be explained)
```

### 2. Cash Status Analysis
```
【Calculation Requirements】
Cash burn rate = (Operating cash flow absolute value) / Cash reserves → [Calculation process must be shown]
Safety period = Cash reserves / (Operating cash flow + Investment cash flow) → [Calculation process must be shown]

【Output Requirements】
- Each value must be annotated with data timestamp
- Cash flow analysis must distinguish between operating/investment/financing activities
```

### 3. R&D Investment Analysis
```
【Analysis Dimensions】
1. R&D intensity = R&D expenditure / Total revenue → [Must calculate and note time range]
2. Industry comparison (if data available, source must be noted)
3. Pipeline investment ratio = R&D expenditure / Total operating expenses → [Must calculate]
```

### 4. Financial Health Assessment
```
【Must Analyze】
1. Debt safety margin = Cash reserves / Short-term debt → [Must calculate]
2. Working capital ratio = Current assets / Current liabilities → [Must calculate]
3. Interest coverage ratio = EBIT / Interest expense → [Must calculate]
```

### 5. Investment Recommendations
```
【Must Include】
1. Valuation calculation process (example):
   PE valuation = [Industry average PE] × [Company EPS] → [Data source must be noted]
   DCF valuation = [Cash flow forecast] / (1+[Discount rate])^n → [Assumptions must be explained]

2. Risk hedging plans:
   - At least 2 specific hedging strategies
   - Each strategy must include applicable conditions
```

## Prohibited Items (Important!)
❌ Do not use financial ratios not provided (such as ROIC/ROE, etc.)
❌ Do not use vague time expressions (such as "recently," "past few years")
❌ Do not omit data time ranges

## Self-Check List (Must Check After Generation)
[ ] Do all financial ratios have calculation processes?
[ ] Are all predictions annotated with assumptions?
[ ] Are all missing data items noted?
[ ] Do investment recommendations include risk hedging plans?

## Important Reminders
Please clearly indicate if you encounter the following situations:
1. Key data missing (such as cash reserves/operating cash flow)
2. Data time exceeding 12 months
3. Data with obvious contradictions

Please generate the analysis report strictly according to the above requirements. All conclusions must be traceable to the original data."""
        
      return prompt

class OptionsAnalysisPromptEn(PromptTemplate):
    def format(self, symbol: str, options_data: str, latest_price: float) -> str:
        eastern = pytz.timezone('US/Eastern')
        current_time = datetime.now(eastern)
        
        return f"""# Option Market Analysis for {symbol}

## Basic Information
- Current US Eastern Time: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}
- Current Stock Price: {latest_price}

## Options Data
```json
{options_data}
```

## Analysis Standards (Strictly Follow)
### Data Citation Format
⚠️ All data must be sourced:
- Implied Volatility → [IV: value@expiration] Example: [IV: 45%@2024-03-15]
- Options Trading → [Contract Type: quantity@time] Example: [Call: 5000@2024-03-01]
- Large Trades → [Block Trade: details@time]

### 1. Market Sentiment Analysis
```
【Must Include】
1. Volatility Structure:
   - IV historical percentile calculation (must show calculation process)
   - Put/Call IV difference analysis (must specify expiration dates)
   
2. Trading Activity:
   - Put/Call ratio calculation (must show raw data)
   - Abnormal trading volume identification (must include timestamps)
```

### 2. Event Risk Analysis
```
【Analysis Requirements】
- Each event hypothesis must be labeled with:
  [Expiration Date] + [Abnormal IV Value] + [Volume Change]
- Risk premium calculation must show formula:
  Risk Premium = [Put Option IV] - [Historical Volatility]
```

### 3. Institutional Strategy Analysis
```
【Must Identify】
1. Combination strategy types (straddle/strangle etc.)
2. Strike price concentration (calculate percentage of top 3 strike prices)
3. Fund flow analysis (must distinguish institutional/retail)
```

### 4. Trading Strategy Recommendations
```
【Must Include】
1. Each strategy must be labeled with:
   - Applicable conditions (must reference IV/Delta data)
   - Maximum loss calculation (must show formula)
   - Break-even point calculation
   
2. Hedging plans must include:
   - Hedging cost (must calculate premium expenditure)
   - Protection period (must specify expiration date)
```

## Prohibited Items (Important!)
❌ Do not use Greek letter data not provided (such as Vega/Theta)
❌ Do not make vague statements about volatility levels (must specify exact values)
❌ Do not omit data time ranges

## Self-Check List (Must verify after generation)
[ ] Do all IV values have data annotations?
[ ] Is break-even point calculation included?
[ ] Are all missing data items marked?
[ ] Is a risk hedging plan included?

## Biotech/Pharmaceutical Industry Special Requirements
1. Focus on analyzing these signals:
   - Short-term IV abnormal spikes (may indicate clinical data release)
   - Deep out-of-money call option trading (may indicate M&A rumors)
   - Straddle combination concentration (reflects market expectations for events)

2. Must evaluate:
   - Whether IV term structure reflects FDA approval dates
   - Whether put option premiums include regulatory risk
   - Whether block trades may involve insider information

## Important Reminders
1. All strategy recommendations must be based on the provided options chain data
2. Stop analysis if you discover:
   - Missing critical data (such as IV surface/open interest)
   - Data more than 7 trading days old
   - Unable to verify data consistency

Please generate an analysis report strictly according to these requirements. All conclusions must be traceable to the original data."""

class CatalystAnalysisPromptEn(PromptTemplate):
    """Catalyst事件分析模板"""
    
    def __init__(self):
        self.template = """# Please provide a comprehensive analysis of {company_name}'s catalyst events. Below is information about recent catalyst events and major events related to drugs and indications:

<Noah Data>
{catalyst_data}
</Noah Data>

## Analysis Guidelines (Strictly Follow)
All analysis must be based on data within <Noah Data>. Do not fabricate any data.

### 1. Event Horizon Scanning [!Required]
Present a table showing upcoming catalyst events, including event details, estimated occurrence time, and importance to the company (High/Medium/Low)

### 2. Catalyst Event Analysis [!In-depth Analysis]
Based on data in <Noah Data>, conduct in-depth analysis of catalyst events, including historical clinical data of catalyst-related drugs, competitor clinical data, and competitive landscape:

#### 2.1 Historical Clinical Data of Catalyst Drug (if provided in <Noah Data>)

Include all historical clinical data provided in <Noah Data>, including trial design, primary endpoints, secondary endpoints, enrollment criteria, efficacy, safety, etc.

#### 2.2 Competitor Clinical Data (if provided in <Noah Data>)

Include all competitor clinical data provided in <Noah Data>, including trial design, primary endpoints, secondary endpoints, enrollment criteria, efficacy, safety, etc., along with comparative analysis of competitor clinical data.
Analysis should consider differences between trials (patient characteristics, enrollment criteria, primary endpoints, secondary endpoints, patient numbers, etc.), and comparability between different trials.

#### 2.3 Competitive Landscape Analysis

Analyze whether competition exists for the catalyst drug. If competition exists, analyze the competitive landscape, including competitors' targets, indications, development stages, whether they are leading in progress, whether clinical data advantages exist, etc.

Based on the above analysis, assess the probability of positive and negative outcomes for catalyst events, and provide evidence supporting these probabilities.

Please generate the analysis report strictly according to the above requirements. All data must come from <catalyst_data>, and all assumptions and calculations must be clearly labeled in this section:
## Assumptions and Calculations
[List all assumptions used and complete calculation processes here]"""

    def format(self, **kwargs) -> str:
        """Format prompt template with parameters"""
        return self.template.format(**kwargs)
   
class IncludingPastCatalystAnalysisPromptEn(PromptTemplate):
    """Catalyst事件分析模板"""
    
    def __init__(self):
        self.template = """# Please provide a comprehensive analysis of {company_name}'s catalyst events. Below is information about recent catalyst events and major events related to drugs and indications:

<Noah Data>
{catalyst_data}
</Noah Data>

## Analysis Guidelines (Strictly Follow)
All analysis must be based on data within <Noah Data>. Do not fabricate any data.

### 1. Event Horizon Scanning [!Required]
Present a table showing recent and upcoming catalyst events, including event details, estimated occurrence time, and importance to the company (High/Medium/Low)

### 2. Catalyst Event Analysis [!In-depth Analysis]
Based on data in <Noah Data>, conduct in-depth analysis of catalyst events, including historical clinical data of catalyst-related drugs, competitor clinical data, and competitive landscape:

#### 2.1 Historical Clinical Data of Catalyst Drug (if provided in <Noah Data>)

Include all historical clinical data provided in <Noah Data>, including trial design, primary endpoints, secondary endpoints, enrollment criteria, efficacy, safety, etc.

#### 2.2 Competitor Clinical Data (if provided in <Noah Data>)

Include all competitor clinical data provided in <Noah Data>, including trial design, primary endpoints, secondary endpoints, enrollment criteria, efficacy, safety, etc., along with comparative analysis of competitor clinical data.
Analysis should consider differences between trials (patient characteristics, enrollment criteria, primary endpoints, secondary endpoints, patient numbers, etc.), and comparability between different trials.

#### 2.3 Competitive Landscape Analysis

Analyze whether competition exists for the catalyst drug. If competition exists, analyze the competitive landscape, including competitors' targets, indications, development stages, whether they are leading in progress, whether clinical data advantages exist, etc.

Based on the above analysis, assess the probability of positive and negative outcomes for catalyst events, and provide evidence supporting these probabilities.

Please generate the analysis report strictly according to the above requirements. All data must come from <catalyst_data>, and all assumptions and calculations must be clearly labeled in this section:
## Assumptions and Calculations
[List all assumptions used and complete calculation processes here]"""

    def format(self, **kwargs) -> str:
        """Format prompt template with parameters"""
        return self.template.format(**kwargs)

class IntegratedReportPromptEn:
    def format(self, symbol: str, report_date: str, latest_price: float, market_cap: float, technical_analysis: str, financial_analysis: str, options_analysis: str = None, catalyst_analysis: str = None) -> str:
        """Format prompt for generating integrated investment report"""
        return f"""# Investment Analysis Report Generation Instructions

## Core Requirements (Strictly Follow)
⚠️ All conclusions must be verified through the following methods:
1. Data annotation → [Source type: value@time] Example: [Financial report: revenue $1.2B@2023-Q4]
2. Calculation display → Formula + parameters + results Example: PE valuation = 25(industry PE) × 1.5(premium coefficient) = 37.5
3. Assumption declaration → [Assumption condition] + [Impact range] Example: [Assuming new drug approval] may increase target price by 30%

# Analysis Subject
{symbol} ({latest_price} @ {report_date})
Market Cap: {market_cap}

## Input Data
```markdown
### Technical Analysis
{technical_analysis}

### Financial Analysis
{financial_analysis}

### Options Analysis
{options_analysis if options_analysis else "No data"}

### Catalyst Analysis
{catalyst_analysis if catalyst_analysis else "No data"}
```

## Report Structure (Must Strictly Follow)
1. Rating and Target Price [!Must include calculation process]
   ```
   [Buy/Hold/Sell] Rating
   Bull Case: [value] (must show pipeline success rate × market potential)
   Base Case: [value] (must weight average various factors)
   Bear Case: [value] (must calculate risk discounting)
   ```

2. Key Arguments [!Three-point structure]
   ```
   【Argument】[no more than 10 characters]
   - Evidence chain: [data1] → [data2] → [inference]
   - Difference point: Key disagreement with market consensus
   - Data support: At least 2 data point annotations
   ```

3. Risk Hedging Plan [!Specifically executable]
   ```
   if [technical signal] then [action]
   - Trigger condition: [indicator+threshold]
   - Execution parameters: [position ratio/time window]
   - Hedging cost: [calculation process]
   ```

4. Data Dashboard [!Structured presentation]
   | Category    | Key Indicators            | Recent Changes  |
   |-------------|---------------------------|-----------------|
   | Technical   | Support/Resistance levels | [Change trend]  |
   | Financial   | Cash burn rate            | [Calculation]   |
   | Options     | IV anomaly                | [Data source]   |
   | Catalyst    | Event probability         | [Calculation]   |

## Prohibitions (Zero Tolerance)
❌ No data references without source annotation
❌ No use of vague expressions like "possibly" or "approximately" 
❌ No omission of calculation process to directly give conclusions

## Verification Checklist (Check each item after generation)
[ ] Each argument has a complete evidence chain
[ ] Each value has calculation/source annotation
[ ] Risk plan contains specific trigger conditions
[ ] Data dashboard contains latest change information

## Important! Data Reliability Verification
Immediately terminate analysis if you discover:
1. Critical data missing affecting core conclusions
2. Contradictions between different data sources that remain unresolved
3. Data time exceeds validity period:
   - Financial data >12 months
   - Technical data >1 month
   - Options data >7 trading days

## Output Format
```markdown
# [Stock Symbol] Investment Analysis Report
**Report Date**: {report_date}

### 1. Investment Conclusion
{{Integrated conclusion based on multi-dimensional analysis}}

### 2. Key Verification Logic
{{Structured presentation of core argumentation process}}

### 3. Execution Framework
{{Specific actionable trading plan}}
```
Please strictly follow this template to generate the final report"""
    
class OneStepReportGenerationPromptEn:
    def format(self, symbol: str, report_date: str, latest_price: float, market_cap: float, technical_data: str, financial_data: str, options_data: str, catalyst_data: str) -> str: 
        """Format prompt for generating integrated investment report"""
        return f"""# Investment Analysis Report Request

Please generate a comprehensive investment analysis report based on the following multi-dimensional analysis. The report should be thorough yet focused, professionally written yet accessible, analytically deep with forward-looking insights, and provide clear, actionable recommendations.

Please use only the provided data for your analysis, and cite data sources with conclusions (e.g., "According to financial reports, 2024 revenue was $100M, a 20% year-over-year increase", "According to earnings call transcripts, management projects 2025 revenue of $150M, a 15% year-over-year increase"). All assumptions and projections must be based on existing data and reasonable inference. Absolutely do not fabricate data or hallucinate information. If needed data is not provided, explicitly note the missing data. If your analysis relies on assumptions, clearly label these conditions alongside your conclusions.

# Analysis Subject
{symbol}

# Report Date
{report_date}

# Latest Price
{latest_price}

# Market Capitalization
{market_cap}

# Catalyst Event Analysis Data (if available)
{catalyst_data}

# Technical Analysis and News Data
{technical_data}

# Financial Analysis Data
{financial_data}

# Options Analysis Data (if available)
{options_data}

Please structure the final report as follows:

1. Investment Rating and Target Price
   - Clearly state the investment rating (Buy/Accumulate/Hold/Reduce/Sell)
     * Provide 12-month target prices based on three scenarios:
       * Bull Case: Based on complete pipeline success and maximum market share
       * Base Case: Based on current trajectory and market expectations
       * Bear Case: Based on increased competition and R&D underperformance

   - Explain the calculation basis for target prices in detail
   - List 3-5 most compelling investment rationales
   - Analyze differences from market consensus

2. Executive Summary
   - Investment Highlights:
     * Product commercialization progress
     * R&D pipeline milestones
     * Market share changes
     * Financial indicator improvements
   - Latest Catalyst Event Analysis:
     * Catalyst events
     * Probability of positive and negative outcomes for catalyst events and supporting evidence
     * Impact of catalyst events on target price
   - Risk Warnings:
     * R&D risks
     * Competitive risks
     * Regulatory risks
     * Financial risks

3. Core Product Analysis
   - Marketed Products:
     * Market share
     * Sales growth
     * Competitive landscape
     * Patent protection
   - Pipeline Products:
     * Clinical progress
     * Market potential
     * Success probability
     * Expected launch timing
   - Catalyst Events:
     * Detailed analysis of catalyst events and recent important events, including detailed clinical data (design, efficacy, safety, etc.) for relevant products, analysis and comparisons
     * Probability of positive and negative outcomes for catalyst events and supporting evidence
     * Impact of catalyst events on target price

4. Financial Analysis
   - Revenue Structure:
     * Product revenue breakdown
     * Geographic revenue distribution
     * Growth drivers
   - Profitability:
     * Gross margin trends
     * Expense control
     * Cash flow status
   - R&D Investment:
     * Investment scale
     * Funding sources
     * Key projects

5. Technical Analysis
   - Trend Assessment:
     * Primary trend direction
     * Trend strength
     * Key support levels
     * Important resistance levels
   - Volume Analysis:
     * Price-volume relationship
     * Institutional movements
     * Abnormal trading
   - Market Sentiment:
     * Technical indicators
     * Options market signals
     * Institutional holding changes

6. Trading Recommendations
   ## Entry Strategy
   - Target price range
   - Phased entry ratio
   - Entry timing selection
   - Risk control measures

   ## Position Management
   - Holding period recommendations
   - Position management plan
   - Hedging strategy options
   - Rebalancing condition settings

   ## Exit Strategy
   - Profit-taking price settings
   - Stop-loss price settings
   - Risk warning mechanisms
   - Exit timing selection

7. Risk Monitoring
   - Technical Monitoring:
     * Price breakthrough levels
     * Volume anomalies
     * Options anomalies
   - Fundamental Monitoring:
   - Event Risks:

8. Assumptions and Calculation Process
If you used any data not provided, made any assumptions, or performed any calculations in the report, please list them in detail here.

Report requirements:
1. Highlight differentiated views, especially divergences from market consensus
2. All predictions and assumptions must be based on existing data and reasonable inference
3. Price targets and trading recommendations need specific data support
4. Risk analysis should combine quantitative and qualitative approaches
5. Recommendations should have clear execution conditions and timeframes
6. Align with biotech/pharmaceutical industry characteristics, highlighting R&D and commercialization progress
7. Adapt to US market characteristics, considering global competitive landscape
8. Cite data sources when referencing data or viewpoints
9. If using assumptions, label them alongside conclusions
10. If performing calculations, show the calculation process
11. Output the report in markdown format, meeting the highest standards of hedge fund investment report formatting and writing
12. Carefully check report content to ensure no important information is omitted, no errors exist, no hallucinations occur, and no data is fabricated

## Important: The data in the generated report must be completely based on the content provided above. Please check carefully and do not fabricate any data. If you perform calculations on the provided data, provide detailed calculation processes. Report accuracy is extremely important, thus data fabrication is not allowed.""" 
    
class TwoStepReportGenerationPromptEn:
    def format(self, symbol: str, report_date: str, latest_price: float, market_cap: float, technical_data: str, financial_data: str, options_data: str, catalyst_analysis: str) -> str: 
        """Format prompt for generating integrated investment report"""
        return f"""# Biomedical Investment Analysis Report Generation Instructions

## Core Standards (Strictly Follow)
⚠️ Use a "Data-Inference-Verification" three-part argumentation structure:
1. Data anchoring: Must note [Source type: Value@time]
2. Inference chain: Show logical relationships between at least 3 data points
3. Cross-verification: Technical and fundamental conclusions must mutually confirm each other

# Analysis Subject
{symbol} ({latest_price} @ {report_date})
Market Cap: {market_cap}

## Input Data Sets
```markdown
### Catalyst Event Analysis
{catalyst_analysis}

### Technical Data, News, Announcements, and Social Media Information
{technical_data}

### Financial Data and Investor Conference Records
{financial_data}

### Options Chain
{options_data}
```

## Report Structure (Generate in sequence)

1. Investment Rating and Target Price
   - Clearly state investment rating (Buy/Accumulate/Hold/Reduce/Sell)
     * Provide 12-month target prices based on three scenarios (Bull Case, Base Case, Bear Case) with rationales:
   - Explain target price calculation basis in detail
   - List 3-5 most compelling investment or short-selling reasons

2. Detailed Catalyst Event Analysis:
   - Specific description of catalyst events
   - Detailed data on relevant drugs
   - Competitors' clinical data
   - Probabilities of positive and negative outcomes for catalyst events and supporting evidence
   - Impact of catalyst events on target price

3. Detailed Financial Analysis
   - Revenue:
     * Product/regional revenue breakdown
     * Major product details
     * Growth drivers
   - Profitability and cash flow status
   - R&D investment and key projects

4. Detailed Technical Analysis
   - Trend assessment:
     * Primary trend direction
     * Trend strength
     * Key support levels
     * Important resistance levels
   - Abnormal trading
     * Abnormal trading dates
     * Abnormal trading prices
     * Abnormal trading volumes
   - Combining news, announcements, and catalyst information to explain technical analysis
   - Using technical analysis to assess whether the market has priced in future catalyst events

5. Detailed Options Analysis
Using comprehensive options analysis to determine
   - Institutional movements
   - Strategies
   - Abnormal trades and potential insider information, whether they indicate early leaks of future catalyst event results
   - Market sentiment, whether excessive optimism or pessimism exists
   - Combining news, announcements, and catalyst information to explain options analysis
   - Using options analysis to assess whether the market has priced in future catalyst events

6. Actionable Trading Recommendations
   ## Position Establishment Strategy (Short/Long/Wait)
   - Target price range
   - Phased entry proportions
   - Entry timing selection
   - Risk control measures

   ## Position Management
   - Recommended holding period
   - Position management plan
   - Hedging strategy options
   - Rebalancing condition settings

   ## Exit Strategy
   - Profit-taking price settings
   - Stop-loss price settings
   - Risk warning mechanisms
   - Exit timing selection

7. Risk Monitoring
   - Technical monitoring:
     * Price breakout levels
     * Volume anomalies
     * Options anomalies
   - Fundamental monitoring:
   - Event risks:

8. Detailed Assumptions and Calculation Processes
If you used any data not provided, made any assumptions, or performed any calculations in the report, please list them in detail here.

Report requirements:
1. Meet the highest standards of hedge fund investment report formatting and writing
2. All predictions and assumptions must be based on existing data and reasonable inference
3. Price targets and trading recommendations need concrete data support
4. Recommendations should have clear execution conditions and timeframes
5. Align with biomedical industry characteristics, highlighting R&D and commercialization progress
6. Adapt to US market characteristics, considering the global competitive landscape
7. Cite data sources when referencing data or viewpoints
8. Please output the report in markdown format
9. Please carefully check the report content to ensure all data comes from the **input data sets**, no important information is omitted, there are no errors, no hallucinations, and no fabricated data""" 

class SpecializedReportPromptEn:
    def format(self, symbol: str, report_date: str, latest_price: float, market_cap: float, technical_data: str, financial_data: str, options_data: str, catalyst_analysis: str) -> str: 
        """Format prompt for generating integrated investment report"""
        return f"""# Biomedical Investment Analysis Report Generation Instructions

## Core Guidelines (Strictly Follow)
⚠️ Use a "Data-Inference-Verification" three-part argumentation structure:
1. Data anchoring: Must cite [<source type>: <value>@<time>]
   - If news data has URL links, citation should be: [<news Source value>@<time>](<URL value>)
2. Inference chain: Demonstrate logical relationships between at least 3 data points
3. Cross-verification: Technical and fundamental conclusions must mutually validate each other

# Analysis Subject
{symbol} ({latest_price} @ {report_date})
Market Cap: {market_cap}

## Input Data Sets
```markdown
### Catalyst Event Analysis
{catalyst_analysis}

### Technical Data, News, Announcements and Social Media Information
{technical_data}

### Financial Data and Investor Conference Records
{financial_data}

### Options Chain
{options_data}
```

## Report Structure (Generate in sequence)
1. Stock Price Movement Attribution Analysis
   - Description of price movement patterns
   - Detailed analysis of price movement causes
      * Focus on news, announcements, catalyst events and clinical trial data

2. Investment Rating and Target Price
   - Clear investment rating (Buy/Accumulate/Hold/Reduce/Sell)
     * Provide 12-month target prices based on three scenarios (Bull Case, Base Case, Bear Case) with rationales
   - Detailed explanation of target price calculation methodology
   - List 3-5 most compelling investment or short-selling rationales
   
3. Actionable Trading Recommendations
   ## Position Strategy (Short/Long/Wait)
   - Target price range
   - Phased position building ratios
   - Entry timing selection
   - Risk control measures

   ## Position Management
   - Recommended holding period
   - Position management plan
   - Hedging strategy options
   - Rebalancing condition settings

   ## Exit Strategy
   - Profit-taking price levels
   - Stop-loss price levels
   - Risk warning mechanisms
   - Exit timing selection

4. Detailed Assumptions and Calculation Process
If you used any data not provided in the report, made any assumptions, or performed any calculations, please list them in detail here.

Report Requirements:
1. All predictions and assumptions must be based on existing data and logical reasoning
2. Price targets and trading recommendations must be supported by specific data
4. Recommendations must include clear execution conditions and timeframes
5. Align with biomedical industry characteristics, highlighting R&D and commercialization progress
6. Account for US market characteristics and global competitive landscape
7. Cite data sources when referencing data or viewpoints
8. Output the report in markdown format
9. Carefully verify report content to ensure all data comes from the **input data sets**, no important information is omitted, and there are no errors, hallucinations, or fabricated data"""