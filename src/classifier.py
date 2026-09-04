"""Failure Classifier — categorizes payment failures into actionable types.

Uses a RandomForestClassifier trained on error codes, payment methods,
amounts, and temporal features to classify failures as:
- transient: Temporary issue, auto-retry
- recoverable: Can be recovered with alternative payment method
- terminal: Permanent failure, needs human intervention  
- suspicious: Potentially fraudulent, flag for review

Falls back to rule-based classification using bank_error_codes.json
when the ML model is not yet trained.
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix
import joblib


class FailureClassifier:
    """Classifies payment failures into actionable categories."""
    
    CATEGORIES = ["transient", "recoverable", "terminal", "suspicious"]
    
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent / "data")
        self.data_dir = Path(data_dir)
        
        # Load error code mappings
        error_codes_path = self.data_dir / "bank_error_codes.json"
        if error_codes_path.exists():
            with open(error_codes_path) as f:
                self.error_code_map = json.load(f)
        else:
            self.error_code_map = {}
        
        # ML model components
        self.model: Optional[RandomForestClassifier] = None
        self.label_encoder = LabelEncoder()
        self.method_encoder = LabelEncoder()
        self.error_encoder = LabelEncoder()
        self._is_trained = False
        
        # Try to load pre-trained model
        model_path = self.data_dir / "classifier_model.joblib"
        if model_path.exists():
            self._load_model(model_path)
    
    def _extract_features(self, payment: Dict[str, Any]) -> np.ndarray:
        """Extract feature vector from a payment record."""
        # Parse timestamp
        created_at = payment.get("created_at", "")
        if isinstance(created_at, str) and created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                hour = dt.hour
                day_of_week = dt.weekday()
                is_weekend = 1 if day_of_week >= 5 else 0
                is_business_hours = 1 if 9 <= hour <= 18 else 0
            except (ValueError, AttributeError):
                hour, day_of_week, is_weekend, is_business_hours = 12, 2, 0, 1
        else:
            hour, day_of_week, is_weekend, is_business_hours = 12, 2, 0, 1
        
        # Amount features
        amount = float(payment.get("amount", 0))
        amount_bucket = min(int(amount / 1000), 50)  # Cap at 50k
        is_high_value = 1 if amount > 10000 else 0
        
        # Method encoding
        method = payment.get("method", "unknown")
        method_map = {"upi": 0, "card": 1, "netbanking": 2, "wallet": 3, "unknown": 4}
        method_code = method_map.get(method, 4)
        
        # Error code encoding
        error_code = payment.get("error_code", "UNKNOWN")
        known_errors = list(self.error_code_map.keys())
        error_idx = known_errors.index(error_code) if error_code in known_errors else len(known_errors)
        
        # Retry count
        retry_count = int(payment.get("retry_count", 0))
        
        features = np.array([
            method_code,
            error_idx,
            amount_bucket,
            is_high_value,
            hour,
            day_of_week,
            is_weekend,
            is_business_hours,
            retry_count,
        ], dtype=np.float64)
        
        return features
    
    def classify_rule_based(self, payment: Dict[str, Any]) -> Tuple[str, float]:
        """Rule-based fallback classification using error code mappings."""
        error_code = payment.get("error_code", "UNKNOWN")
        
        if error_code in self.error_code_map:
            mapping = self.error_code_map[error_code]
            category = mapping["category"]
            confidence = 0.90  # High confidence for known codes
        else:
            # Unknown error — classify as recoverable with lower confidence
            category = "recoverable"
            confidence = 0.50
        
        return category, confidence
    
    def classify(self, payment: Dict[str, Any]) -> Tuple[str, float, Dict[str, float]]:
        """Classify a payment failure.
        
        Returns:
            Tuple of (category, confidence, all_probabilities)
        """
        if self._is_trained and self.model is not None:
            features = self._extract_features(payment).reshape(1, -1)
            probabilities = self.model.predict_proba(features)[0]
            category_idx = np.argmax(probabilities)
            category = self.CATEGORIES[category_idx]
            confidence = float(probabilities[category_idx])
            probs_dict = {cat: float(prob) for cat, prob in zip(self.CATEGORIES, probabilities)}
        else:
            category, confidence = self.classify_rule_based(payment)
            probs_dict = {cat: 0.0 for cat in self.CATEGORIES}
            probs_dict[category] = confidence
        
        return category, confidence, probs_dict
    
    def train(self, payments: List[Dict[str, Any]], labels: List[str]):
        """Train the classifier on labeled payment data."""
        X = np.array([self._extract_features(p) for p in payments])
        
        # Encode labels
        self.label_encoder.fit(self.CATEGORIES)
        y = self.label_encoder.transform(labels)
        
        # Train model
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            class_weight="balanced",
        )
        self.model.fit(X, y)
        self._is_trained = True
        
        # Save model
        model_path = self.data_dir / "classifier_model.joblib"
        joblib.dump({
            "model": self.model,
            "label_encoder": self.label_encoder,
        }, model_path)
    
    def evaluate(self, payments: List[Dict[str, Any]], true_labels: List[str]) -> Dict[str, Any]:
        """Evaluate classifier on test data. Returns metrics dict."""
        predictions = []
        confidences = []
        
        for payment in payments:
            category, confidence, _ = self.classify(payment)
            predictions.append(category)
            confidences.append(confidence)
        
        # Compute metrics
        report = classification_report(
            true_labels, predictions,
            labels=self.CATEGORIES,
            output_dict=True,
            zero_division=0,
        )
        
        cm = confusion_matrix(true_labels, predictions, labels=self.CATEGORIES)
        
        return {
            "classification_report": report,
            "confusion_matrix": cm.tolist(),
            "predictions": predictions,
            "confidences": confidences,
            "accuracy": report.get("accuracy", 0),
        }
    
    def _load_model(self, model_path: Path):
        """Load a pre-trained model."""
        try:
            data = joblib.load(model_path)
            self.model = data["model"]
            self.label_encoder = data["label_encoder"]
            self._is_trained = True
        except Exception:
            self._is_trained = False
