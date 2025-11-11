# 🚦 RTAverse: A Machine Learning-Based Analysis and Forecasting of Road Traffic Accidents in Angeles City

**RTAverse** is a machine learning-based forecasting system designed to analyze and predict road traffic accidents (RTAs) in Angeles City, Philippines. The project's primary goal is to shift local traffic management from a reactive to a **proactive, data-driven approach**.

By analyzing historical accident data (2015-2024), the system identifies high-risk hotspots and temporal patterns, providing actionable insights to local authorities to improve road safety.

---

## 🚀 Features

The RTAverse web application provides a secure, interactive dashboard for authorized users.

* **Interactive Hotspot Map:** Visualizes forecasted accident-prone areas on an interactive map, **color-coded by risk level** (Low, Moderate, High).
* **Analytical Dashboard:** A comprehensive dashboard displaying key trends and graphs, including:
    * Accidents by Hour of Day
    * Accidents and Severity by Day of Week
    * **Top 10 Most Accident-Prone Barangays**
    * Proportion of Alcohol Involvement by Hour
    * Victim Demographics (Age, Gender)
    * Accidents by Offense Type
    * Overall Accident Trend
* **Data Management Pipeline:** A secure database portal for authorized users to upload new accident data. The system automatically preprocesses, cleans, and retrains the model to ensure forecasts remain up-to-date.

---

## 🛠️ Tech Stack

| Category | Tools Used |
| :--- | :--- |
| **Machine Learning** | Python, Pandas, Scikit-learn, **XGBoost** |
| **Backend** | Flask |
| **Database** | MySQL |
| **Frontend** | HTML, JavaScript, **Folium** (for map visualizations) |
| **Deployment** | Render (Application Hosting), Aiven (Managed Database) |

---

## ⚙️ Methodological Framework

The project follows the **Cross-Industry Standard Process for Data Mining (CRISP-DM)** framework.

1.  **Business Understanding:** Define the problem (reactive traffic management) and the goal (proactive forecasting).
2.  **Data Understanding:** Utilize historical RTA data (2015-2024) from the Angeles City Police Office (Camp Tomas J. Pepito).
3.  **Data Preparation:** Clean, transform, and reduce the dataset. This includes handling missing values, encoding categorical data, and feature engineering.
4.  **Modeling:** Evaluate multiple algorithms (k-NN, Naïve Bayes, Decision Tree, Random Forest, SVM, AdaBoost, and XGBoost). **XGBoost was selected** as the final model.
5.  **Evaluation:** Validate the model using metrics like MAE, MSE, RMSE, MAPE, and $R^2$. The final model achieved the **lowest Mean Absolute Error (MAE) of 0.22**. The system's quality was also assessed using the ISO/IEC 25010 model.
6.  **Deployment:** The RTAverse dashboard is deployed as a secure web application.

---

## 📊 Key Findings

The analysis of the accident data revealed several key factors influencing RTA risk:

* **High-Risk Times:** **Late-night hours (TIME\_CLUSTER\_Midnight)** were identified as the single most significant factor contributing to accident risk.
* **High-Risk Locations:** **Barangay Balibago** consistently showed the highest concentration of accidents in the city.
