# WEEX AI Quant Trading System

## Overview
This project implements a **production-grade AI-assisted quantitative trading system**
for crypto futures markets.  
The system is designed to operate autonomously using exchange REST APIs, combining
machine learning–based signal filtering with **strict, rule-based risk management
and execution discipline**.

The architecture explicitly separates:
- **Signal inference (AI)**
- **Risk control**
- **Order execution**
- **Runtime monitoring & persistence**

This separation ensures robustness, auditability, and compliance with competition
and exchange requirements.

---

## System Architecture

The system is composed of four primary layers:

1. **Market Data Layer**  
   Retrieves historical and live futures market data via REST APIs.

2. **Feature Engineering Layer**  
   Builds strictly lagged, causal features for inference.

3. **Inference Layer (AI)**  
   Evaluates trade opportunities probabilistically using a trained ML model.

4. **Execution & Risk Layer**  
   Enforces leverage, position sizing, exits, and execution safety.

Each layer is isolated to prevent cascading failures and to simplify debugging.

---

## Data Pipeline

Supported futures market data includes:
- OHLCV candlestick data
- Volume-based indicators
- Volatility and ATR-based measures

Historical data is used **only** for model training and validation.  
Live trading decisions are made strictly using **past and closed candles** to avoid
look-ahead bias.

---

## Feature Engineering

The feature pipeline includes:
- Log returns and momentum indicators
- ATR-based volatility normalization
- Volume trend and participation measures
- Trend and regime-aware features
- Time-based contextual encodings

All features are derived exclusively from historical observations.

---

## AI Logic

Machine learning models are used to:
- Filter potential trade opportunities
- Estimate confidence for directional bias
- Adapt signal behavior under changing volatility regimes

The AI model **does not place trades directly**.  
It only provides directional intent and confidence.

All risk management, sizing, and exits are handled deterministically
outside the model.

---

## Risk Management & Execution

Risk controls are enforced at multiple levels:
- Fixed per-trade risk limits
- Maximum margin usage per position
- Maximum concurrent long and short positions
- ATR-based stop, target, early-failure, and time-based exits

Execution is performed using market-safe order logic with retries and verification.

---

## Runtime State & Persistence

During live operation, the system maintains:
- Current open positions
- Time-to-exit diagnostics per trade
- Closed trade history with PnL attribution
- Portfolio equity snapshots

Runtime state is persisted locally for:
- UI dashboards
- Crash recovery
- Post-trade analysis

---

## AI Compliance Logging

For competition compliance, each AI-assisted trade includes:
- Model identifier
- Input feature snapshot
- Output decision metadata
- Human-readable reasoning summary

These logs are uploaded to the exchange as required.

---

## Exchange Integration (WEEX)

The execution layer integrates with WEEX REST APIs for:
- Market data ingestion
- Order placement and closing
- Position monitoring
- AI log submission

Exchange-specific calibration is applied to:
- Feature scaling
- Volatility thresholds
- Risk parameters

All trades comply with leverage limits and competition rules.

---

## Operational Resilience

The system is designed for 24/7 unattended operation:
- Runs as a systemd service
- Automatically restarts on failure
- Uses retry-safe API calls
- Maintains state across restarts (VM-level persistence)

---

## Project Status

- ✅ Data ingestion implemented  
- ✅ Feature engineering implemented  
- ✅ AI inference engine integrated  
- ✅ Risk-controlled execution live  
- ✅ Runtime state & trade history tracking  
- ⏳ Ongoing strategy evaluation and refinement  

---

## Disclaimer

This project is for research and competition purposes only.
Trading futures involves significant risk.  
Past performance does not guarantee future results.
