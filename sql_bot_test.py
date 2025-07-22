import streamlit as st
import pandas as pd

st.set_page_config(page_title="SQL Query Generator", layout="centered")

st.title("🩺 SQL Query Generator for Clinical Data")

st.markdown("""
Welcome!  
Select a common query from the list below or write your own description, and I’ll generate a **working SQL query** based on your clinical database schema, along with example input and output tables so you can understand what it does.
""")

common_queries = [
    "Determine the number of patients in the project",
    "View the data on the first 100 patients",
    "View the first 100 observations about the patients",
    "Select patients with age at diagnosis between X and Y",
    "Given the birthdate and diagnosis date, create a new table with patient, diagnosis and age at diagnosis",
    "Create a subset of the patient_dimension table for patients with specific demographic characteristics and conditions",
    "Select medications (concept_cd like RXNORM) for a subset of patients",
    "Select diagnosis (concept_cd like ICD) for a subset of patients",
    "Select labs (concept_cd like LOINC) for a subset of patients",
    "Get a list of concepts and the number of patients with that code",
    "Save the results to a temp table",
    "Drop the temp table since we no longer need it",
    "View the top 100 concepts by number of patients",
    "Create a pivot with one row per patient and features in columns",
    "Select a random 1000 patients",
    "Create a primary key to speed up queries",
    "Determine the total number of visits for the sample"
]

query_choice = st.selectbox("📋 Select a common query (optional):", [""] + common_queries)

custom_request = st.text_input("💬 Or describe your SQL request:")

if query_choice:
    user_request = query_choice
else:
    user_request = custom_request


def generate_sql_and_examples(request: str) -> dict:
    request = request.lower()

    # Default dummy dfs
    dummy_patients = pd.DataFrame({
        "patient_num": [1, 2, 3],
        "birth_date": ["1980-01-01", "1990-05-20", "1975-07-15"],
        "sex_cd": ["M", "F", "M"],
        "race_cd": ["WHITE", "BLACK", "ASIAN"]
    })
    dummy_obs = pd.DataFrame({
        "patient_num": [1, 2, 1],
        "encounter_num": [101, 102, 103],
        "concept_cd": ["ICD9_250", "ICD9_401", "RXNORM_12345"],
        "start_date": ["2020-01-01", "2021-06-01", "2019-12-15"]
    })

    if "number of patients" in request:
        return {
            "sql": """
SELECT COUNT(DISTINCT patient_num) AS patient_count
FROM patient_dimension;
""",
            "input_df": dummy_patients,
            "output_df": pd.DataFrame({"patient_count": [3]})
        }

    elif "first 100 patients" in request:
        return {
            "sql": """
SELECT *
FROM patient_dimension
LIMIT 100;
""",
            "input_df": dummy_patients,
            "output_df": dummy_patients
        }

    elif "first 100 observations" in request:
        return {
            "sql": """
SELECT *
FROM observation_fact
LIMIT 100;
""",
            "input_df": dummy_obs,
            "output_df": dummy_obs
        }

    elif "age at diagnosis" in request and "between" in request:
        out = dummy_obs.copy()
        out["age_at_diagnosis"] = [40, 30, 45]
        return {
            "sql": """
SELECT p.patient_num, TIMESTAMPDIFF(YEAR, p.birth_date, o.start_date) AS age_at_diagnosis
FROM patient_dimension p
JOIN observation_fact o ON p.patient_num = o.patient_num
WHERE TIMESTAMPDIFF(YEAR, p.birth_date, o.start_date) BETWEEN X AND Y;
""",
            "input_df": pd.merge(dummy_patients, dummy_obs, on="patient_num"),
            "output_df": out[["patient_num", "age_at_diagnosis"]]
        }

    elif "create a new table with patient" in request:
        out = dummy_obs.copy()
        out["age_at_diagnosis"] = [40, 30, 45]
        return {
            "sql": """
CREATE TABLE patient_diagnosis_age AS
SELECT p.patient_num, o.concept_cd, TIMESTAMPDIFF(YEAR, p.birth_date, o.start_date) AS age_at_diagnosis
FROM patient_dimension p
JOIN observation_fact o ON p.patient_num = o.patient_num;
""",
            "input_df": pd.merge(dummy_patients, dummy_obs, on="patient_num"),
            "output_df": out[["patient_num", "concept_cd", "age_at_diagnosis"]]
        }

    elif "subset of the patient_dimension" in request:
        out = dummy_patients[
            (dummy_patients["sex_cd"] == "M") & (dummy_patients["race_cd"] == "WHITE")
        ]
        return {
            "sql": """
SELECT p.*
FROM patient_dimension p
JOIN observation_fact o ON p.patient_num = o.patient_num
WHERE p.sex_cd = 'M' AND p.race_cd = 'WHITE' AND o.concept_cd = 'YOUR_CONDITION';
""",
            "input_df": pd.merge(dummy_patients, dummy_obs, on="patient_num"),
            "output_df": out
        }

    elif "random 1000 patients" in request:
        return {
            "sql": """
SELECT *
FROM patient_dimension
ORDER BY RAND()
LIMIT 1000;
""",
            "input_df": dummy_patients,
            "output_df": dummy_patients.sample(frac=1)
        }

    elif "total number of visits" in request:
        visits = pd.DataFrame({
            "encounter_num": [101, 102, 103],
            "patient_num": [1, 2, 1],
            "start_date": ["2020-01-01", "2021-06-01", "2019-12-15"]
        })
        return {
            "sql": """
SELECT COUNT(*) AS total_visits
FROM visit_dimension;
""",
            "input_df": visits,
            "output_df": pd.DataFrame({"total_visits": [3]})
        }

    # fallback
    return {
        "sql": "-- Sorry, I don’t recognize this request yet.",
        "input_df": pd.DataFrame(),
        "output_df": pd.DataFrame()
    }


if user_request:
    result = generate_sql_and_examples(user_request)

    st.subheader("✅ Generated SQL Query:")
    st.code(result["sql"], language="sql")

    if not result["input_df"].empty:
        st.markdown("### 📥 Example Input Table")
        st.dataframe(result["input_df"])

    if not result["output_df"].empty:
        st.markdown("### 📤 Example Output Table")
        st.dataframe(result["output_df"])
