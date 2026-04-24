import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error

def train_pipeline(data_path="bakery_inventory.csv"):
    """
    End-to-end ML pipeline for demand prediction (hourly_velocity).
    """
    print("Loading data and engineering features...")
    df = pd.read_csv(data_path)
    
    # 1. Feature Engineering
    # Convert timestamp
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour_of_day'] = df['timestamp'].dt.hour
    
    # Create is_weekend (Saturday/Sunday)
    df['is_weekend'] = df['day_of_week'].isin(['Saturday', 'Sunday']).astype(int)
    
    # Sort values temporarily to correctly compute rolling metrics
    df = df.sort_values(by=['item_id', 'timestamp']).reset_index(drop=True)
    
    # Create rolling_velocity (last 3 values)
    # Important: Use shift(1) to avoid data leakage (current hour's demand shouldn't predict itself)
    df['rolling_velocity'] = df.groupby('item_id')['hourly_velocity'].transform(
        lambda x: x.shift(1).rolling(window=3, min_periods=1).mean()
    )
    df['rolling_velocity'] = df['rolling_velocity'].fillna(0)
    
    # Encode item_id and day_of_week (Label Encoding)
    encoders = {}
    for col in ['item_id', 'day_of_week']:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col])
        encoders[col] = le
        
    # Convert boolean fields to integers
    for col in ['is_peak_hour', 'is_stock_out']:
        df[col] = df[col].astype(int)
        
    # Prepare Features (X) and Target (y)
    features = ['item_id', 'current_stock', 'threshold', 'day_of_week', 
                'is_peak_hour', 'is_stock_out', 'hour_of_day', 'is_weekend', 'rolling_velocity']
    target = 'hourly_velocity'
    
    X = df[features]
    y = df[target]

    # 3. Train-Test Split
    # Using shuffle=False to prevent future data from leaking into training (Temporal split approach)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    # 2 & 4. Model Selection & Training
    # RandomForestRegressor is chosen because it robustly handles non-linear relationships and 
    # interactions between our categorical/temporal features (like hour and day) without the 
    # need for complex scaling or one-hot encoding required by linear models.
    print("Training initial base model...")
    base_model = RandomForestRegressor(n_estimators=100, random_state=42)
    base_model.fit(X_train, y_train)

    # 5. Evaluation
    y_pred = base_model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    
    print("\n--- Base Model Evaluation ---")
    print(f"MAE:  {mae:.4f}")
    print(f"RMSE: {rmse:.4f}")

    # 6. Hyperparameter Tuning (LIGHTWEIGHT)
    print("\nRunning Hyperparameter Tuning (GridSearchCV)...")
    param_grid = {
        'n_estimators': [50, 100, 150],
        'max_depth': [None, 10, 20],
        'min_samples_split': [2, 5]
    }
    
    # cv=3 for simple, lightweight tuning
    grid_search = GridSearchCV(
        RandomForestRegressor(random_state=42), 
        param_grid, 
        cv=3, 
        scoring='neg_mean_absolute_error',
        n_jobs=-1
    )
    grid_search.fit(X_train, y_train)
    
    best_model = grid_search.best_estimator_
    print(f"Best Parameters: {grid_search.best_params_}")
    
    # Re-evaluate with tuned model
    best_pred = best_model.predict(X_test)
    best_mae = mean_absolute_error(y_test, best_pred)
    best_rmse = np.sqrt(mean_squared_error(y_test, best_pred))
    
    print("\n--- Tuned Model Evaluation ---")
    print(f"MAE:  {best_mae:.4f}")
    print(f"RMSE: {best_rmse:.4f}")

    # 7. Save Model & Encoders
    joblib.dump(best_model, 'model.pkl')
    joblib.dump(encoders, 'encoder.pkl')
    print("\nSuccess: Model saved to 'model.pkl' and 'encoder.pkl'")

if __name__ == "__main__":
    train_pipeline()
