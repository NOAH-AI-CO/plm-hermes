import base64
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
import ta
import datetime
import numpy as np
import os

def draw_technical_plot(ticker):
    if not os.path.exists("ta_images"):
        os.makedirs("ta_images")
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    file_path = f"ta_images/{ticker}_{date}.jpeg"
    if os.path.exists(file_path):
        with open(file_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    # TODO: change data source to be in house seeking alpha api
    df_daily = yf.Ticker(ticker).history(period='1y')[map(str.title, ['open', 'close', 'low', 'high', 'volume'])]
    # df_daily.ta.macd(close='close', fast=12, slow=26, append=True)
    # df_daily.ta.rsi(close='close', length=14, append=True)
    # Force lowercase (optional)
    df_daily.columns = [x.lower() for x in df_daily.columns]
    df_daily['macds_12_26_9'] = ta.trend.MACD(df_daily['close'], 12, 26, 9).macd_signal()
    df_daily['macdh_12_26_9'] = ta.trend.MACD(df_daily['close'], 12, 26, 9).macd_diff()
    df_daily['macd_12_26_9'] = ta.trend.MACD(df_daily['close'], 12, 26, 9).macd()
    df_daily['rsi_14'] = ta.momentum.RSIIndicator(df_daily['close'], 14).rsi()
    df_daily['change'] = df_daily['close'].diff().fillna(0)
    # Individual Plot Elements:

    ## OHLC Candlestick Chart
    trace_candles = go.Candlestick(x=df_daily.index,  # df_daily.index stores dates (x-axis)
                                    open=df_daily.open,  # Open for OHLC candlesticks
                                    high=df_daily.high,  # High for OHLC candlesticks
                                    low=df_daily.low,  # Low for OHLC candlesticks
                                    close=df_daily.close,  # Close for OHLC candlesticks
                                    name='Candlestick')  # Naming this to Candlestick for legend on the side of plot

    ## OHLC Bar Chart
    trace_bars = go.Ohlc(x=df_daily.index,  # index stores dates (x-axis)
                            open=df_daily.open,  # Open for OHLC bars
                            high=df_daily.high,  # High for OHLC bars
                            low=df_daily.low,  # Low for OHLC bars
                            close=df_daily.close,  # Close for OHLC bars
                            name='Bar Chart')  # Naming this to Bar Chart

    ## Daily Close Line
    trace_close = go.Scatter(x=list(df_daily.index),  # index stores dates (x-axis)
                                y=list(df_daily.close),  # want only close values plotted
                                name='Close',  # Name this to Close
                                line=dict(color='#87CEFA',  # Define color for line
                                        width=2))  # Define width for line

    # Open and Close markers
    d = 1  # Marker will be placed d position points above or below daily open/close valu, respectively.
    df_daily["marker"] = np.where(df_daily["open"] < df_daily["close"], df_daily["high"] + d, df_daily["low"] - d)
    df_daily["Symbol"] = np.where(df_daily["open"] < df_daily["close"], "triangle-up",
                                    "triangle-down")  # triangle up for + day, triangle down for - day
    df_daily["Color"] = np.where(df_daily["open"] < df_daily["close"], "green",
                                    "red")  # defining green positive change and red for negative daily change


    # 8 Day EMA over 21 Day EMA:


    ## Volume
    trace_volume = go.Bar(x=list(df_daily.index),
                            y=list(df_daily.volume),
                            name='Volume',
                            marker=dict(color='gray'),
                            yaxis='y2',
                            legendgroup='two')

    ## MACD Histogram
    trace_macd_hist = go.Bar(x=df_daily.index,
                                y=df_daily['macdh_12_26_9'],
                                name='MACD Histogram',
                                marker=dict(color='gray'),
                                yaxis='y3',
                                legendgroup='three')

    ## MACD Line
    trace_macd = go.Scatter(x=df_daily.index,
                            y=df_daily['macd_12_26_9'],
                            name='MACD',
                            line=dict(color='black', width=1.5),  # red
                            yaxis='y3',
                            legendgroup='three')

    ## MACD Signal Line
    trace_macd_signal = go.Scatter(x=df_daily.index,
                                    y=df_daily['macds_12_26_9'],
                                    name='Signal',
                                    line=dict(color='red', width=1.5),  # plum
                                    yaxis='y3',
                                    legendgroup='three')

    ## RSI
    trace_rsi = go.Scatter(x=df_daily.index, 
                            y=df_daily['rsi_14'],
                            mode='lines',
                            name='RSI',
                            line=dict(color='black',
                                        width=1.5),
                            yaxis='y4',
                            legendgroup='four')

    # RSI Overbought
    trace_rsi_70 = go.Scatter(mode='lines',
                                x=[min(df_daily.index), max(df_daily.index)],
                                y=[70, 70],
                                name='Overbought > 70%',
                                line=dict(color='green',
                                        width=0.5,
                                        dash='dot'),
                                yaxis='y4',
                                legendgroup='four')

    # RSI Oversold
    trace_rsi_30 = go.Scatter(mode='lines',
                                x=[min(df_daily.index), max(df_daily.index)],
                                y=[30, 30],
                                name='Oversold < 30%',
                                line=dict(color='red',
                                        width=0.5,
                                        dash='dot'),
                                yaxis='y4',
                                legendgroup='four')

    # RSI Center Line
    trace_rsi_50 = go.Scatter(mode='lines',
                                x=[min(df_daily.index), max(df_daily.index)],
                                y=[50, 50],
                                line=dict(color='gray',
                                        width=0.5,
                                        dash='dashdot'),
                                name='50%',
                                yaxis='y4',
                                legendgroup='four')

    ## Plotting Layout
    layout = go.Layout(xaxis=dict(titlefont=dict(color='silver'),  # Color of our X-axis Title
                                    tickfont=dict(color='grey'),  # Color of ticks on X-axis
                                    linewidth=1,  # Width of x-axis
                                    linecolor='black',  # Line color of x-axis
                                    gridwidth=1,  # gridwidth on x-axis marks
                                    gridcolor='rgb(204,204,204)',  # grid color
                                    # Define ranges to view data. I chose 3 months, 6 months, 1 year, and year to date
                                    ),
                        # Define different y-axes for each of our plots: daily, volume, MACD, and RSI -- hence 4 y-axes
                        yaxis=dict(domain=[0.70, 1.0], fixedrange=False, title='Price',
                                    titlefont=dict(color='rgb(200,115,115)'),
                                    tickfont=dict(color='rgb(200,115,115)'),
                                    linecolor='black',
                                    mirror='all',
                                    gridwidth=1,
                                    gridcolor='rgb(204,204,204)'),
                        yaxis2=dict(domain=[0.53, 0.66], fixedrange=False, title='Volume',
                                    titlefont=dict(color='rgb(200,115,115)'),
                                    tickfont=dict(color='rgb(200,115,115)'),
                                    linecolor='black',
                                    mirror='all',
                                    gridwidth=1,
                                    gridcolor='rgb(204,204,204)'),
                        yaxis3=dict(domain=[0.27, 0.5], fixedrange=False, title='MACD',
                                    titlefont=dict(color='rgb(200,115,115)'),
                                    tickfont=dict(color='rgb(200,115,115)'),
                                    linecolor='black',
                                    constraintoward='center',  # might not be necessary
                                    mirror='all',
                                    gridwidth=1,
                                    gridcolor='rgb(204,204,204)'),
                        yaxis4=dict(domain=[0., 0.24], range=[10, 90], title='RSI',
                                    tick0=10, dtick=20,
                                    titlefont=dict(color='rgb(200,115,115)'),
                                    tickfont=dict(color='rgb(200,115,115)'),
                                    linecolor='black',
                                    mirror='all',
                                    gridwidth=1,
                                    gridcolor='rgb(204,204,204)'),
                        title=(ticker + ' Daily Data'),  # Give our plot a title
                        title_x=0.5,  # Center our title
                        titlefont=dict(color='grey'),
                        legend=dict(font=dict(color='grey')),
                        paper_bgcolor='rgb(255,255,255)',  # Background color of main background
                        plot_bgcolor='rgb(226,238,245)',  # Background color of plot
                        height=768,  # overall height of plot
                        width=768,
                        margin=dict(l=60, r=20, t=50, b=5)  # define margins: left, right, top, and bottom
                        )
    # All individual plots in data element
    plotting_data = [trace_close, trace_candles, trace_bars,
                        trace_volume,
                        trace_macd_hist, trace_macd, trace_macd_signal, trace_rsi, trace_rsi_30, trace_rsi_50,
                        trace_rsi_70]

    # Plot
    fig = go.Figure(data=plotting_data, layout=layout)
    
    fig.update(layout_xaxis_rangeslider_visible=False)

    # Uncomment the following line to write your plot to full_figure.html, and auto open
    # fig.write_html('first_figure.html', auto_open=True)
    fig.show()
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    fig.write_image(file_path)
    # END OF draw_technical_plot #########################################
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')






