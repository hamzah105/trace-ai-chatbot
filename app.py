from config.database import check_db_connection
from backend.analytics.metrics import AnalyticsManager

# Check MongoDB
check_db_connection()

# Initialize analytics
analytics = AnalyticsManager()

print("✔️ Analytics module initialized")

# Add test metric
analytics.add_metric(
    timestamp="2026-05-15 10:00",
    user_prompt="Hello AI",
    response_time=1.5,
    model_name="llama3",
    tokens_used=50
)

# Show dataframe
analytics.show_metrics()