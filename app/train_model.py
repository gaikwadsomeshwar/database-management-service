"""Standalone Training and Inference CLI for the Ensemble Forecasting Model.

Allows developers and researchers to:
1. Train the EnsembleForecaster on historical telemetry (Prometheus or synthetic series).
2. Evaluate accuracy metrics (MAE, RMSE, MAPE).
3. Serialize the trained model artifact to `models/ensemble_forecaster.joblib`.
4. Run inference using the trained model to predict future traffic and scaling recommendations.

Usage:
    # 1. Train and save the model:
    python app/train_model.py --train

    # 2. Evaluate model with custom history length:
    python app/train_model.py --train --history-points 360 --evaluate

    # 3. Load trained model and predict future horizon:
    python app/train_model.py --predict --horizon 10

    # 4. End-to-end (Train -> Save -> Predict):
    python app/train_model.py --train --predict --horizon 10
"""

import argparse
import logging
import math
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple

import joblib
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from forecasting.data_source import fetch_history
from forecasting.model import EnsembleForecaster

MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)
DEFAULT_MODEL_PATH = MODELS_DIR / "ensemble_forecaster.joblib"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def calculate_metrics(actual: np.ndarray, predicted: np.ndarray) -> Dict[str, float]:
    """Calculate MAE, RMSE, and MAPE."""
    mae = float(np.mean(np.abs(actual - predicted)))
    rmse = float(np.sqrt(np.mean((actual - predicted) ** 2)))
    # Avoid zero division in MAPE
    denom = np.where(actual == 0, 1e-5, actual)
    mape = float(np.mean(np.abs((actual - predicted) / denom)) * 100.0)
    return {
        "MAE": round(mae, 4),
        "RMSE": round(rmse, 4),
        "MAPE_pct": round(mape, 2),
    }


def train_model(
    history_points: int = 360,
    seasonal_periods: int = 60,
    holt_winters_weight: float = 0.5,
    save_path: Path = DEFAULT_MODEL_PATH,
    evaluate: bool = True,
) -> Tuple[EnsembleForecaster, Dict[str, float]]:
    """Fetch history, fit ensemble model, evaluate, and save artifact."""
    logger.info("Fetching request rate history (%d points)...", history_points)
    raw_history = fetch_history("request_rate")
    history = np.asarray(raw_history, dtype=float)

    if len(history) < history_points:
        logger.info("Using available history length: %d points", len(history))
    else:
        history = history[-history_points:]

    # Train / validation split (85% train, 15% validation) if evaluate=True
    metrics = {}
    if evaluate and len(history) > 40:
        split_idx = int(len(history) * 0.85)
        train_data = history[:split_idx]
        val_data = history[split_idx:]
        val_horizon = len(val_data)

        eval_model = EnsembleForecaster(
            seasonal_periods=seasonal_periods,
            holt_winters_weight=holt_winters_weight,
        ).fit(train_data)

        val_predictions = eval_model.predict(horizon=val_horizon)
        metrics = calculate_metrics(val_data, val_predictions)
        logger.info("Validation Metrics (horizon=%d steps): %s", val_horizon, metrics)

    logger.info("Fitting EnsembleForecaster on full history...")
    forecaster = EnsembleForecaster(
        seasonal_periods=seasonal_periods,
        holt_winters_weight=holt_winters_weight,
    ).fit(history)

    # Save artifact
    logger.info("Saving trained model artifact to %s", save_path)
    joblib.dump(forecaster, save_path)

    return forecaster, metrics


def load_and_predict(
    horizon: int = 10,
    model_path: Path = DEFAULT_MODEL_PATH,
    target_rps_per_replica: float = 20.0,
    min_replicas: int = 1,
    max_replicas: int = 10,
) -> List[Dict[str, Any]]:
    """Load serialized model and generate predictions and replica recommendations."""
    if not model_path.exists():
        raise FileNotFoundError(
            f"Trained model not found at {model_path}. Run with --train first."
        )

    logger.info("Loading model artifact from %s", model_path)
    forecaster: EnsembleForecaster = joblib.load(model_path)

    predictions = forecaster.predict(horizon=horizon)
    results = []

    for step, rate in enumerate(predictions, 1):
        rec_replicas = math.ceil(rate / target_rps_per_replica)
        clamped_replicas = max(min_replicas, min(max_replicas, rec_replicas))
        results.append({
            "step": step,
            "predicted_request_rate": round(float(rate), 2),
            "recommended_replicas": clamped_replicas,
        })

    return results


def parse_args():
    parser = argparse.ArgumentParser(description="Train and Run EnsembleForecaster.")
    parser.add_argument("--train", action="store_true", help="Train the model and save to disk")
    parser.add_argument("--predict", action="store_true", help="Load saved model and run inference")
    parser.add_argument("--history-points", type=int, default=360, help="Training history window length")
    parser.add_argument("--horizon", type=int, default=10, help="Prediction horizon in steps")
    parser.add_argument("--seasonal-periods", type=int, default=60, help="Seasonal period length")
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH), help="Path to save/load model")
    parser.add_argument("--eval", "--evaluate", dest="eval", action="store_true", default=True, help="Compute validation evaluation metrics (default: True)")
    parser.add_argument("--no-eval", dest="eval", action="store_false", help="Skip validation evaluation during training")
    return parser.parse_args()


def main():
    args = parse_args()
    model_path = Path(args.model_path)

    if not args.train and not args.predict:
        # Default behavior: run train then predict
        args.train = True
        args.predict = True

    print("=" * 70)
    print("ENSEMBLE FORECASTER - MODEL TRAINING & INFERENCE ENGINE")
    print("=" * 70)

    if args.train:
        forecaster, metrics = train_model(
            history_points=args.history_points,
            seasonal_periods=args.seasonal_periods,
            save_path=model_path,
            evaluate=args.eval,
        )
        print("\n[TRAINING COMPLETE]")
        print(f"Artifact Saved To : {model_path}")
        if metrics:
            print(f"Validation MAE    : {metrics['MAE']} req/s")
            print(f"Validation RMSE   : {metrics['RMSE']} req/s")
            print(f"Validation MAPE   : {metrics['MAPE_pct']}%")

    if args.predict:
        predictions = load_and_predict(horizon=args.horizon, model_path=model_path)     
        print(f"\n[INFERENCE RESULTS - NEXT {args.horizon} HORIZON STEPS]")
        print(f"{'Step':<8} {'Predicted Rate (req/s)':<25} {'Recommended Replicas':<20}")
        print("-" * 55)
        for p in predictions:
            print(f"{p['step']:<8} {p['predicted_request_rate']:<25.2f} {p['recommended_replicas']:<20}")
        print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
