"""Small, explainable Phase 2 topic classifier.

This intentionally stores only a label for later use. It does not calculate
analytics or produce any Phase 3 reports.
"""

TOPIC_KEYWORDS = {
    "Healthcare AI": (
        "healthcare", "medical", "medicine", "patient", "hospital",
        "diagnosis", "disease", "clinical", "doctor", "radiology",
    ),
    "Power Systems": (
        "power system", "power grid", "electricity", "electrical grid",
        "voltage", "transformer", "load flow", "smart grid", "renewable",
    ),
    "E-commerce AI": (
        "e-commerce", "ecommerce", "online shopping", "shopping cart",
        "marketplace", "product recommendation", "customer churn",
    ),
    "Deep Learning": (
        "deep learning", "neural network", "cnn", "rnn", "lstm",
        "transformer", "large language model", "llm", "llama",
    ),
    "Machine Learning": (
        "machine learning", "supervised learning", "unsupervised learning",
        "regression", "classification", "clustering", "training data",
        "feature engineering", "random forest", "support vector machine",
    ),
}


def classify_topic(user_message: str, model_response: str = "") -> str:
    """Return one allowed Phase 2 label using deterministic keyword scores."""
    text = f"{user_message} {model_response}".casefold()
    best_topic = "General"
    best_score = 0

    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in text)
        if score > best_score:
            best_topic = topic
            best_score = score

    return best_topic
