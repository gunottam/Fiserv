# Legacy XGBoost-only trainer — kept for reference.
# Production training and benchmarking: run from `backend/`:
#   python -m scripts.train_model
# See `backend/scripts/train_model.py` and `backend/README.md`.

import pandas as pd
import numpy as np
import joblib
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error

def train_pipeline(data_path="bakery_inventory.csv"):
    """
    End-to-end ML pipeline for demand prediction (hourly_velocity) using XGBoost.
    """
    print("Loading data and engineering features...")
    df = pd.read_csv(data_path)
    
    # 1. Feature Engineering
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour_of_day'] = df['timestamp'].dt.hour
    df['is_weekend'] = df['day_of_week'].isin(['Saturday', 'Sunday']).astype(int)
    
    df = df.sort_values(by=['item_id', 'timestamp']).reset_index(drop=True)
    
    df['rolling_velocity'] = df.groupby('item_id')['hourly_velocity'].transform(
        lambda x: x.shift(1).rolling(window=3, min_periods=1).mean()
    )
    df['rolling_velocity'] = df['rolling_velocity'].fillna(0)
    
    encoders = {}
    for col in ['item_id', 'day_of_week']:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col])
        encoders[col] = le
        
    for col in ['is_peak_hour', 'is_stock_out']:
        df[col] = df[col].astype(int)
        
    features = ['item_id', 'current_stock', 'threshold', 'day_of_week', 
                'is_peak_hour', 'is_stock_out', 'hour_of_day', 'is_weekend', 'rolling_velocity']
    target = 'hourly_velocity'
    
    X = df[features]
    y = df[target]

    # 2. Train-Test Split (Chronological)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    # 3. Model Upgrade to XGBoost!
    # XGBoost builds sequential trees to correct previous errors. It's incredibly fast,
    # prevents overfitting with built-in regularization, and wins tabular Kaggle competitions.
    print("Training XGBoost Base Model...")
    base_model = XGBRegressor(n_estimators=100, random_state=42, objective='reg:squarederror')
    base_model.fit(X_train, y_train)

    # 4. Evaluation
    y_pred = base_model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    
    print("\n--- Base XGBoost Evaluation ---")
    print(f"MAE:  {mae:.4f}")
    print(f"RMSE: {rmse:.4f}")

    # 5. Hyperparameter Tuning for XGBoost
    print("\nRunning Hyperparameter Tuning for XGBoost...")
    param_grid = {
        'n_estimators': [100, 200],
        'max_depth': [3, 6, 9],
        'learning_rate': [0.05, 0.1]
    }
    
    grid_search = GridSearchCV(
        XGBRegressor(random_state=42, objective='reg:squarederror'), 
        param_grid, 
        cv=3, 
        scoring='neg_mean_absolute_error',
        n_jobs=-1
    )
    grid_search.fit(X_train, y_train)
    
    best_model = grid_search.best_estimator_
    print(f"Best XGBoost Parameters: {grid_search.best_params_}")
    
    # Re-evaluate with tuned model
    best_pred = best_model.predict(X_test)
    best_mae = mean_absolute_error(y_test, best_pred)
    best_rmse = np.sqrt(mean_squared_error(y_test, best_pred))
    
    print("\n--- Tuned XGBoost Evaluation ---")
    print(f"MAE:  {best_mae:.4f}")
    print(f"RMSE: {best_rmse:.4f}")

    # 6. Save Model
    joblib.dump(best_model, 'model.pkl')
    joblib.dump(encoders, 'encoder.pkl')
    print("\nSuccess: Elite XGBoost model saved to 'model.pkl' and 'encoder.pkl'")

if __name__ == "__main__":
    train_pipeline()
