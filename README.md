# WEEX AI Quant Trading System

## Overview
This project implements an AI-assisted quantitative trading system for
crypto futures markets. The system is designed to operate via exchange
REST APIs and focuses on robust feature engineering, market regime awareness,
and disciplined risk-controlled execution.

## Data Pipeline
The system currently supports futures market data including:
- OHLCV candlestick data
- Funding rates
- Volume-based and volatility-based indicators

Historical data is used only for model training and validation.
Live trading decisions are made strictly using lagged information to
avoid look-ahead bias.

## Feature Engineering
The feature pipeline includes:
- Log returns and momentum indicators
- Volatility and ATR-based measures
- Volume trends and buy pressure estimation
- Trend and regime detection features
- Time-based cyclical encodings

All features are constructed using past market data only.

## AI Logic
Machine learning models are used to:
- Identify favorable market regimes
- Filter trade signals probabilistically
- Adapt decision thresholds based on volatility conditions

The AI model does not directly predict prices. Risk management,
position sizing, and execution constraints are handled outside the model.

## Exchange-Agnostic Training
The core model is trained on historical crypto futures data with similar
market microstructure characteristics. The training focuses on learning
general market behaviors rather than exchange-specific artifacts.

## WEEX Execution Plan
After approval, the execution layer will integrate directly with WEEX
REST APIs for:
- Market data ingestion
- Order placement and management
- Position and risk monitoring

Before live trading, exchange-specific calibration will be applied using
WEEX market data to adjust feature normalization, volatility scaling, and
signal thresholds. All trades will comply with leverage limits and
competition rules.

## Project Status
- Data ingestion implemented
- Feature engineering implemented
- Model training and evaluation in progress
- WEEX API integration pending approval
