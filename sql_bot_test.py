import streamlit as st

st.title("i2b2 SQL Query Generator")

# Show schema
st.markdown("### Database Schema (i2b2)")
st.code("""
observation_fact: encounter_num, patient_num, concept_cd, start_date
patient_dimension: patient_num, birth_date, death_date, sex_cd, race_cd, ethnicity_cd, language_cd, marital_status_cd, zip_cd
concept_dimension: concept_cd, name_char
visit_dimension: encounter_id, patient_num, start_date, end_date
""", language="sql")

# User request
user_request = st.text_input("Describe your SQL request (English):")

# SQL generation
def generate_sql(request: str) -> str:
    request = request.lower()
    
    if "patients with race" in request:
        # Example: patients with race_cd = 'X'
        race = request.split("race")[-1].strip().strip(":").strip()
        if not race:
            race = "[RACE_CODE_HERE]"
        return f"""
SELECT patient_num, birth_date, sex_cd, race_cd
FROM patient_dimension
WHERE race_cd = '{race}';
"""

    elif "count of patients by sex" in request or "patients by sex" in request:
        return f"""
SELECT sex_cd, COUNT(*) AS patient_count
FROM patient_dimension
GROUP BY sex_cd;
"""

    elif "observations for concept" in request:
        # Example: concept_cd = 'XYZ'
        concept = request.split("concept")[-1].strip().strip(":").strip()
        if not concept:
            concept = "[CONCEPT_CODE_HERE]"
        return f"""
SELECT o.patient_num, o.encounter_num, o.concept_cd, o.start_date
FROM observation_fact o
WHERE o.concept_cd = '{concept}';
"""

    elif "patients who visited between" in request:
        # Example: date1 and date2 placeholders
        return f"""
SELECT DISTINCT v.patient_num
FROM visit_dimension v
WHERE v.start_date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD';
"""

    else:
        return "-- Sorry, I don’t recognize this request yet. Please rephrase or extend the rules."

if user_request:
    st.subheader("Generated SQL Query:")
    sql_query = generate_sql(user_request)
    st.code(sql_query, language="sql")

