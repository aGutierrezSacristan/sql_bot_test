import streamlit as st

st.set_page_config(page_title="SQL Query Generator", layout="centered")

st.title("🩺 SQL Query Generator for Clinical Data")

st.markdown("""
Welcome!  
Select a common query from the list below or write your own description, and I’ll generate a **working SQL query** based on your clinical database schema.  
""")

# Common queries
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
    "View the first 100 rows of the pivot",
    "Select a random 1000 patients",
    "Create a primary key to speed up queries",
    "Determine the total number of visits for the sample"
]

query_choice = st.selectbox("📋 Select a common query (optional):", [""] + common_queries)

custom_request = st.text_input("💬 Or describe your SQL request:")

# Decide which request to use
if query_choice:
    user_request = query_choice
else:
    user_request = custom_request

def generate_sql(request: str) -> str:
    request = request.lower()

    if "number of patients" in request:
        return """
SELECT COUNT(DISTINCT patient_num) AS patient_count
FROM patient_dimension;
"""

    elif "first 100 patients" in request:
        return """
SELECT *
FROM patient_dimension
LIMIT 100;
"""

    elif "first 100 observations" in request:
        return """
SELECT *
FROM observation_fact
LIMIT 100;
"""

    elif "age at diagnosis" in request and "between" in request:
        return """
SELECT p.patient_num, TIMESTAMPDIFF(YEAR, p.birth_date, o.start_date) AS age_at_diagnosis
FROM patient_dimension p
JOIN observation_fact o ON p.patient_num = o.patient_num
WHERE TIMESTAMPDIFF(YEAR, p.birth_date, o.start_date) BETWEEN X AND Y;
"""

    elif "create a new table with patient" in request:
        return """
CREATE TABLE patient_diagnosis_age AS
SELECT p.patient_num, o.concept_cd, TIMESTAMPDIFF(YEAR, p.birth_date, o.start_date) AS age_at_diagnosis
FROM patient_dimension p
JOIN observation_fact o ON p.patient_num = o.patient_num;
"""

    elif "subset of the patient_dimension" in request:
        return """
SELECT p.*
FROM patient_dimension p
JOIN observation_fact o ON p.patient_num = o.patient_num
WHERE p.sex_cd = 'M' AND p.race_cd = 'WHITE' AND o.concept_cd = 'YOUR_CONDITION';
"""

    elif "medications" in request:
        return """
SELECT *
FROM observation_fact
WHERE concept_cd LIKE 'RXNORM%';
"""

    elif "diagnosis" in request:
        return """
SELECT *
FROM observation_fact
WHERE concept_cd LIKE 'ICD%';
"""

    elif "labs" in request:
        return """
SELECT *
FROM observation_fact
WHERE concept_cd LIKE 'LOINC%';
"""

    elif "list of concepts" in request and "number of patients" in request:
        return """
SELECT concept_cd, COUNT(DISTINCT patient_num) AS patient_count
FROM observation_fact
GROUP BY concept_cd;
"""

    elif "save the results to a temp table" in request:
        return """
SELECT *
INTO #temp_table
FROM patient_dimension
WHERE race_cd = 'YOUR_RACE';
"""

    elif "drop the temp table" in request:
        return """
DROP TABLE #temp_table;
"""

    elif "top 100 concepts" in request:
        return """
SELECT concept_cd, COUNT(DISTINCT patient_num) AS patient_count
FROM observation_fact
GROUP BY concept_cd
ORDER BY patient_count DESC
LIMIT 100;
"""

    elif "pivot" in request:
        return """
-- Example: pivot diagnosis codes as columns
SELECT p.patient_num,
       MAX(CASE WHEN o.concept_cd = 'ICD1' THEN 1 ELSE 0 END) AS ICD1,
       MAX(CASE WHEN o.concept_cd = 'ICD2' THEN 1 ELSE 0 END) AS ICD2
FROM patient_dimension p
LEFT JOIN observation_fact o ON p.patient_num = o.patient_num
GROUP BY p.patient_num;
"""

    elif "random 1000 patients" in request:
        return """
SELECT *
FROM patient_dimension
ORDER BY RAND()
LIMIT 1000;
"""

    elif "create a primary key" in request:
        return """
ALTER TABLE patient_dimension
ADD PRIMARY KEY (patient_num);
"""

    elif "total number of visits" in request:
        return """
SELECT COUNT(*) AS total_visits
FROM visit_dimension;
"""

    else:
        return "-- Sorry, I don’t recognize this request yet. Please rephrase or contact admin to add this pattern."


if user_request:
    st.subheader("✅ Generated SQL Query:")
    sql_query = generate_sql(user_request)
    st.code(sql_query, language="sql")

    # Copy button
    st.markdown(
        f"""
        <button onclick="navigator.clipboard.writeText(`{sql_query.strip()}`)">📋 Copy to clipboard</button>
        """,
        unsafe_allow_html=True
    )
